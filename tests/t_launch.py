# -*- coding: utf-8 -*-
"""把 Soul 拉起来，确认落点页面。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import SOUL_PKG  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    print("启动 %s" % SOUL_PKG)
    try:
        dev.u2().app_start(SOUL_PKG, wait=True)
    except Exception as e:
        print("u2 app_start 失败 %r，改用 am start" % e)
        dev.sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % SOUL_PKG, timeout=30)

    scr = Screen(dev)
    for i in range(12):
        time.sleep(2)
        snap = scr.get(force=True)
        pg = detect(snap)
        pkg, act = dev.current_app()
        print("  %2ds page=%-9s nodes=%-4d fg=%s" % ((i + 1) * 2, pg, len(snap.nodes), act[:40]))
        if pg != "unknown":
            print("\n落点页面 = %s" % pg)
            for t in snap.texts()[:12]:
                print("   %s" % t[:40])
            return 0
    print("\n仍未识别到主框架页面，可能停在登录/验证页")
    snap = scr.get(force=True)
    for t in snap.texts()[:16]:
        print("   %s" % t[:44])
    return 1


if __name__ == "__main__":
    sys.exit(main())
