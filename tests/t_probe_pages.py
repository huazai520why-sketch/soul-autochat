# -*- coding: utf-8 -*-
"""L1+L2 联测：点四个 tab，验证「语义定位 -> 点击 -> 页面变化」闭环。

会真实点击模拟器。只点底栏 tab，不进入任何会话。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.page import badges, detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402

TABS = ["星球", "广场", "聊天", "自己"]


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)

    print("== 四 tab 点击闭环 ==")
    for tab in TABS:
        snap = scr.get(force=True)
        before = snap.signature()
        target = hand.tap_hit(snap, text=tab, settle=1.3)
        if target is None:
            print("  %-3s MISS" % tab)
            continue
        snap2 = scr.get(force=True)
        after = snap2.signature()
        page = detect(snap2)
        bd = badges(snap2)
        print("\n  %s -> 点(%d,%d) click=%s" % (tab, target.center[0], target.center[1],
                                                target.clickable))
        print("     page=%-9s sig %s -> %s %s"
              % (page, before, after, "CHANGED" if before != after else "SAME!"))
        print("     badges=%s" % (bd or "-"))
        print("     texts: %s" % " | ".join(snap2.texts()[:14]))

    # 回到聊天 tab，方便人工核对
    snap = scr.get(force=True)
    hand.tap_hit(snap, text="聊天", settle=1.0)
    print("\n已回到聊天 tab")


if __name__ == "__main__":
    sys.exit(main())
