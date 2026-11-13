# -*- coding: utf-8 -*-
"""数据层：直读 Soul 的 IM-SDK 数据库（root，明文 SQLite）。

为什么不用 UI 抓聊天记录：
- UI 需要「扫列表 -> 判红点 -> 进会话 -> OCR」，一轮几十秒还可能点错人；
- 库里 session.unReadCount / lastMsgText / timestamp 全都有，毫秒级且无歧义。

表结构（2026-11-02 实测，13k 消息 / 1248 会话）：
  chatmsg(id,msgId,sessionId,senderId,receiverId,localTime,serverTime,msgType,
          msgStatus,msgReceiveStatus,msgContent,text)
  session(id,sessionId,chatType,userType,toUserId,unReadCount,timestamp,
          lastMsgText,msgStatus,status,dbStatus,extInfo)

msgType: 1=文本(11184) 27=系统引导(1196) 35=? (426) 2/5/8/9=图片/语音/礼物
localTime / timestamp 均为 **毫秒**。
"""
import os
import re
import sqlite3
import time
from pathlib import Path

from core.log import get_logger
from core.paths import DATA

log = get_logger("data.imdb")

DB_DIR_ANDROID = "/data/data/cn.soulapp.android/databases"
SP_INFO = "/data/data/cn.soulapp.android/shared_prefs/sp_info_gather.xml"
MSG_TEXT = 1          # 纯文本消息
MSG_SYSTEM = 27       # 系统引导卡片（tagAuthGuide），不是真人消息
MSG_SYS2 = 35         # 系统推送（"Ta正在使用个性化提示装扮"），text 为空，content 是 JSON
SYS_TYPES = (MSG_SYSTEM, MSG_SYS2)
CACHE = DATA / "cache"

_OFFICIAL_UID = -1    # 负数 toUserId = 官方/系统会话

# 营销/系统推送的文案特征（2026-11-02 实测，2042683xx 号段全是这类）
_OFFICIAL_HINTS = (
    "活动", "积分", "礼物", "周报", "兑换", "优惠", "上新", "系列", "限时",
    "福利", "领取", "会员", "直播", "任务", "打卡", "高定", "功能常驻",
    "邀你", "快来看看", "即将登场",
)


def _ms(v):
    """毫秒时间戳 -> 本地时间字符串。"""
    try:
        v = int(v)
    except Exception:
        return "?"
    if v > 10 ** 12:
        v = v / 1000.0
    return time.strftime("%m-%d %H:%M", time.localtime(v))


class Session(object):
    __slots__ = ("session_id", "to_uid", "unread", "ts", "last_text",
                 "chat_type", "user_type", "ext")

    def __init__(self, row):
        self.session_id = row["sessionId"]
        self.to_uid = row["toUserId"]
        self.unread = row["unReadCount"] or 0
        self.ts = row["timestamp"] or 0
        self.last_text = row["lastMsgText"] or ""
        self.chat_type = row["chatType"]
        self.user_type = row["userType"]
        self.ext = row["extInfo"]

    @property
    def is_group(self):
        return "-" in str(self.session_id)

    @property
    def is_official(self):
        """官方/营销会话。

        两级判据：负数 toUserId 肯定是；文案命中 **≥2 个**营销词也算。
        不用号段硬编码 —— 号段会变，文案特征更稳。

        🔴 2026-11-04（必回闭环修复）：原来是「命中 ≥1 个词」就算官方号。
          而词表里「礼物 / 活动 / 直播 / 会员 / 任务 / 系列」都是**真人日常高频词**
          —— 她说一句「你送我的礼物呢」就会被判成官方号，于是在 clear 清红点、
          wake 唤醒候选、acct 待回统计里被**直接跳过 = 永不回复**（违背必回）。
          改为「≥2 个词」：实测库内 1356 个真人会话（toUid>0）只有 4 个被判官方、
          且这 4 个全是真营销号（命中 2~4 个词），收紧后仍 100% 识别。
        """
        try:
            if int(self.to_uid) < 0:
                return True
        except Exception:
            return True
        t = self.last_text or ""
        hit = sum(1 for h in _OFFICIAL_HINTS if h in t)
        return hit >= 2

    @property
    def time_str(self):
        return _ms(self.ts)

    def __repr__(self):
        return "<Session %s uid=%s unread=%s %s %r>" % (
            self.session_id[-8:], self.to_uid, self.unread, self.time_str,
            self.last_text[:14])


class Msg(object):
    __slots__ = ("msg_id", "session_id", "sender", "receiver", "ts",
                 "msg_type", "status", "text", "content")

    def __init__(self, row):
        self.msg_id = row["msgId"]
        self.session_id = row["sessionId"]
        self.sender = row["senderId"]
        self.receiver = row["receiverId"]
        self.ts = row["localTime"] or 0
        self.msg_type = row["msgType"]
        self.status = row["msgStatus"]
        self.text = row["text"] or ""
        self.content = row["msgContent"] or ""

    @property
    def time_str(self):
        return _ms(self.ts)

    def __repr__(self):
        return "<Msg %s %s %r>" % (self.time_str, self.sender, self.text[:18])




# session 摘要文本 → msgType：只认明确的媒体/系统标记，其余一律当文本。
# 为什么不把所有 [xx] 都当表情：她的贴纸在 chatmsg 里本来就是「[狗子]」这种文本，
# 判成 emoji 会走固定话术、把上下文丢掉（实测库内 15486 条里这类很多）。
_DIGEST_MEDIA = (
    ("[语音]", 5), ("[图片]", 2), ("[照片]", 2), ("[视频]", 2),
    ("[文件]", 2), ("[链接]", 2),
)
_DIGEST_TIP = ("[当前版本过低", "[互动消息]", "[系统", "[戳一下]")


def _digest_mt(text):
    """session.lastMsgText -> msgType。"""
    t = (text or "").strip()
    for k, mt in _DIGEST_MEDIA:
        if t.startswith(k):
            return mt
    for k in _DIGEST_TIP:
        if t.startswith(k):
            return MSG_SYS2
    return MSG_TEXT

class IMDB(object):
    """一个账号的 IM 库。path 指向本地缓存副本（由 sync 维护）。"""

    def __init__(self, path, uid=None):
        self.path = Path(path)
        self._con = None
        self.uid = uid or self._guess_uid()
        # 🔴 2026-11-08 21:2x：把 device 引用挂到库对象上。
        #   `data/pending.py` 的「设备存活校验」用 getattr(db, "dev", None)，
        #   而这个属性从来没有被赋过值 → 那层过滤**从来没生效**，
        #   于是日志一直显示「待回 71 人（未读 6 / 已读未回 65）」，真实候选只有 9 个。
        #   数字虚高会误导判断（也会影响红点闸的判据），这里补上。
        self.dev = None

    # ---------- 连接 ----------
    def _usable_path(self):
        """返回一个「能读到 wal 尾部」的库路径（必要时用干净快照）。

        🔴 2026-11-04 必回盲区（实测对照，同一份 db+wal）：
          · 带设备拉下来的旧 -shm → 只读读成 unread=0、末条 07:02（她 08:12 的话不存在）
          · 只 db+wal（无 shm）    → 读到 unread=2、08:12:52「没忙什么」
          shm 是 App 进程的 mmap 索引，比 wal 旧时 SQLite 会按它的 mxFrame 截断 wal，
          于是 latest() 判「最后一条是我发的」→ candidates 静默吞掉必回。
        处理：能删就删（SQLite 自己重建）；删不掉（句柄被本进程/别的进程占着）
        就把 db+wal 复制成 `<db>-snap.db`（全新 inode → shm 必然重建）再打开。
        """
        wal = Path(str(self.path) + "-wal")
        shm = Path(str(self.path) + "-shm")
        if not wal.exists() or wal.stat().st_size == 0:
            return self.path
        if not shm.exists() or shm.stat().st_mtime >= wal.stat().st_mtime:
            return self.path
        try:
            shm.unlink()
            log.info("删除陈旧 shm（%s）→ SQLite 重建后即可读到 wal 尾部", self.path.name)
            return self.path
        except OSError:
            pass
        snap = Path(str(self.path) + "-snap.db")
        try:
            import shutil
            for suf in ("-shm", "-wal", ""):
                q = Path(str(snap) + suf)
                if q.exists():
                    try:
                        q.unlink()
                    except OSError:
                        pass
            shutil.copy2(str(self.path), str(snap))
            shutil.copy2(str(wal), str(snap) + "-wal")
            # FIX 2026-11-12 P0-1: snapshot integrity check
            #   copy2 of actively-written WAL db can produce corrupt snapshot
            #   ("file is not a database"), causing _guess_uid() to return
            #   None and open_account() to fail with "uid mismatch".
            #   Verify snapshot; on failure fall back to main db (valid uid).
            try:
                import sqlite3 as _sq
                _v = _sq.connect(str(snap))
                try:
                    _r = _v.execute("PRAGMA integrity_check").fetchone()
                    if not _r or str(_r[0]).lower() != "ok":
                        raise RuntimeError("integrity_check: %r" % (_r,))
                    _v.execute("SELECT COUNT(*) FROM session LIMIT 1").fetchone()
                finally:
                    _v.close()
            except Exception as _ie:
                log.warning(
                    "快照 integrity 校验失败（%d KB wal）→ 回退主库：%r",
                    int(wal.stat().st_size / 1024), _ie)
                return self.path
            log.info("陈旧 shm 删不掉 → 用快照 %s 打开（%d KB wal）",
                     snap.name, int(wal.stat().st_size / 1024))
            return snap
        except Exception as e:      # noqa: BLE001
            log.warning("快照失败，退回原库（可能读不到 wal 尾部）: %r", e)
            return self.path

    @property
    def con(self):
        if self._con is None:
            if not self.path.exists():
                raise RuntimeError("库不存在: %s" % self.path)
            p = self._usable_path()
            self._con = sqlite3.connect("file:%s?mode=ro" % p.as_posix(),
                                        uri=True, timeout=5)
            self._con.row_factory = sqlite3.Row
        return self._con

    def close(self):
        if self._con is not None:
            self._con.close()
            self._con = None

    def _guess_uid(self):
        """自己 uid。

        实测规律：sessionId = 自己uid + str(toUserId) 直接拼接，长度不定。
        例如 96691646 + 204268346 -> '96691646204268346'。
        所以用 sid 去掉 toUid 后缀反推，取众数；失败再退回 chatmsg 里发文本最多的人。
        """
        try:
            rows = self.con.execute(
                "SELECT sessionId, toUserId FROM session WHERE sessionId IS NOT NULL "
                "AND toUserId IS NOT NULL LIMIT 300"
            ).fetchall()
        except Exception:
            return None
        votes = {}
        for sid, touid in rows:
            sid, touid = str(sid), str(touid)
            if touid and sid.endswith(touid) and len(sid) > len(touid):
                pre = sid[: -len(touid)]
                votes[pre] = votes.get(pre, 0) + 1
        if votes:
            return max(votes.items(), key=lambda kv: kv[1])[0]
        try:
            row = self.con.execute(
                "SELECT senderId, COUNT(*) c FROM chatmsg WHERE msgType = ? "
                "GROUP BY senderId ORDER BY c DESC LIMIT 1", (MSG_TEXT,)).fetchone()
            return str(row[0]) if row else None
        except Exception:
            return None

    # ---------- 查询 ----------
    def sessions(self, unread_only=False, include_official=True, limit=0):
        sql = "SELECT * FROM session"
        args = []
        if unread_only:
            sql += " WHERE unReadCount > 0"
        sql += " ORDER BY timestamp DESC"
        if limit:
            sql += " LIMIT %d" % int(limit)
        out = []
        for row in self.con.execute(sql, args):
            s = Session(row)
            if not include_official and s.is_official:
                continue
            out.append(s)
        return out

    def session(self, session_id):
        row = self.con.execute(
            "SELECT * FROM session WHERE sessionId = ?", (session_id,)).fetchone()
        return Session(row) if row else None

    def messages(self, session_id, limit=20, skip_system=True):
        """按时间正序返回最近 limit 条。

        skip_system=True 时排除 msgType=27（系统引导卡片），
        否则「最后一条」会被系统卡片污染 —— 实测 204268346 等会话就是这种。
        """
        sql = "SELECT * FROM chatmsg WHERE sessionId = ?"
        if skip_system:
            sql += " AND msgType NOT IN (%d,%d)" % SYS_TYPES
        sql += " ORDER BY localTime DESC LIMIT %d" % int(limit)
        rows = [Msg(r) for r in self.con.execute(sql, (session_id,))]
        rows.reverse()
        return rows

    def last_message(self, session_id, skip_system=True):
        ms = self.messages(session_id, limit=1, skip_system=skip_system)
        return ms[0] if ms else None

    # ---------- session 摘要：入向不落 chatmsg 时的唯一可信来源 ----------
    def session_digest(self, session_id):
        """session 表里的「最新一条」摘要，dict 或 None。

        🔴 2026-11-04（必回闭环·数据链，实测 402857053）：
          该号 App **只更新 session（unReadCount/lastMsgText），不写 chatmsg 入向**
          —— 24h chatmsg 入向 1 条，而 session 里有她 07:17 的新话「可能手滑了吧」。
          于是所有「只读 chatmsg」的判定全盲（切号后 4.5h 实测）：
            末条判定 → 误判「最后一条是我发的 → 无需回复」39 次
            文本反查 sid → 「反查不到 sessionId」88 次
            身份校验 → fail-closed 永远不发 63 次
          session.lastMsgText 与列表红点是同一份数据，必须纳入。
        """
        try:
            r = self.con.execute(
                "SELECT toUserId, unReadCount, lastMsgText, timestamp, chatType "
                "FROM session WHERE sessionId = ?", (session_id,)).fetchone()
        except Exception as e:
            log.debug("读 session 摘要异常: %r", e)
            return None
        if r is None:
            return None
        return {
            "to_uid": str(r["toUserId"] or ""),
            "unread": int(r["unReadCount"] or 0),
            "text": (r["lastMsgText"] or "").strip(),
            "ts": int(r["timestamp"] or 0),
            "chat_type": r["chatType"],
        }

    def my_recent_texts(self, session_id, limit=40):
        """我最近发过的文本集合（判摘要最后一句到底是谁说的）。"""
        out = set()
        try:
            for m in self.messages(session_id, limit=limit):
                if str(m.sender) == str(self.uid) and (m.text or "").strip():
                    out.add((m.text or "").strip())
        except Exception:
            pass
        return out

    def my_text_ts(self, session_id, text, limit=60):
        """我发过这句的最近时间（毫秒），没有则 0。

        🔴 为什么需要（2026-11-04）：她说的可能和我曾说过的一模一样
          （「哈哈」「在的」「嗯」）。只按文本判方向会把她的话当成我说的 →
          永不回复（漏回 = 最差失败模式）。所以再用**时间邻近**做一次交叉验证：
          摘要时间必须贴近我发那句的时间，才算同一句。
        """
        text = (text or "").strip()
        if not text:
            return 0
        best = 0
        try:
            for m in self.messages(session_id, limit=limit):
                if str(m.sender) != str(self.uid):
                    continue
                if (m.text or "").strip() == text:
                    best = max(best, int(m.ts or 0))
        except Exception:
            pass
        return best

    def latest(self, session_id):
        """会话最新一条：(Msg|None, source)，source ∈ {"db", "session", ""}。

        取 chatmsg 末条与 session 摘要里**时间更新**的那个。
        摘要若是我自己最后说的（文本命中 my_recent_texts）→ 合成 sender=uid，
        上层照旧判「我发的 → 无需回复」，不会因为她没回就重复发。

        🔴 实测（402857053，2026-11-04）：chatmsg 末条停在 87h 前，session 却是
          3 分钟前 —— 只看 chatmsg 会把她刚说的话当空气，回出来全是 3 天前的上下文
          （这就是「答非所问」的根因，不是模型笨）。
        """
        msg = self.last_message(session_id)
        dig = self.session_digest(session_id)
        if not dig or not dig["text"]:
            return msg, ("db" if msg is not None else "")
        d_ts, d_txt = int(dig["ts"] or 0), dig["text"]
        m_ts = int(getattr(msg, "ts", 0) or 0)
        if msg is not None and d_ts <= m_ts:
            return msg, "db"
        mine = d_txt in self.my_recent_texts(session_id)
        if mine:
            # 时间窗交叉验证：隔了 3 分钟以上 → 不是同一句，是她说了同样的话
            ts_mine = self.my_text_ts(session_id, d_txt)
            if not ts_mine or abs(d_ts - ts_mine) > 180000:
                mine = False
        sender = str(self.uid) if mine else str(dig["to_uid"] or "")
        return Msg({
            "msgId": "", "sessionId": session_id,
            "senderId": sender, "receiverId": str(dig["to_uid"] or ""),
            "localTime": d_ts, "msgType": _digest_mt(d_txt),
            "msgStatus": 0, "text": d_txt, "msgContent": "",
        }), "session"

    def digest_matches(self, session_id, texts, min_len=2):
        """当前会话的摘要文本是否出现在 texts 里（身份校验的强证据）。

        🔴 用途：pendingq 进会话后要确认「这是不是候选那个人」。原来只能拿
          气泡文本去 chatmsg 反查 —— 入向不落库的账号上必然失败 → fail-closed
          永远不发（实测「[狗子]」「那不知道」各失败 10 次）。
          摘要就是列表预览，和屏幕上的最后一句话必然一致，是最稳的一条证据。
        """
        dig = self.session_digest(session_id)
        if not dig or not dig["text"]:
            return False
        want = (dig["text"] or "").strip()
        if len(want) < min_len:
            return False
        for t in texts:
            t = (t or "").strip()
            if not t or len(t) < min_len:
                continue
            if t == want or (len(t) >= 4 and (want.startswith(t) or t.startswith(want))):
                return True
        return False

    def pending(self, min_gap_s=0):
        """待回会话：有未读 / 非官方 / 最后一条是对方发的。

        返回按最后消息时间正序（先回最久没回的）。
        """
        out = []
        for s in self.sessions(unread_only=True, include_official=False):
            last = self.last_message(s.session_id)
            if last is None:
                continue
            if self.uid and str(last.sender) == str(self.uid):
                continue          # 最后一条是我发的 -> 不算待回
            if min_gap_s and (time.time() * 1000 - int(s.ts)) < min_gap_s * 1000:
                continue
            out.append((s, last))
        out.sort(key=lambda x: x[0].ts)
        return out

    def stats(self):
        return {
            "sessions": self.con.execute("SELECT COUNT(*) FROM session").fetchone()[0],
            "unread": self.con.execute(
                "SELECT COUNT(*) FROM session WHERE unReadCount>0").fetchone()[0],
            "unread_total": self.unread_total(),
            "messages": self.con.execute("SELECT COUNT(*) FROM chatmsg").fetchone()[0],
            "uid": self.uid,
        }

    def sessions_for_texts(self, texts, min_len=2, unread_only=False):
        """用「会话里可见的消息文本」反查 sessionId（chatmsg + session 摘要）。

        UI 列表行里没有 uid、昵称也不在库里，只能靠原文反查。加权规则
        （数值越大越可信）：
          session.lastMsgText 精确  3  ← 列表预览就是它，而且是**最新**那句
          chatmsg.text 精确         2
          session.lastMsgText 前缀  2  ← 预览被截断（「...」）时只能前缀比
          chatmsg.text 前缀         1
          目标会话有未读红点        +1  ← 红点=她刚发，与「该回谁」语义一致

        🔴 2026-11-04（必回闭环）：402857053 号入向不落 chatmsg 时，
          原来只查 chatmsg → 她刚发的话**必然**反查不到（88 次/4.5h），
          流程退化成「仅凭 OCR」或 fail-closed。session 摘要必须一起查。

        unread_only=True 时只统计有红点的会话（短文本 2~3 字专用，防撞车）。
        """
        hits = {}
        unread = {}
        try:
            for r in self.con.execute(
                    "SELECT sessionId, unReadCount FROM session"):
                unread[str(r["sessionId"])] = int(r["unReadCount"] or 0)
        except Exception:
            pass

        def _add(sid, w):
            sid = str(sid)
            if unread_only and unread.get(sid, 0) <= 0:
                return
            hits[sid] = hits.get(sid, 0) + w

        def _q(sql, arg, w):
            try:
                for (sid,) in self.con.execute(sql, arg).fetchall():
                    _add(sid, w)
            except Exception:
                pass

        for t in texts:
            t = (t or "").strip()
            if len(t) < min_len:
                continue
            _q("SELECT DISTINCT sessionId FROM session WHERE lastMsgText = ? LIMIT 30",
               (t,), 3)
            _q("SELECT DISTINCT sessionId FROM chatmsg WHERE text = ? LIMIT 30",
               (t,), 2)
            if len(t) >= 4:
                _q("SELECT DISTINCT sessionId FROM session "
                   "WHERE lastMsgText LIKE ? LIMIT 30", (t + "%",), 2)
                _q("SELECT DISTINCT chatmsg.sessionId FROM chatmsg "
                   "WHERE text LIKE ? LIMIT 30", (t + "%",), 1)
        for sid in list(hits):
            if unread.get(sid, 0) > 0:
                hits[sid] += 1
        return sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))

    def unread_total(self):
        """全部会话未读数之和。

        业务硬约束（用户 2026-11-02 定）：**红点必须清零才允许进星球匹配**。
        调度层用本方法做闸，不要用像素判红点。
        """
        r = self.con.execute(
            "SELECT SUM(unReadCount) FROM session WHERE unReadCount > 0").fetchone()
        return int(r[0] or 0)


# ---------------- 同步：从设备拉库到本地缓存 ----------------
def list_device_dbs(device):
    """列出设备上所有 IM-SDK 库（文件名里含 -DATA.db）。

    🔴 2026-11-08 10:42（生产实测修复）：
      `/data/data/cn.soulapp.android/databases` 是 **u0_a52 私有目录**，
      非 root 的 adb shell 读它必然 `Permission denied`（实测 10:35）。
      改前直接 `ls` 且把 stderr 混进 stdout 一起解析 → 拿到空列表
      → `open_account()` 抛「设备上没有 IM-SDK 库」→ **整个 daemon 瘫痪**。
      改法：优先 `su -c ls`，失败再退回普通 `ls`（兼容已 root/adb root 的环境）。
    """
    names = []
    for cmd in ("su -c 'ls %s'" % DB_DIR_ANDROID, "ls %s" % DB_DIR_ANDROID):
        try:
            out = device.text(cmd)
        except Exception:
            continue
        for line in (out or "").replace("\r", "").split("\n"):
            n = line.strip()
            if n.startswith("IM-SDK-") and n.endswith("-DATA.db"):
                names.append(n)
        if names:
            break
    # 去重（su 与普通 ls 可能各拿到一次）
    seen, uniq = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _merge_device_into_mirror(device, name, local, dest_dir):
    """设备库缩水时：把设备侧**新增行合并进本地镜像**（历史保留），而不是跳过同步。

    🔴 2026-11-08 21:0x（P0「消息几小时才回」的真根因，实测）：
      旧实现是「设备库 < 本地 50% → `return local`」，等于**一次都不同步**。
      而 Soul 今天 10:25 把账号库清空（9.0MB → 167KB），本地镜像从 **09:29 起彻底冻结**：
      她 19:56「为啥呀」、20:21「好吧」只存在于设备库，镜像里末条仍是我早上发的那句
      → `candidates()` 判「最后一条是我发的」→ 静默跳过，几条消息等了几小时没人回。
      当天 107 条回复里 16-20 点只有 12 条，其余全靠红点 OCR 撞运气。

      正确姿势：设备库仍是**新消息的唯一来源**，把它并进镜像：
        · chatmsg：按 msgId 唯一索引 INSERT OR IGNORE（不重复、不丢历史）
        · session ：按 sessionId UPSERT 未读/时间/摘要（这几列以设备为准）
    返回 (新增消息数, 变更会话数)；任何一步失败返回 None，调用方按旧行为用镜像继续跑。
    """
    import sqlite3

    tmp_dir = dest_dir / "_merge"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp_db = tmp_dir / name
    for suffix in ("", "-wal", "-shm"):
        p = tmp_dir / (name + suffix)
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
    for suffix in ("", "-wal"):
        src = "%s/%s%s" % (DB_DIR_ANDROID, name, suffix)
        rc, _out, err = device.run(["pull", src, str(tmp_dir / (name + suffix))], timeout=120)
        if rc != 0 and suffix == "":
            log.warning("合并设备库：pull 失败 %r", err[:120])
            return None
    if not tmp_db.exists():
        return None

    con = sqlite3.connect(str(local))
    try:
        con.execute("ATTACH DATABASE ? AS dev", (str(tmp_db),))

        def cols(table, schema="main"):
            try:
                return [r[1] for r in con.execute("PRAGMA %s.table_info(%s)" % (schema, table))]
            except Exception:
                return []

        main_cols = cols("chatmsg")
        dev_cols = set(cols("chatmsg", "dev"))
        use = [c for c in main_cols if c != "id" and c in dev_cols]
        if not use or "msgId" not in use:
            log.warning("合并设备库：chatmsg 列不匹配（main=%d dev=%d）", len(main_cols), len(dev_cols))
            return None
        before = con.total_changes
        con.execute("INSERT OR IGNORE INTO main.chatmsg (%s) SELECT %s FROM dev.chatmsg"
                    % (", ".join(use), ", ".join(use)))
        new_msgs = con.total_changes - before

        s_cols = cols("session")
        s_dev = set(cols("session", "dev"))
        s_use = [c for c in s_cols if c != "id" and c in s_dev]
        touched = 0
        if s_use and "sessionId" in s_use:
            upd = [c for c in s_use if c != "sessionId"]
            before2 = con.total_changes
            con.execute(
                "INSERT INTO main.session (%s) SELECT %s FROM dev.session WHERE 1 "
                "ON CONFLICT(sessionId) DO UPDATE SET %s"
                % (", ".join(s_use), ", ".join(s_use),
                   ", ".join("%s=excluded.%s" % (c, c) for c in upd)))
            touched = con.total_changes - before2
        con.commit()
        try:
            con.execute("DETACH DATABASE dev")
        except Exception:
            pass
        return new_msgs, touched
    except Exception as e:
        log.warning("合并设备库到镜像失败: %r", e)
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def sync(device, name, dest_dir=None, keep=3, retries=3):
    """把设备上的一个库（db+wal+shm）拉到本地缓存。返回本地路径。

    🔴 一致性坑（2026-11-02 实测，导致过 `database disk image is malformed`）：
      App 一直在写库，我们逐文件 pull 时，**db 和 wal 拿到的是两个不同时刻的状态**
      → 本地打开时应用 wal 失败 → 整个库报 malformed，所有查询全崩（daemon 停摆）。
    修法：
      ① 先删本地三个文件再拉（避免旧文件残留混进新库）
      ② 拉完立刻做 `PRAGMA integrity_check`
      ③ 坏了就重拉，最多 retries 次；全失败抛异常让上层知道
    """
    import sqlite3

    dest_dir = Path(dest_dir or CACHE) / name.replace("-DATA.db", "")
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / name

    # 🔴🔴🔴 2026-11-08 10:38（用户硬规则：两个账号的库必须分开，不能串）
    #
    #   【事故预防·数据不可恢复】设备上**被登出的账号，库会被 Soul 清空/截断**：
    #     实测 10:35 —— 96691646 登出后，它的库从 14.2MB(20900 条) 掉到 76KB。
    #   而下面的 `_pull_all()` 第一步就是**删掉本地三个文件**再 pull，
    #   所以只要有人（或定时任务）在当前登录 402 的情况下调一次
    #   `sync(966的库)`，本地 20900 条历史就被 76KB 空库永久覆盖。
    #
    #   保护：**先量设备侧库大小，再和本地比**。
    #     · 设备库 >= 本地 50%  → 正常增量，放行
    #     · 设备库 <  本地 50%  → 判定「被清空/被截断」，**拒绝同步**并抛异常
    #       （上层 open_account 会捕获降级，这一轮不跑，但历史数据保住）
    #   同时把本地库先另存 `*.keep`，万一判断失误也还能人工找回。
    #
    #   为什么用文件大小而不是行数：行数要先打开库（可能 malformed），
    #   大小用 `stat` 一条命令 0.05s，且 14.2MB→76KB 这种量级差不会误判。
    _dev_sz, _loc_sz = 0, 0
    try:
        if local.exists():
            _loc_sz = local.stat().st_size
        # 🔴 注意：这里不能写 "stat -c %%s %s/%s" % (...) —— 两个 %s 会被
        #   stat 的格式串吃掉（实测 TypeError）。用 + 拼接最稳。
        #
        # 🔴🔴 2026-11-08 12:3x（保护失效的真根因，实测发现）：
        #   原来这里写的是 `su -c 'stat ...'`，但**本环境根本没有 su**
        #   （`/system/bin/sh: su: inaccessible or not found`），
        #   而 adb shell 本身就是 **root**（`whoami` → root），
        #   根本不需要 su。结果：命令永远失败 → `_dev_sz` 永远 0
        #   → 下面 `_dev_sz > 0` 永远为假 → **保护逻辑从未生效过一次**。
        #   后果：Soul 清空设备库后，sync() 照常 pull，把本地 14.2MB 历史
        #   覆盖成 76KB 空库（实测 11-08 10:35 与 12:30 各发生一次）。
        #   修法：先试不带 su 的裸 stat（root shell 直接可读），失败再退回 su。
        _stat_cmd = "stat -c %s " + DB_DIR_ANDROID + "/" + name
        _rc, _out, _ = device.run(["shell", _stat_cmd], timeout=20)
        if isinstance(_out, (bytes, bytearray)):
            _out = _out.decode("utf-8", "replace")
        _txt = (_out or "").strip().splitlines()
        if not (_txt and _txt[-1].strip().isdigit()):
            # 退回 su 形态（有些设备 shell 非 root，需要 su）
            _cmd2 = "su -c 'stat -c %s " + DB_DIR_ANDROID + "/" + name + "'"
            _rc, _out, _ = device.run(["shell", _cmd2], timeout=20)
            if isinstance(_out, (bytes, bytearray)):
                _out = _out.decode("utf-8", "replace")
            _txt = (_out or "").strip().splitlines()
        if _txt and _txt[-1].strip().isdigit():
            _dev_sz = int(_txt[-1].strip())
        else:
            log.debug("量设备库大小失败（原始输出 %r）—— 保护无法生效", (_txt or [])[-3:])
    except Exception as _e:
        log.debug("量库大小失败（跳过保护）: %r", _e)
        _dev_sz, _loc_sz = 0, 0

    if _loc_sz > 2 * 1024 * 1024 and _dev_sz > 0 and _dev_sz < _loc_sz * 0.5:
        # 🔴🔴 2026-11-08 10:52（生产实测修正：光"拒绝"会让 daemon 完全瘫痪）
        #
        #   实测：Soul 在 10:25~10:49 把**两个账号的库都清空了**
        #     96691646：2 个 session / 50 条 chatmsg（原 1500/20900）
        #     402857053：54 个 session / 60 条 chatmsg（原 1298/10590）
        #   如果这里直接 raise，`open_account()` 就永远拿不到库
        #   → daemon 每轮都抛异常 → 整个机器人瘫痪（比数据被覆盖更糟）。
        #
        #   正确做法（既保数据又不瘫痪）：
        #     · 先把本地镜像备份成 `.keep`（人工可找回）
        #     · **不覆盖本地库**，直接**继续用本地镜像**（它是最近一次的真实快照）
        #     · 打 warning 说清「设备库被清空，本轮用本地镜像」
        #   注意：本地镜像会比设备旧，所以 `watch`/`dirty` 判定要允许这种陈旧，
        #   否则会陷入「库比设备旧 → 一直强制刷新 → 一直走这条分支」的循环。
        try:
            keep = dest_dir / (name + ".keep")
            if not keep.exists():
                import shutil as _sh
                _sh.copy2(str(local), str(keep))
                log.warning("已把本地镜像另存为 %s", keep.name)
        except Exception as _e:
            log.debug("存 .keep 失败: %r", _e)
        log.warning(
            "设备库 %s 只剩 %.0fKB（本地镜像 %.1fMB）—— 疑似 Soul 已清空该账号记录，"
            "**保留本地镜像、本轮用它继续跑**（不覆盖、不报错）",
            name[:28], _dev_sz / 1024.0, _loc_sz / 1048576.0)
        # 🔴 2026-11-08 21:0x：**不再直接 return**。镜像冻结是「消息几小时不回」的
        #   真根因（详见 _merge_device_into_mirror 注释）。设备库仍是新消息唯一来源，
        #   把新增行并进镜像即可：历史保留 + 新消息可见，两个目标同时满足。
        _mg = _merge_device_into_mirror(device, name, local, dest_dir)
        if _mg is not None:
            log.warning("设备库缩水 → 已增量合并进镜像：新增消息 %d 条 / 更新会话 %d 个"
                        "（历史行全部保留）", _mg[0], _mg[1])
        else:
            log.warning("设备库缩水 → 增量合并失败，本轮继续用本地镜像（可能看不到最新消息）")
        # 🔴🔴 2026-11-12（DS-07：缩水合并分支缺 wal_checkpoint(TRUNCATE)）
        #   正常 sync 的 _pull_all 尾部（见 830 行）会在合并后做
        #   `PRAGMA wal_checkpoint(TRUNCATE)`，但**缩水分支**直接 return local，
        #   不经过它 —— 于是 `_merge_device_into_mirror` 写入主库后遗留的
        #   -wal/-shm 若比主库旧，后续只读连接会按旧 shm 截断 wal 尾部，
        #   把刚并进镜像的新消息「看没了」（与 2026-11-04 必回盲区同根因）。
        #   修法：与 _pull_all 一致，缩水合并后也 checkpoint 一次（幂等、只读安全）。
        try:
            import sqlite3 as _sq
            _c = _sq.connect(str(local), timeout=5)
            try:
                _r = _c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                log.info("缩水合并后 wal checkpoint -> %r", _r)
            finally:
                _c.close()
        except Exception as _e_cp:
            log.warning("缩水合并后 wal checkpoint 失败（只影响读到 wal 尾部）: %r", _e_cp)
        return local

    def _pull_all():
        # 🔴 2026-11-13 修复 DS-03（P1 失败同步毁掉本地镜像）：**删本地前先备份**。
        #    原来正常增量路径第一步就删本地 db/wal/shm（777-784），随后才 pull；
        #    pull 失败（rc!=0）或 integrity 不过时，本地历史镜像（14.2MB/20900 条）
        #    已永久删除且无备份（缩水保护只在「设备<本地 50%」分支做 .keep）。
        #    改：删前 copy2 到 `.keep`，失败后能恢复（或至少不丢历史）。
        _keep_files = []
        for suffix in ("", "-wal"):
            p = dest_dir / (name + suffix)
            if p.exists():
                try:
                    kp = dest_dir / (name + suffix + ".keep")
                    import shutil as _sh
                    _sh.copy2(str(p), str(kp))
                    _keep_files.append(kp)
                except Exception as _ke:
                    log.warning("DS-03 备份 %s 失败（继续）: %r", p.name, _ke)
        # ① 先删（旧 wal 残留会让新库被判损坏）
        for suffix in ("", "-wal", "-shm"):
            p = dest_dir / (name + suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # 🔴 2026-11-04（必回盲区根因）：**不 pull 设备侧的 -shm**。
        #    实测对照（同一份 db+wal）：
        #      · 带着设备 shm → 只读连接读成 unread=0、末条 07:02（旧值）
        #      · 只拷 db+wal   → 读到 unread=2、08:12:52「没忙什么」（真值）
        #    shm 是 App 进程的 mmap 索引，跨机器/跨时刻都无意义；一旦比 wal 旧，
        #    SQLite 就按它的 mxFrame 截断 wal 尾部 ⇒ 她最新的话在库里「不存在」，
        #    latest() 判「最后一条是我发的」→ candidates 静默吞掉必回。
        #    本地 shm 由 SQLite 打开时自行重建，不需要也不该从设备搬。
        for suffix in ("", "-wal"):
            src = "%s/%s%s" % (DB_DIR_ANDROID, name, suffix)
            dst = str(dest_dir / (name + suffix))
            rc, out, err = device.run(["pull", src, dst], timeout=120)
            if rc != 0 and suffix == "":
                # 🔴 DS-03：pull 失败时恢复备份，别让本地镜像裸奔（历史数据优先）。
                for _k in _keep_files:
                    try:
                        import shutil as _sh2
                        _sh2.copy2(str(_k), str(dest_dir / _k.name[:-5]))
                    except Exception as _re:
                        log.warning("DS-03 恢复备份 %s 失败: %r", _k.name, _re)
                raise RuntimeError("pull 失败 %s: %r" % (src, err[:160]))
        stale_shm = dest_dir / (name + "-shm")
        if stale_shm.exists():
            try:
                stale_shm.unlink()
            except OSError:
                pass

    def _ok():
        try:
            con = sqlite3.connect(str(local))
            try:
                r = con.execute("PRAGMA integrity_check").fetchone()
                if not r or r[0] != "ok":
                    return False
                con.execute("SELECT COUNT(*) FROM chatmsg").fetchone()
                return True
            finally:
                con.close()
        except Exception:
            return False

    last_err = None
    for i in range(max(1, retries)):
        try:
            _pull_all()
        except Exception as e:
            last_err = e
            log.warning("第 %d 次 pull 失败: %r", i + 1, e)
            time.sleep(0.8)
            continue
        if _ok():
            break
        last_err = RuntimeError("拉下来的库不一致")
        log.warning("第 %d 次拉到的库 integrity 不通过（App 正在写），重试", i + 1)
        time.sleep(1.0)
    else:
        raise RuntimeError("拉库连续 %d 次都不一致: %r" % (retries, last_err))

# 🔴 2026-11-04（必回盲区根治，实测）：把 -wal 合并进主库。
#    现象：设备侧 App 一直在写 wal，我们逐文件 pull 后本地 -shm 还是上一轮的旧索引
#    （08:20 那次 sync：-wal mtime 08:20:35，-shm 却停在 07:52:37）。SQLite 打开时
#    按旧 shm 的 mxFrame 截断 wal ⇒ **只读连接看不到她 08:12「没忙什么」/ 08:17「[疑惑][疑问]」**
#    （库里把 72803535 读成 unread=0 / 末条 07:02 的我方消息），latest() 就判
#    「最后一条是我发的」→ candidates 直接 skip，必回被静默吞掉。
#    checkpoint(TRUNCATE) 后主库即完整快照，只读连接不再依赖 shm/wal。
    try:
        _c = sqlite3.connect(str(local), timeout=5)
        try:
            _r = _c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            log.info("wal checkpoint -> %r", _r)
        finally:
            _c.close()
    except Exception as e:
        log.warning("wal checkpoint 失败（只影响读到 wal 尾部）: %r", e)

    # 简单清理：只留最近 keep 份库（按 mtime）
    files = sorted(dest_dir.glob("*.db*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep * 3:]:
        try:
            p.unlink()
        except OSError:
            pass
    return local


def current_uid(device):
    """当前登录账号 uid。

    来源：`shared_prefs/sp_info_gather.xml` 里的 <string name="userid">。
    实测 2026-11-02：UI 显示「离殇描绘未来时光」时该值为 402857053，一致。
    切号后此值会变，所以每次都要现读，不能缓存。

    🔴 2026-11-08 10:42（生产实测修复）：
      shared_prefs 同样是 u0_a52 私有目录，非 root 读不到（实测 10:35 返回空）。
      改前只试了非 root 的 `cat`，于是 `current_uid()` 恒返回 None
      → `open_account()` 走 `if not want:` 分支拿第一个库 → **可能拿错账号的库**。
      这正是用户担心的「用 A 的聊天记录去 B 账号搜」。
      改法：先 `su -c cat`，失败再退回普通 `cat`。
    """
    for cmd in ("su -c 'cat %s 2>/dev/null'" % SP_INFO,
                "cat %s 2>/dev/null" % SP_INFO):
        try:
            out = device.text(cmd, timeout=30) or ""
        except Exception:
            continue
        m = re.search(r'name="userid">(\d+)<', out)
        if m:
            return m.group(1)
    return None


_LAST = {"ts": 0.0, "db": None, "uid": ""}
REFRESH_S = 300          # 本地库缓存有效期（用户 2026-11-02：5~10 分钟同步一次就够）


# 🔴🔴 2026-11-08 10:45（用户硬规则：「模拟器内的实时库 只允许读 不允许写」）
#
#   铁律落成代码闸：任何发往**设备侧**的 SQL 必须先过这道检查。
#   白名单 = 只允许以 SELECT / WITH 开头（WITH 用于 CTE，仍只读）。
#   注意：设备端 sqlite3 是以 **root** 跑的（`su -c`），一旦写了没有任何回滚余地，
#        所以闸放在最外层，宁可误拦也不放过。
_WRITE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"vacuum|reindex|pragma\s+\w+\s*=)\b", re.I)


def _assert_readonly(sql):
    """拒绝任何非只读 SQL（发往设备的库）。返回 True 表示安全。"""
    s = (sql or "").strip().lstrip(";").strip()
    if not s:
        return False
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        log.error("⛔ 拒绝非只读 SQL（设备库只读）: %r", s[:120])
        return False
    if _WRITE_RE.search(s):
        log.error("⛔ 拒绝含写操作的 SQL（设备库只读）: %r", s[:120])
        return False
    return True


def _dev_sql(device, dbname, sql, timeout=15):
    """在设备上对指定库跑一条**只读** SQL，返回原始文本（失败返回 ""）。

    抽出来只为让下面的函数少重复那串 `sqlite3 "路径" "SQL"` 样板。

    🔴🔴 2026-11-08 10:45 用户硬规则：「模拟器内的实时库只允许读，不允许写」。
      本函数是所有「设备侧 SQL」的唯一出口，因此在这里加**强制只读闸**：
        · 只放行 SELECT / WITH 开头
        · 命中 insert/update/delete/drop/alter/create/replace/truncate/
          attach/vacuum/pragma xxx= 任一关键字 → 直接拒绝并 error 日志
      这样即使将来有人（或我）写错一句 UPDATE，也不会真的打到设备库上。
      注意：读也走 `su -c`（u0_a52 私有目录，非 root 读不到），
      所以「只读」必须由代码保证，不能依赖文件权限。
    """
    if not _assert_readonly(sql):
        return ""
    # 🔴🔴 2026-11-08 12:59（第二次踩 `su` 这个坑，这次是**错误被当成结果返回**）
    #
    #   本模拟器上 **`su` 根本不存在**（adb shell 本身已经是 root，
    #   `whoami` → root），所以 `su -c '...'` 返回的是：
    #       /system/bin/sh: su: inaccessible or not found
    #   而 `2>&1` 把这句错误**混进 stdout**，`device.text()` 正常返回了它，
    #   于是 `except` 分支永远不触发 → 上层拿到一段「看起来像输出」的报错文本，
    #   解析出空集合 → `_db_name_for_uid` 永远返回 None → 存活校验永远降级。
    #
    #   这和 imdb.sync() 里那个「su 不存在导致截断保护永不生效」是**同一个根因**
    #   （见 2026-11-08 上午的修复）。同一个坑踩两次，所以这次在**唯一出口**处根治：
    #     ① 先试裸命令（本环境 adb 已是 root，直接就能读）；
    #     ② 裸命令失败/报 su 类错误，再退回 `su -c`（兼容真正需要 su 的环境）；
    #     ③ 任何情况下，输出里出现 "su: inaccessible"/"not found"/"Permission denied"
    #        一律判为失败，返回 ""，绝不当成数据往上传。
    _ERR_MARKS = ("su: inaccessible", "su: not found", "Permission denied",
                  "No such file or directory", "inaccessible or not found")

    def _clean(txt):
        t = (txt or "").strip()
        for m in _ERR_MARKS:
            if m.lower() in t.lower():
                return ""
        return t

    # ① 裸 sqlite3（本环境首选：adb 已 root）
    try:
        out = _clean(device.text('sqlite3 "%s/%s" "%s" 2>&1'
                                 % (DB_DIR_ANDROID, dbname, sql), timeout=timeout))
        if out:
            return out
    except Exception:
        pass
    # ② 退回 su -c（兼容非 root adb 环境）
    try:
        return _clean(device.text('su -c \'sqlite3 "%s/%s" "%s"\' 2>&1'
                                  % (DB_DIR_ANDROID, dbname, sql), timeout=timeout))
    except Exception:
        return ""


def _parse_kv(txt):
    """把 `a|1` 逐行解析成 {a: 1}（非法行直接跳过）。"""
    out = {}
    for ln in (txt or "").replace("\r", "").splitlines():
        ln = ln.strip()
        if not ln or "|" not in ln:
            continue
        k, _, v = ln.partition("|")
        try:
            out[str(k).strip()] = int(float(v))
        except Exception:
            continue
    return out


# 🔴🔴 2026-11-12（DS-06：live-uid 缓存 TTL 统一）
#   设备存活 uid 集合的缓存时长。pendingq._device_live_uids 用它做 120s 缓存，
#   data.pending（should_reply / unread_sids）按设计**现查**（每次新鲜，保证
#   清红点目标准确）—— 两边共用**同一个 TTL 常量**，避免将来调时长只改一处
#   导致两边口径漂移。pending.py 侧不缓存，仅引用此常量作为「若加缓存则用同一
#   时长」的约定。
DEVICE_LIVE_TTL_S = 120.0


def device_live_uids(device, uid, timeout=15):
    """**当前账号自己的设备库**里还存在的 toUserId 集合。取不到返回 None。

    🔴🔴 2026-11-08 12:56（P0：本地镜像里的「死人」）

      实测（直接 pull 设备库对比，见 _final.py）：
        账号 96691646：本地镜像 session 1524 行 / 12.2MB
                       设备真实 session   31 行 / 204KB
                       uid 交集 29，**只在本地、设备上已不存在 = 1495 个**
        账号 402857053：本地镜像 1298 → 设备 55（同一现象）

      Soul **真的把这个账号的历史会话清空了**。本地镜像是历史快照
      （`sync()` 的截断保护故意保留它，不覆盖），里面绝大多数会话在 App 里
      已经不存在。拿这些当「待回队列」→ 翻屏翻不到、搜索搜不到 →
      每人白烧 40~50s，**一个人都回不掉**（实测候选里设备上还活着的 0/1）。

    **账号隔离铁律（用户反复强调）**：只查**本账号自己**的那个库。
      · 库名由 `uid` 反推（`IM-SDK-<base64(uid+后缀)>-DATA.db`），绝不遍历两个库；
      · 一个 uid 一个库，A 账号的 uid 集合绝不用于 B 账号的候选过滤。
      这样即使两个库同时存在，也不会出现「拿 A 的人去 B 账号搜」。

    返回：set(str uid) —— 正常
          None        —— 取不到（无 root / adb 抖动 / 库不存在），调用方须**降级不过滤**
    """
    try:
        name = _db_name_for_uid(device, uid)
    except Exception as e:
        log.debug("device_live_uids: 反推库名失败 %r", e)
        name = None
    if not name:
        log.debug("device_live_uids: 找不到 uid=%s 对应的设备库", uid)
        return None
    try:
        txt = _dev_sql(device, name,
                       "select distinct toUserId from session where toUserId>0",
                       timeout=timeout)
    except Exception as e:
        log.debug("device_live_uids: 查 %s 失败 %r", name, e)
        return None
    out = set()
    for ln in (txt or "").replace("\r", "").splitlines():
        s = ln.strip()
        if s and s.lstrip("-").isdigit():
            out.add(s)
    if not out:
        # 🔴🔴 2026-11-12（DS-08 空集判断 · 最终结论：**保持 None，不过滤**）
        #   空集合有两种可能：真的一个人都没有 / 查询失败。
        #   修法原本想把「查询成功但 0 会话」与「查询失败」区分开：成功返回空 set、
        #   失败返回 None，让调用方在「设备真 0 会话」时过滤掉全部镜像僵尸。
        #   —— 但做不到，根因在 `_dev_sql`（本文件 903）：它用 `_clean()` 把
        #   错误标记统一洗成 ""，于是**「0 行成功」和「查询失败」都返回 ""**，
        #   到这一层根本无法区分。
        #   若强行返回空 set：一次 adb 抖动/查询失败（同样得到 ""）会被当成
        #   「设备真没会话」→ 调用方过滤掉**全部**候选 → 漏回（最差失败模式）。
        #   权衡后**宁可保持 None（旧行为=降级不过滤）**：设备缩水 962 次的主因是
        #   「设备仍有很多会话，只是比镜像少」，device_live_uids 返回的是**非空**
        #   集合（仅缺死人）→ 过滤依然生效；真正的「0 会话」是罕见边缘，不值得
        #   为它冒「一次 adb 抖动就漏回全部」的风险。
        #   HY-13 已把同一设备存活校验补到 unread_sids()（清红点目标源），
        #   常见缩水场景已被覆盖；此处保留旧行为并留档。
        return None
    return out


def _db_name_for_uid(device, uid, timeout=15):
    """反推某个 uid 对应的设备库文件名（找不到返回 None）。

    设备上库名形如 `IM-SDK-<base64>-DATA.db`，base64 段由
    「uid + 固定后缀」拼成，无法从 uid 直接算出，所以：
      ① 先看 `device_owner_uid()` 是否正好是这个 uid → 直接用它的库
      ② 否则遍历库名，逐个用 sessionId 前缀众数反推归属，匹配 uid 才返回
    **只返回单个库名**，绝不返回多个 —— 保证账号隔离。
    """
    raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    names = [x.strip() for x in raw.replace("\r", "").splitlines()
             if x.strip().endswith("-DATA.db")]
    if not names:
        return None
    want = str(uid)
    for nm in names:
        # 🔴 2026-11-08 12:58（两个坑一起踩了，都记下来）：
        #   ① `toUserId` 可能是**负数**（官方号 -10011），`length(toUserId)` 算的是
        #      「带负号的长度」→ substr 少切一位 → prefix 变成 '966916464'，永远匹配不上。
        #   ② 想用 `replace(toUserId,'-','')` 去掉负号，被 `_assert_readonly` 的
        #      `\breplace\b` 规则当成写操作**直接拒绝**（它是 INSERT OR REPLACE 的关键字）。
        #      不能为了这个去放宽只读闸（那是设备库唯一的写保护），改用不触发关键字的写法。
        #
        #   最终写法：用 `instr(toUserId,'-')` 判断有无负号，有则长度 -1；
        #   全程只有 substr/length/instr，既正确又过只读闸。
        q = ("select sid_prefix, count(*) c from ("
             "  select substr(sessionId, 1, length(sessionId)"
             "    - length(toUserId) + (case when instr(toUserId,'-')>0 then 1 else 0 end)"
             "  ) sid_prefix"
             "  from session"
             "  where length(sessionId) > length(toUserId)"
             "    - (case when instr(toUserId,'-')>0 then 1 else 0 end)"
             ") group by sid_prefix order by c desc limit 1")
        txt = _dev_sql(device, nm, q, timeout=timeout)
        for ln in (txt or "").replace("\r", "").splitlines():
            ln = ln.strip()
            if "|" in ln:
                pre = ln.split("|")[0].strip()
                if pre == want:
                    return nm
    return None


def _db_owner_uid(device, dbname, uid, timeout=15):
    """判断某个库是不是 **uid 这个账号** 的库。

    判据（探针实测 1261/1261 成立）：
        sessionId == str(uid) + str(toUserId)
      所以「库里满足该等式的行数 / 总行数」就是归属置信度。

    🔴 为什么不用文件名判断：文件名是 `IM-SDK-<base64 token>-DATA.db`，
      token 随登录态变化，和 uid 没有可推导关系（实测两个库 token 完全不同）。
    🔴 为什么不用 chatmsg 投票：入向不落 chatmsg 的账号（402857053）票数会偏低。
    返回 (命中行数, 总行数)；查询失败返回 (0, 0)。
    """
    if not uid:
        return 0, 0
    q = ("select (select count(*) from session "
         "where sessionId = '%s' || toUserId), (select count(*) from session)"
         % str(uid).replace("'", ""))
    txt = _dev_sql(device, dbname, q, timeout=timeout)
    for ln in (txt or "").replace("\r", "").splitlines():
        ln = ln.strip()
        if "|" not in ln:
            continue
        a, _, b = ln.partition("|")
        try:
            return int(float(a)), int(float(b))
        except Exception:
            continue
    return 0, 0


def device_owner_uid(device, timeout=15):
    """设备上「当前登录账号」的 uid（0.05~0.3s，纯只读）。

    优先读 sp_info_gather.xml（`current_uid()`，权威且直接）；
    读不到时退回「逐库用 sessionId 前缀反推」——两个库各自的多数前缀就是各自的 uid。
    都失败返回 None（调用方必须降级，不许瞎猜）。
    """
    try:
        u = current_uid(device)
        if u:
            return str(u)
    except Exception as e:
        log.debug("current_uid 失败，退回前缀反推: %r", e)
    # 兜底：逐库反推（session 表里 sid 去掉 toUserId 后缀的众数，即 _guess_uid 的设备版）
    try:
        raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    except Exception:
        return None
    for nm in [x.strip() for x in raw.replace("\r", "").splitlines()
               if x.strip().endswith("-DATA.db")]:
        q = ("select sid_prefix, count(*) c from ("
             "  select substr(sessionId, 1, length(sessionId)-length(toUserId)) sid_prefix"
             "  from session where toUserId>0 and length(sessionId)>length(toUserId)"
             ") group by sid_prefix order by c desc limit 1")
        txt = _dev_sql(device, nm, q, timeout=timeout)
        for ln in (txt or "").replace("\r", "").splitlines():
            ln = ln.strip()
            if "|" in ln:
                pre = ln.split("|")[0].strip()
                if pre.isdigit():
                    return pre
    return None


def device_unread_map(device, timeout=15, uid=None, strict=True):
    """设备端 sqlite3 直查「未读会话」→ {sid: unread}（0.05~0.2s，不走 pull）。

    🔴 2026-11-04（用户口径：进对话框后 root 能拿到 sid）：
      dumpsys 的 Intent 只有 `(has extras)`、logcat 不打 sessionId、prefs 也没有，
      但 App **进会话一定会把该 sid 的 unReadCount 置 0** —— 所以「进之前/进之后」
      各查一次未读集合，差集就是刚进去的那个会话（精确 sid，不依赖任何文本比对）。
    查不到（无 sqlite3 / 无 root / 库被锁）返回 None，调用方按「无证据」处理、退回文本校验。

    🔴🔴 2026-11-08 修复 P0（跨账号串库，lead 实测复现）：
      【改前】对所有 `-DATA.db` 循环，结果全部 `out[str(sid)] = ...` 合并进同一个
        dict，**没有任何 uid 过滤**。设备上同时存在两个账号的库（实测
        `IM-SDK-SmNjOUhi...`=账号1 uid 96691646、`IM-SDK-WGpBRi94...`=账号2 uid 402857053），
        两个库的 session 表都完整可查 —— 混读**不报错**，只会静默返回另一个账号的会话。
      【实测证据】lead 在 2026-11-08 复现：当前登录 402857053，但本函数返回的 23 个
        sid 里混着 `96691646-10011`（账号1 的群会话）和 `96691646<toUserId>`（账号1 会话）。
        直接对应日志里「身份校验失败 261 次」—— 拿别人的 sid 去当前界面点，必然进错人。
      【改法】先定当前 uid（`device_owner_uid`）→ 逐库用 `sessionId=<uid>||toUserId`
        反推归属 → **只查命中的那一个库**；匹配不到唯一库就返回 None（降级），绝不混读。
      【顺带】SQL 加 `and toUserId > 0` 过滤群/官方会话（`96691646-10011` 这类带横杠
        的 sid，toUserId=-10011 是负数）。这类会话清红点会白烧一轮还进不到 chat 页。

    参数：
      uid    —— 已知当前账号 uid 时传入（省一次 sp_info 读，约 0.1s）
      strict —— True（默认）：定不到 uid 就返回 None，绝不混读；
                False：退回旧行为（扫全部库合并）—— **只用于排障**，业务代码不要传 False。
    """
    try:
        raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    except Exception as e:
        log.debug("列库目录失败: %r", e)
        return None
    dbs = [x.strip() for x in raw.replace("\r", "").splitlines()
           if x.strip().endswith("-DATA.db")]
    if not dbs:
        return None

    # ---- ① 定当前账号 ----
    want = str(uid) if uid else None
    if not want:
        try:
            want = device_owner_uid(device, timeout=timeout)
        except Exception as e:
            log.debug("定当前 uid 失败: %r", e)
    if not want:
        if strict:
            log.warning("定不到当前登录 uid → 拒绝扫库（防跨账号串库），按无证据处理")
            return None
        log.warning("定不到当前登录 uid → 非严格模式，退回扫全部库（可能串号）")
        return _unread_scan_all(device, dbs, timeout)

    # ---- ② 找归属库（sessionId == uid + toUserId）----
    owner, best = None, (0, 0)
    for nm in dbs:
        hit, tot = _db_owner_uid(device, nm, want, timeout=timeout)
        if tot <= 0:
            continue
        if hit > best[0]:
            owner, best = nm, (hit, tot)
        if hit >= tot * 0.9:          # 90% 以上行满足 → 直接认定，不用再试别的库
            owner = nm
            break
    if owner is None:
        # 一个库都不像这个账号的 → 说明 uid 读错了或库还没落盘
        if strict:
            log.warning("没有库归属当前 uid=%s（各库命中 %s）→ 返回 None 降级", want, best)
            return None
        return _unread_scan_all(device, dbs, timeout)
    log.debug("当前 uid=%s → 归属库 %s（%d/%d 行满足 sid 前缀）",
              want, owner, best[0], best[1])

    # ---- ③ 只查这一个库，并过滤群/官方会话 ----
    q = ("select sessionId,unReadCount from session "
         "where unReadCount>0 and toUserId>0")
    got = _parse_kv(_dev_sql(device, owner, q, timeout=timeout))
    return got if got else None


def _unread_scan_all(device, dbs, timeout=15):
    """旧行为：扫全部库并合并（**会跨账号串库**，仅供排障/降级兜底）。

    业务路径不要直接调它 —— 见 `device_unread_map` 的说明。
    """
    out = {}
    for nm in dbs:
        got = _parse_kv(_dev_sql(
            device, nm,
            "select sessionId,unReadCount from session "
            "where unReadCount>0 and toUserId>0", timeout=timeout))
        out.update(got)
    return out if out else None


def open_account(device, name=None, uid=None, max_age=REFRESH_S, force=False):
    """打开「当前登录账号」对应的 IM 库。

    设备上同时存在两个库（每个账号一个），必须按 uid 选对，
    否则会拿另一个账号的数据判断「该回谁」。

    🔴 同步节奏（用户 2026-11-02：「本地库 5 分钟同步一次呗或者 10 分钟」）：
      原来**每一轮 cycle 都重新 pull**（一轮 60~90s，一次 10MB）——
      又慢又容易拉到不一致的库（App 一直在写）。
      现在：
        ① 缓存 5 分钟内直接复用（max_age=300）
        ② 有新消息信号时**强制刷新**（force=True，由 daemon 在 dirty 时调）
      这样既不漏消息，也不会每轮白拉 10MB。
    """
    # ① 缓存命中
    if (not force and name is None and _LAST["db"] is not None
            and (time.time() - _LAST["ts"]) < max_age):
        try:
            want_now = uid or current_uid(device)
            if not want_now or str(_LAST["uid"]) == str(want_now):
                return _LAST["db"]
            log.info("账号已变（%s -> %s）→ 强制重开库", _LAST["uid"], want_now)
        except Exception as e:
            log.debug("缓存校验异常，直接重开: %r", e)

    names = list_device_dbs(device)
    if not names:
        raise RuntimeError("设备上没有 IM-SDK 库")

    if name is not None:
        if name not in names:
            raise RuntimeError("库 %s 不在设备上（有：%s）" % (name, names))
        p = sync(device, name)
        db = IMDB(p, uid=uid)
        db.dev = device
        log.info("已打开指定库 %s uid=%s", name, db.uid)
        return db

    want = uid or current_uid(device)
    log.info("当前登录 uid = %s，共 %d 个库待匹配", want, len(names))
    if not want:
        p = sync(device, names[0])
        # 🔴 2026-11-13 修复 DS-02（P1 设备存活校验失效回潮）：want 为空（current_uid
        #   读不到）的降级分支漏挂 db.dev —— 正常路径（1299/1335）都有 `db.dev=device`，
        #   唯独此分支没有。而 pending.py 的 unread_sids/should_reply 只用
        #   getattr(db,"dev",None)，不回退 _DEV_REF → 设备存活校验被静默跳过，
        #   幽灵会话/待回虚高回潮（11-08 P0 根因）。
        db = IMDB(p)
        db.dev = device
        return db

    # 🔴🔴 2026-11-08 10:36（用户硬规则：「两个账号的数据库要分开，不要用 A 的聊天记录
    #   去全 B 账号搜」）
    #
    #   【发现的真问题】设备上被登出的账号，它的库会被 Soul **清空/截断**：
    #     实测 10:35 —— 96691646 的库从 14.2MB 掉到 76KB（登出后记录被清）。
    #   而 `sync()` 的实现是「先删本地三个文件 → 再 pull」，
    #   于是下次 `open_account()` 走到这个库时，会**用 76KB 的空库覆盖本地
    #   14.2MB / 20900 条历史镜像** —— 数据不可恢复（除非有备份）。
    #
    #   【改法】切号/开库时，先比对「设备库 vs 本地镜像」的行数：
    #     设备库明显更小（< 本地 50% 且少了 200 条以上）→ **判定为被清空**，
    #     拒绝覆盖，抛异常让上层降级（宁可这一轮不跑，也不能毁掉历史数据）。
    #     同时把本地镜像另存一份 `.keep`，保证人工随时能找回。
    #
    #   注意：正常增量同步（设备库更大）不受影响。
    _skipped = []
    for n in names:
        try:
            p = sync(device, n)
        except RuntimeError as _e:
            # sync() 的「拒绝用空库覆盖历史」保护（见该函数内 2026-11-08 注释）
            # 这个库是已登出账号的，跳过它继续找当前账号的库即可。
            log.warning("跳过库 %s：%s", n[:28], _e)
            _skipped.append(n)
            continue
        db = IMDB(p)
        db.dev = device
        if str(db.uid) == str(want):
            log.info("匹配到库 %s (uid=%s, %.1fMB)", n, db.uid, os.path.getsize(p) / 1e6)
            _LAST["db"] = db
            _LAST["ts"] = time.time()
            _LAST["uid"] = str(db.uid)
            return db
        db.close()

    raise RuntimeError("两个库的 uid 都不等于当前账号 %s（跳过的库：%s）"
                       % (want, _skipped))


def health(db, quick=True):
    """库完整体检。返回 True/False。

    为什么要能主动查：`database disk image is malformed` 一旦发生，
    所有查询（唤醒候选/待回/会话列表）全崩，daemon 等于瘫痪且没人知道。
    quick=True 时只做 integrity_check + 试查一张表。
    """
    try:
        r = db.con.execute("PRAGMA integrity_check").fetchone()
        if not r or str(r[0]).lower() != "ok":
            return False
        db.con.execute("SELECT COUNT(*) FROM chatmsg LIMIT 1").fetchone()
        return True
    except Exception as e:
        log.warning("库体检失败: %r", e)
        return False


def invalidate():
    """丢掉本地库缓存（库损坏/切号时调）。"""
    _LAST["db"] = None
    _LAST["ts"] = 0.0
    _LAST["uid"] = ""
