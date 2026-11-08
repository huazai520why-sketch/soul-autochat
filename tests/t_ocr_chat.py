# -*- coding: utf-8 -*-
"""验证：进会话截图 OCR，看能否读出气泡文字与左右位置。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)

    snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", settle=1.5)
        snap = a.snap()
    ds = [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]
    if not ds:
        print("没有红点行")
        return 1
    r = ds[0]
    print("进入 %r" % r.blob[:50])
    a.hand.tap_node(r.node, settle=2.5)
    snap2 = a.snap()
    print("page=%s nodes=%d 有文本节点=%d"
          % (detect(snap2), len(snap2.nodes), len([n for n in snap2.nodes if n.label])))

    t0 = __import__("time").time()
    png = dev.screencap()
    print("截图 %.2fs %d bytes" % (__import__("time").time() - t0, len(png)))
    (LOGS / "_ocr_chat.png").write_bytes(png)

    t0 = __import__("time").time()
    items = ocr.read(png)
    print("OCR %.2fs 识别 %d 条" % (__import__("time").time() - t0, len(items)))

    print("\n-- 全部结果（按 y 排序） --")
    for it in items:
        side = "左" if it.cx < 450 else "右"
        print("   y=%-5d x=[%4d,%4d] %s %-5s %r"
              % (it.cy, it.box[0], it.box[2], side, "%.2f" % it.score, it.text[:30]))

    a.hand.back(settle=1.2)
    print("\n已返回 page=%s" % detect(a.snap()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
