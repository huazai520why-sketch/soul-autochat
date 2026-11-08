# -*- coding: utf-8 -*-
"""探针：先滚到列表最顶，再多次双击，看是否命中红点会话。

红点会话（2026-11-02 实测）：
  204268346  unread=6  11-01 23:19  '你的主页很有趣，我今天看了你3次...'
  463350946  unread=2  11-01 20:57  '[花仙子]撒花'
若双击语义是「跳到有红点的行」，从顶部双击应落在 11-01 附近而不是 10-28。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402


def top_rows(snap, n=3):
    out = []
    for r in rows(snap):
        if 200 <= r.center[1] <= 1500:
            out.append(r)
    return out[:n]


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)
    d = dev.u2()

    print("== 滚到顶部 ==")
    for i in range(12):
        hand.swipe(450, 400, 450, 1400, duration=0.1, settle=0.18)

    snap = scr.get(force=True)
    print("  page=%s" % detect(snap))
    for r in top_rows(snap):
        print("   y=%-5d %r" % (r.center[1], r.blob[:70]))

    print("\n== 从顶部连续双击 5 次 ==")
    for i in range(1, 6):
        snap = scr.get(force=True)
        tab = snap.tab("聊天")
        if tab is None:
            print("  #%d 无 tab" % i)
            break
        x, y = tab.center
        d.double_click(x, y, 0.12)
        time.sleep(1.0)
        snap2 = scr.get(force=True)
        print("  #%d page=%s" % (i, detect(snap2)))
        for r in top_rows(snap2, 2):
            print("       y=%-5d %r" % (r.center[1], r.blob[:66]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
