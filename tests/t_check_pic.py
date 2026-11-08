# -*- coding: utf-8 -*-
"""查最近会话最后一条，确认图片消息是否发出。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    print("uid=%s" % db.uid)
    print("\n-- 最近 6 个会话 --")
    for r in db.con.execute(
            "SELECT sessionId, toUserId, lastMsgText, timestamp FROM session "
            "ORDER BY timestamp DESC LIMIT 6").fetchall():
        print("  sid=%-20s to=%-10s %r" % (r[0], r[1], (r[2] or "")[:36]))

    print("\n-- 最近 6 条非文本消息 --")
    for r in db.con.execute(
            "SELECT sessionId, msgType, text, localTime FROM chatmsg "
            "WHERE msgType != 1 ORDER BY localTime DESC LIMIT 6").fetchall():
        print("  sid=%-20s type=%-3s %r" % (r[0], r[1], (r[2] or "")[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
