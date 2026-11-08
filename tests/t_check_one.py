# -*- coding: utf-8 -*-
"""核实：被误判跳过的那条（列表预览含「中午好」）到底是谁发的、要不要回复。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    db = open_account(Device.get())
    print("uid=%s" % db.uid)

    print("\n== 含「中午好」的消息 ==")
    rows = db.con.execute(
        "SELECT sessionId, senderId, msgType, text, localTime FROM chatmsg "
        "WHERE text LIKE ? ORDER BY localTime DESC LIMIT 6", ("%中午好%",)).fetchall()
    for sid, sender, mt, text, ts in rows:
        who = "我" if str(sender) == str(db.uid) else "她"
        print("   sid=%s [%s] type=%s %r" % (sid, who, mt, (text or "")[:30]))

    print("\n== 这些会话最后 3 条（排除系统消息） ==")
    seen = set()
    for sid, *_ in rows:
        if sid in seen:
            continue
        seen.add(sid)
        s = db.session(sid)
        print("\n   --- %s uid=%s unread=%s ---" % (sid, s.to_uid if s else "?", s.unread if s else "?"))
        for m in db.messages(sid, limit=3):
            who = "我" if str(m.sender) == str(db.uid) else "她"
            print("      %s [%s] type=%-2s %r" % (m.time_str, who, m.msg_type, (m.text or "")[:34]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
