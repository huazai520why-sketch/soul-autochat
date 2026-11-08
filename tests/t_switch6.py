# -*- coding: utf-8 -*-
"""切号：先滑到页面顶部，再点「切换用户」（用户指点：不拉顶会点错位置）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402

TARGET = "抬头仰望星空"


def back_to_me(d, scr, max_try=5):
    for _ in range(max_try):
        s = scr.get(force=True)
        if detect(s) == "me":
            return s
        d.press("back")
        time.sleep(1.2)
    return scr.get(force=True)


def scroll_top(d, times=4):
    """在页面顶部往下拉，回到最顶。"""
    for _ in range(times):
        d.swipe(450, 400, 450, 1450, 0.18)
        time.sleep(0.45)


def close_popup(d, scr):
    s = scr.get(force=True)
    ts = s.texts()
    if any("我知道了" in t for t in ts):
        btn = s.hit(text="我知道了")
        if btn is not None:
            print("   关活动弹窗 %s" % (btn.center,))
            d.click(*btn.center)
            time.sleep(1.5)
            return scr.get(force=True)
    return s


def main():
    dev = Device.get()
    d = dev.u2()
    scr = Screen(dev)

    s = back_to_me(d, scr)
    print("page=%s" % detect(s))
    s = close_popup(d, scr)

    print("\n== 滑到顶部 ==")
    scroll_top(d, 4)
    s = scr.get(force=True)
    print("   page=%s nodes=%d" % (detect(s), len(s.nodes)))
    print("   顶部 6 条文本: %s" % [t[:12] for t in s.texts()[:6]])

    n = s.hit(desc="切换用户") or s.hit(text="切换用户")
    if n is None:
        print("   树里没有切换用户")
        return 1
    print("\n== 点切换用户 b=%s center=%s ==" % (n.bounds, n.center))
    d.click(*n.center)
    time.sleep(2.5)

    s2 = scr.get(force=True)
    ts = s2.texts()
    if not (any("切换账号" in t for t in ts) or any(TARGET == t for t in ts)):
        print("   面板没开 page=%s 前10文本=%s" % (detect(s2), [t[:12] for t in ts[:10]]))
        # 若又误入装扮中心，退回
        if detect(s2) != "me":
            d.press("back")
        return 2
    print("   ✓ 面板打开: %s" % [t for t in ts if t in
                                ("切换账号", "离殇描绘未来时光", TARGET, "添加账号", "管理")])

    print("\n== 点 %r ==" % TARGET)
    d(text=TARGET).click()
    time.sleep(3.5)

    t0 = time.time()
    while time.time() - t0 < 60:
        s3 = scr.get(force=True)
        if detect(s3) in ("me", "chatlist", "square", "planet"):
            break
        time.sleep(2)
    s3 = scr.get(force=True)
    if detect(s3) != "me":
        d(text="自己").click()
        time.sleep(1.6)
        s3 = scr.get(force=True)
    got = "?"
    for x in s3.nodes:
        t = (x.label or "").strip()
        if t in ("离殇描绘未来时光", TARGET):
            got = t
            break
    print("当前账号 = %r  %s" % (got, "OK" if got == TARGET else "!! 不是目标"))
    return 0 if got == TARGET else 3


if __name__ == "__main__":
    sys.exit(main())
