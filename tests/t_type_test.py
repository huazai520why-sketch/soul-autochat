# -*- coding: utf-8 -*-
"""验证灌字：进会话 -> 点输入框 -> 尝试多种方式灌中文 -> 读 UI 树确认 -> 清空。

不发消息。只验证「字能不能进去」。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402

TEXT = "测试中文abc"


def box_text(snap):
    n = snap.find_one(res="et_sendmessage")
    return (n.text if n else None), n


def main():
    dev = Device.get()
    a = Actor(dev)
    d = dev.u2()

    snap = a.snap()
    for _ in range(4):
        if detect(snap) == "chatlist":
            break
        print("  当前 page=%s，返回一层" % detect(snap))
        a.hand.back(settle=1.0)
        snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", settle=1.5)
        snap = a.snap()
    print("  起点 page=%s" % detect(snap))
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    # 跳过官方号（Soul空间站/Soul通知），只进真人会话
    rs = [r for r in rs if r.nickname and not r.nickname.startswith("Soul")]
    if not rs:
        print("没有真人会话")
        return 1
    r = rs[0]
    print("进入 %r" % r.blob[:40])
    a.hand.tap_node(r.node, settle=2.2)

    snap2 = a.snap()
    print("page=%s" % detect(snap2))
    if detect(snap2) != "chat":
        print("!! 不是聊天页，退回并放弃")
        a.hand.back(settle=1.2)
        return 1
    t, n = box_text(snap2)
    print("输入框: b=%s text=%r" % (n.bounds if n else None, t))
    if n is None:
        print("!! 没有 et_sendmessage")
        return 1

    print("\n-- 点输入框 --")
    a.hand.tap_node(n, settle=1.0)

    print("\n-- 方式A: u2 send_keys --")
    try:
        d.send_keys(TEXT)
    except Exception as e:
        print("   send_keys 异常 %r" % e)
    time.sleep(1.2)
    t2, n2 = box_text(a.snap())
    print("   结果 text=%r  %s" % (t2, "OK" if TEXT in (t2 or "") else "FAIL"))

    if TEXT not in (t2 or ""):
        print("\n-- 方式B: element.set_text --")
        try:
            d(resourceId="et_sendmessage").set_text(TEXT)
        except Exception as e:
            print("   set_text 异常 %r" % e)
        time.sleep(1.2)
        t3, _ = box_text(a.snap())
        print("   结果 text=%r  %s" % (t3, "OK" if TEXT in (t3 or "") else "FAIL"))

    print("\n-- 清空 --")
    try:
        d.clear_text()
    except Exception as e:
        print("   clear_text 异常 %r" % e)
    time.sleep(0.8)
    t4, _ = box_text(a.snap())
    print("   清空后 text=%r" % (t4,))

    print("\n-- 返回列表 --")
    a.hand.back(settle=1.2)
    print("   page=%s" % detect(a.snap()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
