# -*- coding: utf-8 -*-
"""核对：那 4 个会话最后的真实消息是什么（含 type），确认「无需回复」判定对不对。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)

    print("== 全库「去看看」作为最后消息的会话 ==")
    rows = db.con.execute(
        "SELECT sessionId, toUserId, unReadCount, lastMsgText FROM session "
        "WHERE lastMsgText LIKE '%去看看%' ORDER BY timestamp DESC LIMIT 10").fetchall()
    for r in rows:
        print("   sid=%s uid=%s unread=%s last=%r"
              % (r[0], r[1], r[2], (r[3] or "")[:20]))

    print("\n== 对每会话看最后 5 条（含类型） ==")
    for r in rows[:4]:
        sid = r[0]
        print("\n   --- sid=%s uid=%s ---" % (sid, r[1]))
        ms = db.con.execute(
            "SELECT senderId, msgType, text, localTime FROM chatmsg "
            "WHERE sessionId = ? ORDER BY localTime DESC LIMIT 5", (sid,)).fetchall()
        for sender, mt, text, ts in ms:
            who = "我" if str(sender) == str(db.uid) else "她"
            print("      [%s] type=%-3s %r" % (who, mt, (text or "")[:36]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
