# -*- coding: utf-8 -*-
"""诊断：语音消息在库里长什么样（msgType / text / 时长）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    print("uid=%s" % db.uid)

    print("\n-- 各 msgType 分布 --")
    for r in db.con.execute(
            "SELECT msgType, COUNT(*) n FROM chatmsg GROUP BY msgType ORDER BY n DESC").fetchall():
        print("   type=%-4s %d" % (r[0], r[1]))

    print("\n-- 最近 10 条语音(type=5) --")
    for r in db.con.execute(
            "SELECT sessionId, senderId, text, localTime, extString FROM chatmsg "
            "WHERE msgType=5 ORDER BY localTime DESC LIMIT 10").fetchall():
        print("   sid=%-18s from=%s text=%r ext=%r"
              % (r[0], "me" if str(r[1]) == str(db.uid) else "her",
                 (r[2] or "")[:40], (str(r[4]) or "")[:40]))

    print("\n-- 最近 10 条非文本消息(含语音/图片) --")
    for r in db.con.execute(
            "SELECT sessionId, senderId, msgType, text, localTime FROM chatmsg "
            "WHERE msgType != 1 ORDER BY localTime DESC LIMIT 10").fetchall():
        print("   sid=%-18s %s type=%-3s %r"
              % (r[0], "me " if str(r[1]) == str(db.uid) else "her",
                 r[2], (r[3] or "")[:36]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
