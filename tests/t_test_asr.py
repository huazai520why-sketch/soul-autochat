# -*- coding: utf-8 -*-
"""用库里真实的语音消息测 ASR。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import voice as V  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    rows = db.con.execute(
        "SELECT * FROM chatmsg WHERE msgType=5 ORDER BY localTime DESC LIMIT 4").fetchall()
    print("取 %d 条语音测试" % len(rows))
    from data.imdb import Msg
    for r in rows:
        m = Msg(r)
        d = V.content(m)
        print("\n--- sid=%s %ds word=%r ---"
              % (m.session_id, int(d.get("duration") or 0), (d.get("word") or "")[:20]))
        t0 = time.time()
        t, how = V.voice_text(m)
        print("    -> (%s) %.1fs %r" % (how, time.time() - t0, t[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
