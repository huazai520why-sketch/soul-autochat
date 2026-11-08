# -*- coding: utf-8 -*-
"""确认发送按钮：灌字前后各 dump 一次，找出新增的可点击节点（不发消息）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402

TEXT = "测试一下"


def sig_nodes(snap):
    """可点击节点指纹集合（res_id + bounds）。"""
    return set((n.res_id.split("/")[-1], n.bounds) for n in snap.nodes if n.clickable)


def main():
    dev = Device.get()
    a = Actor(dev)
    d = dev.u2()

    snap = a.snap()
    for _ in range(4):
        if detect(snap) == "chatlist":
            break
        a.hand.back(settle=1.0)
        snap = a.snap()
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500
          and r.nickname and not r.nickname.startswith("Soul")]
    r = rs[0]
    print("进入 %r" % r.blob[:36])
    a.hand.tap_node(r.node, settle=2.2)

    snap0 = a.snap()
    print("page=%s" % detect(snap0))
    before = sig_nodes(snap0)
    n0 = snap0.find_one(res="et_sendmessage")
    print("空框时输入框: b=%s" % (n0.bounds,))

    print("\n-- 灌字 --")
    a.hand.tap_node(n0, settle=0.8)
    d.send_keys(TEXT)
    time.sleep(1.2)

    snap1 = a.snap()
    n1 = snap1.find_one(res="et_sendmessage")
    print("灌字后输入框 text=%r b=%s" % (n1.text if n1 else None, n1.bounds if n1 else None))

    after = sig_nodes(snap1)
    new = after - before
    print("\n新增可点击节点 %d 个：" % len(new))
    for rid, b in sorted(new, key=lambda x: x[1][1]):
        print("   %-28s b=%s" % (rid or "(no-id)", b))

    print("\n-- 输入框右侧（x>650）全部节点 --")
    for n in snap1.nodes:
        if n.bounds[0] > 650 and n.bounds[1] > 1450:
            print("   %-14s res=%-24s b=%-24s click=%-5s %r"
                  % ((n.cls or "").split(".")[-1], n.res_id.split("/")[-1],
                     n.bounds, n.clickable, n.label[:12]))

    print("\n-- 清空并返回（不发送） --")
    d.clear_text()
    time.sleep(0.8)
    a.hand.back(settle=1.2)
    print("   page=%s" % detect(a.snap()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
