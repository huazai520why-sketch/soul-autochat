# -*- coding: utf-8 -*-
"""当前积压：未读会话、待回、最新消息时间。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    print("账号 uid=%s  会话=%d" % (db.uid, db.stats().get("sessions", 0)))

    n = db.con.execute("SELECT COUNT(*) FROM session WHERE unReadCount>0").fetchone()[0]
    print("未读会话: %d" % n)

    print("\n-- 最近 8 条消息 --")
    rows = db.con.execute(
        "SELECT sessionId, senderId, msgType, text, localTime FROM chatmsg "
        "ORDER BY localTime DESC LIMIT 8").fetchall()
    for sid, snd, mt, tx, lt in rows:
        who = "我" if str(snd) == str(db.uid) else "她"
        ago = (time.time() - (lt or 0) / 1000) / 60
        print("  %5.1f 分钟前 [%s] type=%-2s %r" % (ago, who, mt, (tx or "")[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
