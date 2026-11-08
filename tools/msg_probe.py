# -*- coding: utf-8 -*-
"""新消息探针：她的消息超过 N 秒还没处理，就自动定位原因并修（2026-11-04 用户要求）。

为什么需要独立进程：
  daemon 自己「病了」的时候（卡死、被降级预算拖住、冷却误伤、进程没了）
  是没法自己汇报的 —— 必须有外部视角。这个探针只做两件事：
    ① 用**设备端 sqlite3**（0.05~0.3s，永远是最新库）判定「有没有 >SLA 秒未读」；
    ② 按证据分档处置：清过期冷却 / 杀卡死进程让 guard 重拉 / 拉起缺失进程，
       其余情况只记证据（判据不足时不动手）。

判据（尽量只用可核实的）：
  · 未处理 = session.unReadCount > 0 且 her_ts 距今 > SLA（打开会话读消息会清零未读）
  · 卡死   = daemon.lock.step_ts 距今 > STUCK_S（daemon 每个步骤都会 touch）
  · 进程没了 = data/state/daemon.pid 指向的 pid 不存在
  · 冷却误伤 = pending_skip.json 里有该 sid，且她的消息时间 **晚于** 记冷却的时间

⚠️ 刻意的边界：探针**不动屏幕、不发消息**（会和 daemon 抢屏，风险远大于收益）。
   它只改状态文件、杀/拉起进程。真正的回复仍由 daemon 做。

用法：
  python tools/msg_probe.py              # 常驻循环（默认 15s 一轮，SLA 60s）
  python tools/msg_probe.py --once       # 只跑一轮（诊断/调试用）
  python tools/msg_probe.py --dry        # 只诊断不处置
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE = os.path.join(ROOT, "data", "state")
LOGS = os.path.join(ROOT, "logs")
PROBE_LOG = os.path.join(LOGS, "msg_probe.log")
PROBE_STATE = os.path.join(STATE, "msg_probe.json")
LOCKFILE = os.path.join(STATE, "msg_probe.lock")
DAEMON_OUT = os.path.join(LOGS, "daemon.out")
SKIPFILE = os.path.join(STATE, "pending_skip.json")
PIDFILE = os.path.join(STATE, "daemon.pid")
LOCKJSON = os.path.join(STATE, "daemon.lock")
START_PS1 = os.path.join(ROOT, "tools", "start_daemon.ps1")

DBDIR = "/data/data/cn.soulapp.android/databases"
SP_INFO = "/data/data/cn.soulapp.android/shared_prefs/sp_info_gather.xml"
SYS_TEXT_HINTS = ("[互动消息]", "[互动提醒]", "[系统消息]", "[官方消息]")
SKIP_UID_PREFIX = ("2042683",)     # 官方营销号段


# ---------------- 基础设施 ----------------
def _now():
    return time.time()


def _ts():
    return time.strftime("%m-%d %H:%M:%S")


def log(msg):
    """写日志文件（UTF-8）+ 控制台（ASCII 安全）。"""
    line = "%s %s" % (_ts(), msg)
    try:
        os.makedirs(LOGS, exist_ok=True)
        with io.open(PROBE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line.encode("ascii", "replace").decode("ascii"))
    except Exception:
        pass


def load_json(p, default):
    try:
        with io.open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(p, obj):
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception as e:
        log("save_json fail %r" % (e,))


# ---------------- 单实例锁 ----------------
def _pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/FO", "CSV", "/NH"],
                             capture_output=True, timeout=15).stdout.decode("utf-8", "ignore")
        return str(pid) in out
    except Exception:
        return True          # 判不了就当作活着，别起第二个


def acquire_lock():
    d = load_json(LOCKFILE, {})
    pid = int(d.get("pid") or 0)
    if pid and pid != os.getpid() and _pid_alive(pid):
        return False
    save_json(LOCKFILE, {"pid": os.getpid(), "ts": _now()})
    return True


def touch_lock():
    save_json(LOCKFILE, {"pid": os.getpid(), "ts": _now()})


# ---------------- 设备侧取数 ----------------
_DEV = None


def dev():
    global _DEV
    if _DEV is None:
        from core.device import Device
        _DEV = Device.get()
    return _DEV


_WRITE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"vacuum|reindex|pragma\s+\w+\s*=)\b", re.I)


def _assert_readonly(q):
    """🔴 2026-11-08 10:46 用户硬规则：模拟器内实时库**只读不写**。"""
    s = (q or "").strip().lstrip(";").strip()
    low = s.lower()
    if not s or not (low.startswith("select") or low.startswith("with")):
        log("⛔ 拒绝非只读 SQL（设备库只读）: %r" % (s[:120],))
        return False
    if _WRITE_RE.search(s):
        log("⛔ 拒绝含写操作的 SQL（设备库只读）: %r" % (s[:120],))
        return False
    return True


def _sqlite(d, nm, q, timeout=20):
    """设备端只读查库（自动适配 su / 无 su 两种 shell）。

    🔴 2026-11-08 21:0x（SLA 监控整天瞎掉的根因）：
      本机（MuMu userdebug）**没有 su**（`/system/bin/sh: su: inaccessible`），
      adb shell 本身就是 root。旧实现只写 su 形态 → 归属判定永远拿到空输出
      → 每 15s 打一条「找不到归属 uid=*** 的库 → 不查」，
      60s SLA 监控实际从没生效过（所以「消息几小时不回」没人报警）。
      现在先走裸 sqlite3（实测 /system/bin/sqlite3 存在），失败再退回 su。
    """
    for cmd in ('sqlite3 "%s/%s" "%s" 2>&1' % (DBDIR, nm, q),
                "su -c 'sqlite3 \"%s/%s\" \"%s\"' 2>&1" % (DBDIR, nm, q)):
        txt = d.text(cmd, timeout=timeout) or ""
        if txt.strip():
            return txt
    return ""


def sql(q, timeout=20):
    """在**设备上**直查当前 IM 库（0.05~0.3s，永远最新）。

    返回 (行列表, 库个数)。设备上找不到 sqlite3 时返回 ([], 0)。

    🔴🔴 2026-11-08 10:46（两处生产事故级修复）
      【A 只读铁律】用户硬规则「模拟器内的实时库只允许读，不允许写」。
        设备端 sqlite3 是以 root 跑的，写了无法回滚 → 这里加**强制只读闸**，
        只放行 SELECT/WITH，命中写关键字直接拒绝（见 `_assert_readonly`）。
      【B 跨账号串库】改前 `for nm in dbs:` **把两个账号的库结果合并进同一个 out**，
        而设备上同时存在 96691646 和 402857053 两个库 —— 于是探针会拿
        A 账号的会话当成 B 账号的未读，正是用户明确禁止的
        「用 A 账号的聊天记录去 B 账号搜」。
        改法：先用 sp_info 定当前 uid → 只查**归属当前 uid 的那一个库**
        （判据 sessionId == uid || toUserId）→ 定不到就返回空（宁可不动，不可串号）。
      【C root】/data/data 是 u0_a52 私有目录，非 root 的 ls 必然 Permission denied
        （实测 10:35 返回空 → 探针静默失效）。全部改走 `su -c`。
    """
    if not _assert_readonly(q):
        return [], 0
    d = dev()
    # ---- 列库（必须 su）----
    dbs = []
    for cmd in ("su -c 'ls -1 %s'" % DBDIR, "ls -1 " + DBDIR):
        paths = d.text(cmd, timeout=15) or ""
        dbs = [x.strip() for x in paths.replace("\r", "").splitlines()
               if x.strip().endswith("-DATA.db")]
        if dbs:
            break
    if not dbs:
        return [], 0

    # ---- 定当前账号 uid（必须 su）----
    uid = None
    for cmd in ("su -c 'cat %s 2>/dev/null'" % SP_INFO,
                "cat %s 2>/dev/null" % SP_INFO):
        raw = d.text(cmd, timeout=20) or ""
        m = re.search(r'name="userid">(\d+)<', raw)
        if m:
            uid = m.group(1)
            break

    # ---- 只查归属当前 uid 的那个库 ----
    targets = []
    if uid:
        for nm in dbs:
            q2 = ("select count(*) from session where sessionId='%s'||toUserId"
                  % uid)
            txt = _sqlite(d, nm, q2, timeout=timeout)
            hit = 0
            for ln in txt.replace("\r", "").splitlines():
                ln = ln.strip()
                if ln.isdigit():
                    hit = int(ln)
                    break
            if hit > 0:
                targets = [nm]
                break
        if not targets:
            log("msg_probe：找不到归属 uid=%s 的库 → 不查（防串号）" % uid)
            return [], len(dbs)
    else:
        # 定不到 uid 时**不猜**：只用第一个库也危险，直接放弃（宁可少报，不可串号）
        log("msg_probe：定不到当前登录 uid → 不查（防串号）")
        return [], len(dbs)

    out = []
    for nm in targets:
        raw = _sqlite(d, nm, q, timeout=timeout)
        for ln in raw.replace("\r", "").splitlines():
            ln = ln.strip()
            if not ln or ln.lower().startswith("error") or "no such" in ln.lower():
                continue
            out.append(ln)
    return out, len(targets)


def unread_sessions():
    """[(uid, sid, unread, her_ts_ms, text)]，按 her_ts 倒序。"""
    rows, ndb = sql("select toUserId, sessionId, unReadCount, timestamp, "
                    "ifnull(lastMsgText,'') from session where unReadCount>0 "
                    "order by timestamp desc limit 30")
    out = []
    for ln in rows:
        parts = ln.split("|")
        if len(parts) < 5:
            continue
        uid, sid, unread, ts, txt = parts[0], parts[1], parts[2], parts[3], parts[4]
        try:
            if int(uid) <= 0:            # 负数是群/系统会话，不是真人
                continue
        except Exception:
            continue
        if any(str(uid).startswith(p) for p in SKIP_UID_PREFIX):
            continue
        if any(h in txt for h in SYS_TEXT_HINTS):
            continue
        try:
            out.append((str(uid), str(sid), int(unread), int(float(ts)), txt))
        except Exception:
            continue
    return out, ndb


# ---------------- daemon 体检 ----------------
def daemon_health():
    pid = 0
    try:
        pid = int((io.open(PIDFILE, "r", encoding="utf-8").read() or "0").strip() or 0)
    except Exception:
        pid = 0
    alive = bool(pid) and _pid_alive(pid)
    lock = load_json(LOCKJSON, {})
    step_age = None
    try:
        step_age = _now() - float(lock.get("step_ts") or lock.get("ts") or 0)
    except Exception:
        step_age = None
    log_age = None
    try:
        log_age = _now() - os.path.getmtime(DAEMON_OUT)
    except Exception:
        log_age = None
    return {"pid": pid, "alive": alive, "step_age": step_age,
            "lock_step": lock.get("step"), "log_age": log_age}


def tail_daemon(n=120):
    try:
        with io.open(DAEMON_OUT, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 120000))
            data = f.read().decode("utf-8", "ignore")
        return data.splitlines()[-n:]
    except Exception:
        return []


def last_relevant_evidence(sid, uid):
    """从 daemon.out 尾部找和这个会话/uid 有关的最后几行（用作日志证据）。"""
    ev = []
    for ln in tail_daemon(400):
        if sid in ln or ("uid=" + uid) in ln or ("'" + uid + "'") in ln:
            ev.append(ln.strip()[:160])
    return ev[-3:]


# ---------------- 处置 ----------------
def clear_skip(sid, her_ts_ms, dry):
    """她的消息比冷却记录更晚 → 这条冷却是过期的，清掉（必回优先）。"""
    d = load_json(SKIPFILE, {})
    rec = d.get(str(sid))
    if not isinstance(rec, dict):
        return None
    try:
        skip_ts = float(rec.get("ts") or 0)
    except Exception:
        return None
    if float(her_ts_ms) / 1000.0 <= skip_ts + 1.0:
        return None                      # 冷却是在这条消息之后记的，仍然有效
    reason = rec.get("reason") or "?"
    left = (float(rec.get("hours") or 0) * 60
            - (_now() - skip_ts) / 60.0)
    if dry:
        log("[dry] 会清掉过期冷却 sid=%s reason=%s 原剩 %.0f 分钟" % (sid, reason, max(0, left)))
        return "dry"
    d.pop(str(sid), None)
    save_json(SKIPFILE, d)
    log("已清掉过期冷却 sid=%s reason=%s（她的消息比冷却记录更晚，原剩 %.0f 分钟）"
        % (sid, reason, max(0, left)))
    return "cleared:" + str(reason)


def kill_daemon(h, dry, why):
    """⚠️ 2026-11-08 起**没有调用点**，保留仅供人工排查时显式使用。

    报告 16 §6 第 5 条：探针不该有杀人权（它分不清「真卡死」和「正在跑长阶段」）。
    杀人权统一归 guard/watchdog.py（900s + 轮内心跳）。
    不要在本文件里重新接入它，除非你能给出「探针比 watchdog 判得更准」的证据。
    """
    if dry:
        log("[dry] 会杀掉卡死的 daemon pid=%s（%s）" % (h.get("pid"), why))
        return "dry"
    try:
        subprocess.run(["taskkill", "/PID", str(h["pid"]), "/F"],
                       capture_output=True, timeout=20)
        log("已杀掉卡死的 daemon pid=%s（%s）→ 等 guard 拉起" % (h.get("pid"), why))
        return "killed"
    except Exception as e:
        log("杀 daemon 失败: %r" % (e,))
        return "kill_failed"


def start_daemon(dry):
    if dry:
        log("[dry] 会启动 daemon")
        return "dry"
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", START_PS1], capture_output=True, timeout=90)
        log("已调用 start_daemon.ps1 拉起 daemon")
        return "started"
    except Exception as e:
        log("拉起 daemon 失败: %r" % (e,))
        return "start_failed"


# ---------------- 主逻辑 ----------------
def run_once(sla_s=60, dry=False, stuck_s=300.0, fresh_s=600.0):
    h = daemon_health()
    try:
        rows, ndb = unread_sessions()
    except Exception as e:
        log("探针取数失败（设备不可达？）: %r" % (e,))
        return {"ok": False, "err": repr(e)}

    now_ms = _now() * 1000.0
    pending, backlog = [], []
    for uid, sid, unread, ts, txt in rows:
        age = (now_ms - ts) / 1000.0
        if age < sla_s:
            continue
        # 新消息（默认 10 分钟内到的）才是 SLA 对象；更老的是历史积压，
        # 只报数、不逐条处置（否则探针日志会被 6 小时前的会话刷满）。
        (pending if age <= fresh_s else backlog).append((uid, sid, unread, ts, txt, age))

    if backlog:
        # 积压每 10 分钟报一次，避免刷屏
        st0 = load_json(PROBE_STATE, {})
        if _now() - float(st0.get("_backlog_at") or 0) > 600:
            log("历史积压 %d 条（>%.0f 分钟，不逐条告警）：%s"
                % (len(backlog), fresh_s / 60.0,
                   ", ".join("%s(%d分)" % (u, int(a / 60)) for u, _s, _n, _t, _x, a in backlog[:6])))
            st0["_backlog_at"] = _now()
            save_json(PROBE_STATE, st0)

    if not pending:
        st1 = load_json(PROBE_STATE, {})
        if _now() - float(st1.get("_ok_at") or 0) > 300:
            log("正常：没有超 %ds 未处理的新消息（历史积压 %d 条，daemon=%s 步骤龄=%s）"
                % (int(sla_s), len(backlog), "alive" if h["alive"] else "dead",
                   ("%.0fs" % h["step_age"]) if h["step_age"] is not None else "?"))
            st1["_ok_at"] = _now()
            save_json(PROBE_STATE, st1)
        return {"ok": True, "pending": 0, "backlog": len(backlog), "daemon": h}

    # ---- 进程级：卡死 / 不存在 ----
    if not h["alive"]:
        act = start_daemon(dry)
        log("发现 daemon 进程不存在（pid=%s）→ %s；当前 %d 条未处理"
            % (h["pid"], act, len(pending)))
    elif h["step_age"] is not None and h["step_age"] > stuck_s:
        # 🔴🔴 2026-11-08 12:2x（报告 16 §6 第 5 条，此前一直没落地）：
        #   原来这里直接 kill_daemon() —— 探针变成了**第二个行刑者**。
        #   实测：12 次击杀 + 26 次抢锁，而且判据（step_age>300s）比 watchdog
        #   更激进（watchdog 是 900s），等于 daemon 正在干活时被更早杀掉。
        #   「步骤龄大」既可能是真卡死，也可能是**正在跑一个长阶段**
        #   （pendingq 单轮实测 300~500s、sweep 300~500s）。
        #   探针无法区分这两者，所以它**不该有杀人权**。
        #   现在只告警，把「杀不杀」留给唯一的行刑者 watchdog（900s + 轮内心跳）。
        log("daemon 步骤 %.0fs 未推进（步=%s）→ 仅告警，不杀（杀人权归 watchdog）"
            % (h["step_age"], h["lock_step"]))
        act = "warn_only"

    state = load_json(PROBE_STATE, {})
    done = []
    for uid, sid, unread, ts, txt, age in pending[:6]:
        key = str(sid)
        rec = state.get(key) or {}
        if rec.get("ts") == ts:
            # 同一条消息已经报过：只累加「等了多久」，不再重复刷日志/重复处置
            rec["age"] = int(age)
            state[key] = rec
            continue
        acts = []
        # ① 冷却误伤
        try:
            a = clear_skip(sid, ts, dry)
            if a:
                acts.append(a)
        except Exception as e:
            log("clear_skip 异常 sid=%s: %r" % (sid, e))
        # ② 证据（只记，不动手）
        ev = last_relevant_evidence(sid, uid)
        log("未处理 %d 秒 uid=%s unread=%s 末条=%r 设备库=%d daemon=%s 步骤龄=%s 日志龄=%s 处置=%s"
            % (int(age), uid, unread, (txt or "")[:20], ndb,
               "alive" if h["alive"] else "dead",
               ("%.0fs" % h["step_age"]) if h["step_age"] is not None else "?",
               ("%.0fs" % h["log_age"]) if h["log_age"] is not None else "?",
               ",".join(acts) or "-"))
        for ln in ev:
            log("    证据: " + ln)
        state[key] = {"ts": ts, "uid": uid, "age": int(age), "acted": acts,
                      "at": _now()}
        done.append(uid)

    # 只保留 3 天内的记录
    cutoff = _now() - 3 * 86400
    # 保留 _ok_at / _backlog_at / _last 这些元数据键（原来被这里删掉，
    # 导致「积压每 10 分钟报一次」的闸失效、每 15s 刷一次屏）
    state = {k: v for k, v in state.items()
             if k.startswith("_")
             or (isinstance(v, dict) and float(v.get("at") or 0) > cutoff)}
    state["_last"] = {"at": _now(), "pending": [
        {"uid": u, "sid": s, "unread": n, "age": int(a), "txt": (x or "")[:20]}
        for u, s, n, _t, x, a in pending[:10]]}
    save_json(PROBE_STATE, state)
    return {"ok": True, "pending": len(pending), "backlog": len(backlog),
            "handled": done, "daemon": h}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--every", type=float, default=15.0)
    ap.add_argument("--sla", type=float, default=60.0)
    ap.add_argument("--stuck", type=float, default=300.0)
    ap.add_argument("--fresh", type=float, default=600.0)
    a = ap.parse_args()

    if not acquire_lock():
        log("已有一个探针在跑（%s），本次退出" % LOCKFILE)
        return 0
    log("探针启动 pid=%d every=%.0fs sla=%.0fs dry=%s"
        % (os.getpid(), a.every, a.sla, a.dry))
    if a.once:
        r = run_once(sla_s=a.sla, dry=a.dry, stuck_s=a.stuck, fresh_s=a.fresh)
        log("单轮结束: %r" % (r,))
        return 0
    while True:
        try:
            touch_lock()
            run_once(sla_s=a.sla, dry=a.dry, stuck_s=a.stuck, fresh_s=a.fresh)
        except Exception as e:
            log("探针循环异常: %r" % (e,))
        time.sleep(max(5.0, a.every))


if __name__ == "__main__":
    sys.exit(main())
