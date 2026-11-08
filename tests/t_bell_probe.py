# -*- coding: utf-8 -*-
"""奇遇铃弹出时：dump 结构（不点击），确认判据。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import bell as B  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    print("page=%s nodes=%d fg=%s" % (detect(s), len(s.nodes), dev.current_app()[1].split(".")[-1]))
    print("is_bell = %s" % B.is_bell(s))

    print("\n-- 全部文本 --")
    for i, t in enumerate(s.texts()[:30]):
        print("  %02d %r" % (i, t[:44]))

    print("\n-- 可点击节点 --")
    for n in s.nodes:
        if n.clickable and n.visible and (n.label or n.desc):
            print("   b=%-24s %-14s %r %r"
                  % (n.bounds, n.cls.split(".")[-1], (n.label or "")[:20], (n.desc or "")[:16]))

    p, size, _ = dev.screencap_to(LOGS / "_bell.png")
    print("\n截图 %d bytes" % size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
