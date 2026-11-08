# -*- coding: utf-8 -*-
"""验证：刚发的唤醒消息是否真的进了数据库。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402

KEY = "想点啥好玩的"


def main():
    db = open_account(Device.get())
    print("uid=%s  (库已重新拉取)" % db.uid)

    rows = db.con.execute(
        "SELECT sessionId, senderId, msgType, text, localTime FROM chatmsg "
        "WHERE text LIKE ? ORDER BY localTime DESC LIMIT 5", ("%" + KEY + "%",)).fetchall()
    print("\n含 %r 的消息 %d 条：" % (KEY, len(rows)))
    for sid, sender, mt, text, ts in rows:
        who = "我" if str(sender) == str(db.uid) else "她"
        print("   sid=%s [%s] type=%s %r" % (sid, who, mt, (text or "")[:40]))

    if rows:
        sid = rows[0][0]
        print("\n该会话最近 3 条：")
        for m in db.messages(sid, limit=3):
            who = "我" if str(m.sender) == str(db.uid) else "她"
            print("   %s [%s] %r" % (m.time_str, who, (m.text or "")[:40]))
    db.close()
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
