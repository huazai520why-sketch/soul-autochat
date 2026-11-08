# -*- coding: utf-8 -*-
"""探针：进入一个会话，分析消息气泡结构 —— 怎么判断左右（谁发的）+ 输入框位置。

只读，不发任何消息。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    a = Actor(Device.get())
    snap = a.snap()
    if detect(snap) != "chatlist":
        print("当前不是列表页: %s" % detect(snap))
        return 1

    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    if not rs:
        print("列表为空")
        return 1
    target = rs[0]
    print("进入第一个会话: %r" % target.blob[:50])
    a.hand.tap_node(target.node, settle=2.2)

    snap2 = a.snap()
    print("page = %s  nodes=%d" % (detect(snap2), len(snap2.nodes)))

    print("\n-- 消息区节点（y 130~1460，有文本） --")
    items = [n for n in snap2.nodes
             if n.label and 120 < n.center[1] < 1470]
    items.sort(key=lambda n: (n.center[1], n.bounds[0]))
    for n in items:
        b = n.bounds
        # 左右判据初判
        side = "左" if b[2] <= 600 else ("右" if b[0] >= 300 else "?")
        print("   y=%-5d %-10s b=%-22s %s %r"
              % (n.center[1], (n.cls or "").split(".")[-1], b, side, n.label[:34]))

    print("\n-- 输入框 / 发送 --")
    for n in snap2.nodes:
        b = n.bounds
        if b[1] < 1440:
            continue
        print("   %-14s b=%-24s res=%s click=%s %r"
              % ((n.cls or "").split(".")[-1], b, n.res_id.split("/")[-1],
                 n.clickable, n.label[:18]))

    print("\n-- 返回列表 --")
    a.hand.back(settle=1.3)
    s3 = a.snap()
    print("   page=%s" % detect(s3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
