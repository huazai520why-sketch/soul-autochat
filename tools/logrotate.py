# -*- coding: utf-8 -*-
"""stdout 日志轮转 + 残留清理 —— 独立运行，不导入 daemon（避免重依赖）。

为什么必须有：`logs/daemon.out` 由 watchdog 以 append 句柄常驻写入
（guard/watchdog.py start_daemon：`open(LOG_DIR/"daemon.out", "ab")`），
daemon 是 7×24 常驻进程，**运行期没有任何东西轮转它**。
各模块的 `.log`（core/log.py 的 RotatingFileHandler 8MB×3）已有轮转，不用管；
只有 daemon.out 会无限增长（旧版实测曾长到 39MB）。

另顺带清理两类「只会堆积」的残留：
  · `logs/*.png` —— 诊断截图（_profile/_planet/_me/_search 等），没人回收；
  · `logs/daemon.out.bak-*` —— 重启时手动备份，越攒越多。

算法（沿用旧版 guard/soul_logrotate.py 的验证结论）：
  · **复制→截断，不 rename**：daemon 的 append 句柄不能被抢，rename 会让它
    继续往旧 inode 写，Windows 上直接抛占用；
  · 复制期间新追加的字节留在新文件开头，不丢。

跑法（只读安全，随时可停）：
    python -X utf8 tools/logrotate.py                     # 超阈值才动
    SOUL_LOG_MAX_MB=1 python -X utf8 tools/logrotate.py   # 演练（1MB 强制触发）
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
TARGET = "daemon.out"
# 🔴 2026-11-08 12:2x（报告 16 §6 第 9 条）：
#   原值 20MB，但实测 daemon.out 一周才长到 3.88MB —— **阈值从未触发过**，
#   等于轮转形同不存在。而诊断/取证时经常要「共享读」这个文件，
#   单文件越大，tail/seek 越慢，也越容易和写入方抢句柄。
#   降到 4MB：约每 3~4 天轮转一次，单文件始终可全量扫。
DEFAULT_MAX_MB = 4.0
KEEP = 3
# 残留清理：pgn 截图 / daemon.out.bak 超过多少天删（0 = 不清理）
CLEAN_DAYS = int(os.environ.get("SOUL_LOG_CLEAN_DAYS", "7"))


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


def _max_bytes() -> int:
    raw = os.environ.get("SOUL_LOG_MAX_MB", str(DEFAULT_MAX_MB))
    try:
        value = float(raw)
        if value <= 0:
            raise ValueError("must be positive")
        return max(1, int(value * 1024 * 1024))
    except (TypeError, ValueError) as exc:
        print("[logrotate] invalid SOUL_LOG_MAX_MB=%r: %s; use default" % (raw, exc))
        return int(DEFAULT_MAX_MB * 1024 * 1024)


def _history_paths(path: Path) -> list:
    """daemon.out -> daemon.out.1（.1 最新）。"""
    return [Path(str(path) + ".%d" % i) for i in range(1, KEEP + 1)]


def _copy_snapshot(path: Path):
    """先落一份 fsync 过的快照，截断只删快照已覆盖的字节（复制期间的追加不丢）。"""
    fd, temp_name = tempfile.mkstemp(
        prefix="." + path.name + ".", suffix=".rotate.tmp", dir=str(path.parent))
    temp = Path(temp_name)
    copied = 0
    try:
        with os.fdopen(fd, "wb") as dst, path.open("rb") as src:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        return temp, copied
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _truncate_preserving_appends(path: Path, copied: int) -> None:
    """只移除快照已覆盖的前 copied 字节；复制期间又追加的字节留在开头。"""
    with path.open("r+b") as current:
        current.seek(0, os.SEEK_END)
        size = current.tell()
        if size <= copied:
            current.seek(0)
            current.truncate(0)
            current.flush()
            return
        current.seek(copied)
        remainder = current.read()
        current.seek(0)
        current.write(remainder)
        current.truncate(len(remainder))
        current.flush()


def rotate_daemon_out(threshold: int) -> bool:
    path = LOG_DIR / TARGET
    try:
        if not path.exists():
            return False
        if path.stat().st_size < threshold:
            return False
        history = _history_paths(path)
        temp = None
        try:
            temp, copied = _copy_snapshot(path)
            if copied == 0:
                return False
            for old in history[KEEP - 1:]:
                try:
                    old.unlink(missing_ok=True)
                except OSError:
                    pass
            for i in range(KEEP - 1, 0, -1):
                if history[i - 1].exists():
                    os.replace(history[i - 1], history[i])
            os.replace(temp, history[0])
            temp = None
            _truncate_preserving_appends(path, copied)
            print("[logrotate] rotated %s: snapshot=%d bytes" % (path.name, copied))
            return True
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
    except BaseException as exc:
        print("[logrotate] skipped %s: %s: %s" % (path.name, type(exc).__name__, exc))
        return False


def clean_stale_files(days: int) -> int:
    """删 logs/*.png 和 daemon.out.bak-* 中超过 days 天的。返回删除数。"""
    if days <= 0 or not LOG_DIR.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for p in LOG_DIR.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if not (name.endswith(".png") or name.startswith(TARGET + ".bak-")):
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError as exc:
            print("[logrotate] cannot clean %s: %s" % (name, exc))
    return removed


def main() -> int:
    try:
        _lf = None
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            _lf = open(str(LOG_DIR / "logrotate.log"), "a", encoding="utf-8")
        except OSError:
            pass
        if _lf is not None:
            sys.stdout = _Tee(sys.__stdout__, _lf)
        threshold = _max_bytes()
        rotated = rotate_daemon_out(threshold)
        cleaned = clean_stale_files(CLEAN_DAYS)
        p = LOG_DIR / TARGET
        size_mb = (p.stat().st_size / 1024 / 1024) if p.exists() else 0.0
        print("[logrotate] 巡检 daemon.out=%.1fMB 阈值=%.1fMB 轮转=%s 清理残留=%d"
              % (size_mb, threshold / 1024 / 1024, rotated, cleaned))
        return 0
    except BaseException as exc:
        print("[logrotate] fatal-contained: %s: %s" % (type(exc).__name__, exc))
        return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
