# -*- coding: utf-8 -*-
"""全局锁：保证同一时刻只有一个 daemon 在操作模拟器。

对应旧架构 `guard/soul_global_lock.py` 的核心判据（保留三条，去掉调度复杂度）：

  ① 持锁 pid 已死        → 立即接管（旧架构最常见的人工重启后孤儿锁）
  ② 心跳超过 HEARTBEAT_S → 接管（进程活着但卡死）
  ③ TTL 到期             → 接管

旧架构里踩过的坑（这里一并规避）：
  - **只换 pid 不删锁**：live_push 软重启后旧进程退出没删锁，新进程读到"活锁
    且 owner 在运行"→ 一直等，空转 2.5~15 分钟。所以这里每次 start_round 前
    都**先判 owner 是否真活着**，死了立刻接管并打印接管原因。
  - **把别人的心跳刷成自己的**：只有真拿到锁才 touch，没拿到绝不写文件。

用法：
    from guard import lock
    ok, why = lock.acquire("daemon")
    if ok:
        try:
            lock.touch("pull")
            ...
        finally:
            lock.release()
"""
import json
import os
import socket
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("guard.lock")

LOCK_FILE = STATE / "daemon.lock"
HEARTBEAT_S = 15 * 60        # 心跳超过 15 分钟 -> 判死
TTL_S = 55 * 60              # 锁最长 55 分钟（防僵尸）
STEP_HANG_S = 8 * 60         # 同一步骤超过 8 分钟 -> 判卡死

_held = False
_pid = os.getpid()


# ---------------- 进程存活 ----------------
def _alive(pid):
    if not pid:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid == _pid:
        return True
    if os.name == "nt":
        # Windows：先用 OpenProcess 探测（快、不限权限）
        try:
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
        except Exception:
            pass
        # 🔴 2026-11-03 修复 P0（守护重复拉起）：计划任务里的 watchdog 跑在
        #    session 1，而 WMI 从 SSH 起的 daemon 在 session 0 —— 跨会话时
        #    OpenProcess 可能返回空句柄，把**活进程判死** → clear_stale 删锁 →
        #    再拉一个 daemon（实测 14:44 出现 8752/16108 双实例）。
        #    tasklist 是跨会话可见的，用它兜底确认。
        try:
            import subprocess
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                               capture_output=True, timeout=10)
            txt = (r.stdout or b"").decode("gbk", "ignore") + \
                  (r.stderr or b"").decode("gbk", "ignore")
            if str(pid) in txt:
                return True
        except Exception:
            pass
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


# ---------------- 文件 ----------------
def _read():
    try:
        return json.loads(LOCK_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _write(d):
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        return True
    except Exception as e:
        log.warning("写锁失败: %r", e)
        return False


def _atomic_create(d):
    """原子创建锁文件（O_EXCL），已存在则失败。返回 True/False。

    🔴 2026-11-03 修复 P2：acquire 原来「status() 读空 + write_text 写锁」两步
    非原子，两个 daemon 同时启动可能都读到空锁、先后覆盖、双双持锁运行。
    O_EXCL 创建保证同一时刻只有一个进程能创建成功。
    """
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except Exception as e:
        log.warning("创建锁文件失败: %r", e)
        return False
    try:
        os.write(fd, json.dumps(d, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def status():
    """返回 (是否被别的进程持有, 锁信息)。"""
    d = _read()
    if not d:
        return False, {}
    pid = d.get("pid")
    ts = float(d.get("ts") or 0)
    age = time.time() - ts
    if pid == _pid:
        return False, d
    if not _alive(pid):
        return False, dict(d, why="owner %s 已死" % pid)
    if age > HEARTBEAT_S:
        return False, dict(d, why="心跳 %.0fs 超时" % age)
    if age > TTL_S:
        return False, dict(d, why="TTL 到期")
    return True, d


# ---------------- 对外 ----------------
def acquire(owner="daemon"):
    """抢锁。返回 (ok, why)。ok=True 时本进程持锁。

    🔴 2026-11-03 修复 P2：原来「status() 判空 + _write 写锁」两步非原子，
    两个 daemon 同时启动可能都读到空锁、先后覆盖、双双进入运行。
    改为 O_EXCL 原子创建锁文件：只有一个进程能创建成功；死锁接管先原子搬走旧锁。
    """
    global _held
    if _held:
        return True, "已持有"
    busy, info = status()
    if busy:
        return False, "被 pid=%s 占用（%s）" % (info.get("pid"), info.get("step") or "?")

    now = time.time()
    why = info.get("why")
    # 死锁接管（owner 死 / 心跳超时 / TTL 到期）：先原子搬走旧锁，再原子创建新锁。
    # os.replace 原子重命名，两个进程竞争接管时只有一个能成功搬走。
    if why and LOCK_FILE.exists():
        try:
            bak = LOCK_FILE.with_name(LOCK_FILE.name + ".bak-%d-%d" % (int(time.time()), _pid))
            os.replace(str(LOCK_FILE), str(bak))
        except FileNotFoundError:
            pass            # 别人已搬走，继续尝试创建（大概率创建失败，安全）
        except Exception as e:
            return False, "搬走死锁失败: %r" % e

    d = {"pid": _pid, "owner": owner, "host": socket.gethostname(),
         "ts": now, "start": now, "step": "acquire", "gen": info.get("gen", 0) + 1}
    if not _atomic_create(d):
        # 竞态：另一进程刚创建了锁（或刚接管）→ 保守放弃，下一轮再试
        return False, "锁刚被其他进程抢占，稍后再试"
    _held = True
    if why:
        log.warning("接管锁：%s（旧 pid=%s）", why, info.get("pid"))
    log.info("🔒 拿到锁 pid=%s gen=%s", _pid, d["gen"])
    return True, "ok"


def touch(step=""):
    """刷新心跳。只有持锁时才写。"""
    if not _held:
        return
    d = _read()
    if d.get("pid") != _pid:
        # 锁被别人接管了（自己的心跳不该续别人的命）
        return
    d["ts"] = time.time()
    if step:
        if d.get("step") != step:
            d["step"] = step
            d["step_ts"] = time.time()
    _write(d)


def step_age():
    d = _read()
    if d.get("pid") != _pid:
        return 0
    return time.time() - float(d.get("step_ts") or d.get("ts") or 0)


def release():
    global _held
    if not _held:
        return
    d = _read()
    if d.get("pid") == _pid:
        try:
            LOCK_FILE.unlink()
            log.info("🔓 释放锁 pid=%s", _pid)
        except Exception as e:
            log.warning("删锁失败（留孤儿锁）: %r", e)
    _held = False


def clear_stale():
    """强制清理死锁（人工运维用）。返回说明。"""
    busy, info = status()
    if busy:
        return "仍被活进程持有（pid=%s），不清" % info.get("pid")
    if LOCK_FILE.exists():
        try:
            bak = LOCK_FILE.with_suffix(".lock.bak-%d" % int(time.time()))
            LOCK_FILE.replace(bak)
            return "已清理（备份 %s）" % bak.name
        except Exception as e:
            return "清理失败: %r" % e
    return "没有锁文件"
