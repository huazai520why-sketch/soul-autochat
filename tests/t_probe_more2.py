# -*- coding: utf-8 -*-
"""收键盘 -> 点更多 -> 看面板（找发图入口）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def bar_y(snap):
    """底部工具栏的 y（键盘弹出会把它顶上去）。"""
    n = snap.find_one(res="menu_tab_more_inner_inner_img") or snap.find_one(res="menu_tab_more_inner")
    if n is None:
        cands = [x for x in snap.nodes if x.desc == "更多"]
        n = cands[0] if cands else None
    return n


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("page=%s" % detect(s))

    n = bar_y(s)
    if n is None:
        print("找不到更多按钮")
        return 1
    print("更多按钮 y=%d" % n.center[1])

    # 工具栏被顶到上面 = 键盘弹着，先收键盘
    if n.center[1] < 1450:
        print("键盘弹着 -> 按 back 收起")
        dev.u2().press("back")
        time.sleep(1.2)
        s = a.snap(force=True)
        n = bar_y(s)
        print("收键盘后 更多 y=%d page=%s" % (n.center[1] if n else -1, detect(s)))

    print(">> 点更多 %s" % (n.bounds,))
    a.hand.tap_node(n, settle=2.2)

    s2 = a.snap(force=True)
    print("\n== 面板 page=%s nodes=%d ==" % (detect(s2), len(s2.nodes)))
    for x in sorted(s2.nodes, key=lambda y: (y.center[1], y.center[0])):
        if x.center[1] < 700:
            continue
        if not (x.label or x.desc or x.clickable):
            continue
        print("  y=%-5d x=%-4d %-14s click=%s %r %r res=%s" %
              (x.center[1], x.center[0], x.cls.split(".")[-1], x.clickable,
               (x.label or "")[:14], (x.desc or "")[:10], (x.res_id or "")[-20:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
