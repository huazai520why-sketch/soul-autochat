# -*- coding: utf-8 -*-
"""点「更多」后面板里到底有什么（找发图入口）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("page=%s" % detect(s))
    if detect(s) != "chat":
        snap = CL.to_list(a)
        rows = [r for r in CL.rows(snap) if 200 <= r.center[1] <= 1500]
        a.hand.tap_node(rows[0].node, settle=1.8)
        a.wait_page(("chat",), timeout=6)

    s = a.snap(force=True)
    n = s.hit(text="更多") or s.hit(desc="更多")
    print("点更多 %s" % (n.bounds if n else None,))
    if n:
        a.hand.tap_node(n, settle=2.0)

    s2 = a.snap(force=True)
    print("\n== 面板 page=%s nodes=%d ==" % (detect(s2), len(s2.nodes)))
    for x in sorted([y for y in s2.nodes if (y.label or y.desc or y.clickable)],
                    key=lambda y: (y.center[1], y.center[0])):
        print("  y=%-5d x=%-4d %-14s click=%s %r %r" %
              (x.center[1], x.center[0], x.cls.split(".")[-1], x.clickable,
               (x.label or "")[:16], (x.desc or "")[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
