# -*- coding: utf-8 -*-
"""看非文本消息类型长什么样（图片/卡片/表情）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev, force=True)
    for mt in (2, 8, 9, 35):
        rows = db.con.execute(
            "SELECT msgType, text, msgContent, extMap FROM chatmsg "
            "WHERE msgType=? ORDER BY localTime DESC LIMIT 2", (mt,)).fetchall()
        print("\n===== type=%d （%d 条样本）=====" % (mt, len(rows)))
        for r in rows:
            tx, tc = r[1] or "", r[2] or ""
            print("  text=%r" % tx[:40])
            if tc:
                try:
                    d = json.loads(tc)
                    keys = list(d.keys())[:8]
                    print("  content keys=%s" % keys)
                    for k in keys:
                        v = str(d.get(k))
                        if v and v not in ("", "None"):
                            print("     %-12s %s" % (k, v[:60]))
                except Exception:
                    print("  content(raw)=%r" % tc[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())
