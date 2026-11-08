# -*- coding: utf-8 -*-
"""验证唤醒选人 + 出开场白（不发送）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import wake  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    db = open_account(Device.get())
    print("uid = %s" % db.uid)

    cs = wake.candidates(db, limit=8)
    print("\n候选 %d 人（>=%d句 且 冷>=%dh 且 最后一条是我发的）"
          % (len(cs), wake.MIN_MSGS, wake.COLD_HOURS))
    for c in cs:
        print("   uid=%-10s 消息=%-3d 冷=%.1fh  最后: %r"
              % (c.uid, c.msgs, c.cold_h, (c.last_text or "")[:26]))

    if not cs:
        print("   没有候选")
        return 0

    print("\n== 试着给前 3 位出开场白 ==")
    for c in cs[:3]:
        op = wake.opening(db, c)
        print("   uid=%s 冷%.1fh -> %r" % (c.uid, c.cold_h, op))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
