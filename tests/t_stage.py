# -*- coding: utf-8 -*-
"""验证 stage_line / stuck_line 能不能取到。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import reply as R  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev, force=True)
    row = db.con.execute(
        "SELECT sessionId FROM session WHERE toUserId>0 ORDER BY timestamp DESC LIMIT 1").fetchone()
    sid = row[0]
    R.engine()
    print("sid=%s" % sid)
    st = R._stage_line(sid)
    print("\nstage_line（%d 字）:\n%s" % (len(st), st or "(空)"))
    msgs = db.messages(sid, limit=12)
    hist = R.build_hist(msgs, db.uid, limit=10)
    sk = R._stuck_line(hist)
    print("\nstuck_line（%d 字）:\n%s" % (len(sk), sk or "(空，说明没死磕)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
