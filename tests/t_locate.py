# -*- coding: utf-8 -*-
"""定位器验证：小步长滚动，用 last_text 在列表里找会话行。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import wake  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def to_list(a):
    snap = a.snap()
    for _ in range(3):
        if detect(snap) == "chatlist":
            return snap
        a.hand.back(settle=1.0)
        snap = a.snap()
    a.tap_tab("聊天", settle=1.5)
    return a.snap()


def locate(a, text, max_scroll=24, step=420):
    """小步长向下滚，找含 text 的行。返回 (row, 屏号) 或 (None, -1)。"""
    for i in range(max_scroll):
        snap = a.snap()
        rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
        for r in rs:
            if r.match(text, min_len=6):
                return r, i + 1
        if rs:
            print("   #%02d 首行 %r" % (i + 1, rs[0].blob[:34]))
        a.swipe(450, 1250 - step, 450, 450, duration=0.18, settle=0.45)
    return None, -1


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    snap = to_list(a)
    print("起点 %s" % a.digest(snap))

    cs = wake.candidates(db, limit=2)
    for c in cs:
        print("\n目标 uid=%s 冷%.1fh last=%r" % (c.uid, c.cold_h, (c.last_text or "")[:30]))
        snap = to_list(a)
        r, sc = locate(a, c.last_text)
        if r is None:
            print("   !! 24 屏内没找到")
        else:
            print("   OK 第 %d 屏命中: y=%d %r" % (sc, r.center[1], r.blob[:56]))
            break
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
