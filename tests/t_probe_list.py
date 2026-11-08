# -*- coding: utf-8 -*-
"""探针：找会话列表的滚动容器与「行」容器，替代按像素聚类。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    snap = Screen(Device.get()).get(force=True)

    print("== scrollable 节点 ==")
    for n in snap.nodes:
        if n.scrollable and n.visible:
            kids = [c for c in snap.nodes if c.parent is n]
            print("  %-18s b=%s  direct_kids=%d"
                  % ((n.cls or "").split(".")[-1], n.bounds, len(kids)))
            for c in kids[:6]:
                grand = [g for g in snap.nodes if g.parent is c]
                print("      - %-16s b=%s kids=%d text=%r"
                      % ((c.cls or "").split(".")[-1], c.bounds, len(grand),
                         (c.text or c.desc)[:12]))

    print("\n== 类名含 Recycler/List 的节点 ==")
    for n in snap.nodes:
        c = (n.cls or "")
        if "Recycler" in c or "ListView" in c:
            kids = [x for x in snap.nodes if x.parent is n]
            print("  %s b=%s kids=%d clickable=%s"
                  % (c.split(".")[-1], n.bounds, len(kids), n.clickable))


if __name__ == "__main__":
    main()
