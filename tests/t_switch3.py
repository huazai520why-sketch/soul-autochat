# -*- coding: utf-8 -*-
"""切号（u2 原生选择器版）：控件级点击，不用手算坐标。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402

TARGET = "抬头仰望星空"


def main():
    dev = Device.get()
    d = dev.u2()
    scr = Screen(dev)

    snap = scr.get(force=True)
    print("起点 page=%s nodes=%d" % (detect(snap), len(snap.nodes)))

    # 1) 打开切换面板
    print("\n>> u2 点「切换用户」")
    for i in range(3):
        try:
            el = d(description="切换用户")
            if not el.exists:
                el = d(descriptionContains="切换用户")
            print("   元素 info: %s" % (el.info.get("bounds") if el.exists else None))
            el.click()
        except Exception as e:
            print("   点击异常 %r" % e)
        time.sleep(3.0)
        s = scr.get(force=True)
        ts = s.texts()
        if any("切换账号" in t for t in ts) or any(TARGET == t for t in ts):
            print("   面板打开 nodes=%d" % len(s.nodes))
            print("   面板文本: %s" % [t for t in ts if t in
                                       ("切换账号", "离殇描绘未来时光", TARGET, "添加账号", "管理")])
            break
        print("   第%d次未打开（page=%s）" % (i + 1, detect(s)))
    else:
        print("打不开面板")
        return 1

    # 2) 点目标账号
    print("\n>> u2 点 %r" % TARGET)
    try:
        el2 = d(text=TARGET)
        print("   元素 bounds=%s" % (el2.info.get("bounds") if el2.exists else None))
        el2.click()
    except Exception as e:
        print("   点击异常 %r" % e)
        return 2

    t0 = time.time()
    while time.time() - t0 < 60:
        s = scr.get(force=True)
        pg = detect(s)
        if pg in ("me", "chatlist", "square", "planet"):
            print("   落点 %s %.1fs" % (pg, time.time() - t0))
            break
        time.sleep(2)

    # 3) 确认账号
    s = scr.get(force=True)
    if detect(s) != "me":
        d(text="自己").click()
        time.sleep(1.5)
        s = scr.get(force=True)
    got = "?"
    for n in s.nodes:
        t = (n.label or "").strip()
        if t in ("离殇描绘未来时光", TARGET):
            got = t
            break
    print("\n当前账号 = %r  %s" % (got, "OK" if got == TARGET else "!! 不是目标"))
    return 0 if got == TARGET else 3


if __name__ == "__main__":
    sys.exit(main())
