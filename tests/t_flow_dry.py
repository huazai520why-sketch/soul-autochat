# -*- coding: utf-8 -*-
"""演练：对当前屏所有红点会话跑一遍「必回」判定 + 出话，但不发送。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import flow  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402


def to_list(actor):
    snap = actor.snap()
    for _ in range(4):
        if detect(snap) == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None and (p.primary or p.secondary):
            btn = (p.primary or p.secondary)[0]
            actor.hand.tap_node(btn[1], settle=1.2)
            snap = actor.snap()
            continue
        actor.hand.back(settle=1.0)
        snap = actor.snap()
    if detect(snap) != "chatlist":
        actor.tap_tab("聊天", settle=1.5)
        snap = actor.snap()
    return snap


def main():
    dev = Device.get()
    actor = Actor(dev)
    db = open_account(dev)

    snap = to_list(actor)
    print("起点 %s" % actor.digest(snap))
    dots = [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]
    print("红点行 %d: %s" % (len(dots), [r.nickname for r in dots]))
    if not dots:
        print("没有红点")
        return 0

    results = []
    handled = set()
    for i, r in enumerate(dots[:6]):
        snap = to_list(actor)
        cur = [x for x in rows(snap) if 200 <= x.center[1] <= 1500 and x.has_dot
               and x.nickname not in handled]
        if not cur:
            break
        row = cur[0]
        handled.add(row.nickname)
        print("\n[%d] %r" % (i + 1, row.blob[:50]))
        out = flow.handle_one(actor, db, row, dry_run=True)
        results.append(out)
        print("     side=%s last=%r" % (out.side, (out.last_text or "")[:26]))
        print("     sid=%s" % (out.sid or "-"))
        print("     reply=%r  %s" % (out.reply, out.err))

    print("\n===== 汇总 =====")
    need = [o for o in results if o.side != "me" and o.reply]
    skip = [o for o in results if o.side == "me"]
    bad = [o for o in results if o.err]
    for o in results:
        tag = "需回复" if o in need else ("跳过" if o in skip else "失败")
        print("  [%s] %-12s %r" % (tag, o.nick[:12], (o.reply or o.err)[:40]))
    print("\n  需回复 %d / 跳过 %d / 失败 %d" % (len(need), len(skip), len(bad)))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
