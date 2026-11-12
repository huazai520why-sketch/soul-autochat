# -*- coding: utf-8 -*-
"""data.imdb.log WARN 限频回归测试（2026-11-11 专项 · issue #3）。

跑法：python tests/t_imdb_warn_limit.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `data.imdb.log` WARN 一天 2066 次（阈值 500）。
根因：Soul 清空账号库后，「设备库缩水 → 保留本地镜像继续跑」是**持久状态**，
      sync() 每 5 分钟（或每次库变化）都重跑一遍，这条降级分支每次进都打
      WARN（3 行/次），一天几百上千行，把真异常全淹了。

验证两件事：
  1. `_warn_limited` 首次调用 WARN，同一 key 在窗口内再调用降 DEBUG。
  2. 窗口过后（key 过期）再次进入会重新 WARN —— 状态恢复/再现不被永久静音。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _nolog  # noqa: F401  必须在 import data.imdb 之前，避免写生产日志

from data import imdb as I  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


# ---------------------------------------------------------------- 1 · 限频语义
print("\n--- 1 · _warn_limited 限频语义 ---")
orig_limit = dict(I._WARN_LIMIT)
try:
    I._WARN_LIMIT.clear()
    EV = 10.0                     # 缩短窗口，便于测试

    calls = []

    class FakeLog:
        @staticmethod
        def warning(msg, *a):
            calls.append(("WARN", msg % a))

        @staticmethod
        def debug(msg, *a):
            calls.append(("DEBUG", msg % a))

    orig_log = I.log
    I.log = FakeLog

    # 1a) 首次进入 → WARN
    I._warn_limited("k1", "msg %d", 1, every=EV)
    ck(calls == [("WARN", "msg 1")], "1a 首次调用 WARN：%r" % calls)

    # 1b) 窗口内再次进入 → DEBUG（不刷屏）
    calls.clear()
    I._warn_limited("k1", "msg %d", 2, every=EV)
    ck(calls == [("DEBUG", "msg 2")], "1b 窗口内再调降 DEBUG：%r" % calls)

    # 1c) 窗口过后 → 重新 WARN（状态恢复/再现不被永久静音）
    calls.clear()
    I._WARN_LIMIT["k1"] = time.time() - 11.0    # 假装窗口已过
    I._warn_limited("k1", "msg %d", 3, every=EV)
    ck(calls == [("WARN", "msg 3")], "1c 窗口过后重新 WARN：%r" % calls)

    # 1d) 不同 key 互不影响（每个降级状态独立限频）
    calls.clear()
    I._warn_limited("k2", "other %d", 9, every=EV)
    ck(calls == [("WARN", "other 9")], "1d 不同 key 独立限频：%r" % calls)

    # 1e) 生产默认窗口为 3600s（同一 key 一小时最多 WARN 一次）
    ck(I._WARN_EVERY == 3600.0, "1e 默认窗口 3600s：%s" % I._WARN_EVERY)

    I.log = orig_log
finally:
    I._WARN_LIMIT.clear()
    I._WARN_LIMIT.update(orig_limit)


# ---------------------------------------------------------------- 2 · 关键点已接入
print("\n--- 2 · shrink 降级分支改用限频 ---")
src = Path(I.__file__).read_text("utf-8")
ck("_warn_limited(" in src, "2a imdb.py 已调用 _warn_limited")
ck('"shrink:" + name' in src, "2b shrink 降级 WARN 已按库名限频")
ck("shrink-merge:" in src, "2c 增量合并结果 WARN 已限频")


print("\n=== 结果：BAD = %d ===" % len(BAD))
sys.exit(1 if BAD else 0)
