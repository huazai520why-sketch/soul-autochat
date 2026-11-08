# -*- coding: utf-8 -*-
"""探路：星球页结构 + 找「灵魂匹配」入口（文本优先，坐标兜底不用）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)

    snap, pg = nav.to_tab(a, "星球")
    print("落点 page=%s nodes=%d" % (pg, len(snap.nodes)))
    print("文本 %d 条:" % len([n for n in snap.nodes if n.label]))
    for n in snap.nodes:
        if n.label:
            print("   y=%-5d %-14s b=%-22s click=%-5s %r"
                  % (n.center[1], (n.cls or "").split(".")[-1], n.bounds,
                     n.clickable, n.label[:24]))

    print("\n== 找「灵魂匹配」==")
    cands = [n for n in snap.nodes if n.label and "灵魂" in n.label]
    for n in cands:
        print("   命中 %s b=%s click=%s" % (n.label[:16], n.bounds, n.clickable))
    if not cands:
        print("   树里没有「灵魂」相关节点")

    print("\n== OCR 兜底 ==")
    png = dev.screencap()
    (LOGS / "_planet.png").write_bytes(png)
    items = ocr.read(png)
    print("  识别 %d 条：" % len(items))
    for it in items[:20]:
        print("     y=%-5d x=[%d,%d] %r" % (it.cy, it.box[0], it.box[2], it.text[:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
