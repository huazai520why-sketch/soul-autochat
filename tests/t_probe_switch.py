# -*- coding: utf-8 -*-
"""切号探路：看当前账号是谁、切换入口在哪，点开后打印界面（不主动选账号）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    a = Actor(Device.get())

    print("== 切到「自己」页 ==")
    snap, pg = a.tap_tab("自己", expect="me")
    if snap is None:
        print("  点不到自己 tab")
        return 1
    print("  page=%s" % pg)
    print("  账号相关文本：")
    for n in snap.nodes:
        t = n.label or ""
        if not t:
            continue
        if any(k in t for k in ("切换", "退出", "账号", "星空", "离殇", "设置")):
            print("     y=%-5d c=%-12s %r" % (n.center[1], (n.cls or "").split(".")[-1], t[:26]))

    print("\n== 点「切换用户」 ==")
    n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
    if n is None:
        print("  找不到切换入口")
        return 1
    print("  目标 %s b=%s" % ((n.cls or "").split(".")[-1], n.bounds))
    a.hand.tap_node(n, settle=2.0)

    snap2 = a.snap()
    print("\n  点开后的页面: %s  nodes=%d" % (detect(snap2), len(snap2.nodes)))
    p = P.detect(snap2)
    if p is not None:
        print("  弹窗按钮: %s" % [b[0] for b in p.buttons])
    for i, t in enumerate(snap2.texts()[:24]):
        print("     %02d %s" % (i, t[:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
