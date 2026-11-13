# -*- coding: utf-8 -*-
"""唤醒：给「聊过但冷了很久」的人主动发一句。

旧架构定义（soul_daemon 注释）：
  唤醒老联系人 = 选「聊过≥10句 且 冷≥12h」的人 + jianghua 开场
  节奏：最小间隔 10min、每次 2 人、单批预算 240s

本模块只负责「选人 + 出话」；发送由 hands/input 完成，调度由上层负责。
"""
import json
import os
import time

from brain import reply as R
from core.log import get_logger
from core.paths import STATE
from data.imdb import SYS_TYPES

log = get_logger("brain.wake")

MIN_MSGS = 10          # 聊过至少 10 句（文本消息）
COLD_HOURS = 12        # 冷却至少 12 小时
MAX_PER_ROUND = 2      # 每次唤醒 2 人（对齐旧架构 WAKE_N）
WOKE_COOLDOWN_H = 24   # 同一个人 24 小时内只唤醒一次（用户 2026-11-02 定「按人计」）
# 🔴 2026-11-05（用户定）：连续唤醒 N 次她都不回 → 放弃，不再主动找他。
#    台账 data/state/woke.json 里 "c<uid>" 存连续无回应次数：发送成功 +1，
#    她回过消息就清零（reset_if_replied）。到上限后 candidates 直接跳过。
#    她哪天主动来信 → 计数清零 → 自动恢复候选资格（不是永久拉黑）。
MAX_NO_REPLY = int(os.environ.get("SOUL_WAKE_MAX_NO_REPLY", "3"))

WOKE_FILE = STATE / "woke.json"


def _load_woke():
    try:
        return json.loads(WOKE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save_woke(d):
    try:
        WOKE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        log.warning("保存唤醒台账失败: %r", e)


# 🔴 2026-11-08 03:45（用户口径：「好友唤醒**三次，一天一次**」）
#
#   改前：失败只冷却 1200s（20 分钟）—— 同一个人一天里能被试几十次，
#        既不是「一天一次」，也是现网空烧的一大来源（实测同一人夜间被重试 20+ 次）。
#   改后：**不管成功还是没找着人，这个人都算「今天已经唤醒过一次」**，
#        下一次机会在 24h 后。配合 MAX_NO_REPLY=3 → 三次即永久放弃。
#
#   注意：失败仍保留一个短保险丝（WOKE_FAIL_COOL_S，默认 20 分钟）用于
#    **同一轮内的重试保护**（避免坏页面被连续猛撞），但它不再决定「下次能不能唤醒」，
#    能不能唤醒由 WOKE_COOLDOWN_H(24h) 单独说了算，见 _cooling()。
WOKE_FAIL_COOL_S = float(os.environ.get("SOUL_WAKE_FAIL_COOL", "1200"))
# 失败算不算「今天已经唤醒过」（默认算 = 严格一天一次）
WOKE_FAIL_COUNTS_AS_WAKE = os.environ.get("SOUL_WAKE_FAIL_COUNTS", "1") != "0"


def _cooling(woke, uid, now=None, hours=WOKE_COOLDOWN_H):
    """这次唤醒还在不在冷却期。

    🔴 2026-11-08 03:45（用户口径「一天一次，三次放弃」）：
      改前 —— 失败只挡 20 分钟（f<uid>），过 20 分钟又能再试。
      改后 —— 失败也算「今天唤过一次」：
        · 成功：按 str(uid) 记时间戳 → 24h 内不再找他
        · 找不到人：**同时写 f<uid> 和 str(uid)**（见 _bump_miss），
          于是同样受 24h 约束 ⇒ 真正做到「一天一次」
        · f<uid> 仅作为轮内重试的短保险丝保留（20 分钟）
    这样同一个人一天最多被尝试一次，三次没成 → is_given_up() 永久跳过。
    """
    now = time.time() if now is None else now
    ts = float(woke.get(str(uid)) or 0)
    if ts and (now - ts) < hours * 3600:
        return True
    fts = float(woke.get("f" + str(uid)) or 0)
    return bool(fts and (now - fts) < WOKE_FAIL_COOL_S)


def _no_reply_count(woke, uid):
    """连续多少次唤醒她都还没回。"""
    try:
        return int(woke.get("c" + str(uid)) or 0)
    except Exception:
        return 0


def _her_last_ts(db, sid, limit=8):
    """她在这个会话里最近一条消息的时间（毫秒）；取不到返回 0。

    🔴 2026-11-08（审计漏洞修复，见 reset_if_replied）：
      **不能**拿「会话最大 localTime」当「她回过话」的证据 —— 那里面包含
      我自己刚发的唤醒语。唤醒一发出去，会话最大时间就变成我的消息，
      下一轮扫描就会把它当成「她回了」。

    两级取证（顺序很重要）：
      ① `db.latest(sid)` —— 已融合 chatmsg 末条与 session 摘要，且**判过 sender**
         （含「文本命中我最近发的」交叉验证）。入向不落 chatmsg 的账号
         （实测 402857053）只有这一路能看到她的新话，必须先用它。
      ② 兜底再扫最近几条 chatmsg，筛出非我发的最大时间。
    两路都取不到 → 返回 0（**不清零**：宁可让一个唤不醒的人多留一轮，
      也不能把「我发的」当成「她回的」而让三次放弃失效）。
    """
    best = 0
    try:
        last, _src = db.latest(sid)
        if last is not None and str(last.sender) != str(db.uid):
            best = int(getattr(last, "ts", 0) or 0)
    except Exception as e:
        log.debug("db.latest 取她的末条失败 s=%s: %r", sid, e)
    if best:
        return best
    try:
        msgs = db.messages(sid, limit=limit)
    except Exception as e:
        log.debug("取她的末条时间失败 s=%s: %r", sid, e)
        return 0
    for m in (msgs or []):
        try:
            if str(m.sender) == str(db.uid):
                continue
            ts = int(getattr(m, "ts", 0) or 0)
        except Exception:
            continue
        if ts > best:
            best = ts
    return best


def reset_if_replied(woke, uid, her_ts_ms):
    """唤醒之后**她**回过消息 → 清零计数、解除 24h 冷却。返回是否清零。

    ⚠️ her_ts_ms 必须是「她发的消息」的时间，**不能**传会话最大时间。
       调用方用 `_her_last_ts()` 取（见 candidates）。

    🔴 2026-11-08 04:05（核对时发现的逻辑漏洞）：
      改前只 `pop("c"+uid)` 清零放弃计数，**不动 str(uid) 的 24h 冷却**。
      于是：她昨天回了我 → 计数清零（好）→ 但今天想再唤醒她时，
      仍被昨天那次唤醒的 24h 冷却挡住 —— 对**有回应**的人反而更慢，
      与用户「三次没回应才放弃」的意图相反（她回应了就该恢复正常节奏）。
      改后：她回过消息 ⇒ 计数清零 **且** 解除冷却，立刻恢复候选资格。
      （不解除 f<uid> 短保险丝，那是防坏页面的，与业务语义无关。）

    🔴🔴 2026-11-08 11:05（本函数上一版仍有致命漏洞，已修）：
      上一版由 `candidates()` 传入 `last_ts` = `MAX(localTime)`（含我自己的消息）。
      设备的 localTime 来自手机、ts 来自主机，两者常有秒级偏差；
      只要手机比主机快 >1 秒，「我刚发完的唤醒语」就会被判成「她回了」：
        · c<uid> 被自己清零 → **「三次放弃」永远攒不满**
        · str(uid) 被删 → 24h 冷却被解除 → 同一个人当天被反复唤醒
      实测窗口（审计 48h：`还不睡` 35 连发 0 回复）正与这条吻合：
      一个从不回话的人可以让计数在 1↔0 之间无限循环。
      现在判据改为「**她**最近一条消息的时间」，且由调用方显式提供。
    """
    ts = float(woke.get(str(uid)) or 0)
    if ts and float(her_ts_ms or 0) / 1000.0 > ts + 1:
        _changed = False
        if woke.pop("c" + str(uid), None) is not None:
            _changed = True
        if woke.pop(str(uid), None) is not None:
            _changed = True        # ← 解除 24h 冷却：她回应了，恢复正常节奏
        # 🔴 2026-11-08 11:10：连带清掉 f<uid> 短保险丝。
        #   改前只清 c 和 str(uid)，f<uid>（失败保险丝，默认 20 分钟）仍留着：
        #   她明明回话了，这个人还要再被挡最多 20 分钟才能重新进入候选。
        #   保险丝本意是「防坏页面被连续猛撞」，她一回话就说明页面是好的、
        #   人也找得到 —— 没有任何理由继续挡。不清它，(b) 的「她回一次就恢复」
        #   就只是半恢复（计数清了，但冷却还在）。
        if woke.pop("f" + str(uid), None) is not None:
            _changed = True
        if _changed:
            log.info("她回过话（她末条 %.0fs 晚于本次唤醒）uid=%s → 计数清零、解除冷却/保险丝",
                     float(her_ts_ms or 0) / 1000.0 - ts, uid)
        return _changed
    return False


def is_given_up(woke, uid):
    """连续无回应达到上限 → 放弃。"""
    return _no_reply_count(woke, uid) >= MAX_NO_REPLY


def already_woke(uid, hours=WOKE_COOLDOWN_H):
    return _cooling(_load_woke(), uid, hours=hours)


def mark_woke(uid, failed=False):
    """记一次唤醒。成功 = 按人冷却 24h；失败 = 短冷却（默认 20 分钟）。

    失败用 "f<uid>" 键单独存，成功时清掉，两者互不覆盖。
    """
    d = _load_woke()
    now = time.time()
    if failed:
        d["f" + str(uid)] = now
        log.info("唤醒失败台账 uid=%s（%.0f 分钟内不再试）", uid, WOKE_FAIL_COOL_S / 60.0)
    else:
        d[str(uid)] = now
        d.pop("f" + str(uid), None)
        # 连续无回应 +1（她回过会被 reset_if_replied 清零）
        try:
            d["c" + str(uid)] = int(d.get("c" + str(uid)) or 0) + 1
        except Exception:
            d["c" + str(uid)] = 1
    # 顺手清理 30 天前的，避免文件无限增长
    # ⚠ "c<uid>" 是计数不是时间戳，按时间过滤会把 c=3 当成 1970 年删掉；
    #   有计数的 uid 连它的唤醒时间也要留住，否则 reset_if_replied 拿不到基准。
    cutoff = now - 30 * 24 * 3600
    _cnt_uids = {k[1:] for k in d if k.startswith("c")}
    d = {k: v for k, v in d.items()
         if k.startswith("c") or str(k) in _cnt_uids or float(v or 0) > cutoff}
    _save_woke(d)


# 🔴🔴 2026-11-08 03:40（用户口径：「三次没有回应 **或者唤醒的时候找不到人** → 永久放弃」）
#
#   改前：只有「真的发出去了、她没回」才累加 c<uid>（见 mark_woke(failed=False)）；
#        「搜索无结果 / 进不去会话 / 身份校验失败」这些**找不到人**的情况
#        走的是 mark_woke(failed=True) —— 只记 20 分钟短冷却，**不计入放弃计数**。
#   后果：定位不到的人会被无限次重试，每次白烧 15~40s（这正是现网
#        「633 次翻屏未命中 + 598 次 notfound」的一部分来源），而且永远不放弃。
#
#   现在：把「找不到人」也算作一次**失败唤醒**，计入同一个放弃计数。
#     · 找不到人 = 搜索无结果 / 未进入会话 / 不在会话页 / 身份校验失败 / 没有可用关键词
#     · 三类失败都走 _bump_miss()：c<uid> +1 且记 20min 短冷却
#     · 连续满 MAX_NO_REPLY(3) 次 → is_given_up() 成立 → candidates() 永久跳过
#   注意：她只要**回过一次消息**，reset_if_replied() 就把计数清零，重新给机会
#        （这是「不永久拉黑活人」，与「放弃这个唤不醒的人」并不矛盾）。
def _bump_miss(uid, why=""):
    """记一次「唤醒没成」（含找不到人）。计入放弃计数，并落实「一天一次」。

    🔴 2026-11-08 03:45（用户：三次、一天一次、找不到人也算）：
      · 写 str(uid) = now  → 与成功唤醒同一把 24h 冷却锁 ⇒ 真「一天一次」
      · 写 c<uid> += 1     → 连续没成计数，满 3 次永久跳过
      · 写 f<uid> = now    → 轮内短保险丝（20min），防坏页面被连撞
    她只要回过一次 → reset_if_replied() 清零 c<uid>，重新给机会。
    """
    d = _load_woke()
    now = time.time()
    if WOKE_FAIL_COUNTS_AS_WAKE:
        d[str(uid)] = now          # ← 关键：占掉今天的名额
    d["f" + str(uid)] = now
    try:
        d["c" + str(uid)] = int(d.get("c" + str(uid)) or 0) + 1
    except Exception:
        d["c" + str(uid)] = 1
    _n = d["c" + str(uid)]
    cutoff = now - 30 * 24 * 3600
    _cnt_uids = {k[1:] for k in d if k.startswith("c")}
    d = {k: v for k, v in d.items()
         if k.startswith("c") or str(k) in _cnt_uids or float(v or 0) > cutoff}
    _save_woke(d)
    if _n >= MAX_NO_REPLY:
        log.warning("唤醒放弃 uid=%s（连续 %d 次没成：%s）→ 不再主动找他", uid, _n, why)
    else:
        log.info("唤醒没成 uid=%s（第 %d/%d 次：%s）→ 今天不再找他",
                 uid, _n, MAX_NO_REPLY, why)
    return _n


class Candidate(object):
    __slots__ = ("sid", "uid", "msgs", "last_ts", "last_text", "last_side", "kws")

    def __init__(self, sid, uid, msgs, last_ts, last_text, last_side, kws=None):
        self.sid = sid
        self.uid = uid
        self.msgs = msgs
        self.last_ts = last_ts
        self.last_text = last_text
        self.last_side = last_side
        # 搜索关键词候选（按命中概率排序，见 _kw_list）
        self.kws = list(kws or [])

    @property
    def cold_h(self):
        return (time.time() * 1000 - float(self.last_ts)) / 3600000.0

    def __repr__(self):
        return "<Cand uid=%s msgs=%d cold=%.1fh %r>" % (
            self.uid, self.msgs, self.cold_h, (self.last_text or "")[:16])


def candidates(db, min_msgs=MIN_MSGS, cold_hours=COLD_HOURS, limit=12,
               scan=800):
    """选出可唤醒的人：文本消息数 >= min_msgs、最后一条消息早于 cold_hours 前。

    额外要求：最后一条是**我发的**（否则对方在等我回，那属于「必回」不是「唤醒」）。

    🔴 2026-11-03：LIMIT 只是**扫描窗口**，不能当结果上限。
       原来写 LIMIT limit*4（=32）：按 last 倒序最近 32 个冷会话里，
       31 个已进 24h 台账、1 个最后一条是她 -> 永远返回空。
       现场该库有 136 个合格候选，daemon 却每 60s 报「没有候选」空转。
       现在扫 scan 条（默认 800，覆盖全库 797 个有文本的会话），
       台账一次性载入内存判定，不再每个候选读一遍 json。
    """
    # 跟进阶梯接线（§104-B1）：一次性取归档集合（try/except 兜底成空集）。
    #    发送额度统一由 sendgate 裁决：WOKE_COOLDOWN_H / MAX_NO_REPLY 只管
    #    「多久挑一次人」，能发几条/能不能发由 SG.allow 在真正发送前拍板；
    #    这里只按「已归档 / 超 72h 归档态」筛掉不该唤醒的候选。
    try:
        from brain import sendgate as SG
        from brain import verdict as V
        _arch = set(SG.archived_sids())          # SOUL_FOLLOWUP_ON=0 时返回空集
        _ARCHIVE_H = float(V.ARCHIVE_H)
    except Exception:
        _arch = set()
        _ARCHIVE_H = 72.0
        SG = V = None

    cutoff_ms = (time.time() - cold_hours * 3600) * 1000
    # 🔴 2026-11-03 修复 P2：原来 `MAX(localTime)` 只算文本消息（WHERE msgType=1），
    #    我最近发的是图片/语音/礼物时，文本时间戳已冷 → 误判「冷」而唤醒。
    #    改成：n 仍只计文本消息；last 取「非系统消息」的最大时间（含图片/语音），
    #    系统卡片（27/35）的 localTime 很新，会污染冷判据，必须排除。
    rows = db.con.execute(
        "SELECT sessionId, "
        "SUM(CASE WHEN msgType = 1 AND text IS NOT NULL AND text != '' THEN 1 ELSE 0 END) n, "
        "MAX(CASE WHEN msgType NOT IN (?, ?) THEN localTime END) last "
        "FROM chatmsg "
        "GROUP BY sessionId HAVING n >= ? AND last <= ? "
        "ORDER BY last DESC LIMIT ?",
        (int(SYS_TYPES[0]), int(SYS_TYPES[1]), min_msgs, cutoff_ms, scan)).fetchall()

    woke = _load_woke()
    now = time.time()
    out = []
    _woke_dirty = False
    for sid, n, last_ts in rows:
        s = db.session(sid)
        if s is None or s.is_official:
            continue
        # 唤醒之后她回过消息 -> 清零无回应计数（自动恢复候选资格）
        # ⚠️ 必须传「**她**的末条时间」，不能传 last_ts（那是会话最大时间，
        #    包含我自己刚发的唤醒语 —— 会把「我发的」误判成「她回的」，
        #    导致三次放弃永远攒不满、24h 冷却被自己解除。见 reset_if_replied 注释）。
        # 只有台账里真的有记录才需要判定：没记过账就没什么可清的，
        # 也避免对全库候选（scan 默认 800）逐个多读一次库。
        if woke.get(str(s.to_uid)) or woke.get("c" + str(s.to_uid)):
            if reset_if_replied(woke, s.to_uid, _her_last_ts(db, sid)):
                _woke_dirty = True
        # 连续 N 次唤不醒 -> 放弃（用户 2026-11-05 定）
        if is_given_up(woke, s.to_uid):
            continue
        if _cooling(woke, s.to_uid, now):
            continue            # 24h 内已唤醒过 / 20min 内失败过 -> 跳过
        # 🔴 2026-11-04：latest —— 入向不落 chatmsg 的账号只有 session 摘要能反映最新一句
        last, _src = db.latest(sid)
        if last is None:
            continue
        side = "me" if str(last.sender) == str(db.uid) else "her"
        if side != "me":
            continue            # 对方在等我 -> 交给必回，不唤醒
        # 跟进阶梯接线（§104-B1）：已归档 / 超 72h 归档态 → 不唤醒；
        #    不主动 set_archived（归档写入由 pendingq 负责），整段降级放行。
        _her_ts = 0
        try:
            if SG is not None and SG.ON:
                if str(sid) in _arch:
                    log.info("唤醒候选跳过 sid=%s（已归档，不唤醒）", sid)
                    continue
                _her_ts = _her_last_ts(db, sid)
                if _her_ts and (time.time() * 1000 - _her_ts) / 3600000.0 >= _ARCHIVE_H:
                    _v = SG.state_of(str(sid), her_ts_ms=_her_ts, has_human=True)
                    if getattr(_v, "state", "") == V.ARCHIVED:
                        log.info("唤醒候选跳过 sid=%s（age>=%gh 归档，不唤醒）", sid, _ARCHIVE_H)
                        continue
        except Exception:
            pass            # 拿不到 her_ts / 台账状态机异常 → 不拦（降级放行）
        # 🔴 2026-11-12（F-02）：跟进阶梯里 FOLLOWING/AWAITING（她正在等我回 /
        #    我在跟进她）→ 不唤醒。原来 candidates() 只滤 ARCHIVED，到 send_wake
        #    的 SG.allow 才拦，然后 _bump_miss 把「额度已满/等她回」错计成「唤不醒」
        #    → c<uid>+1 + 24h 冷却，3 次后对仍存活的真人永久放弃（实测
        #    「唤醒被跟进阶梯拦截 following/awaiting 65 次」）。同款 try/except
        #    降级放行：拿不到 state → 不拦。
        try:
            if SG is not None and SG.ON and _her_ts:
                _st = SG.state_of(str(sid), her_ts_ms=_her_ts, has_human=True)
                _stn = getattr(_st, "state", "")
                if _stn in (V.FOLLOWING, V.AWAITING):
                    log.info("唤醒候选跳过 sid=%s（state=%s，不唤醒）", sid, _stn)
                    continue
        except Exception:
            pass            # 台账状态机异常 → 不拦（降级放行）
        out.append(Candidate(sid, s.to_uid, n, last_ts, last.text, side,
                             kws=_kw_list(db, sid, db.uid)))
        if len(out) >= limit:
            break
    if _woke_dirty:
        _save_woke(woke)
    return out


def _kw_list(db, sid, uid, limit=2):
    """搜索关键词候选（按命中概率排序）。

    🔴 2026-11-09 P0 修复（现场实证）：旧实现取「最近 24 条里最长的一整句」，
       偏偏最容易挑中带全角逗号/问号的完整话术（「锅里的水还没开，你那边晋中咋样了」），
       或我方群发开场白模板 —— 两者在 Soul 搜索里实测必然 notfound。
       结果 15:00~15:32 连续 53 次「未找到相关结果」+ 56 次点「取消」退出，
       屏幕上就是用户看到的「瞎操作乱点」，而一条消息都没发出去。
       现统一复用 brain/pendingq.kw_of()（现网 5~8 字命中率 74.1% 的口径）：
       去首尾标点 / 压空格 / 去表情 / 5 字下限 / 非纯数字 / 群发模板过滤 /
       优先「她」的历史长句。txt 传空即强制走历史长句兜底。
    """
    try:
        from brain.pendingq import kw_of
    except Exception:
        return []
    try:
        k = (kw_of(db, sid, "", min_len=5) or "").strip()
    except Exception as e:
        return []
    return [k] if 5 <= len(k) <= 20 else []


def opening(db, cand, nick=""):
    """纯本地生成开场白。失败返回 ""。"""
    b = R.engine()
    if b is None or not hasattr(b, "opening_line"):
        log.warning("旧引擎不支持 opening_line")
        return ""
    msgs = db.messages(cand.sid, limit=8)
    hist = R.build_hist(msgs, db.uid, limit=8)
    t0 = time.time()
    try:
        t, _ms = b.opening_line(sid=cand.sid, nick=nick, hist=hist, kind="wake")
    except Exception as e:
        log.warning("opening_line 异常: %r", e)
        return ""
    t = (t or "").strip()
    log.info("开场白 %.1fs %r", time.time() - t0, t[:30])
    return t


def plan(db, n=MAX_PER_ROUND):
    """本轮唤醒计划：[(候选, 开场白)]，最多 n 个。"""
    out = []
    for c in candidates(db, limit=8):
        if len(out) >= n:
            break
        op = opening(db, c)
        if op:
            out.append((c, op))
    return out


# ---------------- 执行：搜索定位 -> 进会话 -> 发送 ----------------
def send_wake(actor, dev, cand, text, db=None):
    """按 last_text 搜索定位 -> 进会话 -> 发送。返回 (ok, 说明)。

    为什么用搜索而不是滚动列表（用户 2026-11-02 定的方案）：
    列表 1100+ 会话，滚动定位慢且容易跳过；搜索框能直接搜聊天记录，
    实测一次命中（前提：该账号没退出过，索引完整）。

    db 传入时做**身份校验**（搜索结果不保证是目标人）；不传则跳过（兼容旧调用）。
    """
    from brain import nav
    from brain import search as S
    from hands.input import Input

    # 🔴 2026-11-03 修复：唤醒/匹配两条链路原来完全不检查限流，
    #    只有 clear/pendingq 调 can_send()，小时上限对它们无效。
    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            return False, "本小时发送已达上限"
    except Exception:
        pass

    # 🔴 2026-11-03：关键词改为多候选（她原话 → 我原话），逐个试。
    #    原来只用 cand.last_text（= 我发的最后一句），1~2 字时直接放弃。
    kws = [k for k in (getattr(cand, "kws", []) or []) if len(k) >= 2]
    if not kws:
        t = (cand.last_text or "").strip()
        if 2 <= len(t) <= 18:
            kws = [t]
    if not kws:
        _bump_miss(cand.uid, "没有可用关键词")
        return False, "没有可用关键词（她和我最近的话都太短）"

    # 🔴 从搜索开始就把「我造成的库变化」封住：
    #    点进会话那一下 App 会标已读写库，等灌字前再 mark 已经晚了（dirty 已置位）
    #    → 唤醒循环立刻判「有新消息」中断，一句话都发不出去。
    try:
        from data import watch as _W
        _W.mark_self_write(40.0)
    except Exception:
        pass

    # 🔴 2026-11-02：原来这里自建了一套搜索（灌字后只 sleep 2.2 秒就判「无结果」），
    #   而接口实测要 11~14.7 秒才返回 ⇒ 唤醒侧搜索基本全废。
    #   现在只走 brain.search 一处实现，等待窗口与其他入口完全一致。
    if not S.open_search(actor):
        snap, pg = nav.to_chatlist(actor)          # 兜底：先回列表再找一次放大镜
        if pg != "chatlist" or not S.open_search(actor):
            _bump_miss(cand.uid, "打不开搜索页")
            return False, "打不开搜索页"
    hit_kw = ""
    for kw in kws[:2]:
        if S.search(actor, dev, kw):
            hit_kw = kw
            break
        log.warning("搜索 %r 无结果/超时（reason=%s）→ 换下一个关键词",
                    kw, getattr(S, "LAST_REASON", "?"))
        S.leave(actor)
        if not S.open_search(actor):
            log.warning("换关键词失败：打不开搜索页")
            break
    if not hit_kw:
        _bump_miss(cand.uid, "搜索无结果")
        return False, "搜索无结果（试了 %d 个关键词）" % min(len(kws), 2)
    log.info("搜索命中（关键词=%r），点第一条结果进会话", hit_kw)
    # 🔴🔴 2026-11-08 12:4x（P0 修「身份校验失败」94% 的假否决）
    #
    #   实测（search-diagnostician 全量取证，_team/search_diag.md §2.6）：
    #     · 104 次「进的是别的会话」里 **98 次来自 wake**，pendingq 侧只占 6 次
    #     · 同一「未读清零指纹」跨 **39 个不同目标人**重复出现 → 明显是陈旧快照
    #     · wake.py **从未调用过 mark_before_enter()**，所以
    #       `_sid_by_unread_clear()` 读到的 `_UNREAD_BEFORE["set"]` 是
    #       **pendingq 上一次留下的旧快照**，不是「进这个会话之前」的真实状态
    #       → 差分算出来的「清零集合」必然是错的 → 身份校验必然失败
    #       → 发不出去 → `_bump_miss` 记失败台账 → 这个人被冷却，永远回不了
    #
    #   pendingq 侧精确率 91%（59 通过 / 6 否决），判据本身没问题，
    #   缺的就是这一行「进会话前先拍未读快照」。补上即可，不改判据。
    if db is not None:
        try:
            from brain import pendingq as _PQ0
            _PQ0.mark_before_enter(actor)
        except Exception as _e:
            log.warning("wake: 进会话前记未读快照失败（身份校验会退回文本判据）: %r", _e)
    s2, pg2 = S.enter_first(actor)
    if pg2 != "chat":
        S.leave(actor)
        _bump_miss(cand.uid, "未进入会话(%s)" % pg2)
        return False, "未进入会话(%s)" % pg2

    # 二次确认真的在会话页（搜索页也有输入框，灌错地方就永远发不出去）
    from eyes.page import detect as _det
    if _det(actor.snap(force=True)) != "chat":
        log.warning("灌字前不在会话页 → 放弃（避免灌进搜索框）")
        S.leave(actor)
        _bump_miss(cand.uid, "不在会话页")
        return False, "不在会话页"

    # 🔴 2026-11-03 修复 P1（防串台）：搜索结果按关键词排序，第一条不保证是目标人。
    #    pendingq 已有同款校验，唤醒这条一直缺 —— 关键词撞车就会把唤醒语发给别人。
    #    fail-closed：确认不了就不发（记失败台账、20 分钟后重试），绝不发错人。
    if db is not None and os.environ.get("SOUL_WAKE_IDCHECK", "1") != "0":
        try:
            from brain import pendingq as _PQ
            if not _PQ._session_matches(actor, db, cand.sid):
                # 🔴 2026-11-12（HY-15）：`_session_matches` 失败先做**对话页标题昵称**
                #   二次确认。`_session_matches` 第一顺位是未读清零差分，进错人时给
                #   False，但**目标会话没有未读**时返回 None 走文本兜底，短消息在库里
                #   撞车也会返回 False → 误判串台 → 白烧+冷却。
                # 🔴 2026-11-12（F-03）：昵称一致只是**必要**条件，不能单独放行 ——
                #   同名/近名联系人标题一致即串台。昵称放行前叠加「库内 sid 与目标
                #   sid 一致」校验：读当前会话气泡，用 db.digest_matches 确认屏幕会话
                #   就是 cand.sid；确认不了 sid → 维持 fail-closed 不放行。
                _released = False
                try:
                    _nn = _PQ.nick_of(db, cand.sid, cand.uid)
                    if _nn:
                        _nm = _PQ._nick_matches(actor, _nn)
                        if _nm is True:
                            _bs = []
                            try:
                                from eyes import chat as _CH
                                _png = actor.dev.screencap()
                                _bs = [t for t, _sd, _it in _CH.bubbles(_png)
                                       if _sd in ("her", "me") and len(t) >= 2]
                            except Exception as _be:
                                log.debug("F-03 读当前会话气泡失败（不放行）: %r", _be)
                            _sid_ok = False
                            if _bs:
                                try:
                                    _sid_ok = bool(db.digest_matches(cand.sid, _bs, min_len=2))
                                except Exception as _de:
                                    log.debug("F-03 sid 校验异常（不放行）: %r", _de)
                            if _sid_ok:
                                log.info("唤醒身份校验失败但昵称一致且库内 sid 确认（%r）→ 放行 sid=%s",
                                         _nn, cand.sid)
                                _released = True
                            else:
                                log.warning("唤醒昵称一致但无法确认库内 sid=%s → 不放行", cand.sid)
                except Exception as _e:
                    log.debug("唤醒昵称二次确认异常（按失败处理）: %r", _e)
                if not _released:
                    log.warning("唤醒身份校验失败（搜索结果不是目标会话）→ 不发送 uid=%s", cand.uid)
                    actor.hand.back(settle=1.0)
                    S.leave(actor)
                    _bump_miss(cand.uid, "身份校验失败")
                    return False, "身份校验失败"
        except Exception as e:
            # 🔴 2026-11-13 修复 HY-02（P1 串台）：身份校验任何异常都必须 fail-closed。
            #   原来 `log.debug("...按通过处理")` 不中止发送 —— 搜索结果按关键词排序，
            #   第一条不保证是目标人（547-549 注释自认），校验异常一旦放开就可能把
            #   唤醒语发给错误的人。改：异常即 back + leave + 记失败台账，绝不放行。
            log.warning("唤醒身份校验异常（fail-closed，不发送）uid=%s: %r", cand.uid, e)
            try:
                actor.hand.back(settle=1.0)
            except Exception:
                pass
            try:
                S.leave(actor)
            except Exception:
                pass
            try:
                _bump_miss(cand.uid, "身份校验异常")
            except Exception:
                pass
            return False, "身份校验异常(fail-closed)"

    # 跟进阶梯接线（§104-B2）：真正灌字前过发送闸，发送额度统一由 sendgate 裁决。
    #    has_human=True：唤醒面向真人老友，不按系统卡口径降级；
    #    异常降级放行（台账/状态机出问题绝不掐断唤醒链路）。
    try:
        from brain import sendgate as SG
        if SG.ON:
            _d = SG.allow(cand.sid, 1, has_human=True)
            if not _d.ok:
                log.info("唤醒被跟进阶梯拦截 sid=%s state=%s（%s）",
                         cand.sid, _d.state, _d.reason)
                # 🔴 2026-11-12（HY-08）：原来这里只 back 就 return False，
                #   不 mark_woke(failed=True) → 24h 冷却没记 → 下一轮又选中又拦截
                #   → 反复白烧（实测唤醒阶梯拦截 following 65 次）。现在：
                #   ① 记失败台账（含 24h 冷却 + 放弃计数），今天不再找他；
                #   ② 确保回到会话列表（back 一次 + nav.to_chatlist 兜底），
                #      绝不停在会话页让下一轮从错误页面起手。
                # 闸之前已完成导航/进会话（见上方 S.search / _enter），
                # 先按成功路径同款 back 退一层；异常吞掉不改变返回值语义。
                try:
                    actor.hand.back(settle=1.2)
                except Exception:
                    pass
                try:
                    from brain import nav as _nav
                    _snap, _pg = _nav.to_chatlist(actor)
                    if _pg != "chatlist":
                        log.warning("跟进阶梯拦截后回列表失败（page=%s）→ 已尽力返回",
                                    _pg)
                except Exception as _e:
                    log.debug("跟进阶梯拦截后回列表异常（已尽力）: %r", _e)
                # 🔴 2026-11-12（F-02）：SG.allow 拦截 = 额度/跟进阶梯问题（follow/
                #   awaiting），**不是「找不到人」** → 不记 _bump_miss（否则 c<uid>+1
                #   + 24h 冷却，3 次后对仍存活的真人永久放弃）。只记日志 + back +
                #   to_chatlist（HY-08 已保留）。候选侧已在 candidates() 提前滤掉
                #   FOLLOWING/AWAITING，走到这里说明是轮内状态变化/边界情况，
                #   本轮不发送，但**不递增放弃计数**，下轮候选仍会回来。
                return False, "跟进阶梯拦截(%s)" % _d.state
    except Exception:
        pass

    inp = Input(dev)
    ok, got = inp.type_and_verify(text, actor)
    if not ok:
        inp.clear()
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "灌字失败")
        return False, "灌字失败(%r)" % (got,)
    if not inp.tap_send(actor, settle=1.6):
        inp.clear()
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "找不到发送按钮")
        return False, "找不到发送按钮"
    # 🔴 2026-11-12（F-01）：sent_ok 是三态（ok/unknown/residual，见 hands/input.py）。
    #   只有 residual（输入框还有字 = 明确没发）才算失败并记 _bump_miss；
    #   unknown（转场帧读不到输入框，大概率已发）按已发记账，避免「实际已发却
    #   被记失败」→ 次日重复唤醒/重复发消息。
    _ok = inp.sent_ok(actor, text, timeout=6)
    _why = getattr(inp, "last_reason", "") or ""
    if (not _ok) and _why == "residual":
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "发送后输入框未清空(残留)")
        return False, "发送后输入框未清空(残留)"
    # ok 或 unknown（大概率已发）→ 按已发记账

    # 🔴 自己发消息也会写库 → 不抑制的话，唤醒循环里「库有变化」立刻中断，
    #    每次唤醒只能发 1 个人就退出（实测日志：唤醒 OK 后马上「检测到新消息」）。
    try:
        from data import watch as _W
        _W.mark_self_write(6.0)
    except Exception:
        pass
    try:
        from brain import ratelimit as _RL
        _RL.note_sent()
    except Exception:
        pass

    actor.hand.back(settle=1.2)      # 会话内 back 是安全的
    mark_woke(cand.uid)
    # 跟进阶梯接线（§104-B2）：只有真正发送成功才按真实条数记账，
    #    发送额度统一由 sendgate 裁决；异常吞掉不记账，绝不改变原有返回值语义。
    try:
        from brain import sendgate as SG
        if SG.ON:
            SG.note_sent(cand.sid, 1)
    except Exception:
        pass
    log.info("已记唤醒台账 uid=%s（24h 内不再找他）", cand.uid)
    return True, "已发送"
