# -*- coding: utf-8 -*-
"""验证：她连发多条 → 合并喂入 → 引擎回多条（不实际发送）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import flow as F  # noqa: E402
from brain import reply as R  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    # ① 纯函数：条数自适应
    print("=== target_n 自适应 ===")
    cases = [
        (["嗯"], "单字"),
        (["哈哈"], "两字"),
        (["今天输了点钱"], "7字"),
        (["你在干嘛呢"], "提问短"),
        (["今天去打了会儿麻将，输了两百多，心疼我的新衣服"], "长句"),
        (["今天输了", "心疼我的新衣服呀"], "连发2条"),
        (["在吗", "问你个事", "你多大了"], "连发3条"),
        (["今天打麻将输了三百多块钱，你说我是不是该戒了"], "长句提问"),
    ]
    for lines, tag in cases:
        hist = [{"role": "me", "text": "x"}, {"role": "her", "text": "y"}]
        print("  %-10s %d 字连发%d → 回 %d 条" %
              (tag, len("".join(lines)), len(lines), R.target_n(lines, hist)))

    # ② 真实会话：取她连发 + 生成多条
    dev = Device.get()
    db = open_account(dev, force=True)
    R.set_db(db)
    rows = db.con.execute(
        "SELECT sessionId, toUserId FROM session WHERE toUserId>0 "
        "ORDER BY timestamp DESC LIMIT 6").fetchall()
    for sid, uid in rows:
        burst = F.her_burst(db, sid, db.uid)
        if not burst:
            continue
        msgs = db.messages(sid, limit=12)
        hist = R.build_hist(msgs, db.uid)
        n = R.target_n(burst, hist)
        print("\n=== sid=%s 她连发 %d 条 ===" % (sid, len(burst)))
        for b in burst:
            print("   她: %r" % b[:40])
        print("   合并后喂入: %r" % R.merge_burst(burst)[:80])
        print("   她要回 %d 条 → 生成中…" % n)
        out = R.generate(sid, R.merge_burst(burst), hist=hist, n_cand=n)
        print("   引擎给了 %d 条:" % len(out))
        for i, t in enumerate(out, 1):
            print("     %d) %r" % (i, t))
        break
    return 0


if __name__ == "__main__":
    sys.exit(main())
