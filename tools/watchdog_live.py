# -*- coding: utf-8 -*-
"""生产守护 v2：检测 daemon 存活 + 卡死 + 死循环，自动处置。

🔴🔴 v1 的致命 bug（必须记）：v1 用 `logs/daemon.out` 的 mtime 判活，
   但生产是用 `pythonw.exe run.py daemon` 由计划任务拉起的，**stdout 没有重定向**，
   daemon.out 从 01:16 之后就不再更新。于是 v1 每 2 分钟都会判「静默 > 240s」
   → kill 掉**完全健康**的 daemon → 再拉起 → 再判 → 无限误杀。
   这就是「脚本瞎操作、空烧」的直接原因之一。
   v2 改成看**模块日志**（brain.pendingq.log / brain.act.log / core.device.log），
   这些由 logging 的 RotatingFileHandler 写，与 stdout 重定向无关。

处置规则（每 2 分钟一次，由计划任务 SoulLiveWatch 拉起）：
  · daemon 进程不在              → 拉起
  · 三个模块日志**全部**静默 > 300s → 判定卡死，kill + 拉起
  · 10 分钟内「强制重启 Soul」>= 4 → 判定死循环，kill + 拉起
  · 设备掉线                     → adb connect
所有动作写 alerts.log。
"""
import io
import json
import os
import re
import subprocess
import sys
import time

if getattr(sys.stdout, "buffer", None) is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
else:
    # 计划任务用 pythonw.exe 启动时 sys.stdout 可能是 None；直接访问 .buffer
    # 会令进程在导入阶段退出 1。无控制台时丢弃普通 print，异常仍写 alerts.log。
    sys.stdout = io.StringIO()
if getattr(sys.stderr, "buffer", None) is not None:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
else:
    sys.stderr = io.StringIO()

ROOT = r"E:\soul1.0"
LOGDIR = os.path.join(ROOT, "logs")
ALERT = os.path.join(LOGDIR, "alerts.log")
PYW = os.environ.get("SOUL_PYW") or sys.executable.replace("python.exe", "pythonw.exe")
ADB = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
if not os.path.exists(ADB):
    ADB = r"D:\MuMuPlayer\nx_main\adb.exe"
MM = r"D:\MuMuPlayer\nx_main\MuMuManager.exe"
if not os.path.exists(MM):
    MM = r"D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe"
LAUNCH_STATE = os.path.join(ROOT, "data", "state", "watchdog_live_mumu_launch.ts")
LOCK_JSON = os.path.join(ROOT, "data", "state", "daemon.lock")

# 判活用的模块日志：只要其中**任意一个**在动，就说明 daemon 活着
LIVE_LOGS = ("brain.pendingq.log", "brain.act.log", "core.device.log",
             "brain.clear.log", "data.imdb.log", "brain.wake.log")
STALL_SEC = 300
LOOP_WINDOW = 600
LOOP_RESTART_MAX = 4


def say(msg):
    line = "[watchdog] %s %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(ALERT, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _ps(cmd):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        say("powershell 失败 %r" % (e,))
        return ""


def daemon_pids():
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
              "Where-Object { $_.CommandLine -match 'run\\.py\\s+daemon' } | "
              "ForEach-Object { $_.ProcessId }")
    return [int(x) for x in re.findall(r"\d+", out)]


def watchdog_pids():
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
              "Where-Object { $_.CommandLine -match 'run\\.py\\s+watchdog' } | "
              "ForEach-Object { $_.ProcessId }")
    return [int(x) for x in re.findall(r"\d+", out)]


def kill_daemon():
    _ps("Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
        "Where-Object { $_.CommandLine -match 'run\\.py\\s+daemon' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def start_daemon():
    """必须用计划任务拉起 —— 直接 Start-Process 会被 ssh 会话结束时连带杀掉。"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Start-ScheduledTask -TaskName 'SoulGuard'"],
                       capture_output=True, timeout=60)
        return True
    except Exception as e:
        say("拉起失败 %r" % (e,))
        return False


def live_age():
    """返回 (最年轻的模块日志 age, 那个日志名)。"""
    best, name = 1e9, "-"
    for f in LIVE_LOGS:
        p = os.path.join(LOGDIR, f)
        if not os.path.exists(p):
            continue
        a = time.time() - os.path.getmtime(p)
        if a < best:
            best, name = a, f
    return best, name


def lock_age():
    """Age of the daemon's own heartbeat, or None when the lock has no timestamp."""
    try:
        with open(LOCK_JSON, "r", encoding="utf-8") as f:
            d = json.load(f) or {}
        raw = d.get("step_ts") or d.get("ts")
        return max(0.0, time.time() - float(raw)) if raw else None
    except Exception:
        return None


def count_restart_app(window=LOOP_WINDOW):
    p = os.path.join(LOGDIR, "brain.nav.log")
    if not os.path.exists(p):
        return 0
    try:
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 300000))
            txt = f.read().decode("gbk", errors="replace")
    except Exception:
        return 0
    now = time.time()
    cnt = 0
    for l in txt.splitlines():
        if "重启 Soul" not in l and "重启 App" not in l:
            continue
        m = re.match(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", l)
        if not m:
            continue
        try:
            ts = time.mktime((time.localtime().tm_year, int(m.group(1)), int(m.group(2)),
                              int(m.group(3)), int(m.group(4)), int(m.group(5)), 0, 0, -1))
        except Exception:
            continue
        if now - ts <= window:
            cnt += 1
    return cnt


def adb_ok():
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, timeout=20)
        return "127.0.0.1:16384\tdevice" in r.stdout.decode("utf-8", "replace")
    except Exception:
        return False


def launch_mumu():
    """adb 不通时拉起 MuMu 实例；10 分钟节流，避免任务每 2 分钟重复 launch。"""
    now = time.time()
    try:
        with open(LAUNCH_STATE, "r", encoding="ascii") as f:
            last = float((f.read() or "0").strip())
    except Exception:
        last = 0.0
    if now - last < 600:
        say("MuMu 实例疑似未启动，但 10 分钟内已尝试 launch → 等待下一轮")
        return False
    if not os.path.exists(MM):
        say("MuMuManager 不存在，无法自动 launch: %s" % MM)
        return False
    try:
        os.makedirs(os.path.dirname(LAUNCH_STATE), exist_ok=True)
        with open(LAUNCH_STATE, "w", encoding="ascii") as f:
            f.write(str(now))
        r = subprocess.run([MM, "control", "-v", "0", "launch"],
                           capture_output=True, timeout=120)
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        say("adb 不通 → MuMu launch rc=%s %s" % (r.returncode, out[:120]))
    except Exception as e:
        say("MuMu launch 失败: %r" % (e,))
        return False
    # 实测 Android 需要 30~90s 才上线；本轮最多等 40s，下一轮任务继续确认。
    for _ in range(8):
        time.sleep(5)
        if adb_ok():
            say("MuMu launch 后设备已恢复")
            return True
    return False


def main():
    pids = daemon_pids()
    age, which = live_age()
    lage = lock_age()
    restarts = count_restart_app()

    if not adb_ok():
        say("设备掉线 → adb connect")
        try:
            subprocess.run([ADB, "connect", "127.0.0.1:16384"],
                           capture_output=True, timeout=20)
        except Exception:
            pass
        time.sleep(3)
        if not adb_ok():
            if not launch_mumu():
                say("设备仍不可用 → 本轮不杀 daemon，等 MuMu 启动后再检查")
                return 0

    if not pids:
        say("daemon 不在 → 用计划任务 SoulGuard 拉起")
        start_daemon()
        return 0

    if restarts >= LOOP_RESTART_MAX:
        say("死循环（%ds 内重启 Soul %d 次）→ kill 并拉起" % (LOOP_WINDOW, restarts))
        kill_daemon()
        time.sleep(2)
        start_daemon()
        return 0

    if age > STALL_SEC and (lage is None or lage > STALL_SEC):
        say("全部模块日志静默 %.0fs（>%ds）→ 判定卡死，kill 并拉起" % (age, STALL_SEC))
        kill_daemon()
        time.sleep(2)
        start_daemon()
        return 0

    print("[watchdog] %s 正常 pids=%s 最活跃日志=%s(%.0fs) lock=%s 重启Soul=%d"
          % (time.strftime("%H:%M:%S"), pids, which, age,
             ("%.0fs" % lage) if lage is not None else "missing", restarts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
