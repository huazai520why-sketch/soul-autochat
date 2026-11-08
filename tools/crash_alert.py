# -*- coding: utf-8 -*-
"""崩溃/异常告警 —— 独立运行，只读日志，落 alerts.log 告警。

新版（soul1.0）没有旧版 faulthandler 写的 `crash.<vm>.log`，所以盯两个真实信号源：
  ① `logs/daemon.out`  —— daemon 的 stdout，Traceback/ERROR/自杀 都落在这里；
  ② `logs/guard.watchdog.log` —— 看门狗日志，「拉起 / 强杀 / 卡死」都记在这里，
     它每 60s 一轮，是 daemon 反复崩溃循环（watchdog 拉起→再崩→再拉）的第一现场。

只报「类型 + 命中行数」，绝不贴日志正文（正文可能含她的 uid/昵称/消息，隐私红线）。

跑法：
    python -X utf8 tools/crash_alert.py --once     # 巡检一次
    python -X utf8 tools/crash_alert.py            # 常驻，每 60s 巡检
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
STATE = ROOT / "data" / "state" / ".crash_seen.json"
ALERTS = LOG_DIR / "alerts.log"

# 监控对象：文件名 -> (信号正则, 说明)。正则只匹配「类型/动作」，不捕获正文。
_EXC_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?:Error|Exception|Interrupt|Exit|Timeout|Warning))"
    r"(?=\s*:|\s*$)"
)
MONITOR = {
    "daemon.out": (re.compile(r"Traceback|ERROR|Exception|自杀|CRITICAL"), "daemon 异常"),
    "guard.watchdog.log": (re.compile(r"拉起 daemon|已强杀卡死|强杀卡死|判卡死|心跳.*超时"), "看门狗处置"),
}
# 只看文件尾部的增量上限，避免大文件全量读
TAIL_MAX = 256 * 1024


class _Tee:
    """把 print 同时写到终端和日志文件（计划任务无控制台时靠文件留痕）。"""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def _load_state() -> dict:
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        files = d.get("files", {})
        if not isinstance(files, dict):
            return {}
        out = {}
        for name, sig in files.items():
            if not isinstance(name, str) or not isinstance(sig, dict):
                continue
            try:
                out[name] = {"mtime_ns": int(sig["mtime_ns"]), "size": int(sig["size"])}
            except (KeyError, TypeError, ValueError):
                continue
        return out
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as exc:
        print("[crash-alert] state unreadable: %s: %s" % (type(exc).__name__, exc))
        return {}


def _save_state(files: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".crash_seen.", suffix=".tmp", dir=str(STATE.parent))
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"files": files}, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temp, STATE)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _append_alert(when: str, fname: str, kind: str, detail: str) -> None:
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    line = "[%s] [alert] 文件=%s 类型=%s %s\n" % (when, fname, kind, detail)
    with ALERTS.open("a", encoding="utf-8", newline="\n") as fp:
        fp.write(line)
        fp.flush()
        os.fsync(fp.fileno())


def _increment(path: Path, old_size: int) -> str:
    """读从 old_size 到文件尾的增量（最多 TAIL_MAX，且不越过截断边界）。"""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if old_size > size:      # 被轮转/截断了，只能读当前尾部
        start = max(0, size - TAIL_MAX)
    else:
        start = max(0, old_size, size - TAIL_MAX)
    try:
        with path.open("rb") as fp:
            fp.seek(start)
            data = fp.read()
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def patrol() -> int:
    previous = _load_state()
    current = dict(previous)
    emitted = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for fname, (re_sig, kind) in MONITOR.items():
        path = LOG_DIR / fname
        if not path.exists():
            continue
        try:
            stat = path.stat()
            sig = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
            old = previous.get(fname)
            if old is None:
                # 首次：只建基线，不把历史存量信号当「新崩溃」报（否则部署当天噪音刷屏）
                current[fname] = sig
                continue
            old_size = old["size"]
            inc = _increment(path, old_size)
            if inc:
                hits = re_sig.findall(inc)
                if hits:
                    # 异常类型（daemon.out）单独提取；看门狗命中则是「动作词」
                    if fname == "daemon.out":
                        types = [t for t in (_EXC_RE.findall(inc)) if t]
                        detail = "命中=%d行 异常=%s" % (
                            len(hits), ",".join(types[:3]) if types else "未知")
                    else:
                        detail = "命中=%d行" % len(hits)
                    _append_alert(now, fname, kind, detail)
                    emitted += 1
            current[fname] = sig
        except BaseException as exc:
            print("[crash-alert] %s: %s: %s" % (fname, type(exc).__name__, exc))
    _save_state(current)
    return emitted


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=float, default=60.0)
    args = ap.parse_args(argv)

    # 计划任务跑时无控制台，stdout 会丢 —— tee 到日志文件，事后可查
    try:
        _lf = open(str(LOG_DIR / "crash_alert.log"), "a", encoding="utf-8")
    except OSError:
        _lf = None
    if _lf is not None:
        sys.stdout = _Tee(sys.__stdout__, _lf)

    if args.once:
        print("[crash-alert] tickets=%d" % patrol())
        return 0
    print("[crash-alert] 启动，每 %.0fs 巡检" % args.every)
    while True:
        try:
            n = patrol()
            if n:
                print("[crash-alert] tickets=%d" % n)
        except KeyboardInterrupt:
            break
        except BaseException as exc:
            print("[crash-alert] 巡检异常（已兜住）: %s: %s" % (type(exc).__name__, exc))
        time.sleep(args.every)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
