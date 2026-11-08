# -*- coding: utf-8 -*-
"""探查「收到的新招呼」这行：点进去是什么页面，要不要再点一次才进对话页。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import badges, detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    print("起点 page=%s badges=%s" % (detect(snap), badges(snap)))

    rows = CL.rows(snap)
    target = None
    for r in rows:
        if "新招呼" in r.blob:
            target = r
            break
    if target is None:
        print("没找到「新招呼」行")
        for r in rows:
            print("   %r" % r.blob[:50])
        return 1

    print("\n目标行 %r  b=%s  红点=%s" % (target.blob[:40], target.node.bounds, target.badge))
    print(">> 点进去")
    a.hand.tap_node(target.node, settle=2.5)

    s2 = a.snap(force=True)
    print("\n落点 page=%s nodes=%d fg=%s" % (detect(s2), len(s2.nodes), dev.current_app()))
    print("\n-- 全部文本 --")
    for i, t in enumerate(s2.texts()[:45]):
        print("  %02d %r" % (i, t[:44]))

    print("\n-- 可点击节点（面积大的） --")
    for n in s2.nodes:
        if n.clickable and n.visible:
            w = n.bounds[2] - n.bounds[0]
            h = n.bounds[3] - n.bounds[1]
            if w > 300 and h > 80:
                print("   b=%-24s %-16s %r" % (n.bounds, n.cls.split(".")[-1], (n.label or n.desc or "")[:24]))

    print("\n-- 页面里的「打招呼/私聊/回复」类按钮 --")
    for kw in ("打招呼", "私聊", "回复", "去聊天", "开始聊天", "关注"):
        n = s2.hit(text=kw)
        if n:
            print("   %s -> b=%s click=%s" % (kw, n.bounds, n.clickable))
    return 0


if __name__ == "__main__":
    sys.exit(main())
