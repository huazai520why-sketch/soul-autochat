# -*- coding: utf-8 -*-
"""确认：进有消息的会话，截图，看消息是否肉眼可见但 UI 树里没有。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap()
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]

    target = None
    for r in rs:
        if "渺小的你" in r.blob:
            target = r
            break
    if target is None:
        target = rs[1] if len(rs) > 1 else rs[0]
    print("进入: %r" % target.blob[:50])

    a.hand.tap_node(target.node, settle=2.5)
    snap2 = a.snap()
    print("page=%s nodes=%d" % (detect(snap2), len(snap2.nodes)))

    lbl = [n for n in snap2.nodes if n.label]
    print("有文本节点 %d 个：" % len(lbl))
    for n in lbl[:18]:
        print("   y=%-5d %r" % (n.center[1], n.label[:34]))

    p, size, dt = dev.screencap_to(LOGS / "_chat_page.png")
    print("\n截图 %s  %d bytes  %.2fs" % (p.name, size, dt))

    a.hand.back(settle=1.2)
    print("已返回: page=%s" % detect(a.snap()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
