# -*- coding: utf-8 -*-
"""验证引擎在多条要求下真的返回多条（选一段真实长对话）。"""
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

    # 找聊得最多的会话（历史够长，模型才有话可说）
    row = db.con.execute(
        "SELECT sessionId, COUNT(*) n FROM chatmsg WHERE msgType=1 "
        "GROUP BY sessionId ORDER BY n DESC LIMIT 1").fetchone()
    sid, n = row[0], row[1]
    msgs = db.messages(sid, limit=20)
    hist = R.build_hist(msgs, db.uid)
    print("sid=%s 共 %d 条文本，hist %d 条" % (sid, n, len(hist)))

    for label, feed, n_cand in (
        ("连发 2 条（要 3 条）",
         R.merge_burst(["今天又去打麻将了", "输了一百多，心疼死了"]), 3),
        ("单条长句提问（要 3 条）",
         "你觉得我这个人怎么样，是不是挺没意思的", 3),
        ("单条短句（要 1 条）", "嗯", 1),
    ):
        print("\n=== %s ===" % label)
        print("   喂入: %r" % feed[:100])
        out = R.generate(sid, feed, hist=hist, n_cand=n_cand)
        print("   返回 %d 条:" % len(out))
        for i, t in enumerate(out, 1):
            print("     %d) %r" % (i, t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
