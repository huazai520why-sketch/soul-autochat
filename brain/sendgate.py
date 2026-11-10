# -*- coding: utf-8 -*-
"""发送闸：所有「实际发出消息」的路径在发送前必过这里（obs §104 §6.5）。

统一口径：一个会话能发几条，只由 ``brain.verdict.state_of`` 判定；
发送成功后必须由调用方调 ``note_sent(sid, 实际条数)`` 落账，
否则 2/6 条额度会被系统性击穿。

一键回滚：``SOUL_FOLLOWUP_ON=0`` 时全放行且不落账，
生产出任何异常可立刻退回改造前行为，不用 revert 代码。
"""
import os
import time
from dataclasses import dataclass
from typing import Optional

from brain import verdict as V
from core.log import get_logger
from data import reply_state as RS

log = get_logger("brain.sendgate")

ON = (os.environ.get("SOUL_FOLLOWUP_ON", "1") or "1") != "0"


@dataclass(frozen=True)
class Decision:
    """发送闸裁决。

    Attributes:
        ok: 是否允许发送。
        n: 允许发出的条数（已按额度截断）。
        state: verdict 六档状态。
        reason: 排障说明。
    """

    ok: bool
    n: int
    state: str
    reason: str


def allow(
    sid: str,
    n_lines: int = 1,
    *,
    her_ts_ms: Optional[float] = None,
    my_last_ts_ms: float = 0.0,
    has_human: bool = True,
    now: Optional[float] = None,
) -> Decision:
    """发送前问一次：这个会话现在能发几条。

    Args:
        sid: 会话 id。空串 = 无主会话（奇遇铃 / 匹配开场白等新会话），
            不属于「跟进老友」，直接放行且不纳入额度（见 §6.5 备注）。
        n_lines: 本次打算发的条数。
        her_ts_ms: 她末条真人消息时间（毫秒）；有值时顺带更新水位线。
        my_last_ts_ms: 我方末条时间（毫秒），用于 awaiting 判定。
        has_human: 是否有真人消息；系统卡传 False。
        now: 回放测试用固定当前时间（秒）。

    Returns:
        Decision(ok, n, state, reason)。任何异常都降级为放行，
        绝不让台账/状态机把「必回」链路掐死。
    """
    if not ON:
        return Decision(True, max(1, int(n_lines)), "off", "SOUL_FOLLOWUP_ON=0 已关闭阶梯")
    if not sid:
        return Decision(True, max(1, int(n_lines)), "unbound", "无主会话（开场白），不纳入跟进额度")
    try:
        if RS.is_archived(sid):
            return Decision(False, 0, V.ARCHIVED, "已归档（C4），不回复不唤醒")
        if her_ts_ms and float(her_ts_ms) > 0:
            RS.on_her(sid, float(her_ts_ms), human=has_human)
        rec = RS.get(sid)
        _her = float(rec.get("her_ts_ms") or 0) or float(her_ts_ms or 0)
        if _her <= 0:
            # 🔴 冷启动兜底（上线前实测发现的致命洞）：台账尚未建立水位线时，
            #    state_of 会判 no_human 并返回 allowed=0 —— 而 flow / wake / picreq
            #    这些路径都不经过 candidates 的 on_her，会把「必回」链路整条掐死。
            #    处理：以当前时刻为回合起点建水位线，之后再按正常的 2/6 条额度裁决。
            _now_s = float(now if now is not None else time.time())
            _her = _now_s * 1000.0
            RS.on_her(sid, _her, human=True)
            rec = RS.get(sid)
            log.info("发送闸 sid=%s 水位线未建立 → 以当前时刻冷启动（不阻断必回）", sid)
        v = V.state_of(
            sid=sid,
            her_ts_ms=_her,
            sends=rec.get("sends") or [],
            now=now,
            my_last_ts_ms=my_last_ts_ms,
            # has_human 由调用方用 eyes.sysmsg 判过；台账里的 sys_only 只是历史标记，
            # 不能反过来把「她刚说的真人话」判成 no_human（会漏回）。
            has_human=has_human,
            n_lines=n_lines,
        )
        ok = v.allowed > 0
        log.info("发送闸 sid=%s state=%s 允许 %d/%d 条 ｜ %s",
                 sid, v.state, v.allowed, n_lines, v.reason)
        return Decision(ok, v.allowed, v.state, v.reason)
    except Exception as e:
        log.warning("发送闸异常（降级放行，不阻断必回）sid=%s: %r", sid, e)
        return Decision(True, max(1, int(n_lines)), "error", "降级放行: %r" % (e,))


def note_sent(sid: str, n: int = 1) -> None:
    """发送成功后记账（按真实条数，不按轮次）。"""
    if not ON or not sid:
        return
    try:
        RS.note_sent(sid, n)
    except Exception as e:
        log.warning("记账失败 sid=%s n=%d: %r", sid, n, e)


def on_her(sid: str, her_ts_ms: float, human: bool = True) -> None:
    """她来消息时推进水位线；系统消息传 human=False（C5/C8）。"""
    if not ON or not sid:
        return
    try:
        RS.on_her(sid, her_ts_ms, human=human)
    except Exception as e:
        log.warning("水位线更新失败 sid=%s: %r", sid, e)


def is_archived(sid: str) -> bool:
    """候选链/唤醒链共用：是否已被归档。"""
    if not ON or not sid:
        return False
    try:
        return RS.is_archived(sid)
    except Exception:
        return False


def archived_sids():
    """全量归档 sid（供 candidates 一次性排除）。"""
    if not ON:
        return []
    try:
        return RS.archived_sids()
    except Exception:
        return []


def state_of(sid: str, **kw):
    """给 data.pending.summary() 的四桶统计用：返回 Verdict。"""
    if not sid:
        return V.state_of(has_human=False)
    try:
        rec = RS.get(sid)
        return V.state_of(
            sid=sid,
            her_ts_ms=float(rec.get("her_ts_ms") or kw.get("her_ts_ms") or 0),
            sends=rec.get("sends") or [],
            now=kw.get("now"),
            my_last_ts_ms=kw.get("my_last_ts_ms") or 0.0,
            has_human=kw.get("has_human", True),
            n_lines=kw.get("n_lines", 1),
        )
    except Exception:
        return V.state_of(has_human=False)


__all__ = ["ON", "Decision", "allow", "note_sent", "on_her",
           "is_archived", "archived_sids", "state_of"]
