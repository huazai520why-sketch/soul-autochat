# -*- coding: utf-8 -*-
"""切号（稳健版）：点切换用户 -> 轮询等面板 -> 点目标账号 -> 确认。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402

TARGET = "抬头仰望星空"


def open_panel(a, timeout=12):
    for attempt in range(3):
        snap = a.snap()
        n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
        if n is None:
            print("   [%d] 找不到切换用户" % (attempt + 1))
            return None
        print("   [%d] 点切换用户 %s" % (attempt + 1, n.bounds))
        a.hand.tap_node(n, settle=2.2)
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = a.snap()
            ts = s.texts()
            if any("切换账号" in t for t in ts) or any(TARGET == t for t in ts):
                print("   面板已开 (%d 节点): %s"
                      % (len(s.nodes), [t for t in ts if t in
                                        ("切换账号", "离殇描绘未来时光", TARGET, "添加账号")]))
                return s
            time.sleep(1.0)
        print("   [%d] 面板没开，重试" % (attempt + 1))
    return None


def main():
    a = Actor(Device.get())
    print("当前 page=%s" % detect(a.snap()))
    s = open_panel(a)
    if s is None:
        print("打不开切换面板")
        return 1

    row = s.hit(text_contains=TARGET)
    if row is None:
        print("面板里没有 %r" % TARGET)
        for n in s.nodes:
            if n.label:
                print("   %r b=%s" % (n.label[:20], n.bounds))
        a.hand.back(settle=1.0)
        return 2

    print("点 %r %s" % (TARGET, row.bounds))
    a.hand.tap_node(row, settle=3.5)

    t0 = time.time()
    while time.time() - t0 < 60:
        s = a.snap()
        pg = detect(s)
        if pg in ("me", "chatlist", "square", "planet"):
            break
        time.sleep(2)
    print("落点 %s %.1fs" % (detect(s), time.time() - t0))

    if detect(s) != "me":
        a.tap_tab("自己", settle=1.5)
        s = a.snap()
    got = "?"
    for n in s.nodes:
        t = (n.label or "").strip()
        if t in ("离殇描绘未来时光", TARGET):
            got = t
            break
    print("当前账号 = %r  %s" % (got, "OK" if got == TARGET else "!! 不是目标"))
    return 0 if got == TARGET else 3


if __name__ == "__main__":
    sys.exit(main())
