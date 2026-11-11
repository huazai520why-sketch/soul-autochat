# -*- coding: utf-8 -*-
"""清红点 + 必回 流程。

用户定的硬规则（2026-11-02）：
  进入对话框后，若最后一条是**对方**发的 → 必须回复，不能清完红点就走。

判定用两条独立证据，互相校验：
  ① OCR 气泡左右（x2>=700 = 我，x1<=210 = 对方）
  ② 用 OCR 读到的消息文本反查数据库 chatmsg → sender

安全边界：
  - dry_run=True 时只生成不发送，用于人工确认
  - 发送前校验：会话正确 + 字已灌入 + 发送按钮存在
  - 发送后校验：输入框清空 + 数据库出现新消息
"""
import os
import time

from brain import reply as R
from brain import voice as V
from core.log import get_logger
from eyes import chat as E
from hands.input import Input

log = get_logger("brain.flow")


class Outcome(object):
    __slots__ = ("nick", "last_text", "side", "sid", "reply", "sent", "err", "kind",
                 "burst", "lines")

    def __init__(self):
        self.nick = ""
        self.kind = "text"      # text / voice / image / emoji / other / tip
        self.last_text = ""     # 合并后的「她这轮说的话」（可能含多条）
        self.burst = []         # 她连发的原文列表（单条时为长度 1）
        self.lines = []         # 我这次实际发出的几条
        self.side = "?"
        self.sid = ""
        self.reply = ""
        self.sent = False
        self.err = ""

    def __repr__(self):
        return ("<Outcome %r side=%s reply=%r sent=%s %s>"
                % (self.nick, self.side, (self.reply or "")[:20], self.sent, self.err))


def _device_last_side(device, uid, sid):
    """直接问**设备库**这个会话最后一条是谁发的：返回 (side, text)，失败 (None, "")。

    🔴 2026-11-08 21:2x（「刚回完又回一遍」的根因，实测）：
      本地镜像是 pull 缓存（REFRESH_S=300s），我们自己刚发出去的那句**还没进镜像**，
      于是进会话时出现「OCR=her / 库=me」，旧逻辑判「重拉后仍冲突 → 按她发了处理
      （必回优先）」→ 5 分钟里对同一个人连回 3 条（实测 甜的苦咖啡
      21:14:41 '我不守，没人守' → 21:17:55 '一个人的活，没人替' → 21:19:3x 第三次）。

      设备库才是真值，而且很小（一次 SQL 0.05~0.3s，见 data/imdb._dev_sql 的只读闸）。
      冲突时问它一句就能裁决，不用靠「宁可多回」兜底。
    """
    try:
        from data import imdb as _IM
        name = _IM._db_name_for_uid(device, uid)
        if not name:
            return None, ""
        sql = ("select senderId, ifnull(text,'') from chatmsg where sessionId='%s' "
               "order by localTime desc limit 1" % str(sid))
        txt = _IM._dev_sql(device, name, sql, timeout=12) or ""
        line = ""
        for ln in txt.replace("\r", "").splitlines():
            if ln.strip():
                line = ln.strip()
        if not line or "|" not in line:
            return None, ""
        sender, _, text = line.partition("|")
        return ("me" if sender.strip() == str(uid) else "her"), text
    except Exception as e:
        log.debug("设备库末条查询失败: %r", e)
        return None, ""


def her_burst(db, sid, uid, max_n=None):
    """她**最新连发**的几条（从最后一条往前，遇到我发的就停）。

    用户 2026-11-02：「她刚发来的这一句有可能是几句，不要固定发了多少喂多少」。
    ⇒ 她在等回复期间连发了 3 条，就要把 3 条一起看，不能只答最后一条
      （只答最后一条时，前面那句的问题就永远没人接，她还得多问一遍）。

    跳过系统提示卡片（little_tip 不是她说话）。返回按时间正序。
    """
    limit = max_n or R.HER_BURST_MAX
    if not sid:
        return []
    try:
        rows = db.con.execute(
            "SELECT * FROM chatmsg WHERE sessionId=? ORDER BY localTime DESC LIMIT 24",
            (sid,)).fetchall()
    except Exception as e:
        log.debug("取她连发失败: %r", e)
        return []

    from data.imdb import Msg
    out = []
    for r in rows:
        try:
            m = Msg(r)
        except Exception:
            continue
        if str(m.sender) == str(uid):
            break                      # 我说的 → 连发到这里为止
        t, how = V.her_msg_of(m)
        if how == "tip":
            continue                   # 系统提示不算她说话
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def her_last_real(db, sid, uid):
    """db 末条是系统提示卡片时，往前找她最后一条**真实**消息。

    为什么需要（2026-11-05 实测 uid=***「烟花易冷」）：
      她 22:26 说「伤呐」，紧跟一张系统提示卡片（已读/互动）。
      flow 与 pendingq 都以「末条是 tip」为由跳过 → 她的话永久没人接，
      8.2 小时未回；且因为没走回复路径，sync_turns 不跑，
      turns.md 里也看不出待回（末行仍是我）。

    语义与 her_burst 一致：跳过 tip 往前扫；遇到我发的 → None（已回）。
    返回 Msg（可能是语音/图片，类型判断交给调用方），没有则 None。
    """
    if not sid:
        return None
    try:
        rows = db.con.execute(
            "SELECT * FROM chatmsg WHERE sessionId=? ORDER BY localTime DESC LIMIT 12",
            (str(sid),)).fetchall()
    except Exception as e:
        log.debug("取她最后一条真实消息失败: %r", e)
        return None
    from data.imdb import Msg
    for r in rows:
        try:
            m = Msg(r)
        except Exception:
            continue
        if str(m.sender) == str(uid):
            return None
        _t, _how = V.her_msg_of(m)
        if _how == "tip":
            continue
        return m
    return None


def take_burst(db, out):
    """给 out 填 burst / last_text（合并多条）。返回条数。"""
    if not out.sid:
        out.burst = [t for t in [out.last_text] if t]
        return len(out.burst)
    burst = her_burst(db, out.sid, db.uid)
    if not burst:
        burst = [t for t in [out.last_text] if t]
    out.burst = burst
    if burst:
        out.last_text = R.merge_burst(burst)
    return len(burst)


def read_session(actor):
    """读当前会话：消息列表 + 最后一条。返回 (bubbles, last, png)。

    🔴 2026-11-08 22:4x（白烧 OCR）：
      原来写的是 `bs = E.bubbles(png)` 之后又 `last = E.last_bubble(png)`。
      但 eyes/chat.py 里 last_bubble() 的实现就是 `bs = bubbles(png); return bs[-1]`
      —— 等于对**同一张 png 跑了第二遍 OCR**（实测约 3.5s/次，每进一个会话白花一次）。
      bubbles() 已按 cy 升序排好，直接取 bs[-1] 与 last_bubble() 完全等价。
    """
    png = actor.dev.screencap()
    bs = E.bubbles(png)
    last = bs[-1] if bs else None
    return bs, last, png


# 列表行里不该用来反查的文本
_SKIP_LABELS = {"头像", "匹配", "刚刚在线", "在线", "手机信号满格。", "WLAN 信号满格。"}

# 🔴 2026-11-05：sid 反查失败后的「强制重拉库」节流（60s 一次）。
#    OCR 拿到的短文本/表情刷不出候选时不能反复强拉（一次 pull 几秒，会拖垮清红点）。
_SID_REFRESH_LAST = {"t": 0.0}


def sid_from_row(db, row):
    """**进会话前**用列表行文本反查 sid，命中唯一才返回。

    🔴 提速关键（2026-11-02）：原来必须进会话 -> 截图 OCR(3.5s) -> 拿气泡文本反查，
    而列表行的「消息预览」本身就是 chatmsg.text 原文（短消息不截断），
    直接拿来精确匹配就能拿到 sid -> 省掉一次截图 + 一次 OCR。
    反查不唯一（常见于「嗯」「是的」这种）就返回 None，退回 OCR 慢路径。
    """
    labels = []      # 长文本（>=4 字），全列表可用
    short = []       # 2~3 字，只在**红点会话**里认（防撞车）
    for t in row.labels:
        t = (t or "").strip()
        if len(t) < 2 or t in _SKIP_LABELS:
            continue
        if E.TS_RE.fullmatch(t) or t.endswith("日") or ":" in t[:6]:
            continue
        (labels if len(t) >= 4 else short).append(t)
    if not labels and not short:
        return None
    try:
        hits = db.sessions_for_texts(labels, min_len=4) if labels else []
        if not hits and short:
            # 🔴 2026-11-04：她刚发的话常常只有 2~3 字（「早」「在吗」「？」），
            #    原来 <4 字直接丢 → 必然反查不到 → 落进慢路径 OCR。
            #    短文本只在「有红点」的会话里认（红点=她刚发，候选少、不易撞车）。
            hits = db.sessions_for_texts(short, min_len=2, unread_only=True)
    except Exception as e:
        log.warning("行文本反查异常: %r", e)
        return None
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0][0]
    if hits[0][1] > hits[1][1]:          # 命中数明显更高才算
        return hits[0][0]
    return None


def _enter(actor, row, timeout=8.0, retries=2):
    """进入会话并确认落在 chat 页。返回 (snap, page)。

    🔴 2026-11-02 实测：设备卡时（dump 2~4s）点击后 4s 内可能还没跳转，
      原来直接判「进入后不是 chat 页」就放弃了，红点留着下次再撞。
      现在超时放宽到 8s，并且失败后**重新取树拿新坐标再点一次**。
    """
    # 🔴 2026-11-04（提速）：这里原来先 dump 一次 actor.snap(force=True)，
    #   但返回值在循环里必被 wait_page 覆盖、上层也只用 page → 纯白烧一次 dump(2~3.5s)。
    snap, pg = None, None
    for i in range(retries):
        # settle 1.6(×slow_factor 2.5=4s) -> 0.25：紧跟 wait_page 轮询，
        #   而一次 dump 本身就要 3s 远大于转场 0.5s，等两遍纯属重复。
        actor.hand.tap_node(row.node, settle=0.25)
        snap, pg = actor.wait_page(("chat",), timeout=timeout)
        if pg == "chat":
            return snap, pg
        if i + 1 < retries:
            log.warning("第 %d 次进会话失败（%s），重新取树重试", i + 1, pg)
            time.sleep(1.0)
            s2 = actor.snap(force=True)
            located = False
            try:
                from eyes.chatlist import rows as _rows
                from eyes.page import detect as _detect
                if _detect(s2) == "chatlist":
                    cand = [r for r in _rows(s2)
                            if 200 <= r.center[1] <= 1500
                            and (r.nickname or "") == (row.nickname or "")]
                    if cand:
                        row = cand[0]
                        located = True
            except Exception as e:
                log.warning("重新定位行异常: %r", e)
            if not located:
                # 🔴 2026-11-08 22:42 生产实证（误触 ¥198 订阅页的**直接原因**）：
                #   旧代码不管重定位成功与否，下一轮都继续 `tap_node(row.node)` ——
                #   而 row.node 是**上一棵树**里的坐标。此刻页面早已不是 chatlist
                #   （detect 返回 unknown/chat），同一个坐标落到别的控件上：
                #   实测 22:42:53 点 (x,316) 正好是会话页顶部那枚**铭牌** →
                #   直接打开 H5Activity「我的超级星人铭牌 / 限时6.6折 ¥198」付费页，
                #   该页吞返回键、底栏消失，整轮报废只能重启 App。
                #   ⇒ 重定位不到就**不要再点**，把 page 原样交还上层去导航。
                log.warning("重新定位不到 '%.10s' 的行（当前页 %s）→ 不再用旧坐标乱点",
                            (row.nickname or ""), pg)
                break
    return snap, pg


def handle_one(actor, db, row, dry_run=True, nick=""):
    """处理一个红点会话：进入 -> 判定 -> 生成 -> (发送) -> 返回。

    两条路径：
      快路径（默认）：列表行预览反查 sid -> 库里拿最后一条 -> 直接判定出话（不做 OCR）
      慢路径（反查失败）：进会话 OCR 读气泡 + 文本反查
    实测快路径比慢路径省 3~4s/人。
    """
    out = Outcome()
    out.nick = nick or row.nickname

    # ---------- 快路径 ----------
    sid_fast = sid_from_row(db, row)
    # 🔴 2026-11-04：末条取 latest（chatmsg 与 session 摘要里更新的那个）。
    #    402857053 号入向不落 chatmsg 时，只读 chatmsg 会把「她刚说的话」当空气。
    db_last, _src = db.latest(sid_fast) if sid_fast else (None, "")
    if sid_fast and db_last is not None:
        out.sid = sid_fast
        side = "me" if str(db_last.sender) == str(db.uid) else "her"
        out.side = side
        # 语音（type=5）的 text 通常为空，必须走 voice 层转文字，否则会被当成"无话可说"
        out.last_text, how = V.her_msg_of(db_last)
        out.kind = how
        nb = take_burst(db, out)
        log.info("[%s] 快路径 sid=%s 末条=%s %r（%s/%s，她连发 %d 条）",
                 out.nick, sid_fast, side, (out.last_text or "")[:28], how, _src, nb)

        # 系统提示卡片（little_tip / 引导）不是她说话。
        # 🔴 2026-11-05（必回漏洞，实测 8.2h 未回）：不能直接放弃 ——
        #   她说完话后可能紧跟一张卡片（已读/互动），直接 return 会让她的话
        #   永久没人接；且不触发 sync_turns，档案里也看不出待回。
        #   往前找她最后一条真实消息，找到了就继续走正常流程。
        if how == "tip":
            _real = her_last_real(db, out.sid, db.uid)
            _rt, _rh = V.her_msg_of(_real) if _real is not None else ("", "tip")
            if _rh != "text" or not _rt:
                log.info("[%s] 末条是系统卡片，前面是 %s → 不在此处理", out.nick, _rh or "无")
                actor.hand.back(settle=0.9)
                return out
            # 她可能连发几条（用户 2026-11-02：要一起看，不能只答最后一条）
            _burst = her_burst(db, out.sid, db.uid) or [_rt]
            out.burst = _burst
            out.last_text = R.merge_burst(_burst)
            out.kind = "text"
            out.side = "her"
            how = "text"
            log.info("[%s] 末条是系统卡片，但前有她未接的 %d 句 → 继续出话: %r",
                     out.nick, len(_burst), out.last_text[:40])

        snap, page = _enter(actor, row)
        if page != "chat":
            out.err = "进入后不是 chat 页: %s" % page
            log.warning("[%s] %s", out.nick, out.err)
            return out

        if side == "me":
            log.info("[%s] 最后一条是我发的 -> 无需回复", out.nick)
            actor.hand.back(settle=0.9)
            return out
        # 她最后一条没文本（语音/图片）-> 退回慢路径重新判
        if not out.last_text:
            log.info("[%s] 库里末条无文本，退回慢路径", out.nick)
            return _slow_path(actor, db, out, dry_run)
        return _reply_and_send(actor, db, out, dry_run)

    # ---------- 慢路径 ----------
    snap, page = _enter(actor, row)
    if page != "chat":
        out.err = "进入后不是 chat 页: %s" % page
        log.warning("[%s] %s", out.nick, out.err)
        return out
    return _slow_path(actor, db, out, dry_run)


def _slow_path(actor, db, out, dry_run):
    """OCR 读气泡 -> 反查 sid -> 判定 -> 出话。"""
    bs, last, png = read_session(actor)
    if last is None:
        out.err = "读不到消息"
        log.warning("[%s] %s", out.nick, out.err)
        actor.hand.back(settle=0.9)
        return out
    out.last_text, out.side = last[0], last[1]

    texts = [t for t, s, it in bs]
    cands = db.sessions_for_texts(texts)
    if not cands and time.time() - _SID_REFRESH_LAST["t"] >= 60:
        # 🔴 2026-11-05：库是 300s 拉取缓存，她刚发的话多半还没进
        #    session.lastMsgText / chatmsg → 反查必然落空 → sid 空
        #    → turns/简报/事实/warm 整条档案链断（实测 05:15~08:20 共 20 次）。
        #    强拉一次再查（与下面 OCR 冲突处理同一招），60s 节流。
        _SID_REFRESH_LAST["t"] = time.time()
        try:
            from data.imdb import open_account as _oa
            _db2 = _oa(actor.dev, force=True)
            cands = _db2.sessions_for_texts(texts)
            if cands:
                log.info("[%s] 反查：强拉库后命中 sid=...%s", out.nick, str(cands[0][0])[-8:])
        except Exception as _e:
            log.warning("[%s] 反查：强拉库失败 %r", out.nick, _e)
    if cands:
        out.sid = cands[0][0]
    else:
        out.err = "反查不到 sessionId"
        log.warning("[%s] %s", out.nick, out.err)

    db_last, _src = db.latest(out.sid) if out.sid else (None, "")
    forced_her = False
    if db_last is not None:
        db_side = "me" if str(db_last.sender) == str(db.uid) else "her"
        if db_side != out.side and out.side != "?":
            mode = os.environ.get("SOUL_OCR_CONFLICT", "her")
            log.warning("[%s] OCR 与库不一致：OCR=%s 库=%s（处置=%s）",
                        out.nick, out.side, db_side, mode)
            # 🔴 2026-11-03（用户放行）：库是 pull 缓存（REFRESH 300s），可能滞后于
            #    她刚发的那条。先强制重拉一次库再判；仍冲突则按「她发了」处理
            #    （必回优先），但只在 OCR 确实读到她那句文本时才这么做。
            if mode != "db":
                try:
                    from data.imdb import open_account as _oa
                    _db2 = _oa(actor.dev, force=True)
                    _last2, _src2 = _db2.latest(out.sid) if out.sid else (None, "")
                    if _last2 is not None:
                        db_last = _last2
                        db_side = "me" if str(db_last.sender) == str(db.uid) else "her"
                        log.info("[%s] 冲突重拉库后末条 side=%s", out.nick, db_side)
                except Exception as _e:
                    log.warning("[%s] 冲突重拉库失败: %r", out.nick, _e)
                if db_side != out.side and (out.last_text or "").strip():
                    # 🔴 2026-11-08 21:2x：冲突最终裁决交给**设备库**（真值）。
                    #   设备库说「我发的」→ 不重复回复；说「她发的」→ 必回；
                    #   设备库查不到（adb 抖动）才退回原来的「必回优先」。
                    _dside, _dtxt = _device_last_side(actor.dev, db.uid, out.sid)
                    if _dside == "me":
                        db_side = "me"
                        log.info("[%s] 冲突裁决（设备库）：末条是我 %r → 不回（防重复回复）",
                                 out.nick, (_dtxt or "")[:20])
                    elif _dside == "her":
                        db_side = "her"
                        forced_her = True
                        log.warning("[%s] 冲突裁决（设备库）：末条是她 %r → 必回",
                                    out.nick, (_dtxt or "")[:20])
                    else:
                        forced_her = True
                        log.warning("[%s] 重拉后仍冲突且设备库不可用 → 按「她发了」处理（必回优先）",
                                    out.nick)
        out.side = "her" if forced_her else db_side
        if forced_her:
            her_msg, how = (out.last_text or ""), "text"
        else:
            her_msg, how = V.her_msg_of(db_last)
        out.kind = how
        if how == "tip":
            # 🔴 2026-11-05：同快路径 —— 末条是卡片时往前找她真实的话，
            #   有未接的就继续出话，别让她的话被一张卡片挡死。
            _real = her_last_real(db, out.sid, db.uid)
            _rt, _rh = V.her_msg_of(_real) if _real is not None else ("", "tip")
            if _rh != "text" or not _rt:
                log.info("[%s] 末条是系统卡片，前面是 %s → 不在此处理", out.nick, _rh or "无")
                actor.hand.back(settle=0.9)
                return out
            _burst = her_burst(db, out.sid, db.uid) or [_rt]
            her_msg = R.merge_burst(_burst)
            out.burst = _burst
            how = "text"
            out.side = "her"
            out.kind = "text"
            log.info("[%s] 末条是系统卡片，但前有她未接的 %d 句 → 继续出话: %r",
                     out.nick, len(_burst), her_msg[:40])
        if how == "none" and V.is_voice(db_last):
            log.info("[%s] 语音转写失败，用占位话术照样回", out.nick)
        elif not her_msg:
            her_msg = out.last_text
            out.side = "?"
    else:
        her_msg = out.last_text
        log.warning("[%s] 无库数据，仅凭 OCR 判定 side=%s", out.nick, out.side)

    if out.side == "me":
        log.info("[%s] 最后一条是我发的 -> 无需回复", out.nick)
        actor.hand.back(settle=0.9)
        return out
    out.last_text = her_msg or out.last_text
    nb = take_burst(db, out)
    if nb > 1:
        log.info("[%s] 慢路径：她连发 %d 条 → 合并处理", out.nick, nb)
    return _reply_and_send(actor, db, out, dry_run)


# 🔴 必回兜底话术：旧引擎（豆包）偶尔返回空（日志实测 2 次，都是对方只发「嗯」「是的」），
#   按「必回」铁律绝不能因此不发 —— 用一句不会出错的话顶上。
FALLBACK_LINES = ("嗯嗯，在的", "刚看到，你说", "在呢，你继续", "嗯，我听着")

# 非文本消息的固定话术。
# 为什么不交给引擎现生成：占位串（「她发来一张图片」）喂进去，豆包容易编造
# 图片内容（"你穿这身真好看" 结果她发的是一张表情包），所以用安全短句。
MEDIA_REPLIES = {
    "image": ("这图啥意思呀[笑]", "拍得还挺有意思", "这是哪儿呀"),
    "emoji": ("这表情啥意思哦", "哈哈，收下了", "你这表情我看懂了"),
    "other": ("你发的啥呀，我这边没看清", "刚那条我没看明白"),
}


def fallback_line():
    import random
    return random.choice(FALLBACK_LINES)


def _send_lines(actor, lines, nick, page_checked=False, sid=""):
    """依次发出多条。返回 (成功条数, 错误说明)。

    page_checked=True：调用方**刚**用 wait_page 确认过是 chat 页、
    且中间没有任何 UI 动作（只有模型调用/库读写）→ 省掉一次 dump(2~3.5s)。
    2026-11-04（提速）：实测一次 dump 3s，一个回复要 dump 6 次，这项占 1/6。

    用户 2026-11-02：「回复内容也是可以发多条，不要固定一条」。
    多条之间留 1.6s 间隔 —— 太密会被当成刷屏（Soul 有连发限制），
    太长她又会觉得对面在挤牙膏，1.5~2s 接近真人打字节奏。
    """
    # §104 跟进阶梯：发送前先过闸（页面校验之前）。归档或额度用尽则一条不发；
    #    额度不足时按 allow 返回的 n 截断 lines（Decision.n 已按额度截断）。
    #    sid="" 为无主会话，放行且不纳入额度；台账异常一律降级放行，
    #    绝不让新台账把「必回」链路掐死。
    try:
        from brain import sendgate as SG
        if SG.ON and sid:
            # 🔴 2026-11-10（用户口径「都读实时库，本地库没有用」）：镜像滞后会让
            #    verdict 的 C2「她再发→清零」看不到她刚发的事实 → following 误拦
            #    （实测 13:49 等一束光 13:42「喜欢听你说」被 2/2 拦截，强拉镜像仍
            #    「新增 0 条」）。发送前用 data.imdb._dev_sql **直查设备库 session
            #    行**（0.05~0.3s，不走 pull）：timestamp 显著晚于我方最后发送
            #    （>5s）⇒ 末条必是她 ⇒ 作为 her_ts_ms 喂闸，C2 清零正常生效。
            #    查不到/解析失败 → 不喂，按原台账走，行为向后兼容。
            _her_ts_feed = None
            try:
                from data import imdb as _IM
                from data import reply_state as _RS
                _uid_now = _IM.current_uid(actor.dev)
                _name = _IM._db_name_for_uid(actor.dev, _uid_now)
                _last_send = 0.0
                try:
                    _sends = (_RS.get(sid) or {}).get("sends") or []
                    _last_send = max(_sends) if _sends else 0.0
                except Exception:
                    pass
                if _name:
                    _raw = _IM._dev_sql(
                        actor.dev, _name,
                        "select ifnull(timestamp,0) from session where sessionId='%s' limit 1"
                        % str(sid), timeout=8) or ""
                    _line = ""
                    for _ln in _raw.replace("\r", "").splitlines():
                        if _ln.strip():
                            _line = _ln.strip()
                    if _line:
                        _ts = float(_line.split("|")[0] or 0)
                        _ts_s = _ts if _ts < 1e11 else _ts / 1000.0
                        if _ts_s > _last_send + 5:
                            _her_ts_feed = _ts_s * 1000.0
                            log.info("实时库核对 sid=...%s：session.ts=%.0f > 我方末发 %.0f"
                                     " → 她刚发，按 C2 清零喂闸", str(sid)[-8:], _ts_s, _last_send)
            except Exception as _e:
                log.debug("实时库核对失败（按台账走）: %r", _e)
            _d = SG.allow(sid, len(lines), her_ts_ms=_her_ts_feed)
            if not _d.ok:
                log.info("[%s] 跟进阶梯拦截 sid=%s state=%s（%s）", nick, sid, _d.state, _d.reason)
                return 0, "跟进阶梯拦截(%s)" % _d.state
            if _d.n < len(lines):
                lines = lines[:_d.n]
    except Exception:
        pass
    # 🔴 灌字前必须确认在会话页：搜索页也有输入框，一旦页面没退干净，
    #    整句话会灌进搜索框（实测截图里搜索框残留「这娃儿笑起来乖得很撒，你」），
    #    消息永远发不出去，还会把搜索状态彻底搞乱。
    if not page_checked:
        try:
            from eyes.page import detect as _det
            _pg = _det(actor.snap())
            if _pg != "chat":
                log.warning("[%s] 灌字前页面=%s（不是 chat）→ 放弃发送", nick, _pg)
                return 0, "不在会话页(%s)" % _pg
        except Exception as e:
            log.debug("页面校验异常（继续）: %r", e)

    inp = Input(actor.dev)
    sent = 0
    # 🔴 发送**前**就声明「接下来这些库写入是我自己的」——
    #    发送瞬间 App 就写库，监控线程 1.5s 一轮，等发完再 mark 已经晚了，
    #    会被判成「有新消息」把后面的动作全打断（实测唤醒/清红点都中过）。
    try:
        from data import watch as _W
        _W.mark_self_write(15.0)
    except Exception:
        pass
    try:
        for i, line in enumerate(lines):
            if i:
                time.sleep(1.6)
            # 每条独立兜底：第 2 条抛异常不能把「已发 1 条」的事实也一起吞掉
            try:
                ok, got = inp.type_and_verify(line, actor)
                if not ok:
                    return sent, "第%d条灌字失败(%r)" % (i + 1, got)
                # settle 1.2(×2.5=3s) -> 0.25：紧跟 sent_ok（sleep 0.7 + dump 3s）已在等
                if not inp.tap_send(actor, settle=0.25):
                    inp.clear()
                    return sent, "第%d条找不到发送按钮" % (i + 1)
                # 🔴 2026-11-04（闭环）：按三态记账，与 pendingq.py 的发送路径保持一致。
                #   sent_ok 的三态见 hands/input.py：ok / unknown / residual。
                #   unknown（转场帧读不到输入框）大概率已发出 → 必须记账，否则下轮重发 = 重复消息；
                #   只有 residual（框里还有字）= 明确没发出 → 不记账、留给下轮重试。
                _ok = inp.sent_ok(actor, line, timeout=4)
                _why = getattr(inp, "last_reason", "") or ""
                if (not _ok) and _why == "residual":
                    inp.clear()
                    return sent, "第%d条确认未发出（输入框仍有内容）" % (i + 1)
                if not _ok:
                    log.warning("[%s] 第%d条发送确认读不到输入框 → 按已发出记账（防重复）",
                                nick, i + 1)
            except Exception as e:
                log.warning("[%s] 第%d条发送异常: %r", nick, i + 1, e)
                try:
                    inp.clear()
                except Exception:
                    pass
                return sent, "第%d条异常(%r)" % (i + 1, e)
            sent += 1
            log.info("[%s] 已发送(%d/%d): %r", nick, i + 1, len(lines), line)
            try:
                from data import watch as _W
                _W.mark_self_write(6.0)      # 自己写的库变化，别当成别人来消息
            except Exception:
                pass
            try:
                from brain import ratelimit as _RL
                _RL.note_sent()
            except Exception:
                pass
    finally:
        # §104 跟进阶梯：按真实发出条数记账，覆盖上面 for 里所有 return 早退路径。
        #    只在末尾记一次会漏记早退时已发出的条数，额度会被击穿。
        #    sid="" 或 SOUL_FOLLOWUP_ON=0 时 SG.note_sent 内部自行跳过，不落账。
        #    台账异常一律吞掉，绝不改变本函数既定的返回结果（必回铁律）。
        if sent:
            try:
                from brain import sendgate as SG
                SG.note_sent(sid, sent)
            except Exception:
                pass
    return sent, ""


def _describe_image(db, out):
    """图片消息识图（DeepSeek 视觉）。返回图片描述文本；失败/异常返回 ""。

    2026-11-04：图片消息不再固定话术，识图成功后按图内容走引擎出话（保持人设）。
    失败必须返回 ""（回退固定话术），绝不能因识图失败而不回（必回铁律）。
    """
    try:
        db_last, _src = db.latest(out.sid) if out.sid else (None, "")
        # latest 在 session 摘要更新时会返回合成 Msg（msgContent=""），图片 URL 会丢；
        # 此时 fallback 直接读 chatmsg 末条。
        if db_last is None or not V.image_url(db_last):
            db_last = db.last_message(out.sid) if out.sid else None
        if db_last is None:
            return ""
        url = V.image_url(db_last)
        if not url:
            log.warning("[%s] 图片消息无 URL，无法识图", out.nick)
            return ""
        b = R.engine()
        if b is None:
            return ""
        fn = getattr(b, "describe_image", None) or getattr(b, "brain_describe_image", None)
        if fn is None:
            return ""
        desc = fn(url, timeout=25) or ""
        if desc:
            log.info("[%s] 识图成功 %d 字: %r", out.nick, len(desc), desc[:40])
        else:
            log.info("[%s] 识图返回空", out.nick)
        return desc
    except Exception as e:
        log.warning("[%s] 识图异常: %r", out.nick, e)
        return ""


def _reply_and_send(actor, db, out, dry_run):
    """出话 + 发送 + 返回。调用前须已在会话页。"""
    if out.sid:
        msgs = db.messages(out.sid, limit=12)
        hist = R.build_hist(msgs, db.uid)
    else:
        hist = []
    # 她这句可能只存在于 session 摘要（chatmsg 没有）→ 补进历史末尾，别让模型
    # 看到「历史以我结尾」还硬接话（2026-11-04，纯事实补全）。
    hist = R.hist_with_her(hist, out.last_text)

    # 2026-11-03（用户指出）：本地三技能应在**检测到新消息的第一时间**就排队，
    #   不是等回复发完再跑。这里已拿到 sid + 她这句话，立刻丢进单线程队列
    #   （soul_localq，同会话已在队列会自动跳过），然后照常出话 ——
    #   本地跑 ~28s（画像 L0 + 方案 L1），在线出话只要 1~3s，两条线并行。
    #   ⚠️ 第一条消息仍用**现成档案**出话（本地赶不上），更新后的档案供下一条用。
    if out.sid:
        try:
            R.warm_local(out.sid, db, her_msg=out.last_text, nick=out.nick)
        except Exception as e:
            log.debug("本地分析投递异常（不影响回复）: %r", e)

    # 📝 2026-11-03（用户口径「对话历史必须实时更新」）：
    #   她这句话在**出话之前**就写进 L2。原来要等回复发出去才写（在下面），
    #   于是 V9 读到的「你俩的全部对话」永远缺她最新这一句 —— 历史是滞后的。
    if out.sid and (out.last_text or "").strip():
        try:
            from brain.pack import store as _PKlive
            # ① 先按 DB 游标把新消息补齐（幂等，不会重复写）
            _PKlive.sync_turns(out.sid, msgs, getattr(db, "uid", ""))
            # ② 她最新这句可能只存在于 session 摘要（chatmsg 还没落库）→ 手工补一行。
            #    不推进 last_ts_ms，下一轮 sync 靠末行去重跳过它。
            t = (out.last_text or "").strip()
            if t and _PKlive.last_her_line(out.sid) != t:
                _PKlive.append_turns(
                    out.sid, [(time.strftime("%m-%d %H:%M"), "她", t[:200])])
        except Exception as e:
            log.debug("对话落盘失败（不影响出话）: %r", e)

    # 2026-11-04：图片消息先 DeepSeek 识图；成功则按图内容走引擎出话（保持人设），
    #   失败回退固定话术（识图失败绝不能导致不回，必回铁律）。
    if out.kind == "image":
        _desc = _describe_image(db, out)
        if _desc:
            out.kind = "text"
            out.last_text = "（她发来一张图片，图里是：%s）" % _desc
            log.info("[%s] 图片识图成功 → 按内容出话", out.nick)

    if out.kind in MEDIA_REPLIES:
        import random as _rnd
        lines = [_rnd.choice(MEDIA_REPLIES[out.kind])]
        log.info("[%s] %s 消息 → 固定话术 %r", out.nick, out.kind, lines[0])
    else:
        # 用户 2026-11-02：她连发几条我可以多回几条，不固定一条。
        # 条数按她的内容自适应（target_n），上限 ADAPT_CAP=3。
        # 🔴 2026-11-03：连发已合并成一句话（上限 10 条），合并后长度会被撑大，
        #    若拿合并文本算 target_n 会一路判成 3 条 → 她发几条我就回三条，像刷屏。
        #    所以条数只看**她最后一条**（她一次说完的落脚点）。
        _tn_in = [out.burst[-1]] if out.burst else [out.last_text]
        n = R.target_n(_tn_in, hist)
        lines = R.generate(out.sid or ("x" + str(int(time.time()))),
                           out.last_text, hist=hist, n_cand=n)
        if lines:
            log.info("[%s] 她要回 %d 条 → 引擎给了 %d 条: %r",
                     out.nick, n, len(lines), " | ".join(lines)[:60])
    if not lines:
        # 必回铁律：引擎不给话也必须发一句，不能沉默
        lines = [fallback_line()]
        # 🔴 2026-11-11（FAIL 噪声）：引擎出话**无产出**已被兜底话术完全接住——
        #   必回铁律保证一定发一句（fallback_line 永不空），不是故障，与 PR#13
        #   降级的「已兜住」路径同类。用「无产出」取代「失败」避免被 nightly_collect
        #   的 FAIL 关键字误计；真正的发送失败由 _send_lines 的 err 另行 WARN。
        log.warning("[%s] 引擎无产出 → 用兜底话术 %r", out.nick, lines[0])
    out.lines = list(lines)
    out.reply = " | ".join(lines)

    if dry_run:
        log.info("[%s] DRY 将回复 %d 条: %r", out.nick, len(lines), out.lines)
        actor.hand.back(settle=0.9)
        return out

    # 📷 她要是主动要照片 → 先发一张（用户 2026-11-02 配了桌面 1/2/3.jpg）
    _pic_sent = False
    try:
        from brain import picreq as _PR
        _pic_sent, _why = _PR.try_send(actor, actor.dev, out.sid or out.nick, out.last_text)
        if _pic_sent:
            log.info("[%s] 已按她要的发了照片", out.nick)
    except Exception as _e:
        log.warning("发图判断异常（继续发文字）: %r", _e)

    # 刚刚 _enter/wait_page 已确认 chat 页；中间只有模型与库操作，没有 UI 动作。
    # 例外：picreq 真发了照片（动过 UI）→ 不复用，老老实实再校验一次。
    sent_n, err = _send_lines(actor, out.lines, out.nick,
                              page_checked=not _pic_sent, sid=out.sid or "")
    if sent_n:
        out.sent = True
    if err:
        out.err = err
        log.warning("[%s] %s（已发 %d/%d 条）", out.nick, err, sent_n, len(out.lines))

    # 🧠 本地模型：把这一轮新对话喂给画像(L0)/方案(L1)。
    #    用户 2026-11-02「本地模型补对方人设…也要接入」——后台单线程跑，
    #    不阻塞回复；下一轮出话就能读到更新后的画像。
    # 📝 案情包 L2：把这一轮「她说的 / 我发的」追加进去。
    #    2026-11-03 修：1.0 从来没调过 append_l2，L2 冻结在旧版最后一次写入的时刻；
    #    而旧引擎用 L2 当「你俩的全部对话」注入、并因此丢掉真实 hist
    #    → 模型接着 4~6 天前的话题说话（病例：L2 停在 10-27「炒面」→ 输出「想尝一口」）。
    if sent_n and out.sid:
        try:
            from brain.pack import store as _PK
            # 只记**实际发出去**的那几条（sent_n）——「打算发但发送失败」的句子
            # 若写进对话史，下一轮模型会引用一句她从没见过的「我说的」。
            _PK.note_my_reply(out.sid, " / ".join(out.lines[:sent_n])[:200])
        except Exception as e:
            log.debug("我发的话落盘失败（不影响回复）: %r", e)

    # （本地分析已在 _reply_and_send 入口投递过 —— 越早跑越可能赶上下一轮）

    # 🏠 个人主页：没有档案的补一次（用户 2026-11-02 要求）。
    #    ⚠️ 必须在**还在会话页**时做 —— visit_profile 的入口是会话页右上
    #    「查看主页」/头像，而且它自己会退回会话页。
    #    已有档案时 has_profile() 只读一个文件，0 成本。
    if sent_n and out.sid:
        try:
            from brain import casepack as _CP
            if _CP.ensure_profile(actor, out.sid, db):
                log.info("[%s] 已补建个人主页档案", out.nick)
        except Exception as e:
            log.debug("补建主页异常（不影响主流程）: %r", e)

    actor.hand.back(settle=1.0)
    return out
