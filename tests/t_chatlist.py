# -*- coding: utf-8 -*-
"""L2.5 验收：会话行解析 + 用数据库文本定位未读会话。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes.chatlist import find_row, rows  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)

    # 先回到列表顶部
    for _ in range(6):
        hand.swipe(450, 420, 450, 1380, duration=0.18, settle=0.28)

    snap = scr.get(force=True)
    print("== 会话行解析 == page=%s" % detect(snap))
    rs = rows(snap)
    print("  可见行 = %d" % len(rs))
    for r in rs[:10]:
        print("   y=%-5d %r" % (r.center[1], r.blob[:78]))

    print("\n== 用数据库 lastMsgText 定位 ==")
    db = open_account(dev)
    print("  unread_total = %d" % db.unread_total())
    hit, miss = 0, 0
    for s in db.sessions(unread_only=True):
        tag = "官方" if s.is_official else "真人"
        r = find_row(snap, s.last_text, min_len=4)
        if r is not None:
            hit += 1
            print("  [%s] uid=%-10s unread=%-2s -> 行 y=%d %r"
                  % (tag, s.to_uid, s.unread, r.center[1], r.nickname))
        else:
            miss += 1
            print("  [%s] uid=%-10s unread=%-2s -> 未在当前屏（需滚动） %r"
                  % (tag, s.to_uid, s.unread, (s.last_text or "")[:24]))
    print("\n  命中 %d / 未命中 %d" % (hit, miss))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
