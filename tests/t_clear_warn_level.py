# -*- coding: utf-8 -*-
"""brain.clear.log WARN 降噪回归测试（2026-11-11 专项 · issue #6）。

跑法：python tests/t_clear_warn_level.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.clear.log` WARN 一天 836 次（阈值 500）。
根因：clear.py 里有 12 处 `log.warning` 落在**已被兜住 / 属常态 / 设计内**的路径
      （库判定失败、无底栏自愈、下拉刷新/回顶失败、列表比库旧、进会话单人异常、
      末条是她但发不出（计数中间态）、判定假红点（防空转设计）、轮内铃检查异常等），
      每轮清红点都要重跑这些分支，一天几百上千行，把真异常全淹了，阈值也爆表。

本测试验证两件事（都是静态断言，无需设备）：
  1. 这些「已兜住/设计内」路径**不再打 WARN**（降为 INFO 或 DEBUG）。
  2. 真正需要人看的故障**仍保留 WARN**，不能被一并降掉：
       · 恢复后仍无底栏 → 放弃本轮
       · 一个人都没进去 → 直接收工（异常）
       · 连续 N 次「末条是她但发不出」→ 熔断收工
       · res.err（进会话后不是 chat 页 / 读不到消息 / 反查不到 sid / 部分发送失败）
"""
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  必须在 from brain import ... 之前，避免写生产日志

from brain import clear as C  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


src = Path(C.__file__).read_text("utf-8")

# ------------------------------------------------------------------ 1 · 已兜住路径不再 WARN
print("\n--- 1 · 已兜住 / 设计内路径不再打 WARN ---")

# 每项：(已降级的 INFO/DEBUG 调用片段, 说明)
DEMOTED = [
    ('log.info("库判定待回失败: %r", e)', "库判定待回失败（返回 []，走屏幕/搜索兜底）"),
    ('log.info("[clear] 无底栏(%s) → 不盲点 tab / 不 back，"', "无底栏自愈（goto_main 成功即恢复）"),
    ('log.info("[clear] clear-top 恢复失败（交回上层跳过本轮）: %r", e)',
     "clear-top 恢复失败（交回上层，已兜住）"),
    ('log.info("下拉刷新取 u2 失败: %r", e)', "下拉刷新取 u2 失败（返回 False，放弃本轮刷新）"),
    ('log.info("下拉刷新手势超时（>%.0fs），放弃本次刷新，不阻塞主流程", budget)',
     "下拉刷新手势超时（防卡死设计）"),
    ('log.info("下拉刷新手势失败: %r", box["err"])', "下拉刷新手势失败（返回 False）"),
    ('log.info("回顶取 u2 失败: %r", e)', "回顶取 u2 失败（继续用当前屏）"),
    ('log.info("回顶手势超时（>%.0fs），放弃本次", budget)', "回顶手势超时（继续用当前屏）"),
    ('log.info("列表比库旧（未读 %d 个，屏上没有最新那条）→ 下拉刷新 #%d",',
     "列表比库旧 → 下拉刷新（常态自愈）"),
    ('log.info("下拉刷新不可用 → 本轮放弃刷新，继续用当前列表")',
     "下拉刷新不可用（走搜索兜底）"),
    ('log.info("没进对话页（%s），返回", pg)', "新招呼没进对话页（continue 继续处理）"),
    ('log.info("回不到会话列表，跳过清红点")', "回不到会话列表（交回上层）"),
    ('log.info("回顶失败（继续用当前屏）: %r", e)', "回顶失败（ensure_fresh 兜底）"),
    ('log.info("本小时发送已达上限 → 本轮不清红点（避免封号）")',
     "本小时发送达上限（预期节流，避免封号）"),
    ('log.info("[%s] 进会话处理异常（跳过此人，继续本轮）: %r", r.nickname, e)',
     "单人异常（设计内隔离，本轮继续）"),
    ('log.info("[%s] 末条是她但没发出话（第 %d 次）→ 不判假红点，留给已读未回",',
     "末条是她但发不出（计数中间态）"),
    ('log.info("连续 %d 次进会话都无需回复 → 判定假红点，"',
     "判定假红点（防空转设计，pendingq 兜底）"),
    ('log.info("轮内铃检查异常（继续清扫）: %r", e)', "轮内铃检查异常（继续清扫）"),
    ('log.info("进了 %d 人一条没发、角标=0、库无待回 → 判定假红点，清红点冷却 %.0f 分钟",',
     "收尾判定假红点（防空转设计）"),
]
for frag, why in DEMOTED:
    ck(frag in src, "已降级：%s" % why)

# 这些片段绝不能以 log.warning 开头（确认降级没写错级别）
for frag, why in DEMOTED:
    i = src.find(frag)
    ck(i >= 0, "能找到：%s" % why)
    if i >= 0:
        ck("log.warning" not in frag, "级别不是 WARN：%s" % why)

# ------------------------------------------------------------------ 2 · 真故障仍保留 WARN
print("\n--- 2 · 真正需要人看的故障仍保留 WARN ---")

KEEP_WARN = [
    ('log.warning("[clear] 恢复后仍无底栏(%s) → 放弃本轮，不空烧", pg)',
     "恢复后仍无底栏 → 放弃本轮（自愈失败）"),
    ('log.warning("清红点 %.0fs 一个人都没进去 → 直接收工（异常）",',
     "一个人都没进去 → 直接收工（异常）"),
    ('log.warning("连续 %d 次「末条是她但发不出」→ 本轮先停，交给已读未回",',
     "连续 N 次发不出 → 熔断收工"),
    ('log.warning("[%s] %s", res.nick, res.err)', "res.err（进会话失败/读不到/反查不到/发送失败）"),
]
for frag, why in KEEP_WARN:
    ck(frag in src, "仍保留 WARN：%s" % why)


# ------------------------------------------------------------------ 3 · 运行时验证降级
print("\n--- 3 · 运行时：库判定失败走 INFO 而非 WARN（真跑一次降级分支）---")
import logging  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super(_Capture, self).__init__()
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))


def _lv(lv):
    return logging.getLevelName(lv)


cap = _Capture()
C.log.addHandler(cap)
_orig_should = C._P if hasattr(C, "_P") else None
try:
    # 让延迟 import 到的 data.pending.should_reply 抛异常 → 触发「库判定待回失败」分支
    import data.pending as _P

    def _boom(*_a, **_k):
        raise RuntimeError("probe-fail")

    _orig_sr = _P.should_reply
    _P.should_reply = _boom
    out = C.should_reply_list(None)
finally:
    C.log.removeHandler(cap)
    if _orig_sr is not None:
        _P.should_reply = _orig_sr
ck(out == [], "3a 库判定失败返回空列表（实际 %r）" % out)
warns = [r for r in cap.records if r[0] >= logging.WARNING]
infos = [r for r in cap.records if r[0] == logging.INFO and "库判定待回失败" in r[1]]
ck(not warns, "3b 该分支不再产生任何 WARN（实际 WARN=%r）" % [w[1] for w in warns])
ck(len(infos) == 1, "3c 该分支改记一条 INFO（实际 %d 条）" % len(infos))


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
