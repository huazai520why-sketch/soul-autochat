# -*- coding: utf-8 -*-
"""L0 验收：设备接入层。在副机跑：python tests/t_device.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device, u2_version  # noqa: E402


def line(k, v):
    print("  %-18s %s" % (k, v))


def main():
    ok = 0
    fail = 0

    print("== L0 设备接入层 ==")
    t0 = time.time()
    dev = Device.get()
    line("adb", dev.adb)
    line("serial", dev.serial)
    line("connect", "%.2fs" % (time.time() - t0))

    # 1 root
    try:
        r = dev.root_ok()
        line("root", "uid=0 OK" if r else "NOT root (会降级)")
        ok += 1
    except Exception as e:
        print("  root            FAIL %r" % e)
        fail += 1

    # 2 分辨率
    try:
        w, h = dev.wm_size()
        line("wm size", "%dx%d" % (w, h))
        ok += 1
    except Exception as e:
        print("  wm size         FAIL %r" % e)
        fail += 1
        w = h = 0

    # 3 前台 App
    try:
        pkg, act = dev.current_app()
        line("foreground", "%s / %s" % (pkg, act))
        ok += 1
    except Exception as e:
        print("  foreground      FAIL %r" % e)
        fail += 1

    # 4 截图
    try:
        shot = Path(__file__).resolve().parent.parent / "logs" / "_t_device.png"
        p, n, dt = dev.screencap_to(shot)
        line("screencap", "%d bytes  %.2fs  -> %s" % (n, dt, p.name))
        ok += 1
    except Exception as e:
        print("  screencap       FAIL %r" % e)
        fail += 1

    # 5 u2
    try:
        line("u2 version", u2_version())
        t1 = time.time()
        d = dev.u2()
        dt = time.time() - t1
        line("u2 connect", "%.2fs" % dt)
        t1 = time.time()
        xml = d.dump_hierarchy(compressed=False)
        line("u2 dump", "%d bytes  %.2fs" % (len(xml), time.time() - t1))
        ok += 1
    except Exception as e:
        print("  u2              FAIL %r" % e)
        fail += 1

    print("\n结果: OK=%d FAIL=%d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
