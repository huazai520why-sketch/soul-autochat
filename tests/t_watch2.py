# -*- coding: utf-8 -*-
"""诊断 stat：不同写法哪个能拿到输出。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402

DB = "/data/data/cn.soulapp.android/databases/IM-SDK-SmNjOUhiUUhZa1RWVlgvZUh1NEExdz09-DATA.db"


def t(dev, tag, cmd):
    t0 = time.time()
    try:
        out = dev.text(cmd, timeout=20)
        print("%-14s %.0fms  %r" % (tag, (time.time() - t0) * 1000, (out or "")[:80]))
    except Exception as e:
        print("%-14s %.0fms  EXC %r" % (tag, (time.time() - t0) * 1000, e))


def main():
    dev = Device.get()
    print("adb=%s serial=%s" % (dev.adb, dev.serial))
    t(dev, "id", "id")
    t(dev, "ls-db", "ls -la " + DB)
    t(dev, "stat-无引号", "stat -c '%Y:%s' " + DB + " " + DB + "-wal")
    t(dev, "stat-双引号", "stat -c '%Y:%s' '" + DB + "' '" + DB + "-wal'")
    t(dev, "stat-single", "stat -c '%Y' " + DB)
    t(dev, "u2shell", None) if False else None
    try:
        u = dev.u2()
        r = u.shell("stat -c '%Y' " + DB)
        print("%-14s type=%s output=%r" % ("u2.shell", type(r).__name__, getattr(r, "output", None)))
    except Exception as e:
        print("u2.shell EXC %r" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
