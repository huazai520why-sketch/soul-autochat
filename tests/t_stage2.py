# -*- coding: utf-8 -*-
"""set_db 之后 stage_line 应该有值。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import reply as R  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev, force=True)
    R.set_db(db)
    R.engine()
    rows = db.con.execute(
        "SELECT sessionId, COUNT(*) n FROM chatmsg WHERE msgType=1 "
        "GROUP BY sessionId ORDER BY n DESC LIMIT 3").fetchall()
    for sid, n in rows:
        print("\nsid=%s  文本消息 %d 条（约 %d 轮）" % (sid, n, n // 2))
        print("  %s" % (R._stage_line(sid) or "(空)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
