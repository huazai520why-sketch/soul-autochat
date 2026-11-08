# -*- coding: utf-8 -*-
"""探查：从会话页进对方主页，看能抓到哪些资料，再返回。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    print("起点 page=%s" % detect(snap))

    if detect(snap) != "chat":
        print("不在会话页")
        return 1

    print("\n-- 找进主页的入口 --")
    for kw in ("查看主页", "主页"):
        n = snap.hit(text=kw)
        print("  %-6s -> %s" % (kw, "None" if n is None else "b=%s click=%s cls=%s"
                                % (n.bounds, n.clickable, n.cls)))
    av = [n for n in snap.nodes if n.desc == "头像" or n.label == "头像"]
    for n in av[:3]:
        print("  头像  b=%s click=%s res=%s" % (n.bounds, n.clickable, n.res_id))

    n = snap.hit(text="查看主页")
    if n is None:
        print("找不到「查看主页」")
        return 2

    print("\n>> 点查看主页 %s" % (n.bounds,))
    a.hand.tap_node(n, settle=2.5)
    s2 = a.snap(force=True)
    print("落点 page=%s nodes=%d" % (detect(s2), len(s2.nodes)))
    print("foreground=%s" % (dev.current_app(),))

    print("\n-- 主页文本（前 45） --")
    for i, t in enumerate(s2.texts()[:45]):
        print("  %02d %r" % (i, t[:44]))

    png = dev.screencap()
    (LOGS / "_profile.png").write_bytes(png)
    print("\n截图 logs/_profile.png %d bytes" % len(png))
    print("-- OCR 前 24 --")
    for it in ocr.read(png)[:24]:
        print("  y=%-5d x=%d..%d %r" % (it.cy, it.box[0], it.box[2], it.text[:36]))

    print("\n>> 返回会话")
    a.hand.back(settle=1.5)
    s3 = a.snap(force=True)
    print("返回后 page=%s sig=%s" % (detect(s3), s3.signature()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
