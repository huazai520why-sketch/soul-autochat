# -*- coding: utf-8 -*-
"""当前在图片预览页 -> 点发送 -> 确认回到会话页。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("fg=%s nodes=%d" % (dev.current_app()[1].split(".")[-1], len(s.nodes)))

    btn = s.hit(res="tvSend") or s.hit(text="发送")
    print("发送按钮 %s" % ((btn.bounds if btn else None),))
    if btn is None:
        print("找不到发送按钮，打印底部节点：")
        for n in s.nodes:
            if n.center[1] > 1400 and (n.label or n.clickable):
                print("   y=%d %r %r" % (n.center[1], n.label, n.res_id))
        return 1

    a.hand.tap_node(btn, settle=2.0)
    s2, pg = a.wait_page(("chat",), timeout=10)
    print("发送后 page=%s" % pg)
    p, n, dt = dev.screencap_to(LOGS / "_after_send.png")
    print("截图 %d bytes" % n)
    return 0 if pg == "chat" else 2


if __name__ == "__main__":
    sys.exit(main())
