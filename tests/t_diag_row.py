# -*- coding: utf-8 -*-
"""诊断：搜索结果页的结构，为什么某条点不进会话。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain import search as S  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402

KW = sys.argv[1] if len(sys.argv) > 1 else "抖音 番茄小说"


def main():
    dev = Device.get()
    a = Actor(dev)
    CL.to_list(a)
    if not S.open_search(a):
        print("打不开搜索")
        return 1
    n = S.search(a, dev, KW, max_wait=18)
    print("结果行数 %d" % n)

    s = a.snap(force=True)
    print("\n== 全部可点击节点（y>150） ==")
    for x in sorted([y for y in s.nodes if y.clickable and y.visible and y.bounds[1] > 150],
                    key=lambda y: y.bounds[1]):
        w = x.bounds[2] - x.bounds[0]
        h = x.bounds[3] - x.bounds[1]
        print("  b=%-24s %-14s %dx%d %r"
              % (x.bounds, x.cls.split(".")[-1], w, h, (x.label or x.desc or "")[:26]))

    print("\n== 全部文本 ==")
    for i, t in enumerate(s.texts()[:30]):
        print("  %02d %r" % (i, t[:40]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
