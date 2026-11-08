# -*- coding: utf-8 -*-
"""调试：uid 前缀推断 + 官方过滤为什么漏了 204268346。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    db = open_account(Device.get())
    print("uid =", db.uid)

    print("\n-- sessionId 样本 12 个 --")
    for r in db.con.execute("SELECT sessionId, toUserId FROM session LIMIT 12"):
        print("   %r  toUid=%r" % (r[0], r[1]))

    ids = [r[0] for r in db.con.execute("SELECT sessionId FROM session LIMIT 50")]
    prefix = ids[0]
    for s in ids[1:]:
        i = 0
        while i < min(len(prefix), len(s)) and prefix[i] == s[i]:
            i += 1
        prefix = prefix[:i]
    print("\n最长公共前缀(前50) = %r  len=%d" % (prefix, len(prefix)))

    print("\n-- 未读会话逐个判断 --")
    for s in db.sessions(unread_only=True):
        last = db.last_message(s.session_id)
        print("   %-20s toUid=%-10s official=%-5s last=%r sender=%r"
              % (s.session_id, s.to_uid, s.is_official,
                 (last.text[:20] if last else None),
                 (last.sender if last else None)))

    print("\n-- 文本消息 sender 分布 --")
    for r in db.con.execute(
        "SELECT senderId, COUNT(*) c FROM chatmsg WHERE msgType=1 "
        "GROUP BY senderId ORDER BY c DESC LIMIT 6"
    ):
        print("   %s -> %s" % (r[0], r[1]))
    db.close()


if __name__ == "__main__":
    main()
