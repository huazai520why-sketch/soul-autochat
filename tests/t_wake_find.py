# -*- coding: utf-8 -*-
"""验证：能否在会话列表里按 last_text 找到唤醒候选那一行（只读，不进入）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import wake  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402

MAX_SCROLL = 14


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)

    cs = wake.candidates(db, limit=3)
    if not cs:
        print("无候选")
        return 1
    c = cs[0]
    print("目标 uid=%s 冷%.1fh 最后: %r" % (c.uid, c.cold_h, (c.last_text or "")[:30]))

    snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", settle=1.5)
        snap = a.snap()

    for i in range(MAX_SCROLL):
        snap = a.snap()
        rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
        for r in rs:
            if r.match(c.last_text, min_len=6):
                print("\n>> 第 %d 屏找到: y=%d %r" % (i + 1, r.center[1], r.blob[:60]))
                print("   库中最后: %r" % (c.last_text or "")[:50])
                db.close()
                return 0
        top = rs[0].blob[:40] if rs else "-"
        print("   第 %d 屏未找到（首行 %r）" % (i + 1, top))
        # 向下翻（看更旧的会话）
        a.swipe(450, 1250, 450, 450, duration=0.2, settle=0.5)

    print("\n!! %d 屏内没找到" % MAX_SCROLL)
    db.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
