# -*- coding: utf-8 -*-
"""相册里选第一张 -> 看发送按钮。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("fg=%s" % (dev.current_app(),))

    # 第一张图本体：FrameLayout desc='图片' 最靠上那个
    pics = [x for x in s.nodes if x.clickable and (x.desc or "") == "图片"]
    pics.sort(key=lambda x: (x.center[1], x.center[0]))
    print("图片数 %d" % len(pics))
    if not pics:
        return 1
    p0 = pics[0]
    print(">> 选第一张 %s" % (p0.bounds,))
    a.hand.tap_node(p0, settle=1.8)

    s2 = a.snap(force=True)
    print("\n== 选后 fg=%s nodes=%d ==" % (dev.current_app(), len(s2.nodes)))
    for x in sorted(s2.nodes, key=lambda y: (y.center[1], y.center[0])):
        if not (x.label or x.desc or x.clickable):
            continue
        txt = (x.label or x.desc or "")[:24]
        if x.center[1] > 1300 or "选" in txt or "发送" in txt or "完成" in txt:
            print("  y=%-5d x=%-4d %-14s click=%s %r res=%s" %
                  (x.center[1], x.center[0], x.cls.split(".")[-1], x.clickable,
                   txt, (x.res_id or "")[-22:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
