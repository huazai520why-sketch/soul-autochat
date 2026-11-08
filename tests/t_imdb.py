# -*- coding: utf-8 -*-
"""L3 验收：数据层（直读 IM 库）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import list_device_dbs, open_account  # noqa: E402


def main():
    dev = Device.get()

    print("== L3 数据层 ==")
    names = list_device_dbs(dev)
    print("  device dbs  %d" % len(names))
    for n in names:
        print("    %s" % n)

    print("\n  同步第一个库...")
    db = open_account(dev)
    st = db.stats()
    print("  uid         %s" % st["uid"])
    print("  sessions    %s (unread=%s)" % (st["sessions"], st["unread"]))
    print("  messages    %s" % st["messages"])

    print("\n-- 未读会话（含官方） --")
    for s in db.sessions(unread_only=True)[:10]:
        print("    %-14s uid=%-10s unread=%-3s %s  %r%s"
              % (s.session_id[-12:], s.to_uid, s.unread, s.time_str,
                 s.last_text[:26], "  [官方]" if s.is_official else ""))

    print("\n-- 待回（已过滤官方 + 最后一条不是我） --")
    pend = db.pending()
    print("  count = %d" % len(pend))
    for s, m in pend:
        print("    %s uid=%s unread=%s %s  最后: %r"
              % (s.session_id[-10:], s.to_uid, s.unread, m.time_str, m.text[:30]))

    if pend:
        s, _ = pend[0]
        print("\n-- 最近对话（%s） --" % s.session_id)
        for m in db.messages(s.session_id, limit=8):
            who = "我" if str(m.sender) == str(db.uid) else "她"
            print("    %s %s: %s" % (m.time_str, who, (m.text or "<%s>" % m.msg_type)[:44]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
