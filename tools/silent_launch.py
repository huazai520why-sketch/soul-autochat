"""Silent launcher for soul1.0 console scripts (Windows).

Executed by pythonw.exe, so it has no console of its own. It starts the real
command with CREATE_NO_WINDOW (or DETACHED_PROCESS for the resident daemon)
and redirects stdout/stderr to a log file, so scripts that print() or call
sys.stdout.reconfigure() keep working exactly as before.

The PYTHONPATH shim in tools/_silent/sitecustomize.py is injected into every
child, which makes all of THEIR subprocesses (tasklist / powershell / adb ...)
windowless too. Nothing in the product code is modified.

Usage:  pythonw.exe E:\\soul1.0\\tools\\silent_launch.py <spec-name>
"""
import os
import sys
import subprocess
import traceback

ROOT = r"E:\soul1.0"
TOOLS = os.path.join(ROOT, "tools")
LOGS = os.path.join(ROOT, "logs")
SHIM = os.path.join(TOOLS, "_silent")
PY = r"C:\Users\JIAN\.workbuddy\binaries\python\envs\soulocr\Scripts\python.exe"
PYW = r"C:\Users\JIAN\.workbuddy\binaries\python\envs\soulocr\Scripts\pythonw.exe"
LAUNCH = os.path.join(TOOLS, "silent_launch.py")

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# exe, argv, working dir, stdout log, detached
SPECS = {
    "crash_alert": (PY,  ["-X", "utf8", TOOLS + r"\crash_alert.py", "--once"], ROOT, "crash_alert.out", False),
    "voice_check": (PY,  ["-X", "utf8", TOOLS + r"\voice_check.py"], ROOT, "voice_check.out", False),
    "cost_watch": (PY,  ["-X", "utf8", TOOLS + r"\cost_watch.py"], ROOT, "cost_watch.out", False),
    "daily_review": (PY,  ["-X", "utf8", TOOLS + r"\daily_review.py", "--json", ROOT + r"\data\state\daily_review.json"], ROOT, "daily_review.out", False),
    "logrotate": (PY,  ["-X", "utf8", TOOLS + r"\logrotate.py"], ROOT, "logrotate.out", False),
    "msg_probe": (PY,  [TOOLS + r"\msg_probe.py", "--every", "15", "--sla", "60", "--fresh", "600"], ROOT, "msg_probe.out", False),
    "devwatch": (PYW, [TOOLS + r"\devwatch.py"], ROOT, "devwatch.out", False),
    "watchdog": (PYW, ["run.py", "watchdog"], ROOT, "watchdog.out", False),
    "live_watch": (PYW, [TOOLS + r"\watchdog_live.py"], ROOT, "live_watch.out", False),
    "daemon": (PY,  ["-u", "run.py", "daemon"], ROOT, "daemon_stdout.out", True),
}

ERRLOG = os.path.join(LOGS, "silent_launch.err")


def _err(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SPECS:
        _err("bad spec: %r" % (sys.argv[1:],))
        return 2
    name = sys.argv[1]
    exe, argv, cwd, logname, detach = SPECS[name]
    try:
        os.makedirs(LOGS, exist_ok=True)
        env = os.environ.copy()
        # shim only affects processes started through this launcher
        env["PYTHONPATH"] = SHIM + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("PYTHONIOENCODING", "utf-8")

        # NOTE: do NOT use DETACHED_PROCESS here. The venv python.exe is a
        # redirector shim that re-spawns the real interpreter; under
        # DETACHED_PROCESS that grandchild allocates a NEW visible console.
        # CREATE_NO_WINDOW suppresses it for the whole chain (verified on the
        # msg_probe / watchdog tasks). Breakaway only detaches from the job.
        if detach:
            flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
        else:
            flags = CREATE_NO_WINDOW

        with open(os.path.join(LOGS, logname), "ab", buffering=0) as lf:
            p = subprocess.Popen([exe] + argv, cwd=cwd, env=env,
                                 stdin=subprocess.DEVNULL,
                                 stdout=lf, stderr=subprocess.STDOUT,
                                 creationflags=flags,
                                 close_fds=True)
        if detach:
            return 0
        return p.wait()
    except Exception:
        _err("spec=%s\n%s" % (name, traceback.format_exc()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
