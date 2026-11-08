# -*- coding: utf-8 -*-
"""验证：对已有截图跑 last_bubble，确认能判出「最后一条是谁发的」。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import LOGS  # noqa: E402
from eyes import chat  # noqa: E402


def main():
    p = LOGS / "_ocr_chat.png"
    if not p.exists():
        print("没有截图 %s" % p)
        return 1
    png = p.read_bytes()

    bs = chat.bubbles(png)
    print("== 可见消息 %d 条 ==" % len(bs))
    for t, side, it in bs:
        print("   y=%-5d %-4s %r" % (it.cy, side, t[:40]))

    last = chat.last_bubble(png)
    print("\n最后一条: %r" % (last[0] if last else None))
    if last:
        t, side, it = last
        print("  side = %s   (her=必须回复 / me=不用回)" % side)
        print("  bbox = %s" % (it.box,))
        print("  结论: %s" % ("需要回复" if side in ("her", "?") else "无需回复"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
