# -*- coding: utf-8 -*-
"""brain.flow.log FAIL 降噪回归测试（2026-11-12 专项 · issue #10）。

跑法：python tests/t_flow_fail_level.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.flow.log` FAIL 一天 284 次（阈值 50）。
根因：`brain/flow.py` 有一条「**已兜住 / 必回铁律保证继续**」的 WARN 日志带
      「失败」关键字，被 nightly_collect 的 FAIL 类别（WARNING+ 且命中失败
      关键字）误计：

        `log.warning("[%s] 引擎出话失败 → 用兜底话术 %r", ...)`

      引擎出话无产出时，必回铁律用 fallback_line() 顶上——**一定发一句**，
      不是故障。真正的发送失败由 _send_lines 的返回 err 另行 WARN
      （`已发 %d/%d 条但有错误`）。

  级别降级（「行文本反查异常/第N次进会话失败/反查强拉库失败/识图异常/发图
  判断异常」等已兜住路径）由并列的 WARN 降噪 PR（#13）负责，本测试**不重叠**，
  只锁本 PR 改的这一条 FAIL 专属口径——它不降级（与 #13 口径一致保留 WARN），
  只去掉「失败」关键字避免被 FAIL 计数。

本测试为静态断言（无需设备）：
  1. 「引擎出话失败 → 兜底话术」已重写成「引擎无产出 → 兜底话术」（去掉「失败」），
     避免被 FAIL 关键字误计。
  2. 该路径仍保留 WARN 级别（与 #13 的「真实故障仍保留 WARN」口径一致）。
  3. 兜底话术仍能正常兜底（fallback_line 返回非空）。
"""
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  必须在 from brain import ... 之前，避免写生产日志

from brain import flow as F  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


src = Path(F.__file__).read_text("utf-8")

# ------------------------------------------------------------------ 1 · 已兜住路径去掉「失败」关键字
print("\n--- 1 · 引擎出话无产出路径去掉「失败」关键字 ---")

OLD = 'log.warning("[%s] 引擎出话失败 → 用兜底话术 %r", out.nick, lines[0])'
NEW = 'log.warning("[%s] 引擎无产出 → 用兜底话术 %r", out.nick, lines[0])'
ck(OLD not in src, "源码中不再出现「引擎出话失败」")
ck(NEW in src, "已重写成「引擎无产出 → 兜底话术」（去掉「失败」）")

# ------------------------------------------------------------------ 2 · 仍保留 WARN 级别
print("\n--- 2 · 该路径仍保留 WARN 级别（与 #13 口径一致）---")
i = src.find(NEW)
ck(i >= 0, "能找到兜底话术日志")
if i >= 0:
    ck("log.warning" in src[i:i + len(NEW)],
       "兜底话术路径仍是 WARNING（真故障由调用方另行 WARN，此条保持 WARN 但去关键字）")

# ------------------------------------------------------------------ 3 · 兜底话术可用
print("\n--- 3 · 兜底话术仍能兜底 ---")
fl = F.fallback_line()
ck(bool(fl and fl.strip()), "fallback_line() 返回非空（必回铁律）：%r" % fl)
ck(fl in F.FALLBACK_LINES, "fallback_line() 取自 FALLBACK_LINES")


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
