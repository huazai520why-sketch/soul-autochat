# -*- coding: utf-8 -*-
"""探针：打印会话行内每个节点的文本/坐标，确认行内是否存在红点/未读角标。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.chatlist import _is_descendant, list_view, rows  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    snap = Screen(Device.get()).get(force=True)
    rv = list_view(snap)
    print("list_view =", (rv.bounds if rv else None))

    rs = rows(snap)
    print("rows = %d\n" % len(rs))
    for r in rs[:4]:
        print("== 行 y=%d  node=%s ==" % (r.center[1], r.node.bounds))
        items = [n for n in snap.nodes if _is_descendant(n, r.node)]
        items.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
        for n in items:
            label = n.label or ""
            print("   %-12s b=%-22s click=%-5s %r"
                  % ((n.cls or "").split(".")[-1], n.bounds, n.clickable, label[:30]))
        print()


if __name__ == "__main__":
    main()
