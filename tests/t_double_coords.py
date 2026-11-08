# -*- coding: utf-8 -*-
"""诊断：打印底栏「聊天」tab 区域的完整节点几何，然后用不同坐标/间隔试双击。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402

X1, X2 = 480, 700          # 聊天 tab 的 x 区间
Y1 = 1490


def dump_tab(snap):
    print("-- 底栏聊天区节点 --")
    for n in snap.nodes:
        b = n.bounds
        if b[1] < Y1 or b[3] > 1600:
            continue
        if b[2] < X1 or b[0] > X2:
            continue
        print("   %-12s b=%-24s c=%s  %r"
              % ((n.cls or "").split(".")[-1], b,
                 ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2), n.label[:14]))


def first_line(snap):
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    return rs[0].blob[:40] if rs else "-"


def try_double(dev, x, y, gap, tag):
    d = dev.u2()
    d.double_click(x, y, gap)
    time.sleep(1.2)
    snap = Screen(dev).get(force=True)
    print("   %-22s 点(%d,%d) gap=%.2f -> 第一行 %r | badges=%s"
          % (tag, x, y, gap, first_line(snap), badges(snap) or "-"))
    return snap


def main():
    dev = Device.get()
    scr = Screen(dev)
    snap = scr.get(force=True)

    print("== 当前 ==")
    print("   page=%s 第一行=%r badges=%s"
          % (detect(snap), first_line(snap), badges(snap) or "-"))
    dump_tab(snap)

    tab = snap.tab("聊天")
    print("\n   tab() -> b=%s center=%s" % (tab.bounds, tab.center))

    print("\n== 用容器中心，不同间隔 ==")
    try_double(dev, 598, 1551, 0.05, "container 0.05")
    try_double(dev, 598, 1551, 0.30, "container 0.30")

    print("\n== 用图标中心 (614,1538) ==")
    try_double(dev, 614, 1538, 0.05, "icon 0.05")

    print("\n== 用文本中心 (614,1583) ==")
    try_double(dev, 614, 1583, 0.05, "label 0.05")
    return 0


if __name__ == "__main__":
    sys.exit(main())
