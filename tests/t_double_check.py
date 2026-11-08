# -*- coding: utf-8 -*-
"""双击聊天 tab 一次 -> 识屏 -> 只报告红点，不自动进入会话。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402


def dot_rows(snap):
    return [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]


def show(tag, snap, a):
    print("\n[%s] page=%s badges=%s" % (tag, detect(snap), badges(snap) or "-"))
    if detect(snap) == "chatlist":
        for r in rows(snap):
            mark = " [红点 %d]" % r.badge if r.badge else ""
            print("   y=%-5d %r%s" % (r.center[1], r.blob[:62], mark))
    else:
        for t in snap.texts()[:12]:
            print("   %s" % t[:46])


def main():
    a = Actor(Device.get())

    snap0 = a.snap()
    show("BEFORE", snap0, a)
    d0 = dot_rows(snap0)
    print("\n  当前屏红点 %d %s" % (len(d0), [r.nickname for r in d0]))

    print("\n>> 双击聊天 tab")
    snap1, pg = a.double_tap_tab("聊天", expect="chatlist")
    if snap1 is None:
        print("   未命中 tab")
        return 1
    show("AFTER", snap1, a)
    d1 = dot_rows(snap1)
    print("\n  双击后红点 %d %s" % (len(d1), [r.nickname for r in d1]))
    print("  页面 %s -> %s" % (detect(snap0), pg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
