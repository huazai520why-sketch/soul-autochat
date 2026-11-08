# -*- coding: utf-8 -*-
"""探针：看底栏区域的真实节点层级，判断 tab 为什么上溯不到 clickable 祖先。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    snap = Screen(dev).get(force=True)

    print("== 底部区域 y>1500 ==")
    for n in snap.nodes:
        if n.bounds[1] < 1500 or not n.visible:
            continue
        print("  %s%-22s click=%-5s sel=%-5s b=%s text=%r"
              % ("  " * min(n.depth, 6), (n.cls or "").split(".")[-1],
                 n.clickable, n.selected, n.bounds, n.text[:16]))

    print("\n== '聊天' 的祖先链 ==")
    n = snap.find_one(text="聊天")
    if n is None:
        print("  not found")
        return
    cur, i = n, 0
    while cur is not None and i < 8:
        print("  L%d %-24s click=%-5s b=%s"
              % (i, (cur.cls or "").split(".")[-1], cur.clickable, cur.bounds))
        cur, i = cur.parent, i + 1

    print("\n== 可点击节点（前 20） ==")
    for n in [x for x in snap.nodes if x.clickable and x.visible][:20]:
        print("  %-24s b=%s text=%r" % ((n.cls or "").split(".")[-1], n.bounds, n.label[:16]))


if __name__ == "__main__":
    main()
