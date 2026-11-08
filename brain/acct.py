# -*- coding: utf-8 -*-
"""账号轮转：榨干配额 或 强制 8 小时切号。

旧口径（soul_daemon 2026-10-05 拍板，这里原样复刻）：

  · 切号前提 = **三条同时成立**，且持续 `dry_hold_min`(30) 分钟：
      ① 无人可聊（真待回 = 0）
      ② 没人可唤醒（唤醒池 = 0，或池里有人但都还在冷却 —— 关键是「当下走不走得通」）
      ③ 没有匹配次数（今日剩余 = 0）
  · 连续在线 ≥ 8h → **强制切号**（不等三条件）
  · 切走后 4h 内不得切回该号；两次切号间隔 ≥ 30min
  · 只有 2 个号 → 目标即「另一个」；无号可切则原地不动（宁可等，绝不乱切）

用户 2026-11-02 补充：「除非无人可聊，不然不要出现空烧 / 长时间等待」。
  → 三条件评估是**每轮都做**（很便宜：待回/唤醒池都查本地库），
    只有第 ③ 条要开 UI 读星球页，限频 10 分钟。
"""
import os
import time

from core.log import get_logger
from core.paths import STATE, SOUL_PKG

log = get_logger("brain.acct")

QUOTA_CHECK_EVERY = 600      # 读匹配次数（要开星球页）最密 10 分钟一次
FORCE_SWITCH_H = 8.0         # 连续在线超过 8h 强制切号
FORCE_HARD_H = 10.0          # 硬顶：超过 10h 不管有没有红点都切（账号风控优先）
                             # 为什么要有：切号已下移到「回复之后」，而红点几乎永远清不完
                             # → 若以红点为唯一条件，账号会一直在线不切（实测 42h 未切）。
DRY_HOLD_MIN = 30            # 三条件持续 30 分钟才切
# ⚠️ 2026-11-08：SWITCH_COOL_H **没有实现**。全仓只有这里定义 + daemon.py:401 的
#   一句注释在引用它，没有任何代码读它来做「切走后 4h 内不切回该号」的判定。
#   保留符号是因为 daemon.py 的注释靠它说明设计意图；真要做冷却请显式实现并接线，
#   别以为改这个数字就会生效。
SWITCH_COOL_H = 4.0          # 设计值：切走后 4h 内不切回该号（未接线）
MIN_GAP_MIN = 10             # 两次切号至少间隔 10 分钟（用户 2026-11-02 拍板选 2：
                             # 一个号待 5 分钟→切→再待 5 分钟，轮转快但不至于高频切号撞车）
# 🔴 用户 2026-11-02：「整个流程走完之后 5 分钟没有新消息就切号吧」
#    这是"榨干"的另一种表达 —— 这个号已经没机会了，换一个继续找。
# 🔴🔴 2026-11-08：下面这行原来写 `IDLE_SWITCH_MIN = 5`，然后在文件第 220 行
#   又被 `IDLE_SWITCH_MIN = float(os.environ.get("SOUL_IDLE_SWITCH_MIN","30") or 30)`
#   整个覆盖掉 —— 模块级代码，import 完就是 30。也就是说这里的 5 **从来没有生效过**，
#   而改这一行的人会以为改了（陷阱）。现在删掉 5，唯一的定义留在第 220 行（可被
#   环境变量覆盖）。要调空闲切号阈值：设 SOUL_IDLE_SWITCH_MIN，别改这里。
# 🔴 2026-11-04（闭环）：**切号尝试失败要退避**。
#   实测 02:06~02:12 强制切号连续失败（点击后 uid 没变），因为成功才更新 last_switch，
#   失败不留痕 → 下一轮又重开账号面板、点行、重启 App，每次 30~60s 全白烧，
#   还把设备占着让回复更慢。现在失败也记时间，退避 30 分钟内不再试。
FORCE_RETRY_GAP_MIN = 30

SWITCH_FILE = STATE / "switch_book.json"


def _switch_backoff_left():
    """上次切号**尝试失败**后的剩余退避分钟（0 = 不在退避）。"""
    try:
        d = _load()
        t = float(d.get("last_switch_try") or 0)
        if not t:
            return 0.0
        return max(0.0, FORCE_RETRY_GAP_MIN - (time.time() - t) / 60.0)
    except Exception:
        return 0.0


# ---------------- 切号台账 ----------------
def _load():
    import json
    try:
        return json.loads(SWITCH_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save(d):
    import json
    try:
        SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        SWITCH_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        log.warning("保存切号台账失败: %r", e)


def online_hours():
    """本账号连续在线时长（从第一次见到它的时间算）。"""
    d = _load()
    return (time.time() - float(d.get("online_since") or time.time())) / 3600.0


def note_online(uid):
    """记录当前账号的在线起点（换号时清零重算）。"""
    d = _load()
    if str(d.get("cur_uid") or "") != str(uid):
        d["cur_uid"] = str(uid)
        d["online_since"] = time.time()
        _save(d)
        log.info("账号 %s 在线计时开始", uid)


def last_switch_ago_min():
    d = _load()
    ts = float(d.get("last_switch") or 0)
    return (time.time() - ts) / 60.0 if ts else 1e9


# ---------------- 三条件评估 ----------------
def read_quota(actor):
    """读星球页**灵魂匹配**卡片的「今日剩余 N 次」。返回 (剩余, 是否读到)。

    🔴 2026-11-08 21:3x（切号被卡死的真根因，实测截图 + UI 树）：
      星球页现在是**两张卡并排**：
        左：灵魂匹配 / 「立即寻找懂你的人」（App 改版后**不再显示次数**）
        右：语音匹配 / 「今日剩余3次」
      旧实现把整页文本拼起来找「剩余 N 次」，抓到的是**语音匹配**的 3，
      于是 preflight 一直报「今日还剩 3 次匹配」→ 永不切号；
      而 daemon 侧的记录是「今日匹配额度已用完」。两边打架，人卡在同一个号上。
      修法：只在**左半边（灵魂匹配卡片）**里找次数；找不到就老实返回「读不到」。
    """
    from brain import nav

    snap, pg = nav.to_tab(actor, "星球")
    if pg != "planet":
        return None, False
    import re

    # 灵魂匹配卡片的右边界：用标题节点的几何定，定不到就取屏幕左半
    left_max = 450.0
    for n in snap.nodes:
        if n.visible and (n.text or "").strip() == "灵魂匹配":
            left_max = (n.bounds[0] + n.bounds[2]) / 2.0 + 60
            break

    for n in snap.nodes:
        if not n.visible:
            continue
        t = (n.text or "").strip()
        if not t or n.bounds[0] >= left_max:
            continue
        m = re.search(r"剩余\s*(\d+)\s*次", t)
        if m:
            return int(m.group(1)), True
    for n in snap.nodes:
        if not n.visible or n.bounds[0] >= left_max:
            continue
        t = (n.text or "").strip()
        if "次数已用完" in t or "次数用完" in t:
            return 0, True
    return None, False


def evaluate(actor, db, st, force_quota=False):
    """三条件评估。返回 (should, why)。

    只读，不做任何写操作；读不到的一律当「未知 -> 不切」（旧代码踩过：
    读库失败被当成"池空了"→ 误切号）。
    """
    now = time.time()

    # ① 无人可聊
    try:
        pend = db.pending()
        real = [p for p in pend if not p[0].is_official]
        if real:
            return False, "有人可聊(%d)" % len(real)
    except Exception as e:
        return False, "pending 探测失败（未知）: %r" % e

    # ② 没人可唤醒（池空 或 都在冷却）
    try:
        from brain import wake as W
        cands = W.candidates(db, limit=6)
        if cands:
            gap = W.WAKE_EVERY if hasattr(W, "WAKE_EVERY") else 60
            last = float(st.get("last_wake", 0) or 0)
            if last and (now - last) < gap:
                pass                      # 冷却中 -> 这条路也算堵
            else:
                return False, "唤醒池 %d 人（可唤）" % len(cands)
    except Exception as e:
        return False, "唤醒池未知 -> 不切号: %r" % e

    # ③ 没有匹配次数（限频读 UI）
    rec = _load().setdefault("quota", {})
    q, ok = None, False
    if not force_quota and rec.get("q") is not None and (now - float(rec.get("t") or 0)) < QUOTA_CHECK_EVERY:
        q, ok = rec["q"], True
        log.info("匹配次数（缓存 %.0fs 前）: %s", now - float(rec.get("t") or 0), q)
    else:
        q, ok = read_quota(actor)
        if ok:
            d = _load()
            d["quota"] = {"q": q, "t": now}
            _save(d)
            log.info("匹配次数（现读）: %s", q)
    if not ok:
        # 🔴 2026-11-08 21:3x（用户口径「脚本切号」+ App 改版）：
        #   左卡（灵魂匹配）改版后不再显示剩余次数 → 读不到是**常态**，不是异常。
        #   旧策略「读不到就不切」会让号永远卡在同一个账号（实测 18:07~18:57 连续 9 次）。
        #   新策略：读不到时用**空闲时长**兜底 —— 已经空闲 ≥30 分钟且没有可处理的人，
        #   就允许切号（用户要的是"这个号没活干了就换"，不是"读不到就死等"）。
        if _idle_minutes(st) >= IDLE_SWITCH_MIN:
            log.warning("匹配次数读不到，但已空闲 %.0f 分钟（≥%.0f）→ 允许切号兜底",
                        _idle_minutes(st), IDLE_SWITCH_MIN)
            return True, "次数未知 + 空闲 %.0f 分钟" % _idle_minutes(st)
        return False, "匹配次数读不到（未知）-> 不切号（空闲 %.0f 分钟）" % _idle_minutes(st)
    if q and q > 0:
        return False, "还有 %d 次匹配" % q

    return True, "三条件成立（无人可聊 / 无人可唤醒 / 匹配次数 0）"


def _quota_cached(actor, force=False):
    """读匹配额度（带缓存，10 分钟内不重复开星球页）。返回 (次数, 是否读到)。"""
    now = time.time()
    rec = _load().get("quota") or {}
    if (not force and rec.get("q") is not None
            and (now - float(rec.get("t") or 0)) < QUOTA_CHECK_EVERY):
        return rec["q"], True
    q, ok = read_quota(actor)
    if ok:
        d = _load()
        d["quota"] = {"q": q, "t": now}
        _save(d)
    return q, ok


IDLE_SWITCH_MIN = float(os.environ.get("SOUL_IDLE_SWITCH_MIN", "30") or 30)
_LAST_ACTIVE = {"t": 0.0}


def mark_active():
    """主循环每处理一件事（回消息/匹配/唤醒）就调一次，用来算「空闲多久」。"""
    _LAST_ACTIVE["t"] = time.time()


def _idle_minutes(st):
    """空闲分钟数：优先用最近一次业务活动时间，退回首轮时间。"""
    t = max(_LAST_ACTIVE["t"], float(st.get("round0", 0) or 0))
    if not t:
        return 0.0
    return max(0.0, (time.time() - t) / 60.0)


def preflight(actor, db, st):
    """切号前体检：确认这个号真的没活干了。

    🔴 用户 2026-11-02：「切号之前一定要确认当前账号是否还有未回的消息、
       匹配额度是否归零、唤醒好友是否完成等等一系列问题」。
    原实现里「空闲 5 分钟切号」那条路**直接切**，跳过了三条件检查 ——
    哪怕还有 9 条未读、还有 20 次匹配额度，也会被切走。这个函数就是补这个洞。

    返回 (ok, [未完成项])。读不到的一律当作「未完成」（保守，宁可不切）。
    """
    blockers = []

    # ① 库里未读 —— 只算**真人待回**（设备还在 + 末条是她 + 不在冷却）
    #
    # 🔴 2026-11-08 21:3x（用户口径「脚本切号」切不动的真根因）：
    #   旧实现直接 `SELECT COUNT(*) ... unReadCount>0`，把**僵尸会话**也算进去：
    #   Soul 清过历史的库里，镜像仍有 1300 个会话，其中 211 个在 App 里早就不存在，
    #   它们的 unReadCount 永远 >0 → 切号闸一直报「库里 12 个会话未读」→ 永不切号。
    #   实测 18:07~18:57 连续 9 次「空闲 130~180 分钟，但还有 3 项没做完 → 先不切号」，
    #   匹配额度早就用完，号一直卡在同一个账号上。
    #   现在口径和「红点闸 / candidates()」统一：只有真能去回的人才算未完成。
    try:
        from brain import pendingq as PQ
        from data import imdb as _IM
        _devref = getattr(db, "dev", None)
        _live = _IM.device_live_uids(_devref, db.uid) if _devref is not None else None
        _rows = db.con.execute(
            "SELECT sessionId, toUserId FROM session WHERE unReadCount > 0").fetchall()
        _real = []
        for _sid, _to in _rows:
            _sid = str(_sid)
            if _live is not None and str(_to or "") not in _live:
                continue                      # App 里已经没有这个会话（僵尸）
            _last, _src = db.latest(_sid)
            if _last is None or str(_last.sender) == str(db.uid):
                continue                      # 末条是我发的 / 没有消息
            if PQ.should_skip(_sid, getattr(_last, "text", "") or ""):
                continue                      # 冷却中（刚找过没找到）
            _real.append(_sid)
        if _real:
            blockers.append("库里 %d 个会话未读（真人待回）" % len(_real))
    except Exception as e:
        blockers.append("读未读数失败（未知）: %r" % e)

    # ② 待回（末条是她发的，含已读未回）
    try:
        from brain import pendingq as PQ
        cands = PQ.candidates(db, limit=3)
        if cands:
            blockers.append("%d 个待回未处理" % len(cands))
    except Exception as e:
        blockers.append("待回探测失败（未知）: %r" % e)

    # ③ UI 上还有没有红点
    try:
        from brain import clear as CL
        # 🔴 2026-11-08（库直读 P0）：传 db 走库判定 —— 屏幕行内红点
        #   `unread_msg_number` 实测 4/4 轮 0 个节点，旧判据恒 False，
        #   会让切号闸误以为「已清干净」。
        has_dot, badge, ndots = CL.has_dot_now(actor, db=db)
        if has_dot:
            blockers.append("聊天角标 %s（当前屏红点 %d）" % (badge, ndots))
    except Exception as e:
        log.debug("红点探测失败: %r", e)

    # ④ 匹配额度没榨干
    try:
        q, qok = _quota_cached(actor)
        if not qok:
            blockers.append("匹配额度读不到（未知）")
        elif q and q > 0:
            blockers.append("今日还剩 %d 次匹配" % q)
    except Exception as e:
        blockers.append("匹配额度异常（未知）: %r" % e)

    # ⑤ 唤醒还没跑（刚跑过就不算阻塞，否则人多的时候永远切不了）
    try:
        from brain import wake as W
        last_wake = float(st.get("last_wake", 0) or 0)
        recently = (time.time() - last_wake) < 600      # 10 分钟内唤过 = 本轮已做
        if not recently and W.candidates(db, limit=1):
            blockers.append("还有可唤醒的老友没唤（上次唤醒在 %.0f 分钟前）"
                            % ((time.time() - last_wake) / 60 if last_wake else -1))
    except Exception as e:
        log.debug("唤醒探测失败: %r", e)

    return (len(blockers) == 0), blockers


def maybe_switch(actor, dev, db, st, force_quota=False):
    """决定并执行切号。返回 (switched, why)。"""
    from brain import nav

    # 冷却与间隔
    if last_switch_ago_min() < MIN_GAP_MIN:
        return False, "距上次切号 %.0f 分钟（< %d）" % (last_switch_ago_min(), MIN_GAP_MIN)
    _bo = _switch_backoff_left()
    if _bo > 0:
        return False, "上次切号失败，退避中（剩 %.0f 分钟）" % _bo

    # 空闲切号的时间基准 + 当前在线时长
    idle_min = (time.time() - float(st.get("last_msg_ts") or 0)) / 60.0
    oh = online_hours()

    # ⏰ 8h 强制切号：最高优先，**不等任何条件**（用户 2026-11-04 拍板：强制就是强制）
    #    原来这里也走 preflight，被「库里未读/匹配额度」拦住 → 一个号连续在线 40h+
    #    都不切（实测 online_since=11-02 07:52，acct.log 每轮都报「暂缓强制切号」）。
    if oh >= FORCE_SWITCH_H:
        log.warning("⏰ 已连续在线 %.1fh（≥%.0fh）→ 强制切号（不等三条件/体检）",
                    oh, FORCE_SWITCH_H)

    # 💤 空闲切号：整轮流程都走完 + 5 分钟没新消息
    #    必须先体检（用户 2026-11-02）—— 不体检的话哪怕还有未读/额度/可唤醒也照样切。
    elif idle_min >= IDLE_SWITCH_MIN:
        ok, blockers = preflight(actor, db, st)
        if not ok:
            log.info("💤 空闲 %.1f 分钟，但还有 %d 项没做完 → 先不切号：%s",
                     idle_min, len(blockers), "；".join(blockers))
            return False, "未完成 %d 项: %s" % (len(blockers), blockers[0])
        log.warning("💤 空闲 %.1f 分钟且确认没活干（无未读/无待回/额度 0/已唤醒）→ 切号",
                    idle_min)

    # 🔥 榨干：三条件成立并持续 30 分钟
    else:
        should, why = evaluate(actor, db, st, force_quota=force_quota)
        if not should:
            st["dry_since"] = 0
            return False, why
        since = float(st.get("dry_since") or 0)
        if not since:
            st["dry_since"] = time.time()
            return False, "三条件成立，开始计时（需持续 %d 分钟）" % DRY_HOLD_MIN
        held = (time.time() - since) / 60.0
        if held < DRY_HOLD_MIN:
            return False, "三条件已成立 %.0f 分钟（需 %d）" % (held, DRY_HOLD_MIN)
        log.warning("🔥 账号已榨干（三条件持续 %.0f 分钟）→ 切号", held)

    # 执行（三个分支都汇合到这里，统一更新台账；修掉了原「空闲切号直接 return
    #       不记 last_switch」的隐患）
    ok, why = switch_account(actor, dev)
    if ok:
        d = _load()
        d["last_switch"] = time.time()
        d["prev_uid"] = d.get("cur_uid")
        d["online_since"] = time.time()     # 新号重新计时
        d["dry_since"] = 0
        d["last_switch_try"] = 0            # 成功 → 清掉失败退避
        _save(d)
        st["dry_since"] = 0
        st["last_match"] = 0
        st["last_wake"] = 0
    else:
        # 🔴 2026-11-04（闭环）：失败也留痕，否则下一轮又重开面板空烧 30~60s
        #   （实测 02:06~02:12 连续 3 次尝试全失败，每轮白烧）。
        d = _load()
        d["last_switch_try"] = time.time()
        _save(d)
        log.warning("切号失败（%s）→ 退避 %d 分钟内不再试", why, FORCE_RETRY_GAP_MIN)
    return ok, why


def force_switch_if_due(actor, dev, db, st):
    """8h 强制切号（用户 2026-11-04 拍板）：每轮 cycle 早期调用，到点就切。

    为什么单独拆出来：maybe_switch 在 cycle 第⑥步，前面只要有回复/唤醒/匹配
    就 return，永远走不到 —— 实测一个号连续在线 41h+ 都不切。强制切号必须在
    每轮早期检查，不做 preflight/evaluate（强制就是强制，不等任何条件）。
    返回 (switched, why)。
    """
    if last_switch_ago_min() < MIN_GAP_MIN:
        return False, "距上次切号 %.0f 分钟（< %d）" % (last_switch_ago_min(), MIN_GAP_MIN)
    _bo = _switch_backoff_left()
    if _bo > 0:
        return False, "上次切号失败，退避中（剩 %.0f 分钟）" % _bo
    oh = online_hours()
    if oh < FORCE_SWITCH_H:
        return False, "在线 %.1fh（<%.0fh）" % (oh, FORCE_SWITCH_H)
    log.warning("⏰ 已连续在线 %.1fh（≥%.0fh）→ 强制切号（不等三条件/体检）",
                oh, FORCE_SWITCH_H)
    ok, why = switch_account(actor, dev)
    if ok:
        d = _load()
        d["last_switch"] = time.time()
        d["prev_uid"] = d.get("cur_uid")
        d["online_since"] = time.time()     # 新号重新计时
        d["dry_since"] = 0
        d["last_switch_try"] = 0            # 成功 → 清掉失败退避
        _save(d)
        st["dry_since"] = 0
        st["last_match"] = 0
        st["last_wake"] = 0
    else:
        # 🔴 2026-11-04（闭环）：失败也留痕，否则下一轮又重开面板空烧 30~60s
        #   （实测 02:06~02:12 连续 3 次尝试全失败，每轮白烧）。
        d = _load()
        d["last_switch_try"] = time.time()
        _save(d)
        log.warning("切号失败（%s）→ 退避 %d 分钟内不再试", why, FORCE_RETRY_GAP_MIN)
    return ok, why


def switch_account(actor, dev):
    """切到另一个账号（UI）。返回 (ok, why)。

    实测路径（2026-11-02）：
      「自己」页 → 左上「切换用户」图标 → 面板里点另一个账号行 → 落点还是「自己」页。
    ⚠️ 必须**先滑到顶部**再点：页面滚动时节点坐标会偏 40+ px，会点到「装扮中心」。
    """
    from brain import nav

    try:
        snap, pg = nav.to_tab(actor, "自己")
        if pg != "me":
            log.warning("回不到「自己」页（%s）", pg)
            return False, "回不到自己页(%s)" % pg

        # 滑到顶（关键）
        for _ in range(3):
            actor.hand.swipe(450, 400, 450, 1300, duration=0.18, settle=0.5)

        snap = actor.snap(force=True)
        n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
        if n is None:
            # 兜底：左上角那个图标（实测中心 62,98）
            cands = [x for x in snap.nodes
                     if x.clickable and x.center[1] < 160 and x.center[0] < 160]
            n = cands[0] if cands else None
        if n is None:
            log.warning("找不到「切换用户」入口")
            return False, "找不到切换用户入口"

        log.info("点切换用户 %s", n.bounds)
        actor.hand.tap_node(n, settle=2.0)

        # 🔴 2026-11-08 21:3x（实测：面板其实开了，是判定太急）：
        #   点完「切换用户」后旧代码只 snap 一次；设备慢一点（dump 0.5~2s）
        #   就会拿到上一帧 → 误报「账号面板没打开」→ 直接放弃切号。
        #   实测手动点同一个入口 1.5s 后就能看到「切换账号 / 添加账号」。
        #   改成最多轮询 4 次（每次 1.2s）。
        s = actor.snap(force=True)
        for _w in range(4):
            if "添加账号" in "\n".join(s.texts()):
                break
            time.sleep(1.2)
            s = actor.snap(force=True)
        if "添加账号" not in "\n".join(s.texts()):
            log.warning("账号面板没打开（轮询 4 次仍未出现「添加账号」）")
            return False, "账号面板没打开"

        rows = [x for x in s.nodes
                if x.clickable and x.visible
                and (x.bounds[2] - x.bounds[0]) > 700
                and 100 <= (x.bounds[3] - x.bounds[1]) <= 200]
        rows.sort(key=lambda x: x.bounds[1])
        if len(rows) < 2:
            return False, "面板里只有一个账号（没号可切）"

        # 🔴 不能靠「当前账号在第一行」这种硬假设 —— 切错号代价太大。
        #    做法：先记下当前 uid，切完再读一次 uid 对比；没变就换另一个账号行再试。
        from data.imdb import open_account
        try:
            before = str(open_account(dev).uid)
        except Exception as e:
            log.warning("切号前读 uid 失败（仍然继续）: %r", e)
            before = ""

        # 候选账号行（排除「添加账号」）
        def _cand_rows(sn):
            _rows = [x for x in sn.nodes
                     if x.clickable and x.visible
                     and (x.bounds[2] - x.bounds[0]) > 700
                     and 100 <= (x.bounds[3] - x.bounds[1]) <= 200]
            _rows.sort(key=lambda x: x.bounds[1])
            _cand = [r for r in _rows if "添加账号" not in (r.label or "")
                     and "添加账号" not in (r.desc or "")]
            return _cand or _rows

        # 🔴 2026-11-04 修复：原循环「点完第 1 个账号行 → app_start 重启 → 面板关闭
        #    → 第 2 个账号行的坐标失效」，导致点第 2 个账号 uid 没变。现在每次尝试
        #    前**重新打开面板**，用最新坐标点行。
        for attempt in range(2):
            if attempt == 0:
                s = actor.snap(force=True)
            else:
                snap, pg = nav.to_tab(actor, "自己")
                if pg != "me":
                    return False, "回不到自己页(%s)" % pg
                for _ in range(3):
                    actor.hand.swipe(450, 400, 450, 1300, duration=0.18, settle=0.5)
                # 🔴 2026-11-08 03:45 修复：attempt-1 原来找不到「切换用户」就直接放弃，
                #    但 attempt-0 有「左上角图标」兜底而 attempt-1 没有 —— 不对称。
                #    实测第一次切换就是死在这里（面板关了、入口还在原位）。
                #    现在补上同样的兜底 + 重试两次。
                _n = None
                for _try in range(2):
                    snap = actor.snap(force=True)
                    _n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
                    if _n is None:
                        _cands = [x for x in snap.nodes
                                  if x.clickable and x.center[1] < 160 and x.center[0] < 160]
                        _n = _cands[0] if _cands else None
                    if _n is not None:
                        break
                    time.sleep(2.0)
                if _n is None:
                    return False, "找不到切换用户入口"
                actor.hand.tap_node(_n, settle=2.0)
                s = actor.snap(force=True)
                if "添加账号" not in "\n".join(s.texts()):
                    return False, "账号面板没打开"

            cand = _cand_rows(s)
            log.info("面板候选账号行 %d 个", len(cand))
            # 🔴 2026-11-08 21:3x（实测）：面板第一行就是**当前账号**，
            #   点它当然「uid 没变」，白跑一轮 + 一次 app 重启。
            #   现在从第二行开始点（只有一个号时才回落到第一行）。
            order = (cand[1:] + cand[:1]) if len(cand) > 1 else cand
            if attempt >= len(order):
                break
            target = order[attempt]
            log.info("尝试切到第 %d 个账号 %s", attempt + 1, target.bounds)
            actor.hand.tap_node(target, settle=1.5)

            t0 = time.time()
            while time.time() - t0 < 40:
                time.sleep(2.5)
                try:
                    dev.u2().app_start(SOUL_PKG, wait=True)
                except Exception:
                    pass
                s2, pg2 = nav.to_tab(actor, "自己")
                if pg2 != "me":
                    continue
                try:
                    after = str(open_account(dev).uid)
                except Exception:
                    after = ""
                if before and after and after != before:
                    log.info("✓ 切号成功：%s -> %s", before, after)
                    return True, "已切号 %s -> %s" % (before, after)
                if not before and pg2 == "me":
                    log.info("✓ 切号后回到自己页（无法校验 uid）")
                    return True, "已切号（无 uid 校验）"
                log.info("   切完 uid 没变（%s）", after or "?")
                break
        return False, "两个账号都试了，uid 都没变"
    except Exception as e:
        log.warning("切号异常: %r", e)
        return False, repr(e)
