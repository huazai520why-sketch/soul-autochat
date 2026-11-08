# -*- coding: utf-8 -*-
"""探查：对方主页「瞬间」区域，不滑动的情况下 UI 树里能拿到几条。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    if detect(snap) != "chat":
        print("不在会话页")
        return 1

    n = snap.hit(text="查看主页")
    if n is None:
        print("没有查看主页")
        return 2
    a.hand.tap_node(n, settle=3.0)
    s = a.snap(force=True)
    print("主页 page=%s nodes=%d" % (detect(s), len(s.nodes)))

    print("\n-- 全部有文本节点（按 y） --")
    for x in sorted([y for y in s.nodes if y.label], key=lambda y: (y.center[1], y.center[0])):
        print("  y=%-5d x=%-4d %-14s %r"
              % (x.center[1], x.center[0], x.cls.split(".")[-1], x.label[:44]))

    print("\n-- y>600 的（瞬间区） --")
    low = [y for y in s.nodes if y.label and y.center[1] > 600]
    print("   节点数 %d" % len(low))
    import re
    TS = re.compile(r"^\d{4}-\d{2}-\d{2}")
    stamps = [y.label for y in low if TS.match(y.label.strip())]
    print("   时间戳 %d 个: %s" % (len(stamps), stamps))

    print("\n>> 返回")
    a.hand.back(settle=1.5)
    print("返回后 page=%s" % detect(a.snap(force=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
