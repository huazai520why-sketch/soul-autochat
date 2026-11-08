# -*- coding: utf-8 -*-
"""手动复现匹配：点「开始匹配」后连拍 4 张，看页面到底变成什么。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)

    snap, pg = nav.to_tab(a, "星球")
    print("星球页 page=%s" % pg)
    if pg != "planet":
        print("回不到星球页")
        return 1

    n = snap.hit(text="开始匹配")
    print("「开始匹配」节点 = %s" % ((n.bounds if n else None),))
    if n is None:
        print("-- 当前页所有含「匹配」的文本 --")
        for t in snap.texts():
            if "匹配" in t:
                print("   %r" % t[:40])
        return 2

    print(">> 点击")
    a.hand.tap_node(n, settle=1.0)

    for i, wait in enumerate((2, 4, 8, 12), 1):
        time.sleep(wait)
        s = a.snap(force=True)
        pg2 = detect(s)
        p, size, _ = dev.screencap_to(LOGS / ("_m%d.png" % i))
        txts = [t for t in s.texts() if t.strip()][:10]
        print("\n[%ds 累计] page=%s nodes=%d shot=%dB" % (2 + 4 + 8 + 12 if i == 4 else sum((2, 4, 8, 12)[:i]), pg2, len(s.nodes), size))
        for t in txts:
            print("    %r" % t[:44])
        # 顺带看看有哪些 activity
        try:
            fg = dev.current_app()[1] or ""
            print("    fg=%s" % fg.split(".")[-1])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
