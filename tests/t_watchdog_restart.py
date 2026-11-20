# -*- coding: utf-8 -*-
"""watchdog_restart 风暴回归测试（2026-11-11 专项 · issue #1）。

跑法：python tests/t_watchdog_restart.py      （BAD=0 表示全过）

验证三件事（都是「watchdog_restart 一天 243 次」的根因）：
  1. daemon 启动初始化失败时**不退出进程**，而是自愈重试（_init_account）。
  2. 设备探测失败（probe_serial 抛异常）不再让进程在写 pid 前退出。
  3. watchdog 侧「拉起频率闸」：5 分钟内第 3 次拉起就停手进冷却，
     防止看门狗自己把「拉起→再崩→再拉」放大成风暴。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _nolog  # noqa: F401  必须在 import guard 之前，避免写生产日志

from guard import daemon as D  # noqa: E402
from guard import watchdog as W  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


class FakeDev:
    """模拟设备：前 fail_times 次 ensure_root 失败，之后成功。"""
    def __init__(self, fail_times):
        self.n = 0
        self.fail_times = fail_times

    def ensure_root(self):
        self.n += 1
        if self.n <= self.fail_times:
            raise RuntimeError("adb root failed (simulated)")
        return True


class FakeDB:
    uid = "test-uid"
    path = Path("fake.db")

    def stats(self):
        return {"sessions": 7}


# ---------------------------------------------------------------- 1 · _init_account
print("\n--- 1 · 启动初始化自愈重试（不退出进程）---")
orig_open = D.open_account
orig_rescue = D._dev_rescue
orig_sleep = D.time.sleep
orig_get = D.Device.get
try:
    D.open_account = lambda dev: FakeDB()
    D._dev_rescue = lambda dev, fails: None
    D.time.sleep = lambda s: None   # 不真等

    # 1a) 临时故障（前 2 次失败）→ 无限重试最终成功
    dev = FakeDev(2)
    d1, db1 = D._init_account(dev, max_retries=None)
    ck(d1 is dev and db1.uid == "test-uid", "1a 无限重试：临时故障后成功")
    ck(dev.n == 3, "1a 重试次数正确（%d 次 ensure_root）" % dev.n)

    # 1b) 持续故障 + max_retries=2 → 抛异常（once 演练不挂死）
    dev = FakeDev(999)
    try:
        D._init_account(dev, max_retries=2)
        ck(False, "1b 持续故障 + 有限重试应抛异常")
    except RuntimeError:
        ck(True, "1b 持续故障 + 有限重试抛异常（不无限循环）")

    # 1c) 设备探测失败（Device.get 抛异常）也被自愈重试吞掉
    def _raise_get():
        raise RuntimeError("probe_serial failed (simulated)")
    D.Device.get = staticmethod(_raise_get)
    try:
        D._init_account(None, max_retries=1)
        ck(False, "1c 设备探测失败应抛异常（有限重试到顶）")
    except RuntimeError:
        ck(True, "1c 设备探测失败：有限重试到顶后抛异常，不静默退出")
    # 恢复 Device.get（_init_account 内部再探时能成）
    D.Device.get = orig_get
finally:
    D.open_account = orig_open
    D._dev_rescue = orig_rescue
    D.time.sleep = orig_sleep
    D.Device.get = orig_get


# ---------------------------------------------------------------- 2 · watchdog 拉起闸
print("\n--- 2 · watchdog 拉起频率闸（防风暴放大）---")
W._restarts = []
W._cooldown_until = 0.0

ok, _ = W._restart_ok()
ck(ok, "2a 初始允许拉起")

# 连拉 3 次
for _ in range(3):
    W._record_restart()
ok, why = W._restart_ok()
ck(not ok, "2b 5 分钟内拉起 3 次 → 限流（%s）" % why)

# 冷却期内仍限流
ok, _ = W._restart_ok()
ck(not ok, "2c 冷却期内仍限流")

# 冷却过期后恢复
W._cooldown_until = time.time() - 1
W._restarts = []
ok, _ = W._restart_ok()
ck(ok, "2d 冷却过期后恢复允许拉起")

# 窗口外的时间戳被清掉（模拟很久以前拉过，现在可再拉）
W._cooldown_until = 0.0
W._restarts = [time.time() - W.RESTART_WINDOW_S - 1]
ok, _ = W._restart_ok()
ck(ok, "2e 窗口外拉起记录被清除，允许拉起")


# ---------------------------------------------------------------- 3 · 完整 check 流程
print("\n--- 3 · check() 在 daemon 已死时走拉起/限流分支 ---")
orig_alive = W.daemon_alive
orig_start = W.start_daemon
orig_clear = W.lock.clear_stale
try:
    W.daemon_alive = lambda: (False, "pid 已死 (simulated)")
    W.lock.clear_stale = lambda: "已清理"
    calls = {"n": 0}

    def _fake_start():
        calls["n"] += 1
        return 12345
    W.start_daemon = _fake_start

    W._restarts = []
    W._cooldown_until = 0.0

    ok, why = W.check()
    ck(ok, "3a 首次拉起成功（%s）" % why)
    ck(calls["n"] == 1, "3a 实际调用 start_daemon 1 次")

    # 连拉 3 次后限流：已记录 3 次，下一次 check 应被限流
    W._restarts = []
    W._cooldown_until = 0.0
    for _ in range(3):
        W._record_restart()
    ok, why = W.check()
    ck(not ok and "限流" in why, "3b 已拉起 3 次后再次拉起被限流（%s）" % why)
    ck(calls["n"] == 1, "3b 限流时不调用 start_daemon（仍 1 次）")
finally:
    W.daemon_alive = orig_alive
    W.start_daemon = orig_start
    W.lock.clear_stale = orig_clear


print("\n=== 结果：BAD = %d ===" % len(BAD))
sys.exit(1 if BAD else 0)
