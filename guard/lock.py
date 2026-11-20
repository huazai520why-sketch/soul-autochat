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

# 🔴 2026-11-20 修复（F4 P1）：写锁偶发失败被升级成杀轮
#   原状：touch() 把「写文件失败」和「锁 owner 已变更」都折叠成 return False，
#   调用方（daemon._hb）一律走 ensure→失败即 raise → 整轮异常。
#   实测 07:31:57 `写锁失败: PermissionError(13, '拒绝访问。')`（Windows 文件句柄
#   竞争 / 杀软瞬时锁定），owner 其实还是自己，却因写不进去被判死、杀掉整轮。
#   现在用两个**真值均为 False** 的字符串信号区分：
#     · TOUCH_OWNER_CHANGED → 锁真被别的 pid 占用（互斥被破坏）→ 调用方应 raise
#     · TOUCH_WRITE_FAILED  → owner 仍是自己、只是这一下没写成 → 调用方降级 warning
#   两个都保持 falsy，兼容只判真假的既有调用点（见文件头用法示例）。
TOUCH_OWNER_CHANGED = "owner_changed"
TOUCH_WRITE_FAILED = "write_failed"


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
    """原子写锁文件（tmp + os.replace），崩溃不留半截 JSON。

    🔴 2026-11-14（B3 P1）：原 write_text 非原子，中途崩溃会留半截 JSON，
    `_read` 的 json.loads 抛异常 → 返回 {} → status() 判「未持锁」→
    另一进程可能同时抢锁，放大竞态。与 `_save_skip` / `_save` 同款方案。
    """
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOCK_FILE.with_name(LOCK_FILE.name + ".tmp-%d" % _pid)
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        os.replace(str(tmp), str(LOCK_FILE))
        return True
    except Exception as e:
        # 🔴 2026-11-20 修复（F4 P1）：PermissionError(13) 这类 Windows 文件句柄
        #   竞争 / 杀软瞬时锁定往往是**一瞬间**的，立即重试一次就能成功，不值得
        #   上升成杀轮。只重试一次（不是无限），仍失败才返回 False，由调用方降级。
        try:
            time.sleep(0.05)
            tmp = LOCK_FILE.with_name(LOCK_FILE.name + ".tmp-%d" % _pid)
            tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
            os.replace(str(tmp), str(LOCK_FILE))
            log.info("写锁重试成功（首次失败: %r）", e)
            return True
        except Exception as e2:
            log.warning("写锁失败（重试后仍失败）: %r / %r", e, e2)
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
    if not LOCK_FILE.exists():
        return False, {}
    d = _read()
    if not d:
        return False, {"why": "锁文件为空或损坏"}
    pid = d.get("pid")
    ts = float(d.get("ts") or 0)
    age = time.time() - ts
    if pid == _pid:
        return False, d
    if not _alive(pid):
        return False, dict(d, why="owner %s 已死" % pid)
    # 2026-11-14（G8）：TTL(55min) > 心跳(15min)，原顺序下 TTL 分支不可达。
    #   先判 TTL 再判心跳，语义才与注释一致。
    if age > TTL_S:
        return False, dict(d, why="TTL 到期")
    if age > HEARTBEAT_S:
        return False, dict(d, why="心跳 %.0fs 超时" % age)
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


def ensure(owner="daemon"):
    """Ensure this process still owns a lock.

    This is a safety net for a lock file being removed or replaced while the
    daemon is already running. If the file merely vanished, the current owner
    atomically recreates it. If another live process owns it, this process
    reports failure so the caller can stop instead of running a second daemon.
    """
    global _held
    if not _held:
        return acquire(owner)
    d = _read()
    if d.get("pid") == _pid:
        return True, "已持有"

    _held = False
    ok, why = acquire(owner)
    if ok:
        log.warning("daemon 锁丢失/被替换 → 当前进程已自愈重建")
    return ok, why


def touch(step=""):
    """刷新心跳。只有持锁时才写。

    🔴 2026-11-14（B3 P1）：原 owner 变更时只 log.error + return False，不自愈也不上抛；
    调用点若忽略返回值，本进程会在「已不是 owner」状态下继续跑（_held 仍 True），
    与接管进程并发操作模拟器。现在 owner 变更后直接调 ensure(owner) 尝试原地自愈，
    自愈失败（别人真活着且锁合法）再 return False，由调用方决定收工。
    """
    global _held
    if not _held:
        return False
    d = _read()
    if d.get("pid") != _pid:
        # 锁被别人接管了（自己的心跳不该续别人的命）→ 真正的 owner 变更
        log.error("心跳失败：锁 owner 已变为 pid=%s（本进程 pid=%s）→ 尝试原地自愈",
                  d.get("pid"), _pid)
        _held = False
        ok, why = ensure(step or "daemon")
        if ok:
            return True
        log.error("心跳自愈失败：%s → 本进程应立即停止操作模拟器", why)
        # 🔴 2026-11-20 修复（F4 P1）：返回明确的「owner 变更」信号，
        #   让调用方知道这是互斥被破坏、必须停下，而不是一次普通的写失败。
        return TOUCH_OWNER_CHANGED
    d["ts"] = time.time()
    if step:
        if d.get("step") != step:
            d["step"] = step
            d["step_ts"] = time.time()
    # 🔴 2026-11-20 修复（F4 P1）：到这里 owner 仍是自己，_write 失败只是
    #   「这一下没写成」（Windows 句柄竞争 / 杀软瞬时锁定），不是丢锁。
    #   返回 TOUCH_WRITE_FAILED（仍为 falsy）让调用方降级 warning，
    #   而不是当成 owner 丢失去 raise 杀掉整轮。
    return True if _write(d) else TOUCH_WRITE_FAILED


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
