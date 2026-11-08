# -*- coding: utf-8 -*-
"""切号：先关掉「领福利」活动弹窗，再点「切换用户」，再选账号。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402

TARGET = "抬头仰望星空"
POP_HINTS = ("我知道了", "知道了", "领福利", "戳这里", "关闭")
CLOSE_TEXTS = ("我知道了", "知道了", "关闭", "取消")


def close_popups(d, scr, max_try=5):
    for i in range(max_try):
        s = scr.get(force=True)
        ts = s.texts()
        hit = [k for k in POP_HINTS if any(k in t for t in ts)]
        if not hit:
            if i:
                print("   弹窗已清（共 %d 轮）" % i)
            return s
        btn = None
        for t in CLOSE_TEXTS:
            btn = s.hit(text=t)
            if btn is not None:
                print("   关弹窗：点 %r %s" % (t, btn.center))
                break
        if btn is None:
            # 用视觉位置兜底：弹窗按钮通常在下方居中
            print("   找不到按钮，按返回")
            d.press("back")
        else:
            d.click(*btn.center)
        time.sleep(1.4)
    return scr.get(force=True)


def main():
    dev = Device.get()
    d = dev.u2()
    scr = Screen(dev)

    if detect(scr.get(force=True)) != "me":
        d.press("back")
        time.sleep(1.0)
        if detect(scr.get(force=True)) != "me":
            d(text="自己").click()
            time.sleep(1.6)

    print("== 清弹窗 ==")
    s = close_popups(d, scr)
    print("   page=%s nodes=%d" % (detect(s), len(s.nodes)))

    print("\n== 点切换用户 ==")
    n = s.hit(desc="切换用户") or s.hit(text="切换用户")
    if n is None:
        print("   树里没有切换用户，打印顶部节点")
        for x in s.nodes:
            if x.bounds[3] < 200 and x.label:
                print("      %r b=%s" % (x.label[:14], x.bounds))
        return 1
    print("   目标 b=%s center=%s" % (n.bounds, n.center))
    d.click(*n.center)
    time.sleep(2.5)

    s2 = scr.get(force=True)
    ts = s2.texts()
    if not (any("切换账号" in t for t in ts) or any(TARGET == t for t in ts)):
        print("   面板没开，page=%s 文本=%s" % (detect(s2), [t[:12] for t in ts[:10]]))
        return 2
    print("   面板打开: %s" % [t for t in ts if t in
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
