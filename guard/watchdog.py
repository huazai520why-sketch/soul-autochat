# -*- coding: utf-8 -*-
"""看门狗（对应旧架构 `guard/soul_guard.py`）。

职责只有一件：**daemon 不在了就拉起来**。不抢锁、不碰 App、不改状态。

旧架构的三道闸（这里保留最要紧的两道）：
  ① 锁心跳 > 480s（daemon 每轮 touch）-> 认为卡死
  ② 进程不在了 -> 拉起
  ⚠️ 旧架构教训：`schtasks /Run SoulGuard` 从 SSH（session 0）拉不起 GUI 守护，
     需要登录态（session 1）或由系统计划任务触发。

用法（计划任务每 2 分钟跑一次，或直接常驻）：
    python guard/watchdog.py --once     # 检查一次
    python guard/watchdog.py            # 常驻，每 60s 检查
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.log import get_logger  # noqa: E402
from guard import lock  # noqa: E402

log = get_logger("guard.watchdog")

PID_FILE = ROOT / "data" / "state" / "daemon.pid"
LOG_DIR = ROOT / "logs"

# 🔴🔴 2026-11-08 04:08（stability-forensics 专项：186 次重启的真因）
#
#   改前：HANG_S = 480，而 guard/daemon.py 的 ROUND_BUDGET = 600 ——
#        **数学上必然冲突**：daemon 被允许跑 600s，watchdog 在 480s 就行刑。
#   实测证据（81 次强杀）：
#        · 心跳值 min 480 / p25 510 / median 548 / max 793
#        · **37% 落在刚过线 0~40s 内**，最极端一例「485s > 480s」——过线 5 秒就拔刀
#        · budget 轮均值 672.9s、最大 909s；时长 >480s 的轮 181 次**必然被打**
#   重启史：11-02 07:42 → 11-08 03:26 共 **186 次启动**，
#        平均存活 45min、中位数仅 8.5min、最短 11s。watchdog 占 125 次(67%)。
#
#   改后：HANG_S 提到 900s，并在 daemon 侧补齐轮内心跳（见 daemon._hb）。
#        900s 的取法：
#          · 必须 > ROUND_BUDGET(600) + 单次阶段最坏耗时余量，否则又是同一个坑
#          · 实测单轮最大 1165s 是异常值（含设备假死），正常 600~700s
#          · 取 900s = 600 预算 + 300s 余量，既能容忍正常长轮，
#            又能在**真卡死**时于 15 分钟内介入（原来 8 分钟，误杀率过高）
#        配合轮内心跳后，真正卡死（进程挂住、无任何 touch）仍会被抓到。
HANG_S = float(os.environ.get("SOUL_WATCHDOG_HANG_S", "900") or 900)

# 🔴🔴 2026-11-11（watchdog_restart 一天 243 次 · 看门狗侧防线）
#   daemon 被拉起后**短时间内再次死亡** = 崩溃循环（配置/模型/设备硬故障）。
#   此时无条件再拉起只会变成风暴。规则：5 分钟内第 3 次拉起就停手，
#   改等冷却后再说，期间只告警。真正的病根由 daemon._init_account 的
#   自愈重试 + 落 pid 前移解决；这里只是防「看门狗自己加码」的最后闸。
RESTART_WINDOW_S = float(os.environ.get("SOUL_WATCHDOG_RESTART_WINDOW_S", "300") or 300)
RESTART_MAX_N = int(os.environ.get("SOUL_WATCHDOG_RESTART_MAX", "3") or 3)
RESTART_COOLDOWN_S = float(os.environ.get("SOUL_WATCHDOG_RESTART_COOLDOWN_S", "600") or 600)
_restarts = []          # 最近 N 次拉起时间戳（进程内）
_cooldown_until = 0.0


def read_pid():
    try:
        return int(PID_FILE.read_text("utf-8").strip())
    except Exception:
        return 0


def write_pid(pid):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), "utf-8")


def _real_daemon_pids():
    """反查当前真正存活的 `run.py daemon` 进程 pid（跨会话可靠）。

    🔴 2026-11-13 修复 HY-01（daemon 反复重启循环，P0）：
       watchdog 原来用 `daemon.pid` 文件判活，但该文件被两条启动路径
       竞争写入 —— watchdog 的 `subprocess.Popen` 子进程（锁竞争失败会秒退）
       与 ps1/daemon 自身的 `os.getpid()` 不是同一个进程，导致 pid 记账错配：
       watchdog 记的 pid 是「已死的子进程」，真 daemon 持着锁却没被记。
       改用 CIM 反查命令行含 `run.py daemon` 的进程，跨会话可见、不依赖 pid 文件。
    """
    try:
        import re as _re
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
             "Where-Object { $_.CommandLine -match 'run\\.py\\s+daemon' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, timeout=30)
        out = (r.stdout or b"").decode("utf-8", "replace")
        return [int(x) for x in _re.findall(r"\d+", out)]
    except Exception as e:
        log.warning("反查 daemon pid 失败: %r", e)
        return []


def daemon_alive():
    # 🔴 2026-11-13 修复 HY-01：**锁优先** —— lock 被 owner 持有 = 真 daemon 在跑，
    #   不信 daemon.pid 文件（会被 watchdog 的临时子进程污染成死 pid）。
    busy, info = lock.status()
    if busy:
        opid = info.get("pid")
        return True, "锁被 pid=%s 持有" % opid
    # 锁空时再用 pid 文件兜底（旧 pid 还在跑但锁被误清的罕见场景）
    pid = read_pid()
    if pid and lock._alive(pid):
        return True, "pid=%s 活着（锁空，疑似未持锁）" % pid
    if pid:
        return False, "pid=%s 已死" % pid
    return False, "没有 pid 记录"


def heartbeat_age():
    d = lock._read()
    if not d:
        return None
    return time.time() - float(d.get("ts") or 0)


def _restart_ok():
    """是否允许现在拉起（防看门狗自身加码成风暴）。

    🔴🔴 2026-11-11（watchdog_restart 一天 243 次 · 看门狗侧防线）：
      病根在 daemon 启动即崩（无 pid / 设备故障），上面 _init_account 已根治；
      这里再给看门狗自己上一道闸：5 分钟内拉起 >= RESTART_MAX_N 次就停手，
      冷却 RESTART_COOLDOWN_S 秒，期间只告警不拉 —— 避免「拉起→再崩→再拉」
      由每 60s 一次的检查频率本身放大成刷屏风暴。
    """
    global _cooldown_until
    now = time.time()
    if now < _cooldown_until:
        return False, "冷却中（剩 %.0fs）" % (_cooldown_until - now)
    # 只保留窗口内的时间戳
    while _restarts and (now - _restarts[0]) > RESTART_WINDOW_S:
        _restarts.pop(0)
    if len(_restarts) >= RESTART_MAX_N:
        _cooldown_until = now + RESTART_COOLDOWN_S
        _restarts.clear()
        return False, "5 分钟内拉起已达 %d 次 → 冷却 %.0fs" % (
            RESTART_MAX_N, RESTART_COOLDOWN_S)
    return True, "ok"


def _record_restart():
    _restarts.append(time.time())


def start_daemon():
    """拉起 daemon —— **统一走 `tools/start_daemon.ps1`**（生产唯一入口）。

    🔴 2026-11-13 修复 HY-01（daemon 反复重启循环，P0）：
       原来 watchdog 自己 `subprocess.Popen([py,"-u","run.py","daemon"])`，
       并 `write_pid(p.pid)` 记**自己子进程**的 pid —— 而真正持锁的 daemon
       是 ps1 用 `Start-Process` 拉起的另一个进程（daemon.py:1269 写 os.getpid()）。
       两条路径并存 + pid 记账错配 → watchdog 下轮读到「已死子进程 pid」→
       判「daemon 不在」→ 再拉起 → 循环（21:43~23:18 实测 7+ 次重启，136 个 lock.bak）。
       修复：watchdog 不再 Popen，改调 ps1（ps1 有「已存在即跳过」判活），
       pid 由 daemon 自身落盘，watchdog 只判 lock/进程存活，不写 pid。
    """
    try:
        ps1 = ROOT / "tools" / "start_daemon.ps1"
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True, timeout=90)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
        if r.returncode != 0 and "already running" not in out:
            log.warning("start_daemon.ps1 返回 %s: %s", r.returncode, out[:200])
        # ps1 成功拉起后会自己写 daemon.pid（daemon.py:1269），这里不重复写。
        pids = _real_daemon_pids()
        if pids:
            log.info("已拉起 daemon（ps1 路径，存活 pid=%s）", pids)
            return pids[0]
        log.warning("ps1 返回但未发现存活 daemon 进程")
        return None
    except Exception as e:
        log.error("拉起 daemon 失败: %r", e)
        return None


def check():
    """返回 (是否健康, 说明)。不健康时会尝试拉起。"""
    alive, why = daemon_alive()
    if alive:
        age = heartbeat_age()
        if age is not None and age > HANG_S:
            log.warning("daemon %s，但心跳已 %.0fs（>%.0fs）→ 判卡死", why, age, HANG_S)
            # 🔴 2026-11-03 修复：原来只 return False，main 只打一行日志 ——
            #    进程活着但卡死的 daemon 永远不会被重启（§79 blocked 4h52m 就是这种）。
            #    这里直接强杀 + 清锁，下一轮检查会重新拉起。
            if os.environ.get("SOUL_WATCHDOG_KILL", "1") != "0":
                # 🔴 2026-11-13 修复 HY-01：以 lock owner 为准杀，别用 daemon.pid 文件
                #   （可能被 watchdog 临时子进程污染成死 pid）。
                _, info = lock.status()
                pid = info.get("pid") or read_pid()
                if pid:
                    try:
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True, timeout=30, check=False)
                        log.warning("已强杀卡死 daemon pid=%s，下一轮检查会重新拉起", pid)
                    except Exception as e:
                        log.error("强杀卡死 daemon 失败: %r", e)
                try:
                    msg = lock.clear_stale()
                    log.info("清锁：%s", msg)
                except Exception as e:
                    log.warning("清锁失败: %r", e)
            return False, "心跳 %.0fs 超时（已处置）" % age
        return True, why

    log.warning("daemon 不在（%s）→ 拉起", why)
    # 🔴 2026-11-11：拉起频率闸。daemon 反复「拉起→秒崩」时不要再火上浇油，
    #    否则 watchdog 自己的频率就是风暴源（一天 243 次）。
    ok_r, why_r = _restart_ok()
    if not ok_r:
        log.warning("拉起被限流：%s（daemon 可能持续崩溃，待冷却后重试）", why_r)
        return False, "拉起被限流（%s）" % why_r
    # 先清死锁，否则新进程会一直等
    msg = lock.clear_stale()
    log.info("清锁：%s", msg)
    pid = start_daemon()
    if pid is not None:
        _record_restart()
    return (pid is not None), ("已拉起 pid=%s" % pid if pid else "拉起失败")


def main(argv=None):
    """argv=None → 用 sys.argv（直接命令行运行）；传 [] → 不解析顶层子命令。

    🔴 2026-11-03：run.py 会把自己的子命令 `watchdog` 留在 sys.argv 里，
    这里再解析就会判「未知参数」exit 2；所以由 run.py 显式传 []。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=float, default=60.0)
    args = ap.parse_args(argv)

    if args.once:
        ok, why = check()
        print(("[OK] " if ok else "[FAIL] ") + why)
        return 0 if ok else 1

    log.info("看门狗启动，每 %.0fs 检查一次", args.every)
    while True:
        try:
            ok, why = check()
            if not ok:
                log.warning("检查未通过：%s", why)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("看门狗异常（已兜住）: %r", e)
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
