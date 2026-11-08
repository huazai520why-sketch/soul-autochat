# -*- coding: utf-8 -*-
"""调试：当前会话页 OCR 出来的「疑似我方气泡」到底是什么文本。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import chat as C  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    print("page=%s sig=%s" % (detect(snap), snap.signature()))

    tree = set(t.strip() for t in snap.texts() if t and t.strip())
    print("\n-- UI 树里的文本（%d） --" % len(tree))
    for t in sorted(tree)[:26]:
        print("   %r" % t)

    png = dev.screencap()
    bs = C.bubbles(png)
    print("\n-- OCR 气泡（%d） --" % len(bs))
    for t, side, it in bs:
        mark = "TREE" if t.strip() in tree else "REAL"
        print("   [%s] %-6s y=%-5d x=%d..%d  %r"
              % (side, mark, it.cy, it.box[0], it.box[2], t[:34]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
