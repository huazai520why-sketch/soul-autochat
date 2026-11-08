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


def read_pid():
    try:
        return int(PID_FILE.read_text("utf-8").strip())
    except Exception:
        return 0


def write_pid(pid):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), "utf-8")


def daemon_alive():
    pid = read_pid()
    if pid and lock._alive(pid):
        return True, "pid=%s 活着" % pid
    busy, info = lock.status()
    if busy:
        return True, "锁被 pid=%s 持有" % info.get("pid")
    if pid:
        return False, "pid=%s 已死" % pid
    return False, "没有 pid 记录"


def heartbeat_age():
    d = lock._read()
    if not d:
        return None
    return time.time() - float(d.get("ts") or 0)


def start_daemon():
    """拉起 daemon（分离进程，输出落 logs/daemon.out）。

    🔴 2026-11-03 修复：原来直接起 `guard/daemon.py`，绕过了 `run.py` 的
    `_load_model_env()` —— 被看门狗拉起的实例会用**默认模型**（豆包），
    与手动重启的 deepseek 不一致，而且日志里看不出来。
    现在统一走 `run.py daemon`，与生产入口完全一致。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = open(str(LOG_DIR / "daemon.out"), "ab")
    py = sys.executable
    cmd = [py, "-u", str(ROOT / "run.py"), "daemon"]
    creation = 0
    if os.name == "nt":
        creation = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=out, stderr=out,
                             stdin=subprocess.DEVNULL, creationflags=creation,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except Exception as e:
        log.error("拉起 daemon 失败: %r", e)
        return None
    write_pid(p.pid)
    log.info("已拉起 daemon pid=%s", p.pid)
    return p.pid


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
                pid = read_pid()
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
    # 先清死锁，否则新进程会一直等
    msg = lock.clear_stale()
    log.info("清锁：%s", msg)
    pid = start_daemon()
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
