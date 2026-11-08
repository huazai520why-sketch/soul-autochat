# -*- coding: utf-8 -*-
"""探针：抽查列表前几个会话，找出「有真实气泡」的那个，分析左右分布。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def msgs_of(snap):
    """消息区（避开顶部卡片与底部快捷栏）里有文本的节点。"""
    out = [n for n in snap.nodes if n.label and 560 < n.center[1] < 1400]
    out.sort(key=lambda n: (n.center[1], n.bounds[0]))
    return out


def main():
    a = Actor(Device.get())
    snap = a.snap()
    if detect(snap) != "chatlist":
        print("不在列表页: %s" % detect(snap))
        return 1
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    print("列表 %d 行" % len(rs))

    found = None
    for idx in range(min(6, len(rs))):
        snap = a.snap()
        rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
        if idx >= len(rs):
            break
        r = rs[idx]
        print("\n[%d] %r" % (idx, r.blob[:52]))
        a.hand.tap_node(r.node, settle=2.0)
        s2 = a.snap()
        ms = msgs_of(s2)
        print("     page=%s  消息节点=%d" % (detect(s2), len(ms)))
        for m in ms[:8]:
            print("        y=%-5d b=%-22s %r" % (m.center[1], m.bounds, m.label[:30]))
        if len(ms) >= 3:
            found = (idx, r.blob[:40], ms)
            print("     >> 有气泡，就用这个")
            a.hand.back(settle=1.2)
            break
        a.hand.back(settle=1.2)

    if found:
        idx, blob, ms = found
        print("\n== 选定会话 [%d] %r ==" % (idx, blob))
        print("  气泡左右分布：")
        for m in ms:
            b = m.bounds
            side = "右(我)" if b[0] >= 450 else ("左(她)" if b[2] <= 450 else "跨中")
            print("     y=%-5d x=[%d,%d] %-7s %r" % (m.center[1], b[0], b[2], side, m.label[:34]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
