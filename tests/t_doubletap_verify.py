# -*- coding: utf-8 -*-
"""双击聊天 tab 前后各识别一次屏幕，对比落点。全程只一次双击，其余只读。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402


def show(tag, snap, a):
    print("\n[%s] %s" % (tag, a.digest(snap)))
    print("   page=%s  nodes=%d  badges=%s"
          % (detect(snap), len(snap.nodes), badges(snap) or "-"))
    p = P.detect(snap)
    if p is not None:
        print("   POPUP %s" % [b[0] for b in p.buttons])
    if detect(snap) == "chatlist":
        for r in rows(snap):
            print("   y=%-5d %r" % (r.center[1], r.blob[:68]))
    else:
        for i, t in enumerate(snap.texts()[:16]):
            print("   %02d %s" % (i, t[:46]))


def main():
    a = Actor(Device.get())

    snap0 = a.snap()
    show("BEFORE 双击", snap0, a)
    first0 = [r.blob for r in rows(snap0) if 200 <= r.center[1] <= 1500][:3]

    print("\n>> 双击底栏「聊天」")
    snap1, pg = a.double_tap_tab("聊天", expect="chatlist")
    if snap1 is None:
        print("   双击未命中 tab")
        return 1
    show("AFTER 双击", snap1, a)

    first1 = [r.blob for r in rows(snap1) if 200 <= r.center[1] <= 1500][:3]
    print("\n== 对比 ==")
    print("  页面      %s -> %s" % (detect(snap0), pg))
    print("  指纹      %s -> %s" % (snap0.signature(), snap1.signature()))
    for i in range(3):
        a0 = first0[i] if i < len(first0) else "-"
        a1 = first1[i] if i < len(first1) else "-"
        mark = "=" if a0 == a1 else "!"
        print("  %s 行%d 前:%s" % (mark, i + 1, a0[:52]))
        print("        后:%s" % a1[:52])
    return 0


if __name__ == "__main__":
    sys.exit(main())
