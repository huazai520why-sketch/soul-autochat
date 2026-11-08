# -*- coding: utf-8 -*-
"""退回到 me 页并截图，供人工确认按钮真实位置。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    d = dev.u2()
    scr = Screen(dev)

    for i in range(5):
        snap = scr.get(force=True)
        pg = detect(snap)
        print("  #%d page=%s nodes=%d" % (i, pg, len(snap.nodes)))
        if pg == "me":
            break
        d.press("back")
        time.sleep(1.2)

    snap = scr.get(force=True)
    print("最终 page=%s" % detect(snap))
    p, size, dt = dev.screencap_to(LOGS / "_me.png")
    print("saved %s %d bytes %.2fs" % (p, size, dt))

    print("\n-- 顶部区域全部节点（y<220） --")
    for n in snap.nodes:
        if n.bounds[3] > 220 or not n.visible:
            continue
        print("   %-14s b=%-22s click=%-5s desc=%-10r text=%r"
              % ((n.cls or "").split(".")[-1], n.bounds, n.clickable,
                 (n.desc or "")[:10], (n.text or "")[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
