# -*- coding: utf-8 -*-
"""跟进阶梯状态机（obs 交接报告 §104 定稿，唯一判定源）。

设计约束（改动前必读）：
  * **纯函数**：不 import 项目内任何模块、不读文件、不写日志、不依赖全局状态。
    这样回放测试可以在任意机器上跑，也能被 candidates() / sendgate / summary
    三处共用而不产生循环依赖。
  * 时间单位统一：对外 ``her_ts_ms`` / ``my_last_ts_ms`` 用**毫秒**（与 imdb 一致），
    ``sends`` 与 ``now`` 用**秒**（与 time.time() 一致）。函数内部转秒后比较。
  * 契约 C1~C8 见 obs ``01-项目/Soul自动聊天/DSH交接报告_Soul.md`` §六。

状态机六分支（判定顺序不可调换）：
  1 no_human       她末条只有系统/广告，或压根没有真人消息
  2 awaiting       我方末条晚于她末条人话（等她回）
  3 archived       age >= 72h（归档不发收尾，她再发人话自动重置）
  4 following      本档额度已满 / 滚动 24h 已满（不入队，下一档再评估）
  5 pending_restart age >= 24h 且本回合一条没发过（重新开场，不接旧话）
  6 pending        正常回复（5 分钟 SLO 只管这一档）
"""
from dataclasses import dataclass
from typing import Iterable, Optional

# ---- 定稿常量（改动需同步 obs §六 与 tests/t_followup_replay.py） ----
TIER_H = 24.0        # 档位跨度：0~24 / 24~48 / 48~72
CAP_24H = 2          # 滚动 24h 最多 2 条（首条回复占额度，C6）
CAP_TOTAL = 6        # 累计上限（C7：归档不发收尾句）
ARCHIVE_H = 72.0     # 超过即 archived（C4）

NO_HUMAN = "no_human"
AWAITING = "awaiting"
ARCHIVED = "archived"
FOLLOWING = "following"
PENDING_RESTART = "pending_restart"
PENDING = "pending"

# 计入「待回」的只有这两档（§6.4 四桶口径）
QUEUEABLE = (PENDING, PENDING_RESTART)
BUCKETS = (NO_HUMAN, AWAITING, ARCHIVED, FOLLOWING, PENDING_RESTART, PENDING)


@dataclass(frozen=True)
class Verdict:
    """一次判定的结果。

    Attributes:
        state: 六档状态之一。
        age_h: 距她最后一条真人消息的小时数。
        sent_total: 本回合（她末条人话之后）我方已发条数。
        sent_24h: 滚动 24h 内我方已发条数。
        allowed: 本次实际允许发出的条数（已按 n_lines 截断，最小 0）。
        tier_cap: 当前档位允许的累计条数 min(6, 2*(floor(age/24)+1))。
        reason: 供日志排障的一句话说明。
    """

    state: str
    age_h: float
    sent_total: int
    sent_24h: int
    allowed: int
    tier_cap: int
    reason: str

    @property
    def queueable(self) -> bool:
        """是否应进入待回队列（只有 pending / pending_restart）。"""
        return self.state in QUEUEABLE

    @property
    def restart(self) -> bool:
        """是否走「重新开场」出话（不接旧话）。"""
        return self.state == PENDING_RESTART


def _as_seconds(value: Optional[float]) -> float:
    """把毫秒/秒的混杂输入安全转成秒；None / 非数 / 负数一律当 0。"""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def state_of(
    sid: str = "",
    her_ts_ms: float = 0.0,
    sends: Optional[Iterable[float]] = None,
    now: Optional[float] = None,
    my_last_ts_ms: float = 0.0,
    has_human: bool = True,
    n_lines: int = 1,
    *,
    cap_24h: int = CAP_24H,
    cap_total: int = CAP_TOTAL,
    tier_h: float = TIER_H,
    archive_h: float = ARCHIVE_H,
) -> Verdict:
    """判定一个会话此刻该不该发、能发几条。

    Args:
        sid: 会话 id，仅用于 reason 文案，不参与计算。
        her_ts_ms: 她最后一条**真人**消息时间（毫秒）；0 表示没有真人消息。
        sends: 本回合我方已发送的时刻列表（秒）；由 data.reply_state 提供，
            听任调用方传全量，本函数会按 her_ts 自行裁出本回合。
        now: 当前时间（秒），缺省取 time.time()；回放测试传固定值。
        my_last_ts_ms: 我方最后一条消息时间（毫秒），用于 awaiting 判定；0 表示未知。
        has_human: 是否至少有一条真人消息；C5 系统卡会话传 False。
        n_lines: 本次打算发几条，用于把额度截成 allowed。
        cap_24h: 滚动 24h 上限（默认 2）。
        cap_total: 累计上限（默认 6）。
        tier_h: 档位跨度小时（默认 24）。
        archive_h: 归档阈值小时（默认 72）。

    Returns:
        Verdict，含 state / allowed / 计数与排障说明。

    Raises:
        不抛异常。任何脏数据都按「最保守」处理（no_human 或 allowed=0），
        绝不因为台账异常把生产链路打断。
    """
    import math
    import time

    now_s = _as_seconds(now) or time.time()
    her_s = _as_seconds(her_ts_ms) / 1000.0
    my_s = _as_seconds(my_last_ts_ms) / 1000.0

    # ① 没有真人消息 → 不回、不计待回、不更新水位线（C5）
    if not has_human or her_s <= 0:
        return Verdict(NO_HUMAN, 0.0, 0, 0, 0, 0, "无真人消息（系统卡/广告）")

    age_h = max(0.0, (now_s - her_s) / 3600.0)
    raw_sends = []
    for t in (sends or ()):  # 脏数据逐条过滤，不能让一个 None 毁掉整轮
        v = _as_seconds(t)
        if v > 0:
            raw_sends.append(v)
    # C2：她再发真人消息 → 计数清零。只统计她末条之后的发送。
    turn = [t for t in raw_sends if t >= her_s - 1.0]
    sent_total = len(turn)
    sent_24h = sum(1 for t in raw_sends if t > now_s - 86400.0)

    # ② 我方末条晚于她末条人话 → 等她回（C1 的「她在说」前提不成立）
    if my_s > her_s:
        return Verdict(AWAITING, age_h, sent_total, sent_24h, 0, 0,
                       "我方末条晚于她末条人话，等她回")

    # ③ 归档：不发收尾句、不入队、不唤醒（C4/C7）
    if age_h >= archive_h:
        return Verdict(ARCHIVED, age_h, sent_total, sent_24h, 0, 0,
                       "age %.1fh >= %.0fh → 归档" % (age_h, archive_h))

    tier = int(math.floor(age_h / tier_h)) if tier_h > 0 else 0
    tier_cap = min(cap_total, cap_24h * (tier + 1))

    # ④ 额度已满 → following，下一档解锁再评估
    if sent_total >= tier_cap or sent_24h >= cap_24h:
        return Verdict(FOLLOWING, age_h, sent_total, sent_24h, 0, tier_cap,
                       "本档 %d/%d 条、24h %d/%d 条 → 不再入队"
                       % (sent_total, tier_cap, sent_24h, cap_24h))

    # ⑤ age >= 24h 且本回合一条没发 → 重新开场（C3）
    state = PENDING_RESTART if (age_h >= tier_h and sent_total == 0) else PENDING

    # ⑥ 可发条数：滚动 24h 与累计双上限取小（C1）
    allowed = min(int(n_lines), cap_total - sent_total, cap_24h - sent_24h)
    # §6.6-2：ADAPT_CAP=2 一轮发两句就用光当天额度 → 已跟过的人本轮最多 1 条，
    # 且按**实际发出条数**扣（由 sendgate.note_sent 落账），不按轮次扣。
    if sent_total > 0:
        allowed = min(allowed, 1)
    allowed = max(0, allowed)
    reason = ("%s：age %.1fh，本回合已发 %d/%d 条，24h %d/%d 条 → 允许 %d 条"
              % (state, age_h, sent_total, tier_cap, sent_24h, cap_24h, allowed))
    return Verdict(state, age_h, sent_total, sent_24h, allowed, tier_cap, reason)


__all__ = [
    "TIER_H", "CAP_24H", "CAP_TOTAL", "ARCHIVE_H",
    "NO_HUMAN", "AWAITING", "ARCHIVED", "FOLLOWING", "PENDING_RESTART", "PENDING",
    "QUEUEABLE", "BUCKETS", "Verdict", "state_of",
]
