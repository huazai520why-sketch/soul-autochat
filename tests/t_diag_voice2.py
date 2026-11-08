# -*- coding: utf-8 -*-
"""把一条语音消息的所有字段打出来，找转写/时长藏哪儿。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    cols = [r[1] for r in db.con.execute("PRAGMA table_info(chatmsg)")]
    rows = db.con.execute(
        "SELECT * FROM chatmsg WHERE msgType=5 ORDER BY localTime DESC LIMIT 2").fetchall()
    print("语音消息 %d 条样本" % len(rows))
    for row in rows:
        d = dict(zip(cols, row))
        print("\n=== sid=%s ===" % d.get("sessionId"))
        for k, v in d.items():
            if v is None or v == "" or v == b"":
                continue
            s = str(v)
            print("   %-18s %s" % (k, s[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
