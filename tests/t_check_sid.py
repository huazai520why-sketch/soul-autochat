# -*- coding: utf-8 -*-
"""查最近发出的消息落在哪个 sid，核对串号问题。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    print("uid=%s" % db.uid)

    print("\n-- 最近 5 个会话（按 timestamp） --")
    for r in db.con.execute(
            "SELECT sessionId, toUserId, lastMsgText, timestamp FROM session "
            "ORDER BY timestamp DESC LIMIT 5").fetchall():
        print("   sid=%-20s to=%-10s ts=%s  %r" % (r[0], r[1], r[3], (r[2] or "")[:26]))

    print("\n-- 最近 8 条我发的文本消息 --")
    for r in db.con.execute(
            "SELECT sessionId, text, localTime FROM chatmsg "
            "WHERE msgType=1 AND sender=? ORDER BY localTime DESC LIMIT 8",
            (db.uid,)).fetchall():
        print("   sid=%-20s %r" % (r[0], (r[1] or "")[:30]))

    print("\n-- 反查测试 --")
    for kw in ("打个招呼，你平时爱聊点啥", "你平时这个点都干啥"):
        hit = db.sessions_for_texts([kw])
        print("   %r -> %s" % (kw, hit[:2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
