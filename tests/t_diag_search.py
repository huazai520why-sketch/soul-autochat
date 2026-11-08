# -*- coding: utf-8 -*-
"""诊断：搜索为什么 0 条结果。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain import search as S  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402

KW = sys.argv[1] if len(sys.argv) > 1 else "房子到期了"


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = CL.to_list(a)
    print("起点 page=%s" % detect(snap))

    ok = S.open_search(a)
    print("打开搜索 ok=%s" % ok)
    s = a.snap(force=True)
    print("搜索页 nodes=%d fg=%s" % (len(s.nodes), dev.current_app()[1].split(".")[-1]))
    print("输入框: %s" % ((s.find_one(cls="EditText").bounds if s.find_one(cls="EditText") else None),))

    box = s.find_one(cls="EditText")
    if box is None:
        print("无输入框")
        return 1
    a.hand.tap_node(box, settle=0.6)
    try:
        dev.u2().clear_text()
    except Exception as e:
        print("clear 异常 %r" % e)
    time.sleep(0.4)
    dev.u2().send_keys(KW)
    print("已灌 %r，等 4s" % KW)
    time.sleep(4.0)

    s2 = a.snap(force=True)
    print("\n== 搜后 nodes=%d ==" % len(s2.nodes))
    for t in s2.texts()[:24]:
        print("   %r" % t[:40])
    print("\n大块可点击：")
    for n in S.results(a):
        print("   %s" % (n.bounds,))
    p, size, _ = dev.screencap_to(LOGS / "_search.png")
    print("\n截图 %d bytes" % size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
