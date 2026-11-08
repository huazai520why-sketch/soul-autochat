# -*- coding: utf-8 -*-
"""用 Actor 重测双击：每个动作后强制重新确认页面（本次修正的核心）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402


def main():
    a = Actor(Device.get())

    print("== 先回到列表顶部（每步都确认页面） ==")
    for i in range(12):
        snap, pg = a.swipe_down(expect="chatlist")
        if pg != "chatlist":
            print("  !! 第 %d 次下拉后页面变成 %s" % (i + 1, pg))
            break
    snap = a.snap()
    print("  顶部: %s" % a.digest(snap))

    print("\n== 连续双击（每次自动 re-dump + 确认） ==")
    for i in range(1, 6):
        snap, pg = a.double_tap_tab("聊天", expect="chatlist")
        if snap is None:
            print("  #%d 未命中 tab" % i)
            break
        print("  #%d %s" % (i, a.digest(snap)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
