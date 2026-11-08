# -*- coding: utf-8 -*-
"""继续双击聊天 tab（多次），每次识屏确认位置与红点。出现红点即停，不自动进入。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402

N = 4


def dots(snap):
    return [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]


def first_line(snap):
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    return rs[0].blob[:48] if rs else "-"


def main():
    a = Actor(Device.get())
    snap = a.snap()
    print("起始 %s | 第一行 %r | 红点 %d"
          % (a.digest(snap), first_line(snap), len(dots(snap))))

    for i in range(1, N + 1):
        snap2, pg = a.double_tap_tab("聊天", expect="chatlist")
        if snap2 is None:
            print("#%d 未命中 tab" % i)
            break
        ds = dots(snap2)
        print("#%d page=%-9s 角标=%-4s 第一行=%r 红点=%d %s"
              % (i, pg, badges(snap2).get("聊天"), first_line(snap2),
                 len(ds), [r.nickname for r in ds]))
        if ds:
            print("   >> 出现红点，停在这里")
            for r in rows(snap2):
                if r.has_dot:
                    print("      y=%-5d %r [红点 %d]" % (r.center[1], r.blob[:58], r.badge))
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
