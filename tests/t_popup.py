# -*- coding: utf-8 -*-
"""弹窗处理验证：识别当前弹窗 -> 点「确认」-> 看落点页面。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import badges, detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)

    print("== 弹窗处理 ==")
    snap = scr.get(force=True)
    print("  page(before) = %s" % detect(snap))

    p = P.detect(snap)
    print("  popup        = %r" % p)
    if p is None:
        print("  没有识别到弹窗，打印文本看看：")
        for t in snap.texts()[:12]:
            print("    %s" % t)
        return 1

    # 优先点主按钮（确认/确定）
    if not p.primary:
        print("  没有主按钮，改为点次按钮")
        label, node = p.secondary[0]
    else:
        label, node = p.primary[0]
    print("  点击 %r center=%s" % (label, node.center))
    hand.tap_node(node, settle=1.5)

    snap2 = scr.get(force=True)
    print("\n  处理后 page = %s" % detect(snap2))
    print("  badges      = %s" % (badges(snap2) or "-"))
    print("  文本：")
    for i, t in enumerate(snap2.texts()[:24]):
        print("    %02d %s" % (i, t[:46]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
