# -*- coding: utf-8 -*-
"""只做一件事：切到「抬头仰望星空」。不往返。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import detect  # noqa: E402

MAIN = ("square", "chatlist", "me", "planet")
TARGET = "抬头仰望星空"


def ensure_base(a):
    for _ in range(5):
        s = a.snap()
        pg = detect(s)
        print("   当前 page=%s" % pg)
        if pg in MAIN:
            return s
        ts = s.texts()
        if any("切换账号" in t for t in ts):
            print("   关闭账号面板")
            a.hand.back(settle=1.2)
            continue
        p = P.detect(s)
        if p is not None and (p.primary or p.secondary):
            print("   点弹窗 %r" % (p.primary or p.secondary)[0][0])
            a.hand.tap_node((p.primary or p.secondary)[0][1], settle=1.2)
            continue
        a.hand.back(settle=1.2)
    return a.snap()


def me_user(a):
    if detect(a.snap()) != "me":
        a.tap_tab("自己", settle=1.5)
    snap = a.snap()
    for n in snap.nodes:
        t = (n.label or "").strip()
        if t in ("离殇描绘未来时光", "抬头仰望星空"):
            return t
    return "?"


def main():
    a = Actor(Device.get())
    ensure_base(a)
    print("当前账号 = %r" % me_user(a))

    print("\n>> 打开切换账号")
    snap = a.snap()
    if detect(snap) != "me":
        a.tap_tab("自己", expect="me")
        snap = a.snap()
    n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
    if n is None:
        print("   找不到切换入口")
        return 1
    a.hand.tap_node(n, settle=1.6)

    s2 = a.snap()
    print("   面板: %s" % [t for t in s2.texts() if "账号" in t or t in
                           ("离殇描绘未来时光", "抬头仰望星空", "添加账号")])
    row = s2.hit(text_contains=TARGET)
    if row is None:
        print("   面板里没有 %r" % TARGET)
        a.hand.back(settle=1.0)
        return 2
    print("   点 %r %s" % (TARGET, row.bounds))
    a.hand.tap_node(row, settle=3.0)

    t0 = time.time()
    while time.time() - t0 < 60:
        s = a.snap()
        pg = detect(s)
        if pg in MAIN:
            print("   落点 %s  %.1fs" % (pg, time.time() - t0))
            break
        time.sleep(2)

    got = me_user(a)
    print("\n当前账号 = %r  %s" % (got, "OK" if got == TARGET else "!! 不对"))
    return 0 if got == TARGET else 3


if __name__ == "__main__":
    sys.exit(main())
