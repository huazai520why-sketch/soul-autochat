# -*- coding: utf-8 -*-
"""core.device.log WARN 降噪回归测试（2026-11-11 专项 · issue #8）。

跑法：python tests/t_device_warn.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `core.device.log` WARN 一天 579 次（阈值 500）。
根因：设备层多条「进入恢复/降级路径」的 WARN 在设备抖动/自愈循环时会**每轮都打**：
      - `reset_u2()` 每次重连都打「u2 连接已重置」，但真正原因已由调用方打了 WARN，
        本条是纯重复计数；
      - adb 超时 / adb connect 失败 / adbd 不是 root / adb root 失败 / 截图 CRLF
        在自愈循环里每轮都打，一天几百上千行。

验证两件事：
  1. `warn_limited` 首次调用 WARN，同一 key 在窗口内再调用降 DEBUG，窗口过后重新 WARN。
  2. core/device.py 的 WARN 全走限频，且 reset_u2 不再 WARN（降为 INFO）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _nolog  # noqa: F401  必须在 import core.* 之前，避免写生产日志

from core import log as L  # noqa: E402
from core import device as D  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


# ---------------------------------------------------------------- 1 · 限频语义
print("\n--- 1 · warn_limited 限频语义 ---")
orig_limit = dict(L._WARN_LIMIT)
try:
    L._WARN_LIMIT.clear()
    EV = 10.0                     # 缩短窗口，便于测试

    calls = []

    class FakeLog:
        @staticmethod
        def warning(msg, *a):
            calls.append(("WARN", msg % a))

        @staticmethod
        def debug(msg, *a):
            calls.append(("DEBUG", msg % a))

        @staticmethod
        def info(msg, *a):
            calls.append(("INFO", msg % a))

    # 1a) 首次进入 → WARN
    L.warn_limited(FakeLog, "k1", "msg %d", 1, every=EV)
    ck(calls == [("WARN", "msg 1")], "1a 首次调用 WARN：%r" % calls)

    # 1b) 窗口内再次进入 → DEBUG（不刷屏）
    calls.clear()
    L.warn_limited(FakeLog, "k1", "msg %d", 2, every=EV)
    ck(calls == [("DEBUG", "msg 2")], "1b 窗口内再调降 DEBUG：%r" % calls)

    # 1c) 窗口过后 → 重新 WARN（状态恢复/再现不被永久静音）
    calls.clear()
    L._WARN_LIMIT["k1"] = time.time() - 11.0    # 假装窗口已过
    L.warn_limited(FakeLog, "k1", "msg %d", 3, every=EV)
    ck(calls == [("WARN", "msg 3")], "1c 窗口过后重新 WARN：%r" % calls)

    # 1d) 不同 key 互不影响（每个降级状态独立限频）
    calls.clear()
    L.warn_limited(FakeLog, "k2", "other %d", 9, every=EV)
    ck(calls == [("WARN", "other 9")], "1d 不同 key 独立限频：%r" % calls)

    # 1e) 生产默认窗口为 3600s（同一 key 一小时最多 WARN 一次）
    ck(L._WARN_EVERY == 3600.0, "1e 默认窗口 3600s：%s" % L._WARN_EVERY)

finally:
    L._WARN_LIMIT.clear()
    L._WARN_LIMIT.update(orig_limit)


# ---------------------------------------------------------------- 2 · device.py 已接入
print("\n--- 2 · device.py WARN 降噪已接入 ---")
src = Path(D.__file__).read_text("utf-8")

# 2a) reset_u2 不再 WARN（降为 INFO）—— 这是重复计数的最大来源
ck('log.info("u2 连接已重置")' in src, "2a reset_u2 已降为 INFO")
ck('log.warning("u2 连接已重置")' not in src, "2a2 reset_u2 不再 WARN")

# 2b) 高频恢复路径全部走 warn_limited
ck("warn_limited(" in src, "2b device.py 已调用 warn_limited")
for pat in ('"adb-timeout:', '"adb-connect:', '"adbd-not-root:', '"adb-root-fail:', '"screencap-crlf'):
    ck(pat in src, "2b 高频路径已限频：%s" % pat)

# 2c) 不再有裸 log.warning（全走限频）
import re
bare = [m for m in re.findall(r'log\.warning\(', src)]
ck(not bare, "2c device.py 无裸 log.warning：%s" % bare)

# 2d) core.device 日志器只有 device.py 写（无其他模块往它灌 WARN）
import subprocess
r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, 'core'); "
     "from pathlib import Path; "
     "files=[str(p) for p in Path('.').rglob('*.py') if '__pycache__' not in str(p)]; "
     "hits=[f for f in files if 'get_logger(\"core.device\")' in Path(f).read_text('utf-8') "
     "or \"get_logger('core.device')\" in Path(f).read_text('utf-8')]; "
     "print(hits)"],
    cwd=Path(D.__file__).resolve().parent.parent, capture_output=True, text=True)
hits = r.stdout.strip().strip("[]").replace("'", "").split(", ") if r.stdout.strip() else []
# 允许 core/device.py 自身；其他模块不得再 get_logger("core.device")
others = [h for h in hits if h and "core/device.py" not in h and "tests/" not in h]
ck(not others, "2d 无其他模块写 core.device 日志器：%r" % others)


print("\n=== 结果：BAD = %d ===" % len(BAD))
sys.exit(1 if BAD else 0)
