# -*- coding: utf-8 -*-
"""探针：连续多次双击底栏聊天 tab，记录每次落点，判断是否有推进规律。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402

N = 6


def anchor(snap):
    """取第一个「会话行」作为落点标记（跳过顶部 tips 条）。"""
    for r in rows(snap):
        if 200 <= r.center[1] <= 1500:
            return r
    return None


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)
    d = dev.u2()

    snap = scr.get(force=True)
    p = P.detect(snap)
    if p is not None:
        for label, node in (p.primary or p.secondary):
            hand.tap_node(node, settle=1.2)
            break
        snap = scr.get(force=True)
    if detect(snap) != "chatlist":
        hand.tap_hit(snap, text="聊天", settle=1.2)
        snap = scr.get(force=True)

    print("== 连续双击 %d 次 ==" % N)
    seen = []
    for i in range(1, N + 1):
        snap = scr.get(force=True)
        tab = snap.tab("聊天")
        if tab is None:
            print("  #%d 找不到底栏 tab（page=%s）" % (i, detect(snap)))
            break
        a = anchor(snap)
        x, y = tab.center
        t0 = time.time()
        d.double_click(x, y, 0.12)
        time.sleep(1.0)
        snap2 = scr.get(force=True)
        b = anchor(snap2)
        same = "SAME" if (a and b and a.blob == b.blob) else ""
        print("  #%d %-8s %.2fs  ->  y=%-5s %r  %s"
              % (i, detect(snap2), time.time() - t0,
                 b.center[1] if b else "-", (b.blob[:56] if b else "-"), same))
        seen.append(b.blob if b else "")

    print("\n  落点序列:")
    for i, s in enumerate(seen, 1):
        print("    %d. %s" % (i, s[:60]))
    print("  唯一落点数 = %d / %d" % (len(set(seen)), len(seen)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
