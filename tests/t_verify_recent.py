# -*- coding: utf-8 -*-
"""验证：最近 15 分钟内我发出的消息（确认唤醒真的落地）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    db = open_account(Device.get())
    cutoff = (time.time() - 15 * 60) * 1000
    rows = db.con.execute(
        "SELECT sessionId, senderId, msgType, text, localTime FROM chatmsg "
        "WHERE localTime > ? ORDER BY localTime DESC LIMIT 20", (cutoff,)).fetchall()
    print("近 15 分钟消息 %d 条（uid=%s）" % (len(rows), db.uid))
    for sid, sender, mt, text, ts in rows:
        who = "我" if str(sender) == str(db.uid) else "她"
        hhmm = time.strftime("%H:%M", time.localtime(ts / 1000))
        print("   %s [%s] sid=%s type=%s %r"
              % (hhmm, who, sid[-8:], mt, (text or "")[:34]))

    mine = [r for r in rows if str(r[1]) == str(db.uid)]
    print("\n我发出的 %d 条：" % len(mine))
    for r in mine:
        print("   %s %r" % (time.strftime("%H:%M", time.localtime(r[4] / 1000)), (r[3] or "")[:40]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
