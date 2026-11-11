# -*- coding: utf-8 -*-
"""brain.act.log WARN 降噪回归测试（2026-11-11 专项 · issue #9）。

跑法：python tests/t_act_warn_level.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.act.log` WARN 一天 531 次（阈值 500）。
根因：act.py（Actor 动作编排）的全部 6 处 `log.warning` 都落在**已被兜住 /
      属设计内**的中间态路径上：
        · `_after` 动作后页面与期望不符（clear/pendingq 对失配都有显式兜底）
        · tap_text 未命中（无生产调用方）
        · tap_text 点后重试（重试中间态）
        · tap_tab 未命中（调用方有显式兜底：nav 恢复梯子 / clear clear-top）
        · tap_tab 点后重试（重试中间态）
        · double_tap_tab 未命中（clear `if snap is None: break` / pendingq 落搜索）
      每轮清红点/进会话都会重跑这些分支，一天几百行，把真异常全淹了，
      巡检阈值也随之爆表。真正的故障（页面回不去、自愈失败、进会话失败）
      由**调用方**自己的 WARN 承担（nav「重启 App」、clear「恢复后仍无底栏」、
      flow res.err 等），本模块只降中间态。

本测试验证两件事（都是静态断言，无需设备）：
  1. 这些「已兜住/设计内」路径**不再打 WARN**（降为 INFO）。
  2. 降级不影响 `tools/action_audit.py` 的动作量化 —— 其正则按**行文本**匹配
     （`tap_tab .* 未命中` / `double_tap_tab(...): A -> B` / `: A -> B`），
     与日志级别无关，INFO 级照样命中。
"""
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  必须在 from brain import ... 之前，避免写生产日志

from brain import act as A  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


src = Path(A.__file__).read_text("utf-8")

# ------------------------------------------------------------------ 1 · 已兜住路径不再 WARN
print("\n--- 1 · 已兜住 / 设计内路径不再打 WARN ---")

# 每项：(已降级的 INFO 调用片段, 说明)
DEMOTED = [
    ('log.info("%s: 期望 %s 实际 %s | %s", action, expect, after_page,',
     "动作后页面与期望不符（调用方有显式兜底）"),
    ('log.info("tap_text %r 未命中", text)', "tap_text 未命中（无生产调用方）"),
    ('log.info("tap_text(%s) 点后仍是 %s → 重新定位再点一次", text, pg)',
     "tap_text 点后重试（重试中间态）"),
    ('log.info("tap_tab %r 未命中（不在主框架？page=%s）", name, before)',
     "tap_tab 未命中（调用方有显式兜底）"),
    ('log.info("tap_tab(%s) 点后仍是 %s → 重新定位再点一次", name, pg)',
     "tap_tab 点后重试（重试中间态）"),
    ('log.info("double_tap_tab %r 未命中（page=%s）| %s",',
     "double_tap_tab 未命中（调用方有显式兜底）"),
]
for frag, why in DEMOTED:
    ck(frag in src, "已降级：%s" % why)
    i = src.find(frag)
    ck(i >= 0, "能找到：%s" % why)
    if i >= 0:
        ck("log.warning" not in frag, "级别不是 WARN：%s" % why)

# ------------------------------------------------------------------ 2 · act.py 里不该再有任何 log.warning
print("\n--- 2 · brain/act.py 中不再存在 log.warning 调用 ---")
# 只统计**代码行**（排除注释里的历史说明，如第 195 行改前的写法记录）
code_lines = [ln for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("#")]
ck(not any("log.warning" in ln for ln in code_lines),
   "act.py 代码中无 log.warning（真故障由调用方承担）")

# ------------------------------------------------------------------ 3 · action_audit 量化不受降级影响
print("\n--- 3 · action_audit 正则按行文本匹配（与级别无关）---")
import re  # noqa: E402

# 与 tools/action_audit.py CATS 同源的正则
rx_tap_miss = re.compile(r"tap_tab .* 未命中")
rx_double = re.compile(r"double_tap_tab\((.+?)\): (\S+) -> (\S+)")
rx_noop = re.compile(r":\s*(\w+)\s*->\s*(\w+)")

samples = [
    "11-11 23:30:00 INFO  tap_tab 聊天 未命中（不在主框架？page=chatlist）",
    "11-11 23:30:00 INFO  double_tap_tab(聊天): chatlist -> unknown | page=unknown sig=abc",
    "11-11 23:30:00 INFO  double_tap_tab(聊天): chatlist -> chatlist",
]
ck(bool(rx_tap_miss.search(samples[0])), "3a tap_tab 未命中仍被量化（INFO 级）")
m = rx_double.search(samples[1])
ck(bool(m) and m.groups() == ("聊天", "chatlist", "unknown"),
   "3b double_tap 转场仍被量化（INFO 级）")
m2 = rx_noop.search(samples[2])
ck(bool(m2) and m2.groups() == ("chatlist", "chatlist"),
   "3c 原地打转 X -> X 仍被量化（INFO 级）")


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
