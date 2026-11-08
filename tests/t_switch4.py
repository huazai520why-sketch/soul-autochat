# -*- coding: utf-8 -*-
"""切号：按截图实测的视觉位置点击左上角「切换用户」图标。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402

TARGET = "抬头仰望星空"
# 截图实测：图标在 (450x800 显示) ~ (38-68, 50-76)，x2 -> 实际 (76-136, 100-152)
TRIES = [(106, 126), (96, 116), (116, 136), (62, 98)]


def panel_open(scr):
    s = scr.get(force=True)
    ts = s.texts()
    return (any("切换账号" in t for t in ts) or any(TARGET == t for t in ts)), s, ts


def main():
    dev = Device.get()
    d = dev.u2()
    scr = Screen(dev)

    snap = scr.get(force=True)
    print("起点 page=%s" % detect(snap))
    if detect(snap) != "me":
        d.press("back")
        time.sleep(1.2)
        if detect(scr.get(force=True)) != "me":
            d(text="自己").click()
            time.sleep(1.5)

    for x, y in TRIES:
        print("\n>> 点 (%d,%d)" % (x, y))
        d.click(x, y)
        time.sleep(2.2)
        ok, s, ts = panel_open(scr)
        print("   page=%s nodes=%d" % (detect(s), len(s.nodes)))
        if ok:
            print("   面板打开！文本: %s"
                  % [t for t in ts if t in ("切换账号", "离殇描绘未来时光", TARGET, "添加账号", "管理")])
            break
        print("   没打开，文本前 6: %s" % [t[:12] for t in ts[4:10]])
        # 若误入别的页，退回
        if detect(s) != "me":
            print("   误入 %s，退回" % detect(s))
            d.press("back")
            time.sleep(1.2)
    else:
        print("\n四个候选点都没打开面板")
        return 1

    # 点目标账号
    print("\n>> 点 %r" % TARGET)
    try:
        d(text=TARGET).click()
    except Exception as e:
        print("   点击异常 %r" % e)
        return 2
    time.sleep(3.5)

    t0 = time.time()
    while time.time() - t0 < 60:
        s = scr.get(force=True)
        if detect(s) in ("me", "chatlist", "square", "planet"):
            break
        time.sleep(2)

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
    print("当前账号 = %r  %s" % (got, "OK" if got == TARGET else "!! 不是目标"))
    return 0 if got == TARGET else 3


if __name__ == "__main__":
    sys.exit(main())
