# -*- coding: utf-8 -*-
"""只探查「切换用户」入口和账号面板，不点任何账号行（不改账号状态）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402

OPEN_ONLY = "--open" in sys.argv


def main():
    dev = Device.get()
    a = Actor(dev)
    snap, pg = nav.to_tab(a, "自己")
    print("自己页 page=%s" % pg)
    if pg != "me":
        print("回不到自己页")
        return 1

    # 滑到顶（页面滚动时节点坐标会偏）
    for _ in range(3):
        a.hand.swipe(450, 400, 450, 1300, duration=0.18, settle=0.5)

    s = a.snap(force=True)
    print("\n-- 顶部 160px 内的可点节点 --")
    for n in s.nodes:
        if n.clickable and n.visible and n.center[1] < 160:
            print("   b=%-24s %r %r res=%s"
                  % (n.bounds, (n.label or "")[:16], (n.desc or "")[:14], n.res_id))

    n = s.hit(desc="切换用户") or s.hit(text="切换用户")
    print("\n「切换用户」节点: %s" % ((n.bounds if n else None),))
    if n is None:
        cands = [x for x in s.nodes if x.clickable and x.center[1] < 160 and x.center[0] < 160]
        print("   左上角候选: %s" % [(c.bounds, c.desc) for c in cands])

    if OPEN_ONLY and n is not None:
        print("\n>> 打开面板（只读，不切号）")
        a.hand.tap_node(n, settle=2.0)
        s2 = a.snap(force=True)
        print("面板文本:")
        for t in s2.texts()[:16]:
            print("   %r" % t[:30])
        a.hand.back(settle=1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
