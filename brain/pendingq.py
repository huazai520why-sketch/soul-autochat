# -*- coding: utf-8 -*-
"""已读未回队列：有消息、但没红点的会话也要回。

用户 2026-11-02：「红点清完了之后 要确认一下已读未回的也要处理」
       「进入对话框了之后 如果最后一条消息是对方发来的 那么一定要做回复」

为什么单独一个模块：
  清红点（brain.clear）只能处理**列表里有红点**的会话。
  但「进去看过一眼就退出」会把红点清掉，消息却还没回 —— 这类会话语义上仍是待回，
  只是没有红点可点，必须靠 **搜索 lastMsgText** 定位（brain.search）。
"""
import json
import os
import re
import threading
import time

from brain import casepack as CP
from brain import reply as R
from brain import voice as V
from brain import search as S
from core.log import get_logger
from core.paths import STATE
from hands.input import Input

log = get_logger("brain.pendingq")

MAX_N = 5
# 「新消息」窗口：这么久以内她发来的，和新积压**交错**出队（见 candidates 末尾）。
#   用户 2026-11-03：「有红点就一定有新消息进来」—— 新消息不能被几十个积压挤住。
FRESH_H = float(os.environ.get("SOUL_FRESH_H", "6") or 6)
# 一次扫描取多少个候选（用于判断积压规模 + 排序）。
#   🔴 2026-11-03：原来写死 12 → backlog 永远显示 12，而实际积压 54 个，
#     降级阈值/吞吐全按错的数算，队列末尾的老会话永远进不了视野。
CAND_SCAN = int(os.environ.get("SOUL_CAND_SCAN", "60") or 60)
# 🔴 2026-11-04（P0 处理环节）：find_row 首屏之外最多再往下翻几屏。
#   实测首屏只有 8~10 行，候选 60 个 → 首屏命中率仅 **14%**，86% 被迫走搜索
#   （11~15s/次、且 Soul 不索引几天前的消息 → 常 notfound）。翻 3 屏把命中率抬上来。
FIND_PAGES = int(os.environ.get("SOUL_FIND_PAGES", "3") or 3)
SKIP_UID_PREFIX = ("2042683",)     # 官方营销号段（实测 2042683xx 全是积分/礼物推送）
LOOKBACK_DAYS = 7
SCAN_SESSIONS = 300
# 🔴 2026-11-08 03:30（P0 死锁修复，**阈值按实测数据修正：72h → 24h**）
#
#   超过这个小时数没活跃的会话，不再浪费「翻 3 屏 + 搜索」去定位。
#
#   【72h 是错的，实测拐点在 12h】backlog-profiler 全量配对 2383 个样本
#   （brain.pendingq.log 11-02→11-08）得出：
#     列表命中率： 0–3h 43.9% → 3–6h 3.0% → **12–18h 0.0%** → 24h 后 ≈0
#     回成功率：   0–3h 55.8% → 6–12h 7.7% → **60–72h 精确 0.0%（155/155 全败）**
#
#   队列/产出对照（当前实盘 63 人）：
#     age<24h  → 队列 11，预期回出 ~6 条/轮   ← 最优
#     age<36h  → 队列 17，~6.5
#     age<72h（原设定）→ 队列 33，~6.7        ← 多 22 个白烧，只多赚 0.7 条，耗时×3
#     全量 63  → 预期仅 3.1 条
#
#   所以取 24h（相比 18h 的真实拐点留 6h 安全边际）。
#   注意：**不是不回了** —— 她们仍在库里，等哪天再发新消息（ts 变新）自然回到队列。
#
# 🔴🔴 2026-11-08 12:4x：24h 仍太松，降到 12h（P0-1，_team/search_diag.md §2.1）。
#   实测按年龄分段的回出率：0-1h 49.2% / 3-6h 0.0% / 6-12h 10.7% / 12-24h 0.0% / 24h+ ~0%。
#   12-24h 段回出率 0.0%，却占了候选的相当比例，翻屏 21.2s/次全部白烧。
#   降闸后 44h 窗口预计省 ~229 分钟定位时间，把预算让给 0-1h 的新鲜候选。
#
# 🔴🔴🔴 2026-11-08 12:46（**自我拷问后回退，上面这条改动是错的**）
#
#   我改完 12h 后立刻实测，结果是灾难：
#     · candidates(40) 从 12 个掉到 **1 个**
#     · 日志连续出现「过期淘汰 11 个 → 队列剩 1 个」「队列剩 0 个」
#     · 红点闸被迫「放行匹配（candidates 为空）」，已读未回彻底空转
#
#   为什么错：那个「12-24h 回出率 0.0%」是**历史统计**，而这段历史里
#   `open_search()` 一直是坏的（搜索框文案是「搜索备注、昵称或者聊天记录」，
#   旧代码只认「搜索」两个字 → 必然失败）。**回出率 0% 是搜索坏掉的结果，
#   不是「老会话不值得回」的证据**。拿一个有 bug 时期的统计去定阈值，
#   等于把 bug 当成了证据 —— 这是典型的「用相关性冒充因果」。
#
#   而且方向上更糟：我刚把搜索修好，老会话现在**有可能**回得出去了，
#   此时收紧闸门正好把刚修好的能力关掉。
#
#   ⇒ 回到 24h。真要收紧，必须等搜索修复后的**新**数据（至少跑满一天）再定，
#     而且应该用「搜索成功率」而不是「回出率」作依据。
# 🔴 2026-11-10 §104（用户定稿）：与 RESTART_H **必须对调**，单改任一条都留坑。
#   原 24h 淘汰会把 24~72h 的待回全部踢出，导致「>24h 重新开场」永远触发不了；
#   改成 72h 后，24~72h 的人交给重新开场/跟进阶梯，>72h 才由状态机归档。
STALE_GIVEUP_H = float(os.environ.get("SOUL_STALE_GIVEUP_H", "72") or 72)

# 🔴 2026-11-03（用户定 **B 方案**）：她上一条已超过 RESTART_H 小时 → 不再「接话」，
#   改「重新开场」（换由头、不提旧话题、不道歉）。
#   实盘（16:30 副机两个库）：>72h 待回 29 个，最老 570h ≈ 23.8 天；
#   其中 11 个她只回了「嗯 / 你好 / 哈哈 / [呆] / [狗子]」——
#   隔二十天去答一个「嗯」既没内容，也一定露馅（她早忘了自己说过）。
#   0 = 关闭（全部按正常接话）。
# 🔴 2026-11-10 §104：72 → 24（用户「超过 24h 的积压重新开场」）。
#   判据不再只看 age：handle_pending 改用 verdict 状态机（age>=24h 且本回合 0 条）。
RESTART_H = float(os.environ.get("SOUL_RESTART_H", "24") or 24)
# 每轮最多处理几个「重新开场」：29 个一次性发出去像群发，
#   而且老会话会占掉本轮的发送名额。原来 1 个/轮，配 2 条/轮的额度，
#   17 个 >72h 的会话要 17 轮（约 1 小时）才轮到一遍 —— 现在 2 个/轮。
RESTART_PER_ROUND = int(os.environ.get("SOUL_RESTART_PER_ROUND", "2") or 2)
# 系统类会话文本（不是真人说的话，回了等于对机器说话）
SYS_TEXTS = ("[互动消息]", "[互动提醒]", "[系统消息]", "[官方消息]")

# 🔴 失败台账（用户 2026-11-02：「都出现未找到相关结果了 为什么还有无限次的重试」）
#   搜不到的会话如果每轮都重试，每次白烧 11s（搜索接口本身要 11s 才返回"未找到"）。
#   规则：同一 sid + 同一句末条，失败后冷却 SKIP_HOURS 小时；
#         她一发新消息（末条文本变了）就自动重新试 —— 别把活人永久拉黑。
SKIP_HOURS = 3

# 🔴 2026-11-09 R3（用户拍板：「搜索不到就不搜了啊 等闲下来的时候搜」）
#   旧实现 notfound 一次罚 3 小时 ⇒ 直接表现成「消息进来很久没人回」
#   （实测 21:08 仍有会话「原因=notfound，剩 89 分钟」，等于把她冻到下一场对话）。
#   新口径：本轮搜不到 = 本轮不搜，5 分钟后（≈ 闲下来时）自然重试，不冻结。
#   防白烧：同 sid 30 分钟内 notfound ≥3 次 → 升级 30 分钟，避免反复撞墙。
#   全部可用环境变量回调；设 SOUL_NOTFOUND_COOL_MIN=180 即回到旧行为。
NOTFOUND_COOL_H = float(os.environ.get("SOUL_NOTFOUND_COOL_MIN", "5") or 5) / 60.0
NOTFOUND_STORM_N = int(os.environ.get("SOUL_NOTFOUND_STORM_N", "3") or 3)
NOTFOUND_STORM_H = float(os.environ.get("SOUL_NOTFOUND_STORM_MIN", "30") or 30) / 60.0
# R5：她最后一条超过这么多分钟没接上 → 标红（只记日志，不插手操作）
SLA_WARN_MIN = float(os.environ.get("SOUL_SLA_WARN_MIN", "5") or 5)
# 🔴 2026-11-04（P1）：12h → 3h。原来的 12h 是在「只能靠搜索定位」的前提下定的，
#   而现在 find_row 会翻 3 屏，很多 notfound 的会话下一轮就能在列表里点进去；
#   12h 冷却反而让它们白等半天（实测生效 29 条、中位剩 11.1h）。
#   冷却仍按 (sid + 末条文本) 比对 —— 她一说新话就自动失效，不会误伤。
# 🔴 超时（接口慢/设备卡）**不是**搜不到：只罚 10 分钟就重试。
#   2026-11-02 现网事故：搜索 15s 窗口太紧 → 超时被当成 notfound → 同一人冷却 12 小时没人回。
TIMEOUT_RETRY_H = 0.17
# 🔴 2026-11-10：搜不到任何可靠线索（昵称、独一无二内容都没有）时的冷却。
#   用户口径「还是不行就放弃或者跳过」——但台账 key 含她末条文本，
#   她一发新消息就会自动重新给机会，所以这里只挡「同一句反复撞墙」。
NO_CUE_H = float(os.environ.get("SOUL_NOCUE_COOL_MIN", "30") or 30) / 60.0
ENTER_RETRY_H = 0.5
# 🔴 2026-11-04（A批提速）：短消息/纯表情 find_row 落空后不搜索，短冷却（30分钟）
#   她再发新消息（新红点）下一轮 find_row 就能命中，不会永久失联。
SHORT_RETRY_H = 0.5
# 🔴 2026-11-04（必回闭环）：身份校验连续失败要**熔断**。
#   实测「那不知道」「[狗子]」两会话各失败 8 次：搜索出 2~3 条结果但永远点第一条
#   → 进错会话 → 校验失败 → 2 分钟后重试还是第一条 → 无限空转（每轮白烧 15~20s，
#   而且这些人**永远回不了**）。现在按失败次数依次点第 2、3 条结果，
#   全部试过（IDFAIL_MAX_TRIES）就长冷却 IDFAIL_GIVEUP_H 小时，等她发新消息再试
#   （末条文本变了 → should_skip 自动失效 → 重新给机会）。
IDFAIL_MAX_TRIES = 4
IDFAIL_GIVEUP_H = 2.0
SKIP_FILE = STATE / "pending_skip.json"

# 🔴 2026-11-08（P0「瞎操作」根因修复 · 设备级故障熔断）：
#   改前：主循环里 `if pg != "chatlist": break` —— 回不到列表就**作废整轮**。
#   日志实证（daemon.out 11-08 00:19–00:30）：连续 14 个候选、回 0 条、
#   整轮 533.8s 全废，`已读未回 425s 一条都没回成 → 收工（异常）`。
#   同段 brain.nav.log 23 条全部是 `[nav] unknown 第 1 次 → back` —— nav 的恢复
#   阶梯从没爬上去（全量 `unknown 第 1/2/3 次` = 123/1/1、`强制回首页`=1、`重启 App`=0）。
#
#   为什么不是「逐个排队 + 2min 冷却」（我上一版提案，已被否决）：
#     `not_chatlist` 是**人无关**的故障 —— 同一次设备故障会让所有候选等概率失败。
#     给单个 sid 记冷却 = 假设「这个人有问题」，前提就是错的；冷却到期后设备若仍未恢复，
#     这 14 个人会**再排队撞一次墙**（14×20s=280s 全废，还白记 14 条冷却）。
#   现在：失败先 continue（只跳过这个人），**连续 3 次**才判设备级故障、整轮收工，
#     立刻交给 watchdog / 下一轮，设备恢复后一次全好。成功回一次立刻清零。
#   连续 3 次才判是为了排除单次偶发（实测 dump p50=1.50s / max=4.73s，单次转场很常见）。
_NOT_CHATLIST_STREAK = [0]
NOT_CHATLIST_MAX = 3

# 🔴 2026-11-08（用户：「一定要正常识别对方语音内容然后再回复」）：
#   本轮候选里**哪些 sid 的末条是语音**。
#   用途：语音转写出来的文字只在我们内存里，Soul 列表预览显示的是「[语音]」，
#   拿转写文字去搜索必然「未找到相关结果」，白等 11~30s。
#   所以这些 sid 走 kw_of(..., skip_text=True)，直接用她之前的历史长句当关键词。
#   每轮开头清空（只服务本轮），不落盘。
_VOICE_SIDS = set()

# 🔴 2026-11-03（P0 重复发送，实测：uid=*** 在 09:31~09:35 被连回 5 次）
#   根因：候选只看库里「末条是她」—— 而库是 pull 缓存，我发出去的话要等下一次
#   pull 才会出现。于是一段时间窗里每轮都判定「还没回」，重复灌字。
#   ⇒ 本地记一份「刚回过谁」的台账（落盘，重启不丢），REPLIED_GAP 秒内不再碰。
REPLIED_GAP = 300
REPLIED_FILE = STATE / "replied.json"
_REPLIED = {}
# 身份校验失败计数（**落盘**，重启不清零）：{"sid|末条前40字": {"n": n, "t": ts}}。
# 🔴 2026-11-03 实测教训：原来是内存 dict，而当天为部署改了十几次代码、重启十几次，
#    每次清零 -> 计数永远停在「第 1 次」-> 「第 2 次降级发安全句」的分支一次都走不到，
#    uid=*** 的「算」卡了 10 小时以上（15:41 / 15:49 两次 id_mismatch 都算第 1 次）。
IDFAIL_FILE = STATE / "idfail.json"
_IDFAIL = {}


def _load_replied():
    """读台账 {sid: {"text": 我回的那一句, "ts": 回复时刻}}；兼容旧的 {uid: ts}。"""
    try:
        d = json.loads(REPLIED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    now = time.time()
    out = {}
    for k, v in (d or {}).items():
        try:
            if isinstance(v, dict):
                ts = float(v.get("ts") or 0)
                if ts and now - ts < 7 * 86400:
                    out[str(k)] = {"text": str(v.get("text") or ""), "ts": ts}
            else:
                ts = float(v)
                if now - ts < REPLIED_GAP * 4:
                    out[str(k)] = {"text": "", "ts": ts}
        except Exception:
            continue
    return out


def _mark_replied(uid, sid=None, text=None):
    """记「**这一句**我已经回过了」（不是「这个人最近回过」）。

    🔴 2026-11-04（P0 重复骚扰，实测 uid=*** 08:40:45 / 08:47:28 被回两次）：
      旧台账是 {uid: ts} + REPLIED_GAP=300s 时间窗 —— 她没再说新话时，5 分钟后
      「末条是她」又重新成立，于是同一个人被反复开场，在真人眼里就是个机器人。
      现在记 {sid: {"text": 我回的哪一句, "ts": 时刻}}：
        · 末条还是同一句 → 不论过多久都不再回（这句已经回过）
        · 她发了新话（text 变）或新话时间晚于我回复时刻 → 立刻放行
    """
    key = str(sid) if sid else str(uid)
    try:
        _REPLIED[key] = {"text": (text or "")[:120], "ts": time.time()}
        REPLIED_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPLIED_FILE.write_text(json.dumps(_REPLIED, ensure_ascii=False),
                                encoding="utf-8")
    except Exception:
        pass


def _recently_replied(uid, sid=None, text=None, her_ts_ms=0):
    """这句是不是已经回过了。见 _mark_replied 的说明。"""
    now = time.time()
    rec = None
    if sid:
        rec = _REPLIED.get(str(sid))
    if rec is None:
        rec = _REPLIED.get(str(uid))
    if not isinstance(rec, dict):
        return False
    try:
        ts = float(rec.get("ts") or 0)
    except Exception:
        return False
    if not ts:
        return False
    # 她这条消息发生在我回复**之后** → 是新话（哪怕内容一模一样），必须回
    try:
        if her_ts_ms and float(her_ts_ms) / 1000.0 > ts + 1.0:
            return False
    except Exception:
        pass
    old = (rec.get("text") or "").strip()
    cur = (text or "").strip()
    if not old or not cur:
        # 旧格式台账（只有时间）/ 取不到她原话 → 退回时间窗语义，别当成「永远回过」。
        # 🔴 2026-11-04：窗口从 5 分钟放宽到 30 分钟 —— 实测 08:40:45 回过一次，
        #    08:47:28 又回了一次（第 7 分钟），在真人眼里就是机器人复读。
        return (now - ts) < max(REPLIED_GAP, 1800)
    # 🔴 2026-11-04 修（副机实测发现的错）：原来
    #      return old == cur or (now - ts) < REPLIED_GAP
    #    时间窗把「她换了新话」也判成已回 —— 验证脚本里同一句/新话都返回 True。
    #    新话被吞掉比重复更糟（违背必回）。现在只认「她这一句我已经回过」：
    #    文本不同 = 新话，必须回。
    return old == cur


# ══════════════ 身份校验失败计数（落盘，重启不清零） ══════════════
def _idfail_key(sid, txt):
    return "%s|%s" % (sid, (txt or "")[:40])


def _load_idfail():
    """读失败计数；只保留 24h 内的（过期自动忘，别把活人永久降级）。"""
    try:
        d = json.loads(IDFAIL_FILE.read_text(encoding="utf-8"))
        now = time.time()
        out = {}
        for k, v in d.items():
            try:
                item = v if isinstance(v, dict) else {"n": int(v), "t": now}
                t = float(item.get("t", now))
                if now - t < 86400:
                    out[str(k)] = {"n": int(item.get("n", 0)), "t": t}
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_idfail():
    try:
        IDFAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
        IDFAIL_FILE.write_text(json.dumps(_IDFAIL, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.debug("存 idfail 失败: %r", e)


def _idfail_bump(sid, txt):
    """失败次数 +1（落盘），返回本次是第几次。"""
    k = _idfail_key(sid, txt)
    n = int((_IDFAIL.get(k) or {}).get("n", 0)) + 1
    _IDFAIL[k] = {"n": n, "t": time.time()}
    _save_idfail()
    return n


def _idfail_clear(sid, txt):
    if _IDFAIL.pop(_idfail_key(sid, txt), None) is not None:
        _save_idfail()


_IDFAIL = _load_idfail()



def _l2_last_is_me(sid, her_ts_ms=None):
    """L2 最后一行是不是「我」说的，且时间不早于她最新一条消息。

    2026-11-03 为什么加这道判据：库是 pull 缓存（REFRESH_S=300），
    我发出去的消息要等下一次 pull 才出现 —— 实测 09:30 发完、09:31 库里还看不到，
    于是 pendingq 连回 5 条。而 L2 是**发送成功后立刻写**的，比库实时。

    🔴 2026-11-03 修复 P1：原来只看 L2 末行是不是「我:」，不比对时间 ——
    flow 曾回过她（L2 末行=我），她后来又新发消息且已读，db 末条已是她，
    这里仍判「已回」→ 永久漏回。现在：L2 末行是我 且 该行时间 >= 她最新消息时间
    才算已回；否则（她又有新话）判未回。
    her_ts_ms = 她最新消息的 localTime（毫秒）；None 时退回只看末行角色。
    """
    try:
        from brain.pack import store as _PK
        t = _PK.read_turns(sid) or ""
        last_ln = None
        for ln in reversed(t.splitlines()):
            ln = ln.strip()
            if ln.startswith("- "):
                last_ln = ln
                break
        if not last_ln:
            return False
        if " 我: " not in last_ln:
            return False          # 末行是她 → 未回
        if her_ts_ms:
            # 她的最新消息时间 vs L2 末行时间：她更新 → 她又有新话 → 未回
            try:
                her_stamp = time.strftime("%m-%d %H:%M", time.localtime(her_ts_ms / 1000.0))
            except Exception:
                her_stamp = ""
            m = re.match(r"^- (\d{2}-\d{2} \d{2}:\d{2}) ", last_ln)
            if m and her_stamp and her_stamp > m.group(1):
                return False
        return True
    except Exception:
        pass
    return False


# 🔴 2026-11-04（用户口径）：进会话后核对身份，最硬的证据是 **sid**。
#   App 进会话会把该 session 的 unReadCount 置 0 ⇒ 「进之前 / 进之后」各查一次
#   未读集合，差集就是刚进去的会话。这里存「进之前」的快照（None = 没拿到证据）。
_UNREAD_BEFORE = {"set": None}

# 设备存活校验的缓存（见 _device_live_uids）
_LIVE_CACHE = {"v": None, "ts": 0.0}
_LIVE_TTL_S = float(os.environ.get("SOUL_LIVE_TTL_S", "120") or 120)
_DEV_REF = {"dev": None}
_UNREAD_CACHE = {"ts": 0.0, "sids": set()}


def _device_unread_sids(db):
    """设备库 unReadCount>0 的 sid 集合（60s TTL 缓存）。

    🔴 2026-11-09 P0：msg_probe 直查设备库看到 10 条积压未读，
       但 candidates() 只看本地镜像 + replied.json + turns.md(L2) + pending_skip.json，
       四套本地状态都会滞后，把真红点判成「已回/冷却中」→ 连续 29 轮零回复。
       设备库未读是「她发了且从未进会话读过」的强真值，用它兜底放行。
       一轮内 candidates() 会被调 6+ 次，故加 60s 缓存避免重复 adb。
    """
    now = time.time()
    if now - _UNREAD_CACHE["ts"] < 60.0:
        return _UNREAD_CACHE["sids"]
    out = set()
    try:
        from data import imdb as _IM
        dev = getattr(db, "dev", None) or _DEV_REF.get("dev")
        if dev is not None:
            m = _IM.device_unread_map(dev, timeout=6, uid=getattr(db, "uid", None))
            if m:
                out = {str(k) for k, v in m.items() if v}
    except Exception as e:
        log.debug("设备未读集合取不到（降级为不硬放行）: %r", e)
    _UNREAD_CACHE.update(ts=now, sids=out)
    return out


def invalidate_live_cache():
    """🔴 2026-11-09 P0：库变化时清掉「设备存活 uid」缓存。

    和 invalidate_unread_cache 同理：`_device_live_uids` 有 120s TTL，
    库刚同步进新会话时，缓存里可能还没有这个人 → 被当成「App 里已不存在」
    移出候选（实测一次移出 180 个）。新消息到达时清掉，逼它重新扫设备库。
    """
    _LIVE_CACHE.update(v=None, ts=0.0)
    log.info("设备存活缓存已清除（库变化信号触发）")


def invalidate_unread_cache():
    """🔴 2026-11-09 P0 修复：库变化时清掉设备未读缓存。

    故障链路（18:42 新消息未处理）：
      18:42:20 cycle() 检测到 DBW.urgent() → open_account(force=True) 同步最新库
      → 但 _device_unread_sids() 的 60s TTL 缓存还停留在 60s 前的快照
      → 新消息 sid 不在缓存集合里 → 设备未读「硬放行」失效
      → 新消息被 _recently_replied / _l2_last_is_me / should_skip 掐掉
      → candidates() 返回空 → cycle() 一路走到空闲，新消息永久搁置

    修法：daemon.cycle() 在 _dirty=True 时调本函数清缓存，
    让紧接着的 candidates() 重新查设备库拿到最新的未读集合。
    """
    _UNREAD_CACHE.update(ts=0.0, sids=set())
    log.info("设备未读缓存已清除（库变化信号触发）")


# 🔴 2026-11-09：一轮 cycle 里「设备存活校验」会被多个子流程各调一次，
#    uids 已有 120s 缓存、不会重复扫设备，但旧的 INFO 每次都打 →
#    实测同一秒刷 3~4 行「205 个…剩 95 个」把真日志淹了。
#    相同结论在 TTL 内只 INFO 一次，其余降 DEBUG（要查随时能开）。
_LIVE_LOG = {"sig": None, "ts": 0.0}


def _device_live_uids(db):
    """当前账号设备库里还存在的 toUserId 集合。取不到返回 None（调用方降级不过滤）。

    见 `data/imdb.device_live_uids` 的注释（P0：本地镜像里的「死人」）。
    这里只做一层缓存 + 异常兜底，真正的查询和账号隔离在那里实现。
    """
    now = time.time()
    cache = _LIVE_CACHE.get("v")
    if cache and (now - _LIVE_CACHE.get("ts", 0)) < _LIVE_TTL_S:
        return cache
    dev = getattr(db, "dev", None) or _DEV_REF.get("dev")
    if dev is None:
        log.debug("_device_live_uids: 没有 device 引用，跳过存活校验")
        return None
    from data import imdb as _IM
    uids = _IM.device_live_uids(dev, db.uid)
    if uids:
        _LIVE_CACHE["v"] = uids
        _LIVE_CACHE["ts"] = now
    return uids


def mark_before_enter(actor):
    """点击会话行/搜索结果**之前**调一次，记下未读集合快照。"""
    try:
        from data import imdb as _IM
        _UNREAD_BEFORE["set"] = _IM.device_unread_map(actor.dev)
    except Exception:
        _UNREAD_BEFORE["set"] = None


def _sid_by_unread_clear(actor, sid, tries=3, wait=0.7):
    """未读清零差分判身份：True/False=None（无证据，交给文本校验）。"""
    before = _UNREAD_BEFORE.get("set")
    if not before:
        return None
    try:
        from data import imdb as _IM
    except Exception:
        return None
    cleared = set()
    for i in range(max(1, tries)):
        try:
            after = _IM.device_unread_map(actor.dev)
        except Exception:
            return None
        if after is None:
            return None
        cleared = set(before) - set(after)
        if cleared:
            break
        time.sleep(wait)          # 落库有几十毫秒延迟，等一小会再看
    if not cleared:
        return None               # 她这条本来就没有未读（已读未回）→ 无证据
    # 🔴 2026-11-08（P0 修「身份校验失败 261 次」里的假否决）：
    #   实测 daemon.out 全量 57 次 `身份校验失败（进的是别的会话：清零 [...]，期望 SID）`，
    #   其中 **48 次（84%）的「清零集合」是同一个复用指纹**，跨 38 分钟覆盖 23 个不同目标人：
    #     11-07 00:09:01 ... 清零 ['96691646131306455','96691646215313007','96691646187185972'] → 期望 9669164692166884
    #     11-07 00:47:30 ... 同一个集合                                                      → 期望 96691646451226869
    #   一个集合在 23 个不同目标人上重复出现，**不可能是这 23 次都进了同一个别人的会话**。
    #   真因：_UNREAD_BEFORE 是模块级可变全局（见本文件 _UNREAD_BEFORE 定义），
    #   而 actor.snap() 一次 1.5~4.7s，这个窗口里上一轮的进会话动作已把快照改掉 ——
    #   算出来的 cleared 和本次点击无关，属于**快照污染**，不是「进错人」。
    #   处理：一次清零 >3 个会话明显不像「进了一个会话」→ 当作无证据（返回 None），
    #   交给后面的昵称 / session 摘要 / 气泡反查继续校验，不要在这一层直接 fail-closed 误杀。
    if len(cleared) > 3:
        log.info("未读差分不可信（一次清零 %d 个会话，疑似快照被上一轮污染）→ 交文本校验",
                 len(cleared))
        return None
    if str(sid) in cleared:
        log.info("身份校验通过（未读清零差分 = 精确 sid %s）", sid)
        return True
    log.warning("身份校验失败（进的是别的会话：清零 %r，期望 %s）", list(cleared)[:3], sid)
    return False


def _norm_nick(s):
    """昵称归一化：去空白/…/标点，便于前缀比对（标题常被截断成「燕天…」）。"""
    import re as _re
    t = (s or "").strip()
    t = _re.sub(r"[\s\u3000…\.,，。!！?？~～\-—_]+$", "", t)
    return t


def _nick_matches(actor, nick):
    """对话页标题昵称是否与列表行昵称一致。True / None（无证据）。"""
    nk = _norm_nick(nick)
    if not nk:
        return None
    try:
        from eyes import chat as _C
        snap = actor.snap(force=True)
        title = _C.title_of(snap)
    except Exception as e:
        log.debug("读对话页标题失败: %r", e)
        return None
    t = _norm_nick(title)
    if not t:
        return None
    # 标题可能被截断（「燕天…」）→ 双向前缀比对
    if t == nk or (len(t) >= 2 and nk.startswith(t)) or (len(nk) >= 2 and t.startswith(nk)):
        log.info("身份校验通过（对话页昵称一致：%r）", title)
        return True
    return None          # 不一致不做否决：昵称可能被备注改写，否决会变成漏回


def _session_matches(actor, db, sid, nick=None):
    """进入 chat 后校验当前会话是否真的是候选 sid。

    🔴 2026-11-03 修复 P1（防错发/串台）：列表 `find_row` 按文本片段命中首行、
    搜索 `enter_first` 只点第一条结果，都不校验结果所属 sid/uid —— 可能进错会话，
    把甲的历史出话发给乙，还误记甲已回。这里读当前会话的「对方气泡」文本，
    反查库确认会话身份：
      命中数最高的会话 == 候选 sid 且明显唯一 → 一致（True）；
      读不到气泡 / 反查不到 / 不唯一 / 不一致 → 无法确认（False）。
    fail-closed：发错人 = 高危不可逆，宁可不发（记台账短冷却下轮重试），不可发错。
    """
    # 🔴 2026-11-04：第一顺位 = 未读清零差分（精确 sid，不依赖文本）。
    #   进错人时它会直接给出 False；她这条本来就没未读时返回 None 走文本兜底。
    _u = _sid_by_unread_clear(actor, sid)
    if _u is not None:
        return _u
    # 第二顺位：对话页标题昵称（她这条本来就没未读时的强证据）
    if nick:
        _n = _nick_matches(actor, nick)
        if _n is not None:
            return _n
    from eyes import chat as C
    try:
        png = actor.dev.screencap()
        bs = C.bubbles(png)
    except Exception:
        return False
    # 🔴 2026-11-03：不只取「她」的气泡 —— 短消息（"算"/"没有啊"）在库里撞车，
    #    只靠她那句反查必然不唯一。把「我」的气泡也算进来，命中数更有区分度。
    texts = [t for t, side, it in bs if side in ("her", "me") and len(t) >= 2]
    if not texts:
        return False
    # 🔴 2026-11-04（必回闭环）：先用「session 摘要」这条强证据直接放行。
    #    摘要 = 列表预览 = 屏幕上最后一句话，和站进来看的必然是同一个会话；
    #    而原来的 chatmsg 反查在「入向不落库」的账号上必然失败 → fail-closed
    #    永远不发（实测「[狗子]」「那不知道」各失败 10 次、最终长冷却 2h）。
    try:
        if db.digest_matches(sid, texts, min_len=2):
            log.info("身份校验通过（session 摘要一致）sid=%s", sid)
            return True
    except Exception as e:
        log.debug("摘要校验异常: %r", e)
    try:
        hits = db.sessions_for_texts(texts, min_len=2)
    except Exception:
        return False
    if not hits:
        return False
    top_sid, top_n = hits[0]
    if str(top_sid) != str(sid):
        return False
    if len(hits) > 1 and hits[1][1] >= top_n:
        return False          # 命中数并列 → 不唯一
    return True


_REPLIED.update(_load_replied())



def _load_skip():
    import json
    try:
        return json.loads(SKIP_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save_skip(d):
    import json
    try:
        SKIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        SKIP_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        log.warning("保存失败台账异常: %r", e)


_LAST_SKIP = {}


def should_skip(sid, txt, hours=SKIP_HOURS):
    """这个会话的这句话是不是刚失败过（冷却中）。"""
    rec = _load_skip().get(str(sid)) or {}
    if not rec:
        return False
    if (rec.get("text") or "").strip() != (txt or "").strip():
        return False                  # 末条变了 = 她说了新话，重新试
    age = time.time() - float(rec.get("ts") or 0)
    h = float(rec.get("hours") or hours)      # 台账里记的冷却时长优先（超时只罚 10 分钟）
    if age < h * 3600:
        # 🔴 2026-11-04：把命中的台账挂出来，调用方日志要打**真实原因**。
        #   原来日志写死「上次搜索失败」，实际 reason 有 short_msg/id_mismatch/timeout/
        #   notfound 四种，排查时全被误导成"搜索失败"（实测）。
        _LAST_SKIP[str(sid)] = rec
        return True
    return False


def mark_skip(sid, txt, reason="notfound", hours=None):
    h = SKIP_HOURS if hours is None else hours
    d = _load_skip()
    now = time.time()
    d[str(sid)] = {"ts": now, "text": (txt or "")[:120], "reason": reason, "hours": h}
    # 顺手清掉 7 天前的
    cutoff = now - 7 * 86400
    d = {k: v for k, v in d.items() if float((v or {}).get("ts") or 0) > cutoff}
    _save_skip(d)
    log.info("记入失败台账 sid=%s（%s），%.2f 小时内不再试", sid, reason, h)


def _nf_hits(sid):
    """30 分钟内该 sid 累计 notfound 次数（进程内计数，重启即清）。"""
    now = time.time()
    arr = [t for t in _NF_HITS.get(str(sid), []) if now - t < 1800]
    arr.append(now)
    _NF_HITS[str(sid)] = arr
    if len(_NF_HITS) > 500:                      # 防止常驻进程无限增长
        for k in [k for k, v in _NF_HITS.items() if not v or now - v[-1] > 3600]:
            _NF_HITS.pop(k, None)
    return len(arr)


_NF_HITS = {}
_SLA_WARNED = {}


def _sla_warn(sid, to_uid, her_ts_ms, why):
    """R5：她最后一条超过 SLA_WARN_MIN 分钟还没被接上 → 标红一行（不插手操作）。

    同一 sid 10 分钟内只报一次，避免每 30s 刷屏。
    """
    try:
        age_min = (time.time() - float(her_ts_ms or 0) / 1000.0) / 60.0
    except Exception:
        return
    if age_min < SLA_WARN_MIN:
        return
    now = time.time()
    if now - _SLA_WARNED.get(str(sid), 0) < 600:
        return
    _SLA_WARNED[str(sid)] = now
    log.warning("⏰ 超 %.0f 分钟未回 uid=%s sid=%s（%s）→ 标红，留队列按等待时长重排",
                age_min, to_uid, sid, why)


def cooldown_waiting(max_min=30.0):
    """还有「冷却中但没到 24h 淘汰」的会话在等人回吗？

    🔴 2026-11-09 R8（用户拍板「当前账号没榨干不切号」）
        切号前提①「真待回 = 0」原来直接用 candidates()==0 判，而 candidates()
        会滤掉冷却中的人 ⇒ 21:21 实测「待回 4 人全是冷却中/已回」被判成
        「无人可聊」→ 30 秒后切号，把 4 个可能还在等的人丢给另一账号 8 小时。
        这个函数只用于「切号前多等一口气」，不影响匹配闸门（避免 11-08 的饿死回潮）。

    返回 (n, 最早还剩多少分钟)；n=0 表示确实没人。
    """
    try:
        d = _load_skip()
    except Exception:
        return (0, 0.0)
    now = time.time()
    left = []
    for sid, rec in (d or {}).items():
        if not isinstance(rec, dict):
            continue
        if (rec.get("reason") or "") not in ("notfound", "notfound_fresh",
                                             "notfound_storm", "slow", "timeout"):
            continue
        ts = float(rec.get("ts") or 0)
        if now - ts > 86400:                    # 超过 24h 的陈旧台账不算
            continue
        h = float(rec.get("hours") or 0)
        rem = h * 60 - (now - ts) / 60.0
        if rem > 0:
            left.append(rem)
    if not left:
        return (0, 0.0)
    return (len(left), max(left))


def _burst_n(db, sid, uid):
    """她**最新连发**的条数（用于排序优先级：多条 > 单条）。

    复用 flow.her_burst 的语义（从最后一条往前、遇到我发的就停、跳过系统提示），
    只取条数。任何异常都返回 1（当作单条，绝不因为算条数失败丢掉候选）。
    """
    try:
        from brain import flow
        return max(1, len(flow.her_burst(db, sid, uid) or []))
    except Exception:
        return 1


def candidates(db, limit=MAX_N, days=LOOKBACK_DAYS):
    """待回候选：**最后一条是对方发的**会话（不管已读未读）。

    🔴 为什么不用 `db.pending()`（2026-11-02 实测教训）：
      它依赖 `session.unReadCount > 0`，而「进去看一眼就退出」会把未读数清零、
      红点也消失 —— 那类正好就是用户要的「已读未回」。用 pending() 查只剩 1 个，
      改成看 chatmsg 最后一条的 sender 后恢复到正常数量。

    返回 [(sessionId, to_uid, 末条文本, 末条毫秒时间)]，按她末条时间**升序**（最老优先）。
    """
    cutoff = (time.time() - days * 86400) * 1000
    # 🔴 2026-11-10 §104 C4：归档集合一次性取（循环里逐个读台账会白烧磁盘）。
    _archived = set()
    try:
        from brain import sendgate as _SG0
        _archived = set(str(x) for x in _SG0.archived_sids())
    except Exception as _e0:
        log.debug("归档集合取不到（本轮不排除）: %r", _e0)
    # 🔴 2026-11-09 P0：先取设备库真实未读集合（60s 缓存），供下面硬放行使用。
    _unread_sids = _device_unread_sids(db)
    try:
        rows = db.con.execute(
            "SELECT sessionId, toUserId FROM session "
            "WHERE toUserId > 0 AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (cutoff, SCAN_SESSIONS)).fetchall()
    except Exception as e:
        log.warning("查会话失败: %r", e)
        return []

    # 🔴🔴🔴 2026-11-08 12:56（**本轮最重要的一条**：本地镜像里的「死人」）
    #
    #   实测（_final.py，直接 pull 设备库对比）：
    #     本地镜像 96691646 → session 1524 行 / chatmsg 20979 行 / 12.2MB
    #     设备真实 96691646 → session   31 行 / chatmsg   141 行 / 204KB
    #     uid 交集：设备 31 个，本地 1524 个，**只在本地（设备上已不存在）= 1495 个**
    #   另一账号同理：本地 1298 → 设备 55。
    #
    #   含义：Soul **真的把这个账号的历史会话清空了**，设备上只剩最近 31 个。
    #   而本地镜像是「历史快照」（sync 的截断保护故意保留它，不覆盖），
    #   里面 1495 个会话在 App 里**根本不存在了**。
    #
    #   于是「待回 22 人」这个数字是**假的**：那 22 个人在设备上找不到，
    #   翻屏翻不到、搜索搜不到 —— 这不是搜索的 bug，是**人已经没了**。
    #   实测候选里「设备上还活着」= 0 / 1。白烧 40~50s/人，一个人都回不掉。
    #
    #   修法：候选必须过一道**设备存活校验** —— 只有「设备库里也有这个 toUserId」
    #   的人才进队列。这同时也是用户反复强调的「账号数据隔离」的正面实现：
    #   只用**当前账号自己的设备库**判定，绝不跨库、绝不拿历史快照冒充现状。
    #
    #   降级：设备读不到（adb 抖动/无 root）→ 返回 None → **不过滤**（保持旧行为）。
    #   宁可按旧行为白烧，也不能因为一次 adb 失败把整轮待回全掐掉。
    _live_uids = None
    try:
        _live_uids = _device_live_uids(db)
    except Exception as _e:
        log.warning("设备存活校验取不到（本轮不过滤，按旧行为走）: %r", _e)
    if _live_uids is not None:
        _before = len(rows)
        rows = [(s, u) for (s, u) in rows if str(u) in _live_uids]
        _dead = _before - len(rows)
        if _dead:
            _sig = (_dead, len(rows))
            _now = time.time()
            if _LIVE_LOG.get("sig") != _sig or (_now - _LIVE_LOG.get("ts", 0)) >= _LIVE_TTL_S:
                log.info("设备存活校验：%d 个会话在 App 里已不存在（Soul 清过历史）→ 移出候选，剩 %d 个",
                         _dead, len(rows))
                _LIVE_LOG.update(sig=_sig, ts=_now)
            else:
                log.debug("设备存活校验(TTL 内重复)：移出 %d 个，剩 %d 个", _dead, len(rows))

    out = []
    for sid, to_uid in rows:
        if str(to_uid).startswith(SKIP_UID_PREFIX):
            log.debug("跳过官方号 uid=%s（SKIP_UID_PREFIX）", to_uid)
            continue
        try:
            # 🔴 2026-11-04：取 latest —— 入向不落 chatmsg 的账号（实测 402857053）
            #    只有 session 摘要里有她刚说的话，只读 chatmsg 会让候选永远停在几天前，
            #    进而拿 87h 前的老话去搜索 → 身份校验必然失败（实测各失败 10 次）。
            last, _src = db.latest(sid)
        except Exception:
            continue
        if last is None:
            log.debug("候选跳过 sid=%s：latest() 返回 None（chatmsg 与摘要都空）", sid)
            continue
        # 🔴 §104 C4：归档 ≠ 拉黑。她再发人话（ts 比台账水位线新）→ 回合重置、解除归档。
        #    必须拿到 last 才能比时间，所以放在 latest() 之后、过滤链最前面。
        #    若放在循环开头直接 continue，归档会话将永远解不开（实测推演出的洞）。
        if str(sid) in _archived:
            try:
                from brain import sendgate as _SGa
                from data import reply_state as _RSa
                from eyes import sysmsg as _SMa
                # 🔴 §106 交叉审查实证（P0-1）：只比 ts 会把「我方刚发的跟进」和
                #    Soul 推的系统卡当成她的人话 → 归档复活 + 水位线被污染，
                #    age 归零后最多可再发 6 条。必须同时判 sender 与 human。
                _lt = (last.text or "").strip()
                # 文本为空时（语音/图片占位）只要不是 msgType 27/35 也算真人，
                # 避免她用语音/图片重新开口时归档永远解不开（C4）。
                _human_ok = (_SMa.is_human(_lt, getattr(last, "msg_type", None),
                                           uid=to_uid) if _lt else
                             int(getattr(last, "msg_type", 0) or 0) not in (27, 35))
                _is_new_her = (str(last.sender) != str(db.uid) and _human_ok
                               and int(last.ts or 0) > _RSa.her_ts_of(str(sid)))
                if _is_new_her:
                    _SGa.on_her(str(sid), int(last.ts or 0), human=True)
                    log.info("归档会话来了新的人话 sid=%s → 解除归档，重新计入待回", sid)
                else:
                    log.info("跳过已归档会话 sid=%s（C4：不回、不唤醒、不计待回）", sid)
                    continue
            except Exception as _e_ar:
                log.debug("归档检查异常（本轮仍跳过）: %r", _e_ar)
                continue
        if str(last.sender) == str(db.uid):
            # 🔴🔴 2026-11-09 P0（18:42 新消息未处理 · 真正的锁芯）
            #
            #   【改前】这里是一句**没有任何日志**的 `continue`。
            #   而这个账号（402857053）的特性是「入向消息不落 chatmsg、只更新 session 摘要」，
            #   `latest()` 在「摘要时间 <= chatmsg 时间」时直接返回 chatmsg 那条
            #   ⇒ 她 18:42 刚说的话，被判成「最后一条是我发的 → 不用回」，
            #   静默丢弃、零日志。实测 18:48 连续多轮 `待回 1 人` 但 `candidates 为空`，
            #   就是这条路径吃掉的（其余过滤全都有日志可查）。
            #
            #   【改后】末条是我 + 设备库说这个会话 unReadCount>0
            #   ⇒ 以「设备未读」为准（它是强真值，镜像只是缓存），
            #   用 session 摘要里她的话硬放行进队列；只有摘要也证明是我说的才跳过。
            #   这样 `_recently_replied` 的「她更新于我的回复」语义仍然生效，不会重复发。
            if str(sid) in _unread_sids:
                _dig = {}
                try:
                    _dig = db.session_digest(sid) or {}
                except Exception:
                    _dig = {}
                _d_txt = (_dig.get("text") or "").strip()
                _d_ts = int(_dig.get("ts") or 0)
                if _d_txt and _d_ts and not _recently_replied(
                        to_uid, sid=sid, text=_d_txt, her_ts_ms=_d_ts):
                    log.info("设备未读硬放行·镜像滞后 uid=%s sid=%s 摘要=%r"
                             "（chatmsg 末条是我，但设备说未读 → 判定是她新话）",
                             to_uid, sid, _d_txt[:24])
                    out.append((sid, to_uid, _d_txt, _d_ts,
                                _burst_n(db, sid, db.uid)))
                    continue
                log.info("跳过末条是我 sid=%s uid=%s（设备说未读，但摘要也证明是我说的"
                         "或取不到摘要：%r）", sid, to_uid, _d_txt[:20])
            else:
                log.debug("跳过末条是我 sid=%s uid=%s（设备未读集合里没有 → 真·无需回）",
                          sid, to_uid)
            continue
        # 🔴 2026-11-03（最老优先的配套闸）：`session.timestamp` 会被「未读推送 /
        #    推荐位刷新」更新，与 chatmsg 里她**真正**的末条时间差得很远 ——
        #    实测第二个账号里混进了 257h（10 天）前的会话，session 时间却被刷成近几天。
        #    改成最老优先后这类会抢到队首，把真正该回的挤到后面，所以这里按
        #    真实末条时间再卡一次 LOOKBACK_DAYS 窗口（超期的回了也怪，她早忘了）。
        if int(last.ts or 0) < cutoff:
            log.info("跳过超期会话 sid=%s（她末条已 %.1f 天前）",
                     sid, (time.time() * 1000 - int(last.ts or 0)) / 86400000.0)
            continue
        # 非文本类（语音/图片/表情/卡片）在**本队列里一律跳过**：
        #   它们的 text 恒为空 → 搜不到、列表预览也认不出是谁，
        #   但**必然带红点** → 由 clear.sweep → flow.handle_one 处理，
        #   那条链路已经接好 ASR / 图片话术（brain/voice.py、flow.MEDIA_REPLIES）。
        k = V.kind_of(last)
        if k == "tip":
            # 🔴 2026-11-05：不能静默跳过 —— 她说完话后可能紧跟系统卡片，
            #   原来直接 continue 会让那句话永久没人接（且没有任何日志可查）。
            #   往前找她最后一条真实消息，找到了就换它继续判。
            from brain import flow as _flow
            _real = _flow.her_last_real(db, sid, db.uid)
            if _real is None:
                continue
            last = _real
            k = V.kind_of(last)
            if k == "tip":
                continue
        if k in ("image", "emoji", "other"):
            log.info("非文本消息（%s）sid=%s 走红点路径，这里跳过", k, sid)
            continue
        if V.is_voice(last):
            # 🔴🔴 2026-11-08 01:45 用户明确要求：「一定要正常识别对方语音内容然后再回复」。
            #   改前：语音在这里 `continue`，理由是「留给红点路径（clear.sweep → flow.handle_one）」。
            #   但实测这个理由是**不成立**的：
            #     · `unread_msg_number` 在 dump 里出现 **0 次**（两帧连续验证），
            #       `clear.dots()` 恒为空 → 红点路径**根本不会触发**；
            #     · 于是「她发语音」= 永久无人回。这正是用户反复说「语音没处理好」的真因。
            #   改后：**就地转写**，转出文字就当成正常文本候选进入队列。
            #   实测成本：App 自带 word 命中率仅 1/15（6.7%），其余走本地 whisper，
            #   2~10s 语音 0.1~12s/条（模型已加载后 0.1s 命中缓存，冷启动约 5~12s）。
            #   转写失败 → 用占位串照样进队列（宁可回一句「没听清，你再说一遍」，
            #   也不能让她的语音永远石沉大海）。
            vtxt, vhow = V.voice_text(last)
            if vtxt:
                log.info("语音已转写 sid=%s（%ds, %s）: %r",
                         sid, int(V.duration(last)), vhow, vtxt[:40])
                txt = vtxt
            else:
                log.warning("语音转写失败 sid=%s（%ds）→ 用占位串照常回复",
                            sid, int(V.duration(last)))
                txt = V.PLACEHOLDER
            # 标记这个 sid 是语音：搜索时必须跳过「用转写文字搜」，
            # 因为 Soul 列表预览显示的是「[语音]」，转写文字搜不到（见 kw_of）。
            _VOICE_SIDS.add(str(sid))
        else:
            txt = (last.text or "").strip()

        if not txt:
            log.info("候选跳过 sid=%s uid=%s：末条无文本（kind=%s），不在此队列处理",
                     sid, to_uid, k)
            continue
        # 🔴 2026-11-10 §104 C5/C8：系统/广告消息不回、不计待回、
        #    **不更新 her_ts 水位线**、只跳过不冷却（她紧接着发人话仍要正常回）。
        #    旧判定只认 4 个字面量，漏掉「互相关注后即可…」这类系统卡（夜班实证回错过）。
        _human = txt not in SYS_TEXTS
        try:
            from eyes import sysmsg as _SM
            _human = _SM.is_human(txt, getattr(last, "msg_type", None), uid=to_uid)
        except Exception as _e_sm:
            log.debug("sysmsg 分类异常（退回字面量判定）: %r", _e_sm)
        if not _human:
            try:
                from brain import sendgate as _SG1
                _SG1.on_her(str(sid), int(last.ts or 0), human=False)
            except Exception:
                pass
            log.info("系统/广告消息（%s）sid=%s → 不回不计待回（C5/C8）", txt[:20], sid)
            continue
        # C2：她末条真人消息推进水位线（只在 ts 变新时落盘，会清掉本回合发送计数）。
        try:
            from brain import sendgate as _SG2
            _SG2.on_her(str(sid), int(last.ts or 0), human=True)
        except Exception:
            pass
        # 🔴 2026-11-03 修复 P1：原来 len(txt)<2 把「嗯/好/哦」这类一字纯文本也丢弃。
        #    一字消息若红点已清且当时没发出，就会永久漏回、且无台账可恢复。
        #    现在只丢空文本；一字消息保留为候选，搜索关键词由 kw_of 退回历史长句兜底。
        # 🔴 2026-11-09 P0：设备库 unread>0 = 真红点，硬放行。
        #    台账(replied.json)、L2(turns.md)、冷却(pending_skip.json) 都是本地状态，
        #    镜像滞后时会把新消息误判成「已回/冷却中」，导致红点堆着一条都不回。
        #    这里直接入队，后续定位/身份校验/发送三态确认仍照常执行，不会乱发。
        if str(sid) in _unread_sids:
            log.info("设备未读硬放行 uid=%s sid=%s（跳过台账/L2/冷却）", to_uid, sid)
            out.append((sid, to_uid, txt, int(last.ts or 0), _burst_n(db, sid, db.uid)))
            continue

        # 🔴 2026-11-10 §104：状态机取代「纯文本 old==cur / L2 末行是我」判定。
        #    11-10 夜班实测：这两句误判「被判已回」142 次、跳过已回会话 1549 次 ——
        #    她再发一句一模一样的「哈哈哈」就被当成回过，永久漏回。
        #    现在只有 awaiting / following / archived / no_human 才跳过；
        #    她说了人话且还有额度一律进队列，具体发几条由 handle_pending 的发送闸裁决。
        _vd = None
        try:
            from brain import sendgate as _SG3
            from brain import verdict as _VD
            _vd = _SG3.state_of(str(sid), her_ts_ms=int(last.ts or 0), has_human=True)
            if _vd.state == _VD.ARCHIVED:
                try:
                    from data import reply_state as _RSa
                    _RSa.set_archived(str(sid), True)   # wake.candidates() 也要排除
                except Exception:
                    pass
            if _vd.state in (_VD.AWAITING, _VD.FOLLOWING,
                             _VD.ARCHIVED, _VD.NO_HUMAN):
                log.info("状态机跳过 uid=%s sid=%s state=%s（%s）",
                         to_uid, sid, _vd.state, _vd.reason)
                continue
        except Exception as _e_vd:
            log.debug("状态机异常 → 退回旧台账判定: %r", _e_vd)
            if _recently_replied(to_uid, sid=sid, text=txt, her_ts_ms=last.ts) \
                    or _l2_last_is_me(sid, her_ts_ms=last.ts):
                log.info("跳过已回会话 uid=%s（台账/ L2 末行是我且不早于她最新消息）", to_uid)
                _sla_warn(sid, to_uid, last.ts, "被判已回")
                continue

        if should_skip(sid, txt):
            _r = _LAST_SKIP.get(str(sid)) or {}
            _left_min = (float(_r.get("hours") or 0) * 60
                         - (time.time() - float(_r.get("ts") or 0)) / 60.0)
            log.info("跳过冷却中的会话 sid=%s（原因=%s，剩 %.0f 分钟）",
                     sid, _r.get("reason") or "?", max(0.0, _left_min))
            _sla_warn(sid, to_uid, last.ts, "冷却中 剩%.0f分" % max(0.0, _left_min))
            continue
        out.append((sid, to_uid, txt, int(last.ts or 0), _burst_n(db, sid, db.uid)))

    # 🔴🔴🔴 2026-11-09 P0（最后一道闸 · 设备未读对账）
    #
    #   上面每一个过滤都对，但**组合起来**会把「设备明说有未读」的会话漏掉：
    #     · 镜像滞后 → latest() 返回我的旧消息 → 末条是我
    #     · 设备存活缓存陈旧 → 被判定「App 里不存在」
    #     · 20 分钟/24 小时口径、冷却台账、L2 末行 …
    #   用户口径很清楚：**设备库里 unReadCount>0 的会话，就是有人真的在等我回**。
    #   所以这里做一次无条件对账：设备说未读、但没进 out 的，逐个查明原因并强制补入。
    #   任何上游过滤都不能把它杀掉 —— 这是「新消息不被漏处理」的最后保证。
    #   补入后仍然走「定位 / 身份校验 / 发送三态确认」，不会发错人。
    try:
        _have = {str(x[0]) for x in out}
        _missing = [s for s in _unread_sids if s not in _have]
        _added = 0
        for _s in _missing:
            if _added >= 5:            # 一次最多补 5 个，别把队列冲爆
                break
            try:
                _dig = db.session_digest(_s) or {}
            except Exception:
                _dig = {}
            _t = (_dig.get("text") or "").strip()
            _uid2 = str(_dig.get("to_uid") or "")
            _ts2 = int(_dig.get("ts") or 0)
            if not _t or not _uid2 or not _ts2:
                log.debug("设备未读对账：sid=%s 摘要不完整（text=%r uid=%r ts=%s）→ 无法补入",
                          _s, _t[:16], _uid2, _ts2)
                continue
            if _uid2.startswith(SKIP_UID_PREFIX):
                continue
            if _t in SYS_TEXTS:
                log.info("设备未读对账：sid=%s 末条是系统文本 %r → 不补", _s, _t[:16])
                continue
            log.warning("设备未读对账：sid=%s uid=%s 设备说未读却没进队列 "
                        "（被上游过滤漏掉）→ 强制补入，末条=%r",
                        _s, _uid2, _t[:24])
            out.append((_s, _uid2, _t, _ts2, _burst_n(db, _s, db.uid)))
            _added += 1
        if _missing:
            _lv = log.info if _added else log.debug
            _lv("设备未读对账：设备未读 %d 个，其中 %d 个不在队列（已补 %d 个）",
                len(_unread_sids), len(_missing), _added)
    except Exception as _e:
        log.warning("设备未读对账异常（不影响已有候选）: %r", _e)

    # 🔴 2026-11-03 用户口径：**最老待回优先**（先灭火，再聊新的）。
    #    原来按 session.timestamp 倒序 + 凑够 limit 就 break = 最新优先，
    #    结果是「她 10 小时前那句」永远排在「她 2 分钟前那句」后面，
    #    越老越没人管，p90 延迟被拖到 156min。
    #    注意两点（改的时候踩过）：
    #      ① 扫描窗口仍按 timestamp DESC 取 SCAN_SESSIONS 个（保证覆盖最近会话），
    #         只把**输出顺序**改成按她末条时间升序；
    #      ② 必须扫完窗口再排，不能凑够 limit 就 break（否则永远只拿到最新那几个）。
    #    公平性由「回复台账 / should_skip 冷却」保证：处理完一个就自然往后走，
    #    不需要额外轮转（_ROT 已废）。
    # 🔴 2026-11-03（用户口径：「有红点就一定有新消息，新消息不能被积压挤住」）：
    #   原来整体按「最老优先」→ 积压 54 个时，刚发来消息的人排在队尾，
    #   实测一条 24h 前的和一条刚到的同等对待，新消息等于没抢到队。
    #   现在**新老交错**：最近 FRESH_H 小时的和老积压交替出队，
    #   每轮两边都推进（3 新 + 3 老），既不让新消息饿死，也不让老会话永远轮不到。
    now_ms = time.time() * 1000.0
    _window = FRESH_H * 3600000.0
    fresh = [x for x in out if now_ms - float(x[3] or 0) < _window]
    stale = [x for x in out if now_ms - float(x[3] or 0) >= _window]
    fresh.sort(key=lambda x: -float(x[3] or 0))    # 新的：最新的先
    stale.sort(key=lambda x: float(x[3] or 0))     # 积压：最老的先
    merged = []
    while fresh or stale:
        if fresh:
            merged.append(fresh.pop(0))
        if stale:
            merged.append(stale.pop(0))
    # 🔴 2026-11-04（实时性）：上面是「新老交替」，但 fresh 的窗口是 6 小时 ——
    #   实测她 9 分钟前发的那条排在了一堆 4 小时前的后面（09:15:42 的消息 09:24 才回）。
    #   **很新（<20 分钟）的一律提到最前面**，按时间倒序；老积压从第 N 个之后开始交替。
    # 🔴 2026-11-03（用户口径：「优先回长消息和她发来的多条消息，低于 3 字的排后面」）：
    #   主序改成「内容档位」—— 用**稳定排序**按档位重排，同档位仍保持上面的新老交错
    #   （不破坏之前「新消息不能被积压挤住」的时间公平性）：
    #     档 0：她连发多条（≥2 条）      ← 信息最多、且多半是刚发来在等，最优先
    #     档 1：单条长消息（≥6 字）      ← 有内容、好接
    #     档 2：中等（3~5 字）
    #     档 3：短（<3 字，如「哦/滚/？」）← 排最后（这类搜索不唯一、易空转）
    def _tier(x):
        _, _, txt, _ts, bn = x
        if bn >= 2:
            return 0
        n = len((txt or "").strip())
        if n >= 6:
            return 1
        if n >= 3:
            return 2
        return 3

    merged = sorted(merged, key=_tier)   # 稳定排序：tier 相同者保持原相对顺序
    # 🔴 2026-11-04（实时性，必须在 _tier 之后！）：
    #   上面那个 _tier 排序会把「很新」的候选重新打散 —— 09:30 实测：她 3 分钟前发的
    #   排第 1，而 4/5 分钟前发的掉到第 16、17 位（被「短消息 tier 3」压到最后）。
    #   用户口径是必回优先：**20 分钟内到的一律提到最前面**，tier 只用于同批内部。
    _HOT_MS = 20 * 60 * 1000.0
    hot = [x for x in merged if (now_ms - float(x[3] or 0)) < _HOT_MS]
    rest = [x for x in merged if (now_ms - float(x[3] or 0)) >= _HOT_MS]
    hot.sort(key=lambda x: -float(x[3] or 0))     # 新到的先回
    merged = hot + rest
    # 2026-11-03：把「她末条时间」一起返回（第 4 项）——
    #   handle_pending 要用它判「是不是断太久、该走重新开场」。
    #
    # 🔴🔴 2026-11-08 12:5x（修截断/过滤顺序颠倒 —— search-diagnostician 指出）
    #
    #   原来这里就 `merged = merged[:limit]` 截断了，而**过期闸在下面**。
    #   handle_pending 传 limit=60（CAND_SCAN），一旦池子里前 60 个恰好都是老候选，
    #   新鲜候选会在这一行**被截掉、根本走不到过期闸**，等于闸形同虚设。
    #   当前待回 22 < 60 不触发，但积压一涨就会踩到（历史峰值 63~64 人）。
    #
    #   ⇒ 先过滤（过期闸），再截断。语义上本来就该如此：
    #     limit 是「本轮最多处理几个**有效**候选」，不是「先取 60 个再看有几个有效」。
    #   注意：截断移到过期闸之后（见下方 `merged = merged[:limit]`）。
    # 🔴🔴 2026-11-08 02:50（P0 死锁修复：积压永远清不掉 → 匹配永远被饿死）
    #
    #   现网实况：待回 63~64 人，其中绝大部分是 **92~158 小时**（4~6.6 天）前的老会话。
    #   这些会话的共同点是：
    #     · 翻 3 屏找不到（列表 1270 条，早被顶到几百名开外）
    #     · 搜索搜不到（她 4 天前那句话，Soul 搜索只索引近期聊天记录）
    #   于是每个候选白烧 40~50s：翻屏 21s → 双击 → 进搜索 → 7.3s「未找到相关结果」→ 放弃。
    #   一轮降级处理 10 个 = 白烧 300~500s，**一个人都回不掉**。
    #
    #   后果是死锁：
    #     积压清不掉 → has_dot_now 恒 True → daemon 红点闸门 `仍有红点 → 本轮不匹配`
    #     → 连续匹配（MATCH_STREAK_N=12）**一次都进不去**（实测 11-08 全天匹配 3 次，
    #       改完连续匹配后 0 次）。
    #
    #   修法：给「定位尝试」设一个**过期闸**。超过 STALE_GIVEUP_H 小时的会话，
    #   不再浪费翻屏/搜索（那是注定失败的），直接排除出本轮候选。
    #   注意：**不是不回了** —— 它们仍在库里，等哪天她再发新消息（ts 变新）自然回到队列；
    #   而且「回一条 4 天前的话」本身也没意义（她早忘了，用户要的是能聊起来的人）。
    #
    #   阈值取 72h：实测 24h 内的候选定位成功率高得多，72h 外的几乎全是 notfound。
    #
    # 🔴🔴 2026-11-08 12:4x（P0-1，search-diagnostician 全量取证 _team/search_diag.md §2.1）
    #
    #   上面「取 72h」的说法被实测数据推翻，按年龄分段的**回出率**（44h 窗口）：
    #     0-1h → 49.2%   ← 几乎所有成功都在这一段
    #     3-6h → 0.0%
    #     6-12h → 10.7%
    #     12-24h → 0.0%
    #     24h+  → 0.8% / 0.0%
    #   候选里 61.4% 年龄 ≥24h、48h+ 占 50.1%，而 48h+ 回出率 **0.0%**。
    #   翻屏命中率只有 8.1%，平均 21.2s/次，44 小时烧掉 373.7 分钟。
    #
    #   ⇒ 24h 这个闸太松。降到 12h 能砍掉 61.4% 的无效翻屏（约 229 分钟/44h），
    #     把单轮预算让给真正回得出的人。
    #   语义不变：**不是不回了** —— 她再发新消息 ts 变新就自动回到队列。
    # 🔴 2026-11-10 §104：STALE_GIVEUP_H 24 → 72（与 RESTART_H 对调）。
    #    上面历史注释里的「24h」是改前口径，保留作决策留痕；
    #    现在 >72h 的会话由 verdict 判 archived 并写台账，本闸只作兜底。
    try:
        _stale_ms = STALE_GIVEUP_H * 3600000.0
        _keep, _dropped = [], 0
        for x in merged:
            _age = now_ms - float(x[3] or 0)
            if _age >= _stale_ms:
                _dropped += 1
                try:
                    from data import reply_state as _RSd
                    _RSd.set_archived(str(x[0]), True)
                except Exception:
                    pass
                continue
            _keep.append(x)
        if _dropped:
            log.info("过期淘汰：%d 个候选超过 %.0fh 未活跃（翻屏/搜索注定失败）→ 本轮不排它们，"
                     "队列剩 %d 个", _dropped, STALE_GIVEUP_H, len(_keep))
        merged = _keep
    except Exception as _e:
        log.warning("过期淘汰异常（忽略，按原队列走）: %r", _e)
    # 🔴 2026-11-08 12:5x：截断移到这里（**过滤之后**）。见上方顺序颠倒的注释。
    merged = merged[:limit]
    return [x[:4] for x in merged]


NICK_FILE = STATE / "nick_cache.json"


def _load_nick_file():
    """读盘上的昵称缓存（sid -> 昵称）。

    🔴 2026-11-10：`extMap` 里的昵称只覆盖 48% 的老会话，但**列表行/会话标题上
      一定写着昵称**。所以凡是在界面上看见过的昵称都记下来，
      下次这批 40h+ 的老会话就有昵称可搜了（这是唯一能救它们的手段）。
    """
    out = {}
    try:
        if NICK_FILE.exists():
            import json as _json
            d = _json.loads(NICK_FILE.read_text(encoding="utf-8"))
            now = time.time()
            for k, v in (d or {}).items():
                if isinstance(v, str) and v.strip():
                    out[str(k)] = (now, v.strip())
    except Exception as e:
        log.debug("昵称缓存读取失败（当作空）: %r", e)
    return out


_NICK_CACHE = _load_nick_file()


def nick_of(db, sid, uid):
    """取**对方昵称**（库里唯一可靠的昵称来源：chatmsg.extMap 的 name）。

    🔴 2026-11-10（用户口径「搜昵称」）
      IM-SDK 库没有昵称表，`soul_app.db.im_user.alias` 只缓存本人。
      她发来的消息 `extMap` 里带发送者昵称（JSON，字段名 name/nickName 都有过），
      实测 73 个 >20h 待回会话里 35 个能拿到（48%），拿不到就是 None。

      缓存 10 分钟：一次会话内昵称不会变，避免每个候选都重查一遍 SQL。
    """
    key = str(sid)
    hit = _NICK_CACHE.get(key)
    if hit and (time.time() - hit[0]) < 600.0:
        return hit[1]
    nice = None
    try:
        rows = db.con.execute(
            "SELECT extMap FROM chatmsg WHERE sessionId=? AND senderId<>? "
            "AND extMap IS NOT NULL AND extMap != '' "
            "ORDER BY localTime DESC LIMIT 12", (sid, str(db.uid))).fetchall()
        import json as _json
        for row in rows:
            # 🔴 2026-11-10：IMDB.con 带 row_factory=sqlite3.Row，Row 既不是 tuple
            #   也不是 list —— 按 isinstance 判断会把它当字符串塞进 json.loads，
            #   异常又被 debug 吞掉，表现就是「昵称永远取不到」。
            em = row[0]
            if not em or "name" not in em:
                continue
            try:
                d = _json.loads(em)
            except Exception:
                continue
            for k in ("name", "nickName", "nickname"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    nice = v.strip()
                    break
            if nice:
                break
    except Exception as e:
        log.debug("取昵称异常 sid=%s: %r", sid, e)
    _NICK_CACHE[key] = (time.time(), nice)
    if len(_NICK_CACHE) > 500:
        _NICK_CACHE.clear()
    return nice


def _usable_word(w, min_len):
    """这个词能不能拿去搜（Soul 搜索对短词/纯符号基本无效）。

    实测：`搜索 '嗯'`、`'哦'`、`'🤝'` 一律 0 结果；
    昵称 `。`、`🙇` 同理。拿它们搜只是白烧 30~50s 再记一次失败台账。
    """
    t = (w or "").strip()
    if len(t) < min_len:
        return False
    # 至少含一个汉字/字母/数字：纯 emoji、纯标点、纯空白都搜不到
    return bool(re.search(r"[0-9A-Za-z\u4e00-\u9fff\uff10-\uff19]", t))


def remember_nick(sid, nick):
    """把界面上看到的昵称记下来（列表行/会话标题），供以后「搜昵称」用。"""
    t = (nick or "").strip()
    if not _usable_word(t, 2):
        return
    key = str(sid)
    old = _NICK_CACHE.get(key)
    if old and old[1] == t:
        return
    _NICK_CACHE[key] = (time.time(), t)
    try:
        import json as _json
        data = {k: v[1] for k, v in _NICK_CACHE.items() if v and v[1]}
        NICK_FILE.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        log.info("记住昵称 sid=%s → %r（下次可搜昵称）", key[-10:], t)
    except Exception as e:
        log.debug("昵称缓存落盘失败: %r", e)


def _sessions_with(db, text):
    """文本出现在几个不同会话里（前缀匹配，兼容 kw_of 的 20 字截断）。

    返回 -1 = 查不到/异常（保守，不否决）。
    """
    t = (text or "").strip()
    if len(t) < 4:
        return -1
    try:
        r = db.con.execute(
            "SELECT COUNT(DISTINCT sessionId) FROM chatmsg WHERE text LIKE ?",
            (t + "%",)).fetchone()
        return int(r[0] or 0) if r else 0
    except Exception:
        return -1


def _search_plan(db, sid, to_uid, kw):
    """搜索三级策略（用户 2026-11-10 口径）。

      ① 昵称 —— 唯一性最强，命中即本人；
      ② 对话内容里**独一无二**的一句（只在本会话出现）；多会话重复的直接不搜，
         因为拿它搜必然进错人/搜不到（实测模板句 notfound 率极高）；
      ③ 都没有 → 返回空，上层放弃本轮。

    为什么不是「有内容就搜」：日志实证 `搜索 '就那提示，没啥用'` 能中、而
    `'葛优躺，那是瘫出境界了'` 不中 —— 差别不在长短，在于这句话是否唯一指向一个人。

    返回 [(label, word), ...]，按优先级排好。
    """
    plan = []
    nk = nick_of(db, sid, to_uid)
    if _usable_word(nk, 2):
        plan.append(("昵称", nk))
    elif nk:
        log.info("昵称 %r 太短/纯符号 → 不拿它搜", nk[:12])
    if _usable_word(kw, 5):
        n = _sessions_with(db, kw)
        # 🔴🔴 2026-11-10（身份校验连续失败的真正来源）：
        #   `n == 0` 原来也被放行，但它的真实含义是**这句话在任何 chatmsg 里都不存在**
        #   —— 只可能来自 session 摘要（她的个人简介 / Soul 推荐文案）。
        #   Soul 搜索会把「用户资料」一起搜，于是搜 `希望 Ta 能遇见 35 岁后的`
        #   命中一堆**简介里写着这句话的陌生人**，点进去 4 次全是别人：
        #     23:07:42 转搜索 → 23:08:51「身份校验连续 4 次失败」→ 长冷却 2h → 这条永远不回
        #   现在：0 个会话出现过 → 判定「不是聊天内容」，不许拿去搜。
        #   -1（查询异常）保守放行，避免误伤。
        if n in (-1, 1):
            plan.append(("内容", kw))
        elif n == 0:
            log.info("内容关键词 %r 在库内 0 个会话出现（像是简介/推荐文案）→ 不拿它搜",
                     kw[:16])
        else:
            log.info("内容关键词 %r 在 %d 个会话里都有（不独一无二）→ 不拿它搜",
                     kw[:16], n)
    elif kw:
        log.info("内容关键词 %r 太短/纯符号 → 不拿它搜", kw[:12])
    return plan


def kw_of(db, sid, txt, min_len=3, skip_text=False):
    """选搜索关键词：末条太短就往前找一条更长的；压缩多余空格。

    实测失败案例（2026-11-02）：
      「哦？」2 字 -> 搜索 0 条结果
      「抖音  番茄小说」双空格 -> 搜索 0 条
    所以这里把空白压成一个，长度不够就退回上一条更长的消息。

    🔴 2026-11-08：新增 `skip_text` —— 语音会话专用。
      语音转写出来的文字**只存在于我们内存里**，Soul 列表预览显示的是「[语音]」，
      拿转写文字去搜索 100% 得到「未找到相关结果」，白等 11~30s。
      所以语音会话直接跳过「用末条文字搜」，改走下面的历史长句兜底。
    """
    cand = re.sub(r"\s+", " ", txt or "").strip()
    # 去掉 [表情] 标记再搜：带 [笑] 这类词搜索会命中不到（2026-11-02 实测）
    cand = re.sub(r"\[[^\]]{1,6}\]", "", cand).strip()
    # 🔴 2026-11-04（现网 09:09 实测）：`搜索 '机器人？' -> 等满 30s 仍无结果`。
    #    带全角标点的关键词在 Soul 搜索里命中不了（问句、感叹句几乎必中）。
    #    只去掉**首尾**标点，中间不动（中间标点是原话的一部分）。
    _PUNC = r"\s，。！？、,.!?~～…\-—_:：;；\"'（）()\[\]【】"
    cand = re.sub("^[" + _PUNC + "]+", "", cand)
    cand = re.sub("[" + _PUNC + "]+$", "", cand).strip()
    # 🔴🔴 2026-11-08 12:4x（P0-3，search-diagnostician 全量取证 _team/search_diag.md §2.4）
    #
    #   实测关键词长度 vs 搜索成功率（44h 窗口，1139 候选）：
    #     3~4 字 → 43.5%   5~8 字 → **74.1%（最高）**   纯数字串 → 97% 超时
    #   3~4 字超时累计 358 次 × 30s ≈ 179 分钟纯浪费；
    #   纯数字（手机号/微信号，如 '159****0632'）超时 131 次，几乎必超时。
    #
    #   所以把「够不够长」的闸从 min_len(默认3) 提到 5，并显式禁掉纯数字串。
    #   长度够的候选仍然优先；不够就往下走「历史长句兜底」，而不是硬搜一个必败的词。
    # 🔴 2026-11-12（修 TIMEOUT 175 次）：上面的正则 `[0-9０-９]+` 只匹配**纯数字**，
    #   而实测掩码手机号（如 '159****0632'，注释里点名的例子）带 4 个 `*`，
    #   完全绕过了这道闸 → 拿它去搜索 97% 超时（每 30s 白烧），正是本 issue 的
    #   brain.pendingq.log TIMEOUT 主力来源。补上 `*` / 全角 `＊`，掩码号也禁。
    _KW_MIN = max(min_len, 5)
    _is_digits = bool(cand) and re.fullmatch(r"[0-9０-９*＊]+", cand or "") is not None
    if len(cand) >= _KW_MIN and not _is_digits and not skip_text:
        out = cand[:20]
        # 截断可能把「[旺柴]」切成「[旺」—— 残留的 [ 会让搜索失败（实测）
        out = re.sub(r"\[[^\]]*$", "", out).strip()
        return out
    try:
        msgs = list(db.messages(sid, limit=8))
        # 🔴 2026-11-03 修：**优先用「她」发的长句**，其次才是我的。
        #    原因（实测 16:09-16:12 连续 3 次 id_mismatch）：她末条是「说」「不知道」
        #    这种短词时，退回的「最近一条长句」往往是我发的**开场白模板**
        #    （「有空聊两句不」「你平时这个点都干啥」），同一句话在几十个会话里都有 ——
        #    搜出来第一条不一定是她，进错会话后身份校验必然判「不唯一」，
        #    白烧一轮 30~50s，还要等冷却重试。她的话才是这个会话唯一的。
        for want_mine in (False, True):      # 先她的话，再我的话
            for m in reversed(msgs):         # 各自都从最新往前找
                is_mine = str(m.sender) == str(db.uid)
                if is_mine != want_mine:
                    continue
                t = re.sub(r"\s+", " ", (m.text or "")).strip()
                t = re.sub(r"\[[^\]]{1,6}\]", "", t).strip()
                # 🔴 2026-11-08：兜底句同样要过「5 字下限 + 非纯数字」——
                #   否则末条太短时又会退回到一个必败的关键词（实测 3~4 字成功率仅 43.5%）
                # 🔴 2026-11-12（TIMEOUT 根治）：兜底句同样要挡**掩码手机号**
                #   （'137****8899'）—— 它长度够、但带 `*` 会绕过旧正则被当成
                #   关键词硬搜必超时。与上方主闸同口径：数字 + 星号一律判必败。
                if re.fullmatch(r"[0-9０-９*＊]+", t or ""):
                    continue
                if m.msg_type != 1 or len(t) < 6:
                    continue
                # 🔴🔴 2026-11-08 13:2x（P0-C，reply-diagnostician 实证收益最高的一条）
                #
                #   实测（_team/reply_diag.md §9）：把每次 `搜索 'KW'` 拿去 chatmsg 精确反查，
                #     `未找到相关结果` 45 次里 **只有 3 次（7%）** 关键词在本会话真实存在。
                #     而 219 次 notfound 中很大比例是**我方开场白模板**：
                #     「重庆好玩的地方有很多呀，你要问明」在 **4 个不同 sid** 上重复出现，
                #     且全部 notfound —— 它是**群发模板**，不是这个会话的独有内容。
                #
                #   为什么模板句必败：模板句在几十个会话里都有一模一样的副本，
                #   Soul 搜索要么返回一堆不相关的人（身份校验失败），
                #   要么干脆索引不到（notfound）。两头都是白烧 30~50s。
                #
                #   修法：**先查这个句子是不是群发模板** —— 在库里有 ≥3 个不同会话
                #   出现过同样的话，就跳过它，继续往前找下一句。成本是一次本地 SQL，
                #   省的是 30~50s 的必败搜索 + 一次 3 小时冷却误罚。
                if _is_broadcast_template(db, t):
                    log.debug("兜底关键词 %r 是群发模板（多会话重复）→ 跳过", t[:20])
                    continue
                return t[:20]
    except Exception as e:
        log.warning("取备选关键词异常: %r", e)
    return cand[:20]


_TEMPLATE_CACHE = {}


def _is_broadcast_template(db, text, min_sessions=3):
    """这句话是不是「群发模板」（在 ≥min_sessions 个不同会话里都出现过）。

    🔴 2026-11-08 13:2x（P0-C 的实现）

      背景见 `kw_of` 里的注释：我方开场白模板（「重庆好玩的地方有很多呀…」）
      会在几十个会话里重复出现，拿它当搜索关键词**必然失败**：
        · Soul 搜出一堆不相关的人 → 身份校验失败
        · 或干脆索引不到 → notfound
      两种结果都白烧 30~50s，还会误罚 3 小时冷却。

      判据：用 chatmsg 里同样的文本数**不同 sessionId 的个数**。
        ≥3 → 判为模板，跳过。
      为什么是 3：实测正常对话里同一句话跨 3 个会话重复的概率极低
        （人不会对三个人说一字不差的话），而模板句动辄 4~40 个会话。

      成本：一次本地 SQL（有 60s 缓存），相比它省掉的 30~50s 搜索可忽略。
      失败一律返回 False（**保守**：判不出就当它不是模板，保持旧行为）。
    """
    t = (text or "").strip()
    if not t or len(t) < 6:
        return False
    key = t[:40]
    now = time.time()
    hit = _TEMPLATE_CACHE.get(key)
    if hit and (now - hit[0]) < 60.0:
        return hit[1]
    ans = False
    try:
        row = db.con.execute(
            "SELECT COUNT(DISTINCT sessionId) FROM chatmsg WHERE text = ?",
            (t,)).fetchone()
        n = int(row[0] or 0) if row else 0
        ans = n >= min_sessions
        if ans:
            log.info("模板句检测：%r 出现在 %d 个会话 → 不当搜索关键词", t[:24], n)
    except Exception as e:
        log.debug("模板句检测失败（当作非模板）: %r", e)
        ans = False
    _TEMPLATE_CACHE[key] = (now, ans)
    if len(_TEMPLATE_CACHE) > 400:
        _TEMPLATE_CACHE.clear()
    return ans


def _norm(s):
    """去掉空白和常见标点，便于预览文本与库内原文比对。"""
    import re
    return re.sub(r"[\s，。！？、,.!?~～…\-—_:：;；\"'（）()\[\]【】]+", "", s or "")


def _swipe_once(actor, x1, y1, x2, y2, budget=8.0):
    """列表手势，**秒级超时兜底**。

    🔴 2026-11-04 事故（必须保留）：clear._pull_down 直接调 u2 的 swipe，
      u2 的 HTTP 默认超时 600s —— 08:20:50 那次下拉刷新挂了整整 10 分钟，
      整轮 cycle 停摆，那 10 分钟里她两条新消息一条没处理。
      所以任何手势都要压 client timeout + 线程 join 兜底。
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("手势取 u2 失败: %r", e)
        return False
    # 🔴 2026-11-04（duration 单位事故）：
    #   u2 的 duration 是**秒**（源码 steps = int(duration * 200)，每 step 约 5ms）。
    #   原来这里传 duration=500 → 等价 500 秒的手势，每次都被 join(10s) 放弃，
    #   被放弃的手势还在设备上继续跑，后续点击全排在它后面 —— 翻页等于没翻。
    #   另外 `d._client.timeout` 在 u2 3.7.1 里根本不存在（空操作），已删。
    box = {"ok": False, "err": None}

    # 🔴🔴 2026-11-08（A2 守卫漏洞修复）：这里**绕过 Hand 直接调 u2**，
    #   原来没有 note_action() ⇒ 动作代数不变 ⇒ 滑完紧跟的非 force `actor.snap()`
    #   （find_row:972 / _scroll_top:882）会**复用滑动前那一帧** ⇒ 行指纹相同
    #   ⇒ 误判「列表已到底」⇒ 提前放弃翻屏、该回的人被跳过。
    #
    #   为什么这是**真实可触发**的（实测，非推测）：_swipe_once 滑完到调用方取帧
    #   只有 `duration 0.35 + time.sleep(0.7) = 1.05s`，**小于 Actor.FRAME_TTL 1.2s**，
    #   两道守卫（动作代数未变 / Activity 未变）全部放行。探针 `_test_a2_swipe.py`
    #   修复前 3/3 FAIL（dumps=1、设备已翻到第 2 屏却读回第 1 屏）。
    #   设备越"快"（u2 往返越短）越容易踩到：rtt<=0.15s 落在窗口内，>=0.20s 才安全。
    #
    #   放在**发起手势之前**：u2 的 swipe 不是原子的，中途异常也可能已经滚了屏；
    #   多作废一帧只多付一次 dump，漏作废则是定位错误（方向必须保守）。
    def _job():
        try:
            from core.device import note_action
            note_action()            # A2：裸 u2 手势，手工让帧缓存作废
            d.swipe(x1, y1, x2, y2, duration=0.35)   # 秒！0.35s ≈ 70 steps
            box["ok"] = True
        except Exception as e:      # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_job, name="lswipe", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("列表手势超时（>%.0fs），放弃本次", budget)
        return False
    if not box["ok"]:
        log.warning("列表手势失败: %r", box["err"])
        return False
    time.sleep(0.7)
    return True


def _swipe_list(actor, up=True):
    """会话列表翻一屏。up=True → 看更早的人（手指自下而上）。"""
    if up:
        return _swipe_once(actor, 450, 1100, 450, 400)
    return _swipe_once(actor, 450, 400, 450, 1100)


def first_dot_row(actor):
    """当前屏「第一个红点行」。

    2026-11-04（新消息必回）：末条是「[切]」「？？」这种 1~2 字/纯表情时，
    find_row 的四层文本匹配全落空（① 要 ≥2 字、③ 要 ≥4 字），而 kw_of 退回的
    是**我自己发的开场白模板**，搜它必然「未找到相关结果」—— 实测两条刚发来的
    消息就这样被罚了 3 小时冷却。
    刚发来的消息必然在列表顶部、且带红点 ⇒ 直接进第一个红点行。
    进错人不会串台：进会话后 `身份校验` 用 session 摘要对不上就 fail-closed 不发。
    """
    try:
        from eyes.chatlist import rows as _rows
        snap = actor.snap(force=True)
        for r in _rows(snap):
            if r.has_dot:
                return r
    except Exception as e:
        log.warning("取红点行失败: %r", e)
    return None


def _list_sig(snap):
    """当前屏的行指纹（判断「真的滑动了/到顶了」）。"""
    try:
        from eyes.chatlist import rows as _rows
        return tuple((r.blob or "")[:24] for r in _rows(snap))
    except Exception:
        return ()


def _scroll_top(actor, rounds=4):
    """回列表顶部（最多 rounds 次），否则下次进来从中间开始会漏上面的人。"""
    try:
        prev = _list_sig(actor.snap())
    except Exception:
        prev = ()
    for _ in range(max(1, rounds)):
        if not _swipe_list(actor, up=False):
            return False
        try:
            cur = _list_sig(actor.snap())
        except Exception:
            return False
        if cur and cur == prev:
            return True
        prev = cur
    return True


def find_row(actor, txt, kw=None, min_len=4, pages=None, nick=None, db=None, sid=None):
    """在**会话列表**里找这条消息所属的行（首屏 → 逐屏下翻）。

    用户 2026-11-02/03 反复强调：「明明这个人就在屏幕上 红点也有 为什么还要走搜索」
      —— 列表里看得见就直接点行，搜索是最后手段（一次要 11s）。

    🔴 2026-11-03 修（红点行优先 + 短消息不再直接放弃）：
      原来只拿「末条文本」匹配、且 <4 字直接 return None —— 末条是「哦/滚/对呀/
      看不懂」这种短消息时，屏幕上明明有她的红点行，却连试都不试就甩给搜索
      （实测 17:47~18:03 走搜索的 6 个候选末条全是短消息）。

    🔴 2026-11-04 修（**首屏命中率只有 14%**）：
      实测一轮 52 次处理里 20 次「搜索未找到」、13 次成功（25%）——根因是这个函数
      只看当前一屏（8~10 行），候选 60 个，86% 的会话「在列表里但不在第一屏」。
      现在逐屏下翻（默认 3 屏），每屏用行指纹确认「真的滑动了」，滑不动立刻停；
      全落空则回顶（否则下次从中间开始，上面的人永远找不到）。

    每屏的分层策略（命中即返回）：
      ① 红点行 + 末条短文本（≥2 字）—— 红点=有未读=待回对象，行数少、个个该回，
         允许用很短的文本定位，误命中风险低；
      ② 红点行 + kw（她历史长句）—— 预览若显示她那句长的，这里命中；
      ③ 全列表 + 末条长文本（≥4 字）—— 常规路径；
      ④ 全列表 + kw —— 短消息但无红点（老积压红点早消）时的最后文本尝试。
    """
    from eyes.chatlist import rows
    from eyes.page import detect

    snap = actor.snap()
    if detect(snap) != "chatlist":
        return None
    raw = _norm(txt)
    kwn = _norm(kw) if kw else ""
    # 库摘要（= 列表预览原文）。纯表情/语音/短消息靠它定位，不吃长度门槛。
    dkey = ""
    if db is not None and sid:
        try:
            _dg = db.session_digest(sid) or {}
            _dk = re.sub(r"\[[^\]]{1,6}\]", "", (_dg.get("text") or "")).strip()[:8]
            dkey = _norm(_dk) or ""
        except Exception:
            dkey = ""

    def _hit(c, r, mlen):
        if not c or len(c) < mlen:
            return False
        blob = _norm(r.blob)
        if not blob:
            return False
        if c[:12] and c[:12] in blob:
            return True
        for k in (c[:8], c[-8:]):
            if len(k) >= mlen and k in blob:
                return True
        return False

    def _scan(sn):
        """在**这一屏**里找，返回 (row, 日志文案) 或 (None, '')。

        🔴🔴 2026-11-10（必回 P0：短消息结构性命中率为 0）：
          原实现只靠 `_hit()` 匹配行 blob，而它要求 `len(c) >= mlen`
          （红点行 2 字 / 全列表 4 字）。末条是 '好' / '嗯' / '啥' / '[表情]'
          这类时**任何一层都不可能匹配**，于是：
            处理 '486483065'（末条 '好'，0h 前）→ 翻完 3 屏仍未命中 → 转搜索
          —— 她 3 分钟前刚发、就在列表第一屏的人，照样定位不到，白烧 40s 搜索。
          昵称是列表上**唯一稳定、不受消息内容影响**的信号，所以提到最前：
          屏上昵称唯一 → 直接用；有歧义（'。'这种撞名）→ 退回文本匹配。
          身份真伪仍由 `_session_matches()` fail-closed 兜底，不会串台。
        """
        ni = _norm(nick) if nick else ""
        if len(ni) >= 2:
            _cand = []
            for r in rows(sn):
                rn = _norm(r.nickname)
                if rn and (rn == ni or ni in rn or rn in ni):
                    _cand.append(r)
            if len(_cand) == 1:
                try:
                    return _cand[0], "列表昵称命中 y=%d %r" % (_cand[0].center[1], _cand[0].nickname)
                except Exception:
                    return _cand[0], "列表昵称命中 %r" % _cand[0].nickname
        all_rows = rows(sn)
        # 🔴🔴 2026-11-10（纯表情末条结构性命不中）：
        #   `_norm('[中午好]')` → '中午好'（3 字），而全列表层要求 mlen=4 →
        #   她末条是纯表情、又没有红点（58h 前的老会话必然如此）时，
        #   **任何一层都不可能命中**：
        #     处理 '500117554'（末条 '[中午好]'，58h 前）→ 翻完 3 屏仍未命中 → 烧 43s 搜索
        #   这里补一层「库摘要」匹配：列表预览文本 == 库里的 lastMsgText 原文，
        #   语义精确（与 clear._rows_for_lib 已在生产验证的口径一致），不吃 mlen 门槛。
        #   但短文本可能撞多行 → **只接受屏上唯一命中**，有歧义就退回原逻辑。
        if dkey:
            _hr = [r for r in all_rows if (r.blob or "") and dkey in _norm(r.blob)]
            if len(_hr) == 1:
                return _hr[0], "列表预览命中（库摘要 %r）" % dkey[:8]
        dotted = [r for r in all_rows if r.has_dot]
        for r in dotted:
            if _hit(raw, r, mlen=2):
                return r, "红点行命中（末条 %r）" % raw[:8]
        for r in dotted:
            if _hit(kwn, r, mlen=4):
                return r, "红点行命中（关键词 %r）" % kwn[:8]
        for r in all_rows:
            if _hit(raw, r, mlen=min_len):
                return r, "列表直接命中（全文）"
        for r in all_rows:
            if _hit(kwn, r, mlen=4):
                return r, "列表直接命中（关键词 %r）" % kwn[:8]
        return None, ""

    r, why = _scan(snap)
    if r is not None:
        log.info("%s %r", why, r.nickname)
        return r

    pages = FIND_PAGES if pages is None else int(pages)
    moved_total = 0

    # 🔴🔴 2026-11-10（必回 P0：方向性错误）：
    #   `_swipe_list(up=True)` 是把列表往**更老**的方向翻。而 handle_pending 处理完
    #   上一个候选后，列表已经停在中下部 —— 下一个候选如果比她更新，目标就在
    #   **上面**，继续向下翻等于朝反方向找，翻 3 屏必然落空。
    #   日志实证：22:53 清红点进「霜鸢Icy」时她的行在 y=469/622（屏幕中部），
    #   而 22:56 pendingq 找同一个人 → 翻完 3 屏未命中 → 白烧 43s 搜索。
    #   修法：先向上探一屏（只在确实能滚动时才做，避免已在顶部白烧 4s）。
    _up_sig = _list_sig(snap)
    try:
        if _swipe_list(actor, up=False):
            # 🔴🔴 2026-11-10（实测 P0：向上探屏后点错人）
            #   23:11:38 首次生效就出事了：
            #     `列表昵称命中 '一只羊'（向上 1 屏）'一只羊'` → 直接点列表行
            #     → `身份校验失败（进的是别的会话：清零 ['9669164683008498']，期望 9669164631844588）`
            #   根因：`_swipe_list` 返回后列表**还在惯性滚动**，立刻取树拿到的
            #   是滚动中途的坐标，等真正 click 时那一行已经移位 → 点到相邻会话。
            #   （fail-closed 挡住了错发，但这次白跑一趟 25s。）
            #   修法：等惯性停 + 强制取新帧，坐标才是点击那一刻的真实位置。
            time.sleep(0.8)
            _s_up = actor.snap(force=True)
            if detect(_s_up) == "chatlist":
                _up_sig2 = _list_sig(_s_up)
                if _up_sig2 and _up_sig2 != _up_sig:
                    r, why = _scan(_s_up)
                    if r is not None:
                        try:
                            log.info("%s（向上 1 屏 y=%d）%r", why, r.center[1], r.nickname)
                        except Exception:
                            log.info("%s（向上 1 屏）%r", why, r.nickname)
                        return r
                    snap = _s_up
                else:
                    log.debug("向上探屏无位移（已在顶部），继续原方向")
    except Exception as _e_up:
        log.debug("向上探屏失败（继续向下翻）: %r", _e_up)

    for attempt in (0, 1):
        prev_sig = _list_sig(snap)
        moved = 0
        hit_bottom = False
        for i in range(max(0, pages)):
            if not _swipe_list(actor, up=True):
                break
            moved += 1
            moved_total += 1
            try:
                snap = actor.snap()
            except Exception as e:
                log.warning("翻屏取屏失败: %r", e)
                hit_bottom = True
                break
            if detect(snap) != "chatlist":
                hit_bottom = True
                break
            cur_sig = _list_sig(snap)
            if not cur_sig or cur_sig == prev_sig:
                log.info("列表已到底（第 %d 屏无变化）", i + 1)
                hit_bottom = True
                break
            prev_sig = cur_sig
            r, why = _scan(snap)
            if r is not None:
                log.info("%s（第 %d 屏）%r", why, i + 2, r.nickname)
                return r
        if not hit_bottom or attempt == 1:
            break
        # 🔴 2026-11-04（现网 09:03 实测）：起点不在顶部时向下翻一屏就「到底」，
        #   而候选是**最老待回优先**（目标往往在列表更深处/更上面都有），
        #   直接放弃等于把这一轮废掉。到底 → 回顶再翻一遍（只重来一次）。
        log.info("翻屏到底且未命中 → 回列表顶部再翻一遍")
        if not _scroll_top(actor, rounds=min(6, max(2, pages + 2))):
            break
        try:
            snap = actor.snap()
        except Exception:
            break
        if detect(snap) != "chatlist":
            break

    if moved_total:
        log.info("翻完 %d 屏仍未命中（末条 %r / 关键词 %r）→ 转搜索",
                 moved_total, (txt or "")[:10], (kw or "")[:10])
        # 🔴 2026-11-04（吞吐）：这里原来还 _scroll_top 最多 4 次 ≈ 24s/人。
        #   而下一轮开头本来就会回顶一次 ⇒ 纯浪费。留在原位，下一轮统一回顶。
    return None


def handle_pending(actor, dev, db, max_n=MAX_N, dry_run=False, budget_s=60.0):
    """处理已读未回。返回 dict(sent, tried, skipped, results, aborted)。"""
    # 🔴 2026-11-08：新增 "aborted" —— 区分「正常收工」和「设备级故障中止」。
    #   "" = 正常结束；"not_chatlist" = 连续多次回不到 chatlist（见 NOT_CHATLIST_MAX）。
    #   daemon.py 会消费它打一条 warning，方便在日志里一眼分辨这两件事。
    out = {"sent": 0, "tried": 0, "skipped": 0, "results": [], "aborted": ""}
    # 🔴 2026-11-08：熔断计数按**轮**重置（lead 口径：「同一轮连续 N 次」）。
    #   _NOT_CHATLIST_STREAK 是模块级（跨轮存活），这里每轮开头清零，
    #   保证「连续 3 次」判定的时间窗不跨轮 —— 上一轮 2 次 + 本轮 1 次
    #   不该凑成 3 次误判设备故障。轮内成功回一次也会清零（见主循环）。
    _NOT_CHATLIST_STREAK[0] = 0
    # 语音 sid 集合按轮重置（只服务本轮候选，见 _VOICE_SIDS 注释）。
    _VOICE_SIDS.clear()
    # 🔴 2026-11-08 12:56：把 device 引用挂上，供 _device_live_uids 做「设备存活校验」。
    #   candidates() 只拿到 db，拿不到 dev；这里是它唯一能拿到 dev 的入口。
    _DEV_REF["dev"] = dev
    # 🔴 2026-11-03（用户放行·积压降级）：一次多取几个候选，用数量判断积压。
    #    积压 >=10 时：只走列表直达（跳过 11~15s/次的搜索）、单轮最多回 2 条、
    #    预算放宽到 130s。否则高峰期每轮 1 条、90s 一轮，积压只会越滚越大。
    cands = candidates(db, max(max_n, CAND_SCAN))
    backlog = len(cands)
    # 🔴 2026-11-03（用户口径）：积压「超过 5 条」就进入降级（清红点优先、少搜索）。
    degraded = backlog > 5
    # 🔴 2026-11-04（P1 吞吐）：积压分两档。原来降级后 max_n = min(5, 6) = **5** 条，
    #   而积压长期 40~60 个、单轮 200s → 追不上新增（实测 52 次处理里 7 次是
    #   「预算用尽」散的场）。>=30 时放宽到 10 条 / 300s。
    heavy = backlog >= 30
    if degraded:
        # 🔴 2026-11-03 提高吞吐：原来降级到 2 条/轮，而积压 54 个、
        #   一轮 90~240s → 每小时只回 15~20 条，追不上新增，越堆越多。
        #   现在 6 条/轮 + 200s 预算（ROUND_BUDGET 600s 仍兜得住）。
        max_n = max(max_n, 10 if heavy else 6)
        budget_s = max(budget_s, 300.0 if heavy else 200.0)
        # 🔴 2026-11-03 修（回归）：原来降级会「跳过搜索」，但列表里看不见的会话
        #    必须靠搜索才能进 —— 一旦积压 ≥10 就永远跳过，候选人永远回不到，
        #    积压永远 ≥10，形成死锁（实测 uid=*** 15:07 的消息被空放两次）。
        #    现在降级**只降条数和预算，不砍搜索**。
        # 🔴 2026-11-03 二次修：候选已改为**最老待回优先**（见 candidates），
        #    这本身就是最公平的排队方式 —— 处理完一个台账就跳过它，自然往后走。
        #    原来的 _ROT 轮转会把「最老优先」打乱，已去掉。
        log.warning("已读未回积压 %d 个 → 降级：单轮最多 %d 条、预算 %.0fs（搜索保留，最老优先）",
                    backlog, max_n, budget_s)
    # 🔴 2026-11-03：不再把候选先截到 max_n —— 「重新开场」要按轮控名额。
    #   先切片的话，队首全是老会话时这一轮就只做老会话，刚发来消息的活人继续等。
    #   现在扫完整候选表，靠 restarts_done 计数放行（见循环内）。
    if not cands:
        log.info("已读未回：没有候选")
        return out

    # 🔴 2026-11-04：find_row 从**当前屏**往下翻，起点若停在列表中间，
    #   上面的人这一轮全都翻不到（09:03 实测「第 1 屏无变化」）。
    #   每轮进列表前回顶一次（一次性 ~2-6s），比每个候选各自回顶便宜得多。
    if FIND_PAGES > 0:
        try:
            from brain import nav as _nav
            _s0, _p0 = _nav.to_chatlist(actor)
            if _p0 == "chatlist":
                _scroll_top(actor, rounds=6)
        except Exception as _e:
            log.warning("轮首回列表顶部失败（继续）: %r", _e)

    log.info("已读未回：%d 个候选", len(cands))
    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            log.warning("本小时发送已达上限 → 本轮不做已读未回")
            return out
    except Exception:
        pass
    t_budget = time.monotonic()
    restarts_done = 0
    # 进循环前清一次库变化信号：这一轮前面（清红点/回复自己写的库）可能还挂着 dirty，
    # 不清掉的话第一个人就会被自己刚写的那笔拦下（wake 那边踩过同样的坑）。
    try:
        from data import watch as _W0
        _W0.consume()
    except Exception:
        pass
    for cand in cands:
        sid, to_uid, txt, her_ts = cand
        # ⚡ 2026-11-04（用户口径：新消息不能被积压挤住）：
        #   实测 09:15:42 她发 'hi '，09:17:46~09:23:07 一直在处理 4~144h 的老候选，
        #   09:24:18 才回出去 = **延迟 8.6 分钟**。
        #   这里一有库变化信号就收工，把屏幕让给下一轮的开头（清红点 → 快路径）。
        try:
            from data import watch as _W
            if _W.urgent():
                log.info("⚡ 积压处理途中检测到新消息 → 中止本轮积压，优先回去处理新消息")
                _W.consume()
                break
        except Exception:
            pass
        # 🔔 奇遇铃抢占一切（用户 2026-11-09 定链：铃 > 新消息 > 红点 > 已读未回）：
        #   已读未回处理途中铃弹出来 → 就地处理完再收工（对齐 clear.py 既有做法）。
        if not dry_run:
            try:
                from brain import bell as _BELL
                _snap_r = actor.snap(force=True)
                if _BELL.is_bell(_snap_r, dev=dev):
                    log.info("🔔 已读未回途中来了奇遇铃 → 就地处理，中断本轮")
                    _ok, _why = _BELL.handle(actor, dev, dry_run=dry_run)
                    log.info("🔔 铃处理 ok=%s %s", _ok, _why)
                    break
                # 🔴 2026-11-10 §111（用户原话）：「清理已读未回的途中 发完消息回到聊天页
                #   如果检测到红点 那就优先处理红点」。
                #   复用上面这张 snap（本来就要为铃检查拍一张），零额外 OCR 成本。
                #   只在「本轮已回过人」时让位：一条没回就中断会空转，交给下一轮红点段。
                try:
                    from brain import clear as _CL
                    _bd_r = _CL.badge_chat(_snap_r)
                except Exception:
                    _bd_r = 0
                if _bd_r and int(out.get("sent", 0) or 0) > 0:
                    log.info("🔴 已读未回途中聊天角标=%s → 中止本轮，优先回去清红点", _bd_r)
                    break
            except Exception as _e:
                log.debug("轮内铃检查异常（继续已读未回）: %r", _e)
        _t_cand = time.monotonic()
        if out["sent"] >= max_n:
            break
        # 用户 2026-11-02：一分钟内没进展就进下一步；已经回过人则到预算就收
        used = time.monotonic() - t_budget
        if used > budget_s and out["sent"] > 0:
            log.info("已读未回已用 %.0fs（>%.0fs 预算）→ 先停，剩下的下一轮", used, budget_s)
            break
        if used > budget_s * 2:
            log.warning("已读未回 %.0fs 一条都没回成 → 收工（异常）", used)
            break
        # 🔴 2026-11-03（用户定 B 方案）：断太久 → 不接旧话，改重新开场。
        #   名额按轮控：老会话（几十个）不能把这一轮的额度全吃掉。
        age_h = (time.time() * 1000.0 - float(her_ts or 0)) / 3600000.0
        # 🔴 2026-11-10 §104 C3：重新开场由状态机判（age>=24h 且本回合 0 条），
        #    不能只看 age —— 否则 24~72h 一律重开、已发过的人也重复开场。
        restart = bool(RESTART_H > 0 and age_h >= RESTART_H)
        try:
            from brain import sendgate as _SG4
            from brain import verdict as _VD4
            _rv = _SG4.state_of(str(sid), her_ts_ms=float(her_ts or 0), has_human=True)
            restart = (_rv.state == _VD4.PENDING_RESTART)
        except Exception as _e_rv:
            log.debug("重启状态机异常（沿用 age 判据）: %r", _e_rv)
        if restart and restarts_done >= RESTART_PER_ROUND:
            log.info("跳过老会话 uid=%s（她末条 %.0fh 前）：本轮重新开场名额 %d 已用完，先留给新消息",
                     to_uid, age_h, RESTART_PER_ROUND)
            continue
        out["tried"] += 1
        kw = kw_of(db, sid, txt, skip_text=str(sid) in _VOICE_SIDS)
        _used_nick = None      # 搜索若走了昵称，进会话后用它做身份校验
        log.info("── 处理 %r（末条 %r，%.0fh 前%s，关键词 %r）", to_uid, txt[:14], age_h,
                 "·重新开场" if restart else "", kw[:16])

        # 从列表进：能直接看见就直接点行，看不见才去搜索
        from brain import nav
        # 🔴 2026-11-08（P0「瞎操作」根因修复 · 前置闸）：
        #   改前：`if pg != "chatlist": break` —— 回不到列表就作废整轮（见 NOT_CHATLIST_MAX 注释）。
        #   为什么必须在**进候选前**断言页面而不是失败后补救：Lead 实测 20 次连续 dump 有
        #   **13 次（65%）** `main_tab_msg` / `recycler_view` / `c_ct_chat_fragment_search`
        #   三个关键 res 全部缺失（那些瞬间设备根本不在 chatlist，daemon 自己在操作、
        #   停在 chat 页或转场中）。即「底栏不存在」是连续操作期间的**常态**，不是偶发。
        #   页面不对时，后面 double_tap_tab 必然「未命中」、open_search 必然「找不到搜索入口」
        #   （实测 72 次未命中里 71 次下一行就是「当前屏没有搜索入口」）。
        snap, pg = nav.to_chatlist(actor)
        if pg != "chatlist":
            # nav 的 unknown 恢复梯子常爬不上去（nav.py 内 stuck 会被各分支清零），
            # 这里给一次「am start 首页 + 再取树」的硬复位，仍不行才计入连续失败。
            log.warning("回不到列表（pg=%s）→ am start 首页硬复位后重试一次", pg)
            nav.goto_main(dev)
            snap, pg = nav.to_chatlist(actor)
        if pg != "chatlist":
            # 设备级故障熔断：连续多次复位无效 → 整轮收工，别再逐个排队撞墙。
            _NOT_CHATLIST_STREAK[0] += 1
            log.warning("硬复位后仍回不到列表（pg=%s），连续第 %d 次",
                        pg, _NOT_CHATLIST_STREAK[0])
            if _NOT_CHATLIST_STREAK[0] >= NOT_CHATLIST_MAX:
                log.warning("连续 %d 次回不到 chatlist → 判定设备级故障，本轮提前收工",
                            _NOT_CHATLIST_STREAK[0])
                out["aborted"] = "not_chatlist"
                break
            mark_skip(sid, txt, "not_chatlist", hours=0.034)
            out["skipped"] += 1
            continue          # ← 注意：continue 不是 break，只跳过这个人
        _NOT_CHATLIST_STREAK[0] = 0    # 成功回到 chatlist → 页面恢复了，清零

        # 🔴 2026-11-10（必回 P0）：把昵称一起交给 find_row —— 她的末条是单字/表情时，
        #   文本匹配结构性失效，昵称才是唯一稳定的定位信号。
        try:
            _nick_try = nick_of(db, sid, to_uid)
        except Exception as _e_nk:
            log.debug("取昵称失败（退回纯文本定位）: %r", _e_nk)
            _nick_try = None
        # 🔴 2026-11-10（必回）：重新开场的会话都是几十小时前的老会话，列表里早被顶到
        #   十几屏之外 —— 默认 3 屏根本够不到。实测一个 58h 前的会话：
        #   翻 3 屏落空 → 走搜索 34s → 搜索结果全是别人 → 身份校验连续 4 次失败 →
        #   长冷却 2h → 这条**永远回不了**。深翻 6 屏只要 ~12s，比搜索快一倍多，
        #   而且不会触发 clear_text 把 App 顶回桌面。
        _pg_n = 6 if restart else None
        row = find_row(actor, txt, kw=kw, nick=_nick_try, db=db, sid=sid, pages=_pg_n)
        if row is None and age_h * 60.0 <= 30.0:
            # 🔴 2026-11-08（P0 修「身份校验失败 261 次」的放大器）：
            #   改前：无条件走 first_dot_row —— 它是**设计上的「先点进去再验身份」**
            #   （见 first_dot_row docstring：「进错人不会串台：进会话后身份校验用
            #   session 摘要对不上就 fail-closed 不发」），所以它点进去的那一刻
            #   本来就不知道点的是谁，进错必然 fail-closed。
            #   日志实证：`新消息文本定位不到（末条 …）→ 直接进第一个红点行` 13 次，
            #   每一次都会把该 sid 的 _idfail 计数推高 1；而计数又被
            #   `_prev_n = _IDFAIL[...]["n"]` 直接当 skip 用（见下面 enter_first 调用），
            #   于是 skip 被推到第 2/3/4 条搜索结果 —— 越跳越错，恶性循环。
            #   现在：只有该 sid **本轮还没 idfail 过**时才启用这个兜底，
            #   已经失败过的交给正常搜索路径（按 skip 依次试结果），不再靠盲点红点行加码。
            _idn = int((_IDFAIL.get(_idfail_key(sid, txt)) or {}).get("n", 0))
            if _idn == 0:
                row = first_dot_row(actor)
                if row is not None:
                    log.info("新消息文本定位不到（末条 %r）→ 直接进第一个红点行 %r",
                             txt[:10], row.nickname)
            else:
                log.info("该会话已 idfail %d 次 → 不再走红点兜底（避免盲点加码，改走搜索）",
                         _idn)
        if row is None:
            # 🔴 2026-11-03（用户口径：「堆积>5 先清当前屏红点，清完双击聊天继续清，
            #    尽量不走搜索页」）：双击聊天 tab 会跳到下一个有红点的锚点，
            #    目标会话若还有未读红点就能直达，比搜索（11~15s、短消息还易进错人）快且准。
            #    只试一次、settle 短，推不动立刻转搜索，绝不空等。
            try:
                _snap2, _pg2 = actor.double_tap_tab("聊天", expect="chatlist", settle=1.0)
                if _pg2 == "chatlist":
                    # 只扫当前屏（pages=0）：双击跳过去的是「某个有红点的行」，
                    # 不是列表顶部；再翻 3 屏等于把 24s 白烧一遍（09:13 实测翻了两轮）。
                    row = find_row(actor, txt, kw=kw, pages=0)
            except Exception as _e:
                log.warning("双击找行异常: %r", _e)
        if row is not None:
            log.info("直接点列表行 %r（不走搜索）", row.nickname)
            remember_nick(sid, row.nickname)
            mark_before_enter(actor)      # 未读快照（进会话后用它做 sid 差分校验）
            actor.hand.tap_node(row.node, settle=1.8)
            s2, pg2 = actor.wait_page(("chat",), timeout=6)
            # 🔴 2026-11-03（用户现场口径）：点行**有时只给选中反馈、不跳转**，
            #    「继续再点一次就进去了，但不是每次都这样」。
            #    搜索结果行走 enter_first 的循环，这里补同样的：重新看屏 → 重新定位 → 再点。
            for _try in range(2, 4):
                if pg2 == "chat":
                    break
                row2 = find_row(actor, txt, kw=kw, nick=_nick_try, db=db, sid=sid, pages=_pg_n)
                if row2 is None:
                    log.info("列表里已找不到 %r（可能被顶下去）→ 改走搜索", txt[:12])
                    break
                log.info("第 %d 次点列表行后仍是 %s → 重新定位再点", _try, pg2)
                actor.hand.tap_node(row2.node, settle=1.8)
                s2, pg2 = actor.wait_page(("chat",), timeout=5)
        else:
            # 🔴 2026-11-04（A批提速·短消息快弃）：短消息/纯表情 find_row 4 层落空后，
            #   走搜索大概率「未找到/歧义」（实测 18:41 一轮 9 候选只回成 1 个，8 个
            #   失败白烧 ~100s）。这类直接短冷却，不浪费 11~15s 搜索。
            #   排除：问句（「在吗」得回）、重新开场（断太久要主动联系）。
            _plain = re.sub(r"\[[^\]]{1,6}\]", "", txt or "").strip()
            _is_q = bool(re.search(r"[？?吗呢嘛]", _plain))
            if len(_plain) < 4 and not _is_q and not restart:
                # 🔴 2026-11-04（必回·短消息不再直接放弃）：原来 find_row 只看首屏，
                #   短消息几乎必然落空 → 记 short_msg 0.5h → 到期后列表位置没变、
                #   还是找不到 → 这句**永远回不了**（实测 08:42:54 uid=***
                #   末条「听不懂」，至今 0 回复）。
                #   现在 find_row 已翻 3 屏，命中率大幅提高；仍落空才走搜索，
                #   搜索用 kw（她的历史长句）而非短文本，notfound 按 notfound 冷却。
                _n2 = _norm(_nick_try or "")
                if len(_n2) < 2:
                    # 🔴 2026-11-10（速度）：原来这里无条件「仍尝试搜索一次」，
                    #   而没有昵称可搜时 open_search 要 40~50s 找入口，再用单字
                    #   去搜必然 notfound —— 纯白烧。日志实证 22:57~22:58 连续两人
                    #   这样烧掉 90s，一条没回成。现在直接短冷却，留给下一轮。
                    log.info("末条 %r 短消息且无可用昵称 → 放弃本轮（省 40s 搜索）uid=%s",
                             txt[:12], to_uid)
                    mark_skip(sid, txt, "short_nocue", hours=SHORT_RETRY_H)
                    out["skipped"] += 1
                    continue
                log.info("末条 %r 短消息，昵称 %r 可用 → 走昵称搜索", txt[:12], (_nick_try or "")[:10])
            # 🔴 2026-11-04（吞吐）：单个人已经耗掉 45s（翻屏 21s + 双击 + dump），
            #   再走搜索（6~30s）就把整轮吃光。记 6 分钟冷却，下一轮再来。
            if time.monotonic() - _t_cand > 45.0:
                log.info("这个人已耗时 %.0fs → 本轮放过，6 分钟后再试 uid=%s",
                         time.monotonic() - _t_cand, to_uid)
                mark_skip(sid, txt, "slow", hours=0.1)
                out["skipped"] += 1
                continue
            # 🔴 2026-11-10 §113（用户口径）：搜索三级 —— 昵称 → 独一无二内容 → 放弃
            #   先在**开搜索页之前**算计划：open_search 走慢路径要 40~50s，
            #   没有可搜线索就该直接跳过，不能先把这 40s 烧掉再放弃。
            _plan = _search_plan(db, sid, to_uid, kw)
            if not _plan:
                log.info("昵称和独一无二内容都拿不到 → 放弃本轮 uid=%s（等她发新消息再试）",
                         to_uid)
                mark_skip(sid, txt, "nocue", hours=NO_CUE_H)
                out["skipped"] += 1
                continue
            if not S.open_search(actor):
                out["skipped"] += 1
                continue
            _got = 0
            for _label, _word in _plan:
                log.info("搜索[%s] %r", _label, _word[:16])
                _got = S.search(actor, dev, _word)
                if _got:
                    if _label == "昵称":
                        _used_nick = _word
                        remember_nick(sid, _word)
                    break
                # 熔断/超时都是**通道**问题，跟关键词无关 → 换第二个词也救不回来。
                # 🔴 2026-11-10（速度）：原来只挡 breaker，timeout 还要再烧一个词
                #   （实测 22:56:17 搜索[昵称] 超时 30s → 22:56:49 又搜内容 7s = 43s/人）。
                if getattr(S, "LAST_REASON", "") in ("breaker", "timeout"):
                    break
            if not _got:
                # 🔴🔴 2026-11-08 13:1x（`breaker` 必须单独一支，否则比原 bug 更糟）
                #
                #   `search.py` 现在熔断早退会记 `LAST_REASON="breaker"`（以前误记 timeout）。
                #   但如果这里只判 timeout、其余全落进 else，`breaker` 就会被当成
                #   **notfound → 罚 3 小时冷却** —— 比原来「误记超时罚 10 分钟」严重得多：
                #   熔断是**全局通道**状态，跟这个人的关键词毫无关系，
                #   拿它去惩罚单个会话等于「因为今天下雨，所以这个人 3 小时不许回」。
                #   实测代价：265 次熔断早退，若各罚 3h，涉及的人整段时间全灭。
                #
                #   ⇒ breaker 单独处理：不记任何人的台账（通道问题不归人），
                #     只把本轮这个候选放过，下一轮熔断结束后自然会重试。
                _why = getattr(S, "LAST_REASON", "")
                if _why == "breaker":
                    log.info("搜索通道熔断中（不是这个人的问题）→ 不记台账、下轮再试 uid=%s", to_uid)
                    S.leave(actor)
                    out["skipped"] += 1
                    continue
                if _why == "timeout":
                    # 超时 ≠ 搜不到：罚 10 分钟再试，绝不 12 小时拉黑（那等于不回她）
                    log.info("搜索超时（未判定未找到），10 分钟后再试")
                    mark_skip(sid, txt, "timeout", hours=TIMEOUT_RETRY_H)
                else:
                    # 🔴 2026-11-09 R3（用户拍板「搜索不到就不搜了啊 等闲下来的时候搜」）
                    #   旧：notfound 罚 3 小时 + 新消息 10 分钟。表现为「消息进来很久没人回」，
                    #   实测 21:08 仍有会话剩 89 分钟冷冻结。冻结惩罚本就不该用在这个人身上。
                    #   新：本轮不搜 → 5 分钟后（闲着时）自然重试；30 分钟内撞墙 ≥3 次才升级 30 分钟。
                    _nf = _nf_hits(sid)
                    if _nf >= NOTFOUND_STORM_N:
                        log.warning("搜索无结果累计 %d 次/30min → 升级 %.0f 分钟冷却（防白烧）sid=%s",
                                    _nf, NOTFOUND_STORM_H * 60, sid)
                        mark_skip(sid, txt, "notfound_storm", hours=NOTFOUND_STORM_H)
                    else:
                        log.info("搜索无结果（第 %d 次/30min）→ %.0f 分钟后重试，不冻结 3 小时 sid=%s",
                                 _nf, NOTFOUND_COOL_H * 60, sid)
                        mark_skip(sid, txt, "notfound", hours=NOTFOUND_COOL_H)
                S.leave(actor)
                out["skipped"] += 1
                continue
            # 🔴 2026-11-04（必回闭环）：按该会话**历史失败次数**依次点第 2、3 条搜索结果。
            #   原来 enter_first 永远点第一条 → 目标人不在第一条时死循环失败
            #   （实测「那不知道」「[狗子]」各失败 8 次、永远回不了）。
            try:
                _prev_n = int((_IDFAIL.get(_idfail_key(sid, txt)) or {}).get("n", 0))
            except Exception:
                _prev_n = 0
            mark_before_enter(actor)      # 未读快照（同上）
            s2, pg2 = S.enter_first(actor, skip=_prev_n)

        if pg2 != "chat":
            log.info("没进会话（%s），记台账后跳过", pg2)
            mark_skip(sid, txt, "enter_fail", hours=ENTER_RETRY_H)
            if row is None:
                S.leave(actor)
            out["skipped"] += 1
            continue

        # 用户 2026-11-02：搜索/跳转都不要点太快，页面还没加载完就操作会失败
        time.sleep(1.5)

        # 🔴 2026-11-03 修复 P1（防错发）：列表/搜索定位可能进错会话，
        #    发之前先校验当前会话身份 == 候选 sid，不确认就不发（发错人 = 高危）。
        #    🔴 2026-11-03 三修（止血·用户拍板）：原来的「连续 2 次失败后降级发
        #    通用安全句」= 在「无法确认这是谁」的时刻发任何话都是赌，实测串台
        #    （19:21 把「在呢，刚看到你说的」发给了不相干的『搞笑摆烂结合』），
        #    且固定安全句几十个会话都有 → 反污染 kw_of 关键词 → 定位错人。
        #    改为 fail-closed：身份不明一律不发送，记台账短冷却下轮重试。
        _nick_hint = getattr(row, "nickname", None) if row is not None else None
        if _nick_hint is None:
            _nick_hint = _used_nick      # 走昵称搜进来的，用同一个昵称验标题
        if not _session_matches(actor, db, sid, nick=_nick_hint):
            # 计数**落盘**（重启不清零）—— 见 IDFAIL_FILE 注释。
            _n = _idfail_bump(sid, txt)
            if _n >= IDFAIL_MAX_TRIES:
                # 🔴 2026-11-04（必回闭环·熔断）：搜索结果已经逐条试过（第 2/3 条都点过）
                #   还是认不出来 → 说明这个 sid 在当前界面上确实定位不到（会话被顶下去/
                #   搜索结果只有别的人）。继续 2 分钟一次重试只是白烧 15~20s/次，
                #   且**永远回不了**。改长冷却，等她发新消息（末条变了）自动重新给机会。
                log.warning("身份校验连续 %d 次失败（搜索结果都试过）→ 长冷却 %.1fh，"
                            "等她发新消息再试", _n, IDFAIL_GIVEUP_H)
                mark_skip(sid, txt, "id_mismatch_giveup", hours=IDFAIL_GIVEUP_H)
                # 计数归零：2h 后重试时从第 1 条结果重新试一轮（会话顺序/新消息会变），
                # 否则 skip 会一直停在第 4、5 条，永远试不到正确的那条。
                _idfail_clear(sid, txt)
            else:
                log.warning("身份校验失败（第 %d 次，消息 %r）→ 不发送，防串台"
                            "（fail-closed），下次试第 %d 条搜索结果",
                            _n, txt[:12], _n + 1)
                # 2min 冷却：每次重试都要重搜 11s + 进会话，太短白烧；太长她等太久。
                mark_skip(sid, txt, "id_mismatch", hours=0.034)
            actor.hand.back(settle=1.5)
            if row is None:
                S.leave(actor)
            out["skipped"] += 1
            continue
        _idfail_clear(sid, txt)

        # 🔴 2026-11-10 §104：发送闸 —— 先问「这个会话现在能发几条」，再按额度出话。
        #    §6.6-2：ADAPT_CAP=2 一轮两句就会把 24h 的 2 条额度用光，
        #    所以 n_cand 必须被闸裁过；发送成功后按真实条数记账（不等库 pull）。
        _gate_n = 0
        try:
            from brain import sendgate as _SG5
            _gate = _SG5.allow(str(sid), 99, her_ts_ms=float(her_ts or 0), has_human=True)
            if not _gate.ok:
                log.info("跟进阶梯拦截 sid=%s state=%s（%s）→ 本轮不回",
                         sid, _gate.state, _gate.reason)
                out["skipped"] += 1
                time.sleep(2.0)
                actor.hand.back(settle=1.5)
                if row is None:
                    S.leave(actor)
                continue
            _gate_n = _gate.n
        except Exception as _e_gate:
            log.debug("发送闸异常（降级按原行为）: %r", _e_gate)
            _gate_n = 0

        # 出话（用库里的真实历史）
        if restart:
            # 🔴 用户 2026-11-03 定 B 方案：她那条已经 %.0fh 前，**不当接话处理**。
            #   不喂 hist（旧对话）、不喂她那条（喂了模型就会去答「嗯」），
            #   由引擎「重新开场」模式出一句新由头，只发一条。
            log.info("她末条已 %.0fh（>%.0fh）→ 不接旧话，走重新开场", age_h, RESTART_H)
            hist = []
            lines = R.generate(sid, "", hist=[], n_cand=1, restart_h=age_h)
        else:
            msgs = db.messages(sid, limit=12)
            hist = R.build_hist(msgs, db.uid)
            # 用户 2026-11-02：她这一句可能是几句 → 先取她连发；回复也可以多条。
            from brain.flow import her_burst
            burst = her_burst(db, sid, db.uid)
            if not burst:
                burst = [txt]
            feed = R.merge_burst(burst)
            # 同上：她的末条可能只在 session 摘要里，补进历史末尾
            hist = R.hist_with_her(hist, feed)
            # 条数按她最后一条算（合并后总长会撑大 target_n，见 flow.py 同处注释）
            n = R.target_n([burst[-1]] if burst else [txt], hist)
            if _gate_n:
                n = max(1, min(n, _gate_n))
            lines = R.generate(sid, feed, hist=hist, n_cand=n)
        if not lines:
            # 🔴 必回铁律：已读未回同样是「她说过话」，引擎给不出话也必须回一句，
            #    不能因为生成失败就静默跳过（flow.py 里同样处理）
            from brain.flow import fallback_line
            lines = [fallback_line()]
            log.warning("出话失败 → 用兜底话术 %r", lines[0])
        if _gate_n and len(lines) > _gate_n:
            lines = lines[:_gate_n]
            log.info("发送闸裁剪：本轮最多发 %d 条（额度）", _gate_n)

        if dry_run:
            log.info("[dry] 会回 %d 条: %r", len(lines), lines)
        else:
            # 🔴 2026-11-04（提速）：这里原来再 dump 一次确认在 chat 页 —— 但
            #   `_session_matches()` 刚用「未读清零差分 / 会话内气泡」确认过当前
            #   会话身份（通过的瞬间必然在 chat 页），之后只有库读写与模型调用，
            #   没有任何 UI 动作 → 这次 dump(3~4s) 纯重复。
            #   安全网仍在：真不在 chat 页时 type_and_verify 找不到输入框会直接失败，
            #   不会把话灌进搜索框。
            inp = Input(dev)
            sent_n = 0
            for i, r in enumerate(lines):
                if i:
                    time.sleep(1.6)
                ok, got = inp.type_and_verify(r, actor)
                if not ok:
                    log.warning("第%d条灌字失败（%r）", i + 1, got)
                    inp.clear()
                    break
                # settle 1.2(×slow_factor 2.5=3s) -> 0.25：紧跟的 sent_ok 里
                # sleep(0.7)+dump(3s) 已经在等，重复等待纯浪费。
                if not inp.tap_send(actor, settle=0.25):
                    log.warning("第%d条找不到发送按钮", i + 1)
                    inp.clear()
                    break
                # 🔴 2026-11-04 修（闭环）：**先做三态确认，再记账**。
                #   旧版「tap_send 成功就立即记账」把「输入框还有残留文本 = 明确没发出去」
                #   也记成已回 → 永不重试 = 永久漏回（违背必回铁律）。
                #   现在区分：residual=确实没发 → 不记账、下轮重试；
                #             ok/unknown=确认清空或读不到转场帧 → 按已发记账（防重复发送）。
                _ok = inp.sent_ok(actor, r, timeout=4)
                _why = getattr(inp, "last_reason", "") or ""
                if (not _ok) and _why == "residual":
                    log.warning("第%d条确认未发出（输入框仍有内容）→ 不记账，下轮重试", i + 1)
                    inp.clear()
                    break
                _mark_replied(to_uid, sid=sid, text=txt)
                sent_n += 1
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
                if not _ok:
                    log.warning("第%d条发送确认读不到输入框（按已发出记账，不再重发）", i + 1)
                log.info("✓ 已回(%d/%d) uid=%s: %r", i + 1, len(lines), to_uid, r)

            if sent_n:
                # 🔴 §104：按**实际发出条数**落账，不等实时库 pull（5 分钟延迟会重复发）。
                try:
                    from brain import sendgate as _SG6
                    _SG6.note_sent(str(sid), sent_n)
                except Exception as _e_ns:
                    log.warning("跟进台账记账失败 sid=%s: %r", sid, _e_ns)
                out["sent"] += 1
                if restart:
                    restarts_done += 1
                _idfail_clear(sid, txt)     # 已回，清掉身份校验失败计数
                # 📝 2026-11-03（用户口径）：发出去的消息**不写本地库/L2**，等实时库
                #   （im_data.db 的 pull 同步）自然出现。原来主动 append_l2_once 的副作用：
                #   固定安全句/我的开场白写进 L2 后被 kw_of 当成关键词 → 几十个会话都有
                #   → 定位错人 → 串台。防重复已由 `_mark_replied` 台账 + 库末条 sender
                #   双重覆盖（见 tap_send 后立即记账），不再需要 L2 这份本地缓存。
                backed = CP.ensure_profile(actor, sid, db)
                if backed:
                    log.info("  已补建个人主页档案")
            else:
                out["skipped"] += 1

        # 发送后静默 2s 再退出（用户：页面没加载完就点会出错）
        time.sleep(2.0)
        actor.hand.back(settle=1.5)
        if row is None:          # 只有走搜索进来的才需要退搜索层
            S.leave(actor)
        time.sleep(0.6)

    log.info("已读未回结束：回 %d 条 / 试 %d / 跳过 %d",
             out["sent"], out["tried"], out["skipped"])
    return out
