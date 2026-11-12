# -*- coding: utf-8 -*-
"""「谁该回」判定器：**完全不依赖屏幕**，只读 IM 库。

═══════════════════════════════════════════════════════════════════════
为什么要有这个模块（2026-11-08 实测，这是「总在瞎操作」的结构性根因）
═══════════════════════════════════════════════════════════════════════

同一瞬间同时读库和读屏（探针 N，900x1600）：

    库（sqlite3，0.05s）        屏（u2 dump，3.86s）
    ─────────────────────      ─────────────────────
    会话总数      1261          可见行数        10 行（= 0.67%）
    消息总数     10441          行的时间        全部停在 8 天前
    未读会话        11          带红点行        0
    「该回」        27          能判定的「该回」  0
      ├ 红点且该回   4
      └ 已读但该回  23          ← 屏幕**原理上永远看不到**

两条更硬的证据：
  ① `unread_msg_number`（chatlist.Row.has_dot 依赖的行级红点 res-id）
     在 dump 里连续 4 轮 **0 个节点**；全屏只有 me_red_point / red_text /
     square_red_point 三个底栏 id。⇒ 红点判据是**空的**。
  ② 库未读的 10 条 lastMsgText 拿去屏上 textContains 反查 → **命中 0/10**。
     （列表被滚到 8 天前，她刚说的话根本没渲染出来。）

结论：现有架构在用 **0.67% 的、位置还错** 的信息源，去逼近一个 **100% 已知**的答案。
本模块就是那个「100% 已知」的答案来源：一条 SQL 出全部待回，0.05s。

═══════════════════════════════════════════════════════════════════════
分层
═══════════════════════════════════════════════════════════════════════

本模块属于 `data/` 层，**只依赖 core 和 data.imdb**，绝不 import eyes/brain
（保持项目「guard → brain → eyes/hands → core」的单向依赖）。
因此这里只做「从库里算出结论」，不含任何 UI 动作；要不要点、怎么点由 brain 决定。

对外主入口：
    should_reply(db, now_ms=None) -> [PendingItem, ...]   # 按优先级排好序
    count_pending(db)             -> int                  # daemon 日志用的一眼指标
    unread_sids(db)               -> [sid, ...]           # 清红点的目标清单（替代屏幕红点）

冷却复用 `brain.pendingq` 的失败台账（`should_skip`），但**用延迟导入**：
data 层不能反向依赖 brain 层，且 pendingq 的 import 链很重（会拉起 flow/search）。
"""
import os
import time

from core.log import get_logger

log = get_logger("data.pending")

# 扫描窗口：只看最近 N 天的会话（超期的回了也怪，她早忘了）。
LOOKBACK_DAYS = float(os.environ.get("SOUL_PENDING_DAYS", "7") or 7)
# 一次最多扫描多少个会话（按 timestamp DESC 取窗口，保证覆盖最近会话）
SCAN_SESSIONS = int(os.environ.get("SOUL_PENDING_SCAN", "300") or 300)
# 官方营销号段（与 pendingq.SKIP_UID_PREFIX 保持一致；此处复制常量避免反向 import）
SKIP_UID_PREFIX = ("2042683",)
# 系统类文本：不是真人说的话，回了等于对机器说话（与 pendingq.SYS_TEXTS 一致）
# 🔴 探针实测（2026-11-08）：不过滤的话 `[互动消息]` 会被当成「该回」混进队列
#    （sid 尾 460061497 就是这种）。这类必须排除。
SYS_TEXTS = ("[互动消息]", "[互动提醒]", "[系统消息]", "[官方消息]")

# 优先级常量（数值越小越优先）
PRI_UNREAD = 0          # 有未读（= 屏幕上会有红点，她正在等）
PRI_READ_UNREPLIED = 1  # 已读但末条是她（屏幕上没红点，但必须回）

# 「很新」窗口：20 分钟内到的消息**一律提到最前面**（按时间倒序）。
# 🔴 探针 R 实测（2026-11-08）：只做「同档最老优先」时，队首是 **6.0 天前**的会话，
#    而 9 分钟前刚到的那条排在第 30+ 位 —— 新消息被老积压挤住，等于没抢到队。
#    口径与 brain/pendingq.py:654 的 _HOT_MS 保持一致（那边已生产验证）。
#    用户 2026-11-03 原话：「有红点就一定有新消息，新消息不能被积压挤住」。
HOT_MS = float(os.environ.get("SOUL_PENDING_HOT_MIN", "20") or 20) * 60 * 1000.0


class PendingItem(object):
    """一条「该回」记录。"""

    __slots__ = ("sid", "to_uid", "last_text", "her_ts", "unread",
                 "reason", "priority", "last_sender")

    def __init__(self, sid, to_uid, last_text, her_ts, unread, reason,
                 priority, last_sender=""):
        self.sid = str(sid)
        self.to_uid = str(to_uid)
        self.last_text = last_text or ""
        self.her_ts = int(her_ts or 0)          # 她末条的毫秒时间
        self.unread = int(unread or 0)
        self.reason = reason                    # 'unread' / 'read_unreplied'
        self.priority = int(priority)
        self.last_sender = str(last_sender or "")

    @property
    def age_s(self):
        """她这条消息距今多少秒（用于日志/排序，取不到时间返回一个很大的数）。"""
        if not self.her_ts:
            return 1e9
        return max(0.0, time.time() - self.her_ts / 1000.0)

    def __repr__(self):
        return ("<Pending %s uid=%s %s unread=%d %r %.0fs前>"
                % (self.sid, self.to_uid, self.reason, self.unread,
                   self.last_text[:16], self.age_s))


def _cooling(sid, txt):
    """是否在失败台账冷却期内（延迟 import brain.pendingq，避免反向依赖）。

    失败台账语义（见 brain/pendingq.py:457 should_skip）：
      同一 sid + **同一句末条** 才冷却；她一说新话就自动失效。
    所以冷却不会让人永久失联，只是别每轮白烧。
    """
    try:
        from brain.pendingq import should_skip
        return bool(should_skip(sid, txt))
    except Exception as e:
        # brain 层还没就绪 / 循环 import → 当作不冷却（宁可多试一次，不要漏回）
        log.debug("冷却台账不可用（按不冷却处理）: %r", e)
        return False


def _replied(sid, to_uid, txt, her_ts):
    """「她这一句我已经回过了」——**防重复回的关键闸**（延迟 import，理由同上）。

    🔴🔴 为什么必须有（探针 P 实测暴露，2026-11-08）：
      不加这道闸，should_reply() 报「65 人待回」，而其中**大量是已经回过的**
      —— 因为「末条是她」这个条件在她没再说话时**永远成立**。这正是
      pendingq.py:101 记录的现网事故：「uid=*** 在 09:31~09:35 被连回 5 次」，
      在真人眼里就是个复读机器人。
      `brain.pendingq._recently_replied` 的台账语义是
      「同一 sid + 同一句末条 = 已回过；她说了新话（文本变了 / 时间更晚）才放行」，
      这里**完全复用**它，避免两套口径打架。

    返回 True 表示已回过（该跳过）。
    """
    try:
        from brain.pendingq import _recently_replied
        return bool(_recently_replied(to_uid, sid=sid, text=txt, her_ts_ms=her_ts))
    except Exception as e:
        # 拿不到台账时**按未回过处理**：漏回比重复更糟（用户铁律「必回」优先）
        log.debug("已回台账不可用（按未回过处理）: %r", e)
        return False


def _skip_uid(to_uid):
    """官方营销号段。"""
    return str(to_uid or "").startswith(SKIP_UID_PREFIX)


def unread_sids(db, now_ms=None):
    """当前**有未读**的真人会话 sid 列表（按未读数、时间排序）。

    用途：替代 `clear.dots()` 的「屏幕上找红点行」——屏幕那条路实测恒为空。
    返回 [sid, ...]，不含官方号/群会话。查库异常返回 []。
    """
    if db is None:
        return []
    out = []
    try:
        rows = db.con.execute(
            "SELECT sessionId, toUserId, unReadCount, timestamp, lastMsgText "
            "FROM session WHERE unReadCount > 0 AND toUserId > 0 "
            "ORDER BY timestamp DESC LIMIT ?", (SCAN_SESSIONS,)).fetchall()
    except Exception as e:
        log.warning("查未读会话失败: %r", e)
        return []
    # 🔴🔴 2026-11-12（HY-13 / DS-08：unread_sids 无设备存活校验）
    #   现象：设备库缩水 962 次，清红点目标 `_lib_unread_sids` 几乎全是
    #   「设备上已不存在的幽灵会话」→ 屏上认领不到 → 双击空转。
    #   根因：unread_sids() 只查本地镜像 `unReadCount>0`，**无 device_live_uids
    #   过滤**（对比 should_reply 有，见本文件 248-258）。
    #   修法：与 should_reply 同款设备存活校验。取不到（None）不过滤，保持旧行为。
    try:
        from data import imdb as _IM
        _dev = getattr(db, "dev", None)
        if _dev is not None:
            _live = _IM.device_live_uids(_dev, db.uid)
            if _live is not None:
                _before = len(rows)
                rows = [r for r in rows if str(r["toUserId"] or "") in _live]
                if _before != len(rows):
                    log.debug("unread_sids：设备存活校验移出 %d 个已不存在的会话",
                              _before - len(rows))
    except Exception as _e:
        log.debug("unread_sids：设备存活校验跳过（%r）", _e)
    for r in rows:
        try:
            sid = str(r["sessionId"])
            to_uid = str(r["toUserId"] or "")
        except Exception:
            continue
        if _skip_uid(to_uid):
            continue
        out.append(sid)
    return out


def should_reply(db, now_ms=None, include_cooling=False, include_replied=False,
                 limit=0, max_age_h=0):
    """**核心**：返回「现在该回谁」，按优先级排序。完全不看屏幕。

    判定规则（每条都有实测依据）：

      ┌ 末条是她 + 有未读      → reason='unread'          priority=0（最高）
      │   实测：这类在屏幕上**有红点**，但红点 res-id 已消失（4/4 轮 0 个），
      │   所以 clear.dots() 找不到 → 只能由库判定。
      ├ 末条是她 + 未读=0      → reason='read_unreplied'  priority=1
      │   实测：lead 复现「23 个已读但该回」。她发了、被读过了（进过一次就清零），
      │   屏幕上**没有红点**，现有架构在原理上永远发现不了 → 这是最大的漏回来源。
      └ 末条是我发的           → 不回（等她说）

    排除项：
      · 官方/营销号（toUserId<=0 已在 SQL 过滤；号段 SKIP_UID_PREFIX 再拦一层）
      · 群会话（toUserId<=0，含 `96691646-10011` 这类带横杠 sid）
      · 系统文本（`[互动消息]` 等，不是她说话）
      · 官方文案会话（`Session.is_official`，命中 ≥2 个营销词）
      · **已回过的**（同一 sid + 同一句末条 → 见 `_replied`；`include_replied=True` 可关）
      · 失败台账冷却中的（她说了新话会自动失效，不会永久拉黑）
      · 超过 LOOKBACK_DAYS 的老会话（回了也怪）

    参数：
      include_cooling —— True 时连冷却中的也返回
      include_replied —— True 时连「已回过」的也返回
                         两个 include 都置 True = **真实待回总量**（daemon 统计用）
      limit           —— >0 时截断返回条数
      max_age_h       —— >0 时只返回「她末条距今 <= 这么多小时」的会话。
                         🔴 2026-11-08 03:30（P0 死锁）：红点闸门必须用**和候选队列
                         同一个时效口径**，否则两边差 7 倍（COUNT 用 LOOKBACK_DAYS=7 天，
                         candidates 用 STALE_GIVEUP_H=24h）——只要有一个 6.6 天前的会话
                         没处理，闸门就永远 True，匹配永远进不去。见 count_pending。

    返回：按 (priority, 她末条时间) 排好序的 [PendingItem, ...]。
          **排序规则**：先 unread 后 read_unreplied；同档内**最老优先**
          （用户 2026-11-03 口径「先灭火再聊新的」，实测 p90 延迟因此从 156min 降下来）。
    """
    if db is None:
        return []
    now_ms = float(now_ms or time.time() * 1000.0)
    cutoff = now_ms - LOOKBACK_DAYS * 86400.0 * 1000.0
    # 🔴 2026-11-08 03:30（P0 死锁）：时效闸 —— 与 pendingq.STALE_GIVEUP_H 同口径。
    #   红点闸门必须只数「真的还能回的人」，否则过期积压会把闸门永久顶成 True。
    _age_cutoff = 0.0
    if max_age_h and float(max_age_h) > 0:
        _age_cutoff = now_ms - float(max_age_h) * 3600000.0

    try:
        rows = db.con.execute(
            "SELECT sessionId, toUserId, unReadCount, timestamp, lastMsgText "
            "FROM session WHERE toUserId > 0 AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (cutoff, SCAN_SESSIONS)).fetchall()
    except Exception as e:
        log.warning("查会话失败: %r", e)
        return []

    # 🔴🔴 2026-11-08 13:1x（P0：**统计口径与真实队列不一致**）
    #
    #   这是 `pendingq.candidates()` 之外**另一条独立统计路径**，它不经过
    #   设备存活校验，于是日志长期显示「待回 22 人（未读 4 / 已读未回 18）」
    #   而真实可处理的候选是 0 —— 数字失真，排查时被严重误导
    #   （实测 13:11:39 同一行日志里「待回 22 人」和「已读未回：没有候选」并存）。
    #
    #   实测这 22 人里：15 个「末条是我」、9 个「无 last」、1 个官方号、
    #   1 个冷却中 —— **一个都没被误杀**，是数字本身虚高。
    #
    #   修法：这里也过一遍**当前账号**的设备存活校验（同样的账号隔离原则）。
    #   取不到（None）就不过滤，保持旧行为 —— 统计失败不该让日志变成 0 人。
    try:
        from data import imdb as _IM
        _dev = getattr(db, "dev", None)
        if _dev is not None:
            _live = _IM.device_live_uids(_dev, db.uid)
            if _live:
                _before = len(rows)
                rows = [r for r in rows if str(r["toUserId"] or "") in _live]
                if _before != len(rows):
                    log.debug("pending 统计：设备存活校验移出 %d 个已不存在的会话",
                              _before - len(rows))
    except Exception as _e:
        log.debug("pending 统计：设备存活校验跳过（%r）", _e)

    # 🔴 2026-11-12 夜班修复（D1）：归档集合一次性取（与 pendingq.candidates() C4 口径一致）。
    #   改前 should_reply() 完全没有归档过滤，而 candidates() 有（879-903 行）→ 两条统计
    #   路径口径不一致：日志「待回 N 人」虚高（实测 24h 窗口 39 次「全是冷却/已回僵尸，
    #   但 candidates 为空、count_pending 仍 >0」）。取不到就不过滤（保持旧行为）。
    try:
        from data import reply_state as _RS
        _archived = set(str(x) for x in _RS.archived_sids())
    except Exception:
        _archived = set()

    out = []
    for r in rows:
        try:
            sid = str(r["sessionId"])
            to_uid = str(r["toUserId"] or "")
            unread = int(r["unReadCount"] or 0)
        except Exception:
            continue
        if _skip_uid(to_uid):
            continue
        try:
            # 🔴 必须用 db.latest() 而不是 db.last_message()：
            #   实测 402857053 号**入向不落 chatmsg**（24h 只有 1 条），
            #   只读 chatmsg 会把「她刚说的话」当空气 → 误判「末条是我发的」→ 漏回。
            #   latest() 会在 chatmsg 末条与 session 摘要里取**时间更新**的那个
            #   （见 imdb.py:354 的说明：这就是「答非所问」的根因）。
            last, _src = db.latest(sid)
        except Exception as e:
            log.debug("取 sid=%s 末条失败: %r", sid, e)
            continue
        if last is None:
            continue
        sender = str(getattr(last, "sender", "") or "")
        if db.uid and sender == str(db.uid):
            continue                        # 末条是我发的 → 等她说，不回
        # 🔴 2026-11-12 夜班修复（D1）：归档 ≠ 拉黑 —— 与 pendingq.candidates() 879-903
        #   同款 C4 过滤。她再发人话（ts > 台账水位线）→ 解除归档、重新计入待回；
        #   否则跳过（不回、不唤醒、不计待回）。放在 sender 检查之后：末条是我的
        #   本来就会 continue，归档判定只对「她发的」有意义。
        if str(sid) in _archived:
            try:
                from eyes import sysmsg as _SM
                from data import reply_state as _RS2
                _lt = (getattr(last, "text", "") or "").strip()
                _human_ok = (_SM.is_human(_lt, getattr(last, "msg_type", None), uid=to_uid)
                             if _lt else
                             int(getattr(last, "msg_type", 0) or 0) not in (27, 35))
                _is_new_her = (str(sender) != str(db.uid) and _human_ok
                               and int(getattr(last, "ts", 0) or 0) > _RS2.her_ts_of(str(sid)))
                if not _is_new_her:
                    continue
            except Exception:
                continue
        her_ts = int(getattr(last, "ts", 0) or 0)
        if her_ts and her_ts < cutoff:
            continue                        # 超期（她早忘了）
        # 🔴 2026-11-08 03:30（P0 死锁）：时效闸 —— 只看「还回得掉」的人。
        if _age_cutoff and her_ts and her_ts < _age_cutoff:
            continue
        txt = (getattr(last, "text", "") or "").strip()

        # 系统类文本不是她说话（`[互动消息]` 等）—— 回了等于对机器说话
        if txt in SYS_TEXTS:
            continue

        # 官方文案会话（两级判据里的「文案命中 ≥2 个营销词」那一级）
        try:
            sess = db.session(sid)
            if sess is not None and sess.is_official:
                continue
        except Exception:
            pass

        # 🔴 她这一句我已经回过了 → 跳过（防「同一人被连回 5 次」的现网事故）
        if not include_replied and _replied(sid, to_uid, txt, her_ts):
            continue

        if not include_cooling and _cooling(sid, txt):
            continue

        if unread > 0:
            reason, pri = "unread", PRI_UNREAD
        else:
            reason, pri = "read_unreplied", PRI_READ_UNREPLIED

        out.append(PendingItem(sid, to_uid, txt, her_ts, unread,
                               reason, pri, last_sender=sender))

    # 排序：档位优先 → 同档「最老优先」（先灭火）
    out.sort(key=lambda x: (x.priority, x.her_ts or 0))
    # 🔴🔴 2026-11-08（探针 R 实测后加的，必须在上面之后）：
    #   只做「同档最老优先」时，队首是 **6.0 天前**的会话，而 9 分钟前刚到的那条
    #   排在 30+ 位 —— 新消息被老积压挤住，用户口径明确不允许。
    #   现在「很新（<HOT_MS）」的一律提到最前面，按时间**倒序**（最新的先回）；
    #   老积压保持「最老优先」从后面接。
    #   排序键用三元组：(是否不新, priority, ±时间)
    #     · hot：  (0, priority, -her_ts)  → 新的在前
    #     · 非hot：(1, priority, +her_ts)  → 老的在前
    #   这样 hot 段永远整段排在前面，且段内新→旧、段间档位不乱。
    _now = now_ms
    def _key(x):
        is_hot = (_now - float(x.her_ts or 0)) < HOT_MS
        if is_hot:
            return (0, x.priority, -float(x.her_ts or 0))
        return (1, x.priority, float(x.her_ts or 0))
    out.sort(key=_key)
    if limit and limit > 0:
        out = out[:limit]
    return out


def count_pending(db, real_total=True, max_age_h=None):
    """「现在有几个人在等我回」——daemon 日志用的一眼指标。

    real_total=True（默认）：统计**真实待回总量**（含冷却中、含已回过未回写的）——
      这是用户想看到的「有 27 个人在等我」，不能因为台账冷却就少报。
    real_total=False：只统计「本轮真能处理」的（= 会真正进会话的候选数）。

    🔴 2026-11-08 03:30（P0 死锁真正锁芯）：新增 max_age_h —— **红点闸门必须传它**。
      改前：闸门用的是 real_total=True 且 7 天窗口，实测恒为 63~64 人；
            而 candidates() 里已按 STALE_GIVEUP_H=24h 淘汰，真正可处理只剩 11~26。
      两边口径差 7 倍 ⇒ 只要有一个 6.6 天前的僵尸会话没处理，闸门就永远 True
            ⇒ 匹配永远进不去，而那些人又永远定位不到 ⇒ 硬死锁。
      现在：闸门传 max_age_h=pendingq.STALE_GIVEUP_H，与候选队列同一口径。

    返回 int；库不可用时返回 -1（**用 -1 区分「0 个人」和「查不到」**，
    否则日志里分不清「真没人等」还是「库挂了」）。
    """
    if db is None:
        return -1
    try:
        _kw = {}
        if max_age_h is not None:
            _kw["max_age_h"] = max_age_h
        if real_total:
            return len(should_reply(db, include_cooling=True, include_replied=True,
                                    **_kw))
        return len(should_reply(db, **_kw))
    except Exception as e:
        log.warning("统计待回人数失败: %r", e)
        return -1


def summary(db, max_age_h=None):
    """给 daemon 日志的一行摘要，如：
        `待回 27 人（未读 4 / 已读未回 23），最老 3.2h 前，可立即处理 8 人`

    🔴 2026-11-08 03:30：新增 max_age_h —— daemon 日志要和闸门**同一口径**，
      否则日志显示「待回 64 人」而闸门其实只认 11 人，排查时会被误导（实测踩过）。

    任何异常都不抛（日志不能因为统计失败就崩）。
    """
    _kw = {}
    if max_age_h is not None:
        _kw["max_age_h"] = max_age_h
    try:
        items = should_reply(db, include_cooling=True, include_replied=True, **_kw)
    except Exception as e:
        return "待回 ? 人（统计失败: %r）" % (e,)
    if not items:
        # 🔴 2026-11-10：原来这里直接 return，一行日志都不打 —— 于是
        #   「待回 0 人」这种**最该确认的状态**反而在 data.pending.log 里看不见，
        #   daemon 日志有、本模块日志没有，排查时两边对不上。
        try:
            if _LAST_SUM["v"] != "待回 0 人":
                _LAST_SUM["v"] = "待回 0 人"
                log.info("待回口径分解：待回 0 人（库判定：没人等她回）")
        except Exception:
            pass
        return "待回 0 人"
    n_unread = sum(1 for x in items if x.reason == "unread")
    n_read = len(items) - n_unread
    oldest = max((x.age_s for x in items), default=0.0)
    if oldest >= 3600:
        old_s = "%.1fh" % (oldest / 3600.0)
    else:
        old_s = "%.0fm" % (oldest / 60.0)
    # 可立即处理 = 不在冷却、不是已回过
    try:
        ready = len(should_reply(db, **_kw))
    except Exception:
        ready = -1
    # 🔴 2026-11-10（日志缺陷修复 + 口径留证）：原来只报一个「可立即处理 N 人」。
    #   但 pendingq.candidates() 还要再过一层 STALE_GIVEUP_H(24h) 淘汰 **和**
    #   自己那本 pending_skip.json 冷却台账 → 实测日志喊「可立即处理 11 人」，
    #   候选队列筛完只剩 1 个，一整夜都是「进 1 人 / 回 1 条」。
    #   复盘时完全看不出这 10 个的差额是被 24h 淘汰吃掉还是被冷却吃掉。
    #   这里把 24h 口径单独算一遍并列出来，差额一眼可见。
    ready24 = -1
    try:
        _kw24 = dict(_kw)
        _kw24["max_age_h"] = 24
        ready24 = len(should_reply(db, **_kw24))
    except Exception:
        pass
    # 跟进阶梯接线（§104-B3）：四桶状态分布，只读不落盘。
    #    整体 try/except：统计失败各桶填 -1，不影响原摘要返回。
    #    verdict 共 6 档状态，本摘要按口径输出 5 个桶（pending/following/awaiting/
    #    archived/no_human）；PENDING_RESTART（待回且需重新开场）并入 pending 桶，
    #    不是漏了一档 —— 它与 PENDING 同属 verdict.QUEUEABLE「待回」。
    b_pending = b_following = b_awaiting = b_archived = b_no_human = -1
    try:
        from brain import sendgate as SG
        from brain import verdict as V
        _b = {V.PENDING: 0, V.FOLLOWING: 0, V.AWAITING: 0,
              V.ARCHIVED: 0, V.NO_HUMAN: 0}
        for x in items:
            # 🔴 2026-11-12 夜班修复（D7）：这里未传 my_last_ts_ms → sendgate.state_of 里
            #   or 0.0 → AWAITING 桶恒 0（仅统计口径）。
            #   取舍：pending.py 属 data 层，只依赖 core/data.imdb，**不能** import
            #   brain.pendingq 的 _my_last_ts_ms（会破坏单向依赖）。本文件也无等价辅助
            #   函数 → 按约定加注释留待后续，不大改。要补需在 data 层自建「我方末条时间」
            #   读取（走 db.messages 按 sender==uid 取），不影响本段其余统计。
            v = SG.state_of(str(x.sid), her_ts_ms=x.her_ts, has_human=True)
            _st = getattr(v, "state", "")
            if _st == V.PENDING_RESTART:
                _st = V.PENDING
            if _st in _b:
                _b[_st] += 1
        b_pending = _b[V.PENDING]
        b_following = _b[V.FOLLOWING]
        b_awaiting = _b[V.AWAITING]
        b_archived = _b[V.ARCHIVED]
        b_no_human = _b[V.NO_HUMAN]
    except Exception:
        pass

    txt = ("待回 %d 人（未读 %d / 已读未回 %d），最老 %s 前，可立即处理 %s 人"
           "｜ 四桶 pending=%d / following=%d / awaiting=%d / archived=%d / no_human=%d"
           % (len(items), n_unread, n_read, old_s,
              ready if ready >= 0 else "?",
              b_pending, b_following, b_awaiting, b_archived, b_no_human))
    # 内容变了才打（summary 每轮会被调多次，不能刷屏）
    try:
        if txt != _LAST_SUM["v"]:
            _LAST_SUM["v"] = txt
            log.info("待回口径分解：%s ｜ 其中 24h 可达 %s 人（其余为超期/冷却）",
                     txt, ready24 if ready24 >= 0 else "?")
    except Exception:
        pass
    return txt


# 用可变容器而不是模块级字符串：函数内多处要读改写，用 global 容易触发
# 「name used prior to global declaration」，容器改内容不需要 global 声明。
_LAST_SUM = {"v": ""}


__all__ = ["PendingItem", "should_reply", "count_pending", "unread_sids",
           "summary", "PRI_UNREAD", "PRI_READ_UNREPLIED",
           "LOOKBACK_DAYS", "SCAN_SESSIONS"]
