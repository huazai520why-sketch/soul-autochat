# -*- coding: utf-8 -*-
"""更多 -> 图片 -> 看相册页结构与发送按钮。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def more_btn(snap):
    for x in snap.nodes:
        if x.desc == "更多":
            return x
    return None


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("page=%s" % detect(s))

    n = more_btn(s)
    if n is None:
        print("找不到更多")
        return 1
    if n.center[1] < 1450:
        dev.u2().press("back")
        time.sleep(1.2)
        s = a.snap(force=True)
        n = more_btn(s)
    print("点更多")
    a.hand.tap_node(n, settle=2.0)

    s = a.snap(force=True)
    pic = s.hit(text="图片")
    print("点图片 %s" % ((pic.bounds if pic else None),))
    if pic is None:
        print("找不到图片格")
        return 2
    a.hand.tap_node(pic, settle=2.5)

    s2 = a.snap(force=True)
    print("\n== 相册 page=%s fg=%s nodes=%d ==" % (detect(s2), dev.current_app(), len(s2.nodes)))
    for x in sorted(s2.nodes, key=lambda y: (y.center[1], y.center[0])):
        if not (x.label or x.desc or x.clickable):
            continue
        print("  y=%-5d x=%-4d %-14s click=%s %r %r res=%s" %
              (x.center[1], x.center[0], x.cls.split(".")[-1], x.clickable,
               (x.label or "")[:16], (x.desc or "")[:12], (x.res_id or "")[-22:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
