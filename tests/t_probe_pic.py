# -*- coding: utf-8 -*-
"""探查会话页发图入口：底部工具栏 -> 「更多」/相册 -> 选图。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def dump_bottom(a, tag):
    s = a.snap(force=True)
    print("\n-- %s page=%s nodes=%d --" % (tag, detect(s), len(s.nodes)))
    for n in sorted([x for x in s.nodes if x.center[1] > 1380],
                    key=lambda x: (x.center[1], x.center[0])):
        if not (n.label or n.desc or n.clickable):
            continue
        print("  y=%-5d x=%-4d %-14s click=%s %r %r res=%s"
              % (n.center[1], n.center[0], n.cls.split(".")[-1], n.clickable,
                 (n.label or "")[:14], (n.desc or "")[:12], (n.res_id or "")[-22:]))
    return s


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = CL.to_list(a)
    if detect(snap) != "chatlist":
        print("不在列表")
        return 1
    rows = [r for r in CL.rows(snap) if 200 <= r.center[1] <= 1500]
    if not rows:
        print("列表空")
        return 2
    print("进 %r" % rows[0].blob[:30])
    a.hand.tap_node(rows[0].node, settle=1.8)
    s, pg = a.wait_page(("chat",), timeout=6)
    print("落点 page=%s" % pg)
    if pg != "chat":
        return 3

    dump_bottom(a, "会话页底部")

    # 点「更多」
    s = a.snap()
    n = s.hit(text="更多") or s.hit(desc="更多")
    if n is None:
        print("\n没有「更多」按钮")
    else:
        print("\n>> 点更多 %s" % (n.bounds,))
        a.hand.tap_node(n, settle=1.8)
        dump_bottom(a, "更多面板")
        a.hand.back(settle=1.0)

    # 找相册/图片类资源 id
    s = a.snap(force=True)
    print("\n-- 含 pic/image/album/photo 的节点 --")
    for x in s.nodes:
        rid = (x.res_id or "").lower()
        d = (x.desc or "").lower()
        if any(k in rid for k in ("pic", "image", "album", "photo")) or \
           any(k in d for k in ("图片", "相册", "照片")):
            print("   %-16s b=%-22s click=%s res=%s desc=%r"
                  % (x.cls.split(".")[-1], x.bounds, x.clickable, x.res_id, x.desc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
