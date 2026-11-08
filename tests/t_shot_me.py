# -*- coding: utf-8 -*-
"""截图 me 页，供人工确认「切换用户」按钮的精确位置。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    snap = Screen(dev).get(force=True)
    print("page=%s nodes=%d" % (detect(snap), len(snap.nodes)))

    print("\n-- 左上角区域节点（y<200, x<300） --")
    for n in snap.nodes:
        if n.bounds[1] > 200 or n.bounds[0] > 300:
            continue
        if not n.visible:
            continue
        print("   %-12s b=%-22s click=%-5s desc=%r text=%r"
              % ((n.cls or "").split(".")[-1], n.bounds, n.clickable,
                 n.desc[:12], n.text[:12]))

    p, size, dt = dev.screencap_to(LOGS / "_me.png")
    print("\n截图 %s %d bytes %.2fs" % (p.name, size, dt))

    # OCR 辅助定位
    from eyes import ocr
    for it in ocr.read(p.read_bytes())[:10]:
        print("   ocr y=%-5d x=[%d,%d] %r" % (it.cy, it.box[0], it.box[2], it.text[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
