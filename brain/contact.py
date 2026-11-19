# -*- coding: utf-8 -*-
"""联系方式轮：她开口要 → 一次性 3 条额度（3-4-4 拆发），不占 24h 正常额度。

背景（2026-11-20 用户授权 B 方案，承接 §48 遗留③④）：
  `brain/engine/rules.py` 教模型把 MY_CONTACT 拆三条发（[0:3] / [3:7] / [7:]），
  但 `brain/verdict.py` 的 `CAP_24H = 2` 只给一个会话 24h 两条额度 —— 第三条必被
  `pendingq.py` 的 `lines = lines[:_gate_n]` 裁掉；本回合已发过 1 条时更只剩 1 条，
  于是她看到的是**没说完的号码**。

  实证（2026-11-07）：
    21:03 她「后面呢？是你没说完的号码」
    22:03 她「你是在微信上说不出话么」
  —— 号码发到一半断了，之后再没接上。全库 1.2 万条消息里唯一一次接近交换联系方式。

本模块只做三件事：
  1. `is_ask()`    判断她这条是不是**明确在要**联系方式（保守：宁可漏判）
  2. `is_contact_lines()` 判断模型这次输出的几条是不是 MY_CONTACT 的分片
  3. `done()` / `mark_done()` 「一生一次」台账（JSON 原子写）

2026-11-20 用户授权 **C 方案（窄口子）**：在她**把话推到线下**的三类信号上
（主动提见面 / 让你过去 / 问你在哪），允许**主动**带一次号 —— 由 `is_open_door()` 判定。
其余场景仍是铁律。

**不动的一条铁律**（2026-10-30 用户定，v13 逐字保留）：
  · 除 C 的三类线下信号外，没人要 → 绝不主动发这个号，也不在任何话题里带出它
  · 更不主动开口要她的（不问平台、不暗示、不用代称绕弯子要）
"""
import json
import os
import re
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("brain.contact")

# 「一生一次」台账：sid -> 首次给出时间（秒）
_LEDGER = os.path.join(STATE, "contact_sent.json")
_KEEP_DAYS = 90.0

# ── 她「明确要」的信号 ────────────────────────────────────────────
# 2026-11-20：只放强词。像「我手机没电」「电话吵醒了」这种日常词不进表，
# 因为误判的代价是「多给 3 条额度」（无害），但漏判的代价是「她要了却发不出」
# （最贵的损失）。所以这里按「她要动作」而不是「平台名」来判。
_ASK_STRONG = (
    "号码", "手机号", "联系方式", "加你", "加我", "加个微信", "加微信",
    "给个微信", "留个号", "发我号", "你号多少", "微信多少", "qq号", "扣扣号",
    "vx号", "wx号", "你的vx", "你的wx", "发个号", "发个微信",
)
# 「电话」二字太泛（「被电话吵醒」），必须带「要/给/你的/多少」
_PHONE_ASK = re.compile(r"(?:要|给|留|发|你的|你的那个|多少).{0,4}电话|电话.{0,4}(?:多少|给我|发我)")

_PROMISE = ("我号", "我的号", "我给你", "发你", "记着", "记下", "存一下")

# ── 她「把话推到线下」的三类信号（2026-11-20 用户授权 C 方案·窄口子）──
# 只有这三类允许「主动」带号，且一生一次；其余场景仍绝不主动发。
# 判据原则：按**邀约动作**取词，不取泛词。误判代价 = 莫名其妙发号码（像骗子/像机器），
# 所以宁可漏判（漏判只是退回 B：等她要）。
_DOOR_MEET = (
    "见面", "见一面", "见个面", "见一下", "见个真的", "哪天见", "什么时候见",
    "想见你", "约一下", "约你", "约我", "出来玩", "出来见", "出来吃", "出来坐",
    "线下见", "奔现",
)
_DOOR_COME = (
    "你过来", "过来找我", "过来吧", "过来玩", "过来坐", "来我这", "来我这儿",
    "来找我", "你来啊", "你来找我", "你过来嘛",
)
# 「过来」被这些复合词吃掉时不是邀约（熬过来/缓过来/醒过来/回过神来/挺过来）
_COME_NEG = ("熬过来", "缓过来", "醒过来", "回过神来", "挺过来", "翻过来", "改过来")
# 「见面」被这些否定吃掉（不想见/见不了/没法见）
_MEET_NEG = ("不想见", "见不了", "没法见", "不能见", "别见", "不要见", "不见面")
# 「你在哪」族：必须是她问你，才算出线下的门
_DOOR_WHERE = re.compile(r"你(?:人)?在(?:哪|哪儿|哪里|什么地方|啥地方)|你现在(?:在)?哪|你哪儿的")


def _now() -> float:
    return time.time()


def _load() -> dict:
    try:
        with open(_LEDGER, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("联系方式台账读盘异常（按空处理）: %r", e)
        return {}


def _save(d: dict) -> None:
    """原子写：tmp + os.replace（与 §46 唤醒台账同款）。"""
    try:
        os.makedirs(os.path.dirname(_LEDGER), exist_ok=True)
        tmp = _LEDGER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _LEDGER)
    except Exception as e:
        log.warning("联系方式台账写盘异常: %r", e)


def is_ask(text) -> bool:
    """她这条是不是明确在要联系方式。保守判定，宁漏不误。"""
    s = str(text or "").strip()
    if not s:
        return False
    low = s.lower()
    for w in _ASK_STRONG:
        if w in low:
            return True
    if _PHONE_ASK.search(s):
        return True
    return False


def is_open_door(text) -> bool:
    """她是不是把话推到了线下（主动提见面 / 让你过去 / 问你在哪）。

    2026-11-20 用户授权 C 方案（窄口子）：只有这三类信号才允许**主动**带一次号，
    且受「一生一次」台账约束。保守判定，宁漏不误 —— 见模块顶部说明。
    """
    s = str(text or "").strip()
    if not s:
        return False
    if not any(neg in s for neg in _MEET_NEG):
        for w in _DOOR_MEET:
            if w in s:
                return True
    if _DOOR_WHERE.search(s):
        return True
    for w in _DOOR_COME:
        if w in s:
            if any(neg in s for neg in _COME_NEG):
                continue
            return True
    return False


def is_contact_lines(lines) -> bool:
    """模型输出的几条是不是 MY_CONTACT 的分片（3-4-4 或其它拆法）。

    判据：把所有条里的数字按顺序拼起来，能够还原出 MY_CONTACT，
    且拼出来的数字总长不超过 15（防止把无关长数字串误认）。
    """
    try:
        from brain.engine import rules as R
        target = re.sub(r"\D", "", str(getattr(R, "MY_CONTACT", "") or ""))
    except Exception:
        return False
    if len(target) < 8:
        return False
    seq = "".join(re.sub(r"\D", "", str(x or "")) for x in (lines or []))
    if not seq or len(seq) > 15:
        return False
    return target in seq


def has_promise(text) -> bool:
    """本条是否已经有「给你/记着」这类承诺信号（供日志归因，不参与放行）。"""
    s = str(text or "")
    return any(w in s for w in _PROMISE)


def done(sid) -> bool:
    """这个会话是否已经给过联系方式（一生一次）。"""
    sid = str(sid or "")
    if not sid:
        return True
    d = _load()
    ts = float(d.get(sid) or 0)
    if ts <= 0:
        return False
    # 超过保留期视为失效（避免台账无限膨胀；业务上 90 天足够判「已给过」）
    if (_now() - ts) / 86400.0 > _KEEP_DAYS:
        return False
    return True


def mark_done(sid) -> None:
    """标记已给过。发送成功后调用。"""
    sid = str(sid or "")
    if not sid:
        return
    d = _load()
    # 顺带清理超期条目
    cutoff = _now() - _KEEP_DAYS * 86400.0
    for k in [k for k, v in d.items() if float(v or 0) < cutoff]:
        d.pop(k, None)
    d[sid] = _now()
    _save(d)
    log.info("联系方式已给出 → 台账标记 sid=%s（一生一次）", sid)


def stats() -> dict:
    """排障用：当前台账条数。"""
    d = _load()
    return {"n": len(d), "path": _LEDGER}


__all__ = ["is_ask", "is_open_door", "is_contact_lines", "has_promise", "done", "mark_done", "stats"]
