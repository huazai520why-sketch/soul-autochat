# -*- coding: utf-8 -*-
"""验证「匹配到人 -> 进主页 -> 抓资料 -> 写旧案情包 L4」。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import casepack as CP  # noqa: E402
from brain import match as M  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import profile as P  # noqa: E402
from eyes.page import detect  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    if detect(snap) != "chat":
        print("不在会话页（%s）" % detect(snap))
        return 1

    card = M.read_card(snap)
    print("卡片: 昵称=%r 引力签=%s 共同点=%s %s"
          % (card["nick"], card["tags"], card["common"], card["extra"]))

    prof, ok = M.visit_profile(a)
    print("\n进主页 ok=%s" % ok)
    if not ok:
        return 2
    print("摘要: %s" % P.summary(prof))
    for k in ("nick", "ip", "soul", "days", "match_pct", "follow", "fans", "gifts"):
        print("  %-10s %r" % (k, prof.get(k)))
    print("  tags       %s" % (prof.get("tags"),))
    print("  moments    %s" % ([m[:30] for m in prof.get("moments") or []],))

    # 找当前会话的 sid：session 表里最近活跃的那条
    db = open_account(dev)
    rows = db.con.execute(
        "SELECT sessionId, toUserId, lastMsgText, timestamp FROM session "
        "ORDER BY timestamp DESC LIMIT 3").fetchall()
    print("\n最近 3 个会话:")
    for r in rows:
        print("   sid=%-20s to=%-10s %r" % (r[0], r[1], (r[2] or "")[:26]))
    if not rows:
        print("库里没有会话")
        return 3
    sid = rows[0][0]

    print("\n写案情包 sid=%s" % sid)
    ok2 = CP.save_profile(sid, prof, tags=card["tags"], common=card["common"])
    print("save_profile = %s" % ok2)

    txt = CP.load(sid)
    print("\n-- 读回 L4 --")
    print(txt or "（空）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
