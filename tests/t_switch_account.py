# -*- coding: utf-8 -*-
"""切号往返：离殇 -> 抬头仰望星空 -> 离殇。每步等待加载并确认落点账号。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import detect  # noqa: E402

MAIN_PAGES = ("square", "chatlist", "me", "planet")


def ensure_base(a):
    """确保回到主框架：账号面板/弹窗先关掉。"""
    for _ in range(4):
        s = a.snap()
        pg = detect(s)
        if pg in MAIN_PAGES:
            return s
        ts = s.texts()
        if any("切换账号" in t for t in ts):
            print("   关闭账号面板")
            a.hand.back(settle=1.0)
            continue
        p = P.detect(s)
        if p is not None and (p.primary or p.secondary):
            btn = (p.primary or p.secondary)[0]
            print("   点弹窗按钮 %r" % btn[0])
            a.hand.tap_node(btn[1], settle=1.2)
            continue
        a.hand.back(settle=1.0)
    return a.snap()


def open_me(a):
    if detect(a.snap()) != "me":
        a.tap_tab("自己", expect="me")
    return a.snap()


def whoami(a):
    """从「自己」页读当前账号昵称。"""
    snap = open_me(a)
    for n in snap.nodes:
        t = (n.label or "").strip()
        if t in ("离殇描绘未来时光", "抬头仰望星空"):
            return t
    return "?"


def wait_main(a, timeout=90):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        s = a.snap()
        pg = detect(s)
        last = pg
        if pg in MAIN_PAGES:
            return pg, s
        time.sleep(2)
    return last, a.snap()


def switch_to(a, name):
    print("\n>> 切到 %r" % name)
    snap = open_me(a)
    n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
    if n is None:
        print("   找不到切换用户入口")
        return False
    a.hand.tap_node(n, settle=1.6)

    snap2 = a.snap()
    print("   账号面板: %s" % [t for t in snap2.texts() if "账号" in t or t in
                              ("离殇描绘未来时光", "抬头仰望星空", "添加账号")])
    p = P.detect(snap2)
    if p is not None:
        print("   弹窗: %s" % [b[0] for b in p.buttons])

    row = snap2.hit(text_contains=name)
    if row is None:
        print("   ! 面板里找不到 %r" % name)
        return False
    print("   点击账号行 %s b=%s" % ((row.cls or "").split(".")[-1], row.bounds))
    a.hand.tap_node(row, settle=3.0)

    print("   等待加载...")
    pg, snap3 = wait_main(a, timeout=90)
    print("   落点 page=%s nodes=%d" % (pg, len(snap3.nodes)))
    return pg in MAIN_PAGES


def main():
    a = Actor(Device.get())

    ensure_base(a)
    cur = whoami(a)
    print("== 起始账号: %r ==" % cur)

    other = "抬头仰望星空" if cur != "抬头仰望星空" else "离殇描绘未来时光"
    if not switch_to(a, other):
        print("\n切换失败，停止（不继续切回，避免状态不明）")
        return 1
    time.sleep(3)
    print("   当前账号 = %r" % whoami(a))

    print("\n>> 切回 %r" % cur)
    if not switch_to(a, cur):
        print("\n切回失败！")
        return 2
    time.sleep(3)
    got = whoami(a)
    print("   当前账号 = %r" % got)
    print("\n结果: %s" % ("OK 往返成功" if got == cur else "!! 账号不是原账号"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
