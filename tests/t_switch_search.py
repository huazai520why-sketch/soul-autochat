# -*- coding: utf-8 -*-
"""切号往返 -> 再试搜索（验证用户判断：退出过账号导致搜索记录不在）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import detect  # noqa: E402

MAIN = ("square", "chatlist", "me", "planet")
A1 = "离殇描绘未来时光"
A2 = "抬头仰望星空"
KEY = "留着下次接着讲"


def ensure_base(a):
    for _ in range(4):
        s = a.snap()
        pg = detect(s)
        if pg in MAIN:
            return s
        if any("切换账号" in t for t in s.texts()):
            a.hand.back(settle=1.0)
            continue
        p = P.detect(s)
        if p is not None and (p.primary or p.secondary):
            a.hand.tap_node((p.primary or p.secondary)[0][1], settle=1.2)
            continue
        a.hand.back(settle=1.0)
    return a.snap()


def whoami(a):
    if detect(a.snap()) != "me":
        a.tap_tab("自己", expect="me")
    for n in a.snap().nodes:
        t = (n.label or "").strip()
        if t in (A1, A2):
            return t
    return "?"


def switch_to(a, name):
    print("   >> 切到 %r" % name)
    if detect(a.snap()) != "me":
        a.tap_tab("自己", expect="me")
    snap = a.snap()
    n = snap.hit(desc="切换用户") or snap.hit(text="切换用户")
    if n is None:
        print("      找不到切换入口")
        return False
    a.hand.tap_node(n, settle=1.6)
    s2 = a.snap()
    row = s2.hit(text_contains=name)
    if row is None:
        print("      面板里没有 %r" % name)
        a.hand.back(settle=1.0)
        return False
    a.hand.tap_node(row, settle=3.0)
    t0 = time.time()
    while time.time() - t0 < 60:
        s = a.snap()
        if detect(s) in MAIN:
            print("      落点 %s  %.1fs" % (detect(s), time.time() - t0))
            return True
        time.sleep(2)
    return False


def try_search(a, dev):
    print("\n== 搜索 %r ==" % KEY)
    snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", expect="chatlist")
        snap = a.snap()
    n = snap.hit(res="c_ct_chat_fragment_search") or snap.hit(desc="搜索")
    if n is None:
        print("   找不到搜索图标")
        return False
    a.hand.tap_node(n, settle=1.8)
    s2 = a.snap()
    box = s2.find_one(cls="EditText")
    if box is None:
        print("   搜索页没有输入框")
        return False
    a.hand.tap_node(box, settle=0.7)
    dev.u2().clear_text()
    time.sleep(0.3)
    dev.u2().send_keys(KEY)
    time.sleep(2.2)
    s3 = a.snap()
    texts = s3.texts()
    print("   结果 %d 条文本：" % len(texts))
    for t in texts[:14]:
        print("      %s" % t[:40])
    hit = any("未找到" in t for t in texts)
    print("   >> %s" % ("未找到相关结果" if hit else "有结果（可继续）"))
    return not hit


def main():
    dev = Device.get()
    a = Actor(dev)
    ensure_base(a)
    cur = whoami(a)
    print("起始账号 %r" % cur)
    other = A2 if cur == A1 else A1

    if not switch_to(a, other):
        print("切出失败")
        return 1
    print("   现在 %r" % whoami(a))

    if not switch_to(a, cur):
        print("切回失败")
        return 2
    print("   现在 %r" % whoami(a))

    ok = try_search(a, dev)
    print("\n结论: 切号后%s" % ("能搜到历史对话" if ok else "仍然搜不到历史对话"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
