# -*- coding: utf-8 -*-
"""brain.pendingq.log.2 FAIL 降噪回归测试（2026-11-12 专项 · issue #11）。

跑法：python tests/t_pendingq_fail_level.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.pendingq.log.2` FAIL 一天 195 次（阈值 50）。
根因：pendingq.py 里的多条 `log.warning` 落在**已被兜住 / 属常态 / 设计内**的路径
      （身份校验未读差分中间态、写失败台账异常、SLA 标红指标、查会话失败降级、
      设备存活校验降级、语音转写占位兜底、设备未读对账补入/异常、过期淘汰异常、
      取备选关键词异常、列表手势取 u2/超时/失败、取红点行失败、翻屏取屏失败、
      积压降级、轮首回顶失败、发送达上限节流、回不到列表硬复位中间态、
      双击找行异常、身份校验逐条尝试中间态、发送确认 unknown 记账、跟进台账记账失败），
      每天重跑几百次，把真异常全淹了，巡检阈值也随之爆表。

本测试验证两件事（都是静态断言，无需设备）：
  1. 这些「已兜住/设计内」路径**不再打 WARN**（降为 INFO）。
  2. 真正需要人看的故障/熔断**仍保留 WARN**，不能被一并降掉：
       · 已读未回一条都没回成 → 收工（异常）
       · 连续 N 次回不到 chatlist → 判定设备级故障（熔断）
       · 搜索无结果累计 N 次/30min → 升级冷却（防白烧熔断）
       · 身份校验连续 N 次失败 → 长冷却（熔断）
       · 出话失败 → 兜底话术（必回但异常）
       · 第 N 条灌字失败 / 找不到发送按钮 / 确认未发出（residual → 下轮重试）
"""
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  必须在 from brain import ... 之前，避免写生产日志

from brain import pendingq as P  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


src = Path(P.__file__).read_text("utf-8")

# ------------------------------------------------------------------ 1 · 已兜住路径不再 WARN
print("\n--- 1 · 已兜住 / 设计内路径不再打 WARN ---")

# 每项：(已降级的 INFO 调用片段, 说明)
DEMOTED = [
    ('log.info("身份校验失败（进的是别的会话：清零 %r，期望 %s）", list(cleared)[:3], sid)',
     "身份校验未读差分中间态（fail-closed 不发才是真屏障；P0 证明 84% 是快照污染假否决）"),
    ('log.info("保存失败台账异常: %r", e)', "写失败台账异常（冷却只是优化，不因漏写漏回）"),
    ('log.info("⏰ 超 %.0f 分钟未回 uid=%s sid=%s（%s）→ 标红，留队列按等待时长重排",',
     "SLA 标红（只记录不改行为，10 分钟限频防刷屏）"),
    ('log.info("查会话失败: %r", e)', "查会话失败 → 返回 []（调用方当无候选，已兜住）"),
    ('log.info("设备存活校验取不到（本轮不过滤，按旧行为走）: %r", _e)',
     "设备存活校验降级（显式不过滤，宁可白烧不掐整轮）"),
    ('log.info("语音转写失败 sid=%s（%ds）→ 用占位串照常回复",',
     "语音转写失败 → 占位串照常回复（必回铁律兜底）"),
    ('log.info("设备未读对账：sid=%s uid=%s 设备说未读却没进队列 "',
     "设备未读对账强制补入（设计内最后一道保证）"),
    ('log.info("设备未读对账异常（不影响已有候选）: %r", _e)',
     "设备未读对账异常（已有候选照常返回）"),
    ('log.info("过期淘汰异常（忽略，按原队列走）: %r", _e)',
     "过期淘汰异常（忽略按原队列走）"),
    ('log.info("取备选关键词异常: %r", e)', "取备选关键词异常（退回默认 cand）"),
    ('log.info("手势取 u2 失败: %r", e)', "手势取 u2 失败（返回 False 放弃本次）"),
    ('log.info("列表手势超时（>%.0fs），放弃本次", budget)', "列表手势超时（防卡死设计）"),
    ('log.info("列表手势失败: %r", box["err"])', "列表手势失败（返回 False 放弃本次）"),
    ('log.info("取红点行失败: %r", e)', "取红点行失败（调用方转搜索兜底）"),
    ('log.info("翻屏取屏失败: %r", e)', "翻屏取屏失败（hit_bottom 转搜索兜底）"),
    ('log.info("已读未回积压 %d 个 → 降级：单轮最多 %d 条、预算 %.0fs（搜索保留，最老优先）",',
     "积压降级（设计内吞吐策略）"),
    ('log.info("轮首回列表顶部失败（继续）: %r", _e)', "轮首回顶失败（继续，不中断本轮）"),
    ('log.info("本小时发送已达上限 → 本轮不做已读未回")',
     "本小时发送达上限（预期节流，避免封号）"),
    ('log.info("回不到列表（pg=%s）→ am start 首页硬复位后重试一次", pg)',
     "回不到列表硬复位中间态（恢复尝试，成功即恢复）"),
    ('log.info("硬复位后仍回不到列表（pg=%s），连续第 %d 次",',
     "硬复位后仍回不到（计数中间态；熔断由下方「连续 N 次」另行 WARN）"),
    ('log.info("双击找行异常: %r", _e)', "双击找行异常（转搜索兜底）"),
    ('log.info("身份校验失败（第 %d 次，消息 %r）→ 不发送，防串台"',
     "身份校验逐条尝试中间态（熔断由「连续 N 次长冷却」另行 WARN）"),
    ('log.info("第%d条发送确认读不到输入框（按已发出记账，不再重发）", i + 1)',
     "发送确认 unknown（按已发记账，防重复发送）"),
    ('log.info("跟进台账记账失败 sid=%s: %r", sid, _e_ns)',
     "跟进台账记账失败（不影响已发消息）"),
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
print("\n--- 2 · 真正需要人看的故障/熔断仍保留 WARN ---")

KEEP_WARN = [
    ('log.warning("已读未回 %.0fs 一条都没回成 → 收工（异常）", used)',
     "已读未回一条都没回成 → 收工（异常）"),
    ('log.warning("连续 %d 次回不到 chatlist → 判定设备级故障，本轮提前收工",',
     "连续 N 次回不到 chatlist → 设备级故障熔断"),
    ('log.warning("搜索无结果累计 %d 次/30min → 升级 %.0f 分钟冷却（防白烧）sid=%s",',
     "搜索无结果累计 N 次 → 升级冷却（防白烧熔断）"),
    ('log.warning("身份校验连续 %d 次失败（搜索结果都试过）→ 长冷却 %.1fh，"',
     "身份校验连续 N 次失败 → 长冷却（熔断）"),
    ('log.warning("出话失败 → 用兜底话术 %r", lines[0])', "出话失败 → 兜底话术（必回但异常）"),
    ('log.warning("第%d条灌字失败（%r）", i + 1, got)', "第 N 条灌字失败（单条发送失败）"),
    ('log.warning("第%d条找不到发送按钮", i + 1)', "第 N 条找不到发送按钮"),
    ('log.warning("第%d条确认未发出（输入框仍有内容）→ 不记账，下轮重试", i + 1)',
     "第 N 条确认未发出（residual → 下轮重试）"),
]
for frag, why in KEEP_WARN:
    ck(frag in src, "仍保留 WARN：%s" % why)


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
