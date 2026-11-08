# -*- coding: utf-8 -*-
"""奇遇铃实弹处理：OCR 找「立即私聊」-> 点 -> 发开场白。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import match as M  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    s = a.snap(force=True)
    txt = " ".join(s.texts())
    print("page=%s" % detect(s))
    print("有铃迹象: %s" % any(k in txt for k in ("奇遇铃", "同城奇遇", "关闭弹窗")))

    png = dev.screencap()
    items = ocr.read(png)
    print("\n-- OCR 全文 --")
    for it in items:
        print("   x=%-4d y=%-5d %r" % (it.cx, it.cy, it.text[:30]))

    btn = None
    for it in items:
        if "立即私聊" in it.text or "私聊" in it.text:
            btn = it
            break
    if btn is None:
        print("\n!! OCR 也没找到「立即私聊」，铃可能已消失")
        return 1

    print("\n>> 点「立即私聊」(%d, %d)" % (btn.cx, btn.cy))
    a.hand.tap_xy(btn.cx, btn.cy, settle=2.5)

    s2, pg = a.wait_page(("chat",), timeout=8)
    print("落点 page=%s fg=%s" % (pg, dev.current_app()[1].split(".")[-1]))
    if pg != "chat":
        print("没进会话")
        return 2

    text = M.pick_opener()
    print("开场白 %r" % text)
    ok, why = M.send(a, dev, text)
    print("发送 ok=%s %s" % (ok, why))
    if ok:
        print("\n>> 顺手建档")
        prof, pok = M.visit_profile(a)
        print("   主页 ok=%s %r" % (pok, prof.get("nick") if prof else None))
        a.hand.back(settle=1.2)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
