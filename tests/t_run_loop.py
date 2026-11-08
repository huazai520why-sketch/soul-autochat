# -*- coding: utf-8 -*-
"""完整循环：逐屏扫红点 -> 进会话 -> 判定 -> 需回复就发 -> 返回，直到角标清零或扫完。

⚠️ 默认真发（dry_run=False）。只回复「最后一条是对方发的」会话。
每次发送前打印现场（谁 / 她最后说什么 / 准备回什么），便于事后核对。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import flow  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402

MAX_SCREEN = 8
MAX_REPLY = 6
DRY = "--dry" in sys.argv


def to_list(a):
    snap = a.snap()
    for _ in range(4):
        if detect(snap) == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None and (p.primary or p.secondary):
            btn = (p.primary or p.secondary)[0]
            a.hand.tap_node(btn[1], settle=1.2)
            snap = a.snap()
            continue
        a.hand.back(settle=1.0)
        snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", settle=1.5)
        snap = a.snap()
    return snap


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    print("== 当前账号 uid=%s  DRY=%s ==" % (db.uid, DRY))

    snap = to_list(a)
    print("起点 %s" % a.digest(snap))
    badge = badges(snap).get("聊天") or 0
    if not badge:
        print("聊天角标已经是 0，无需处理")
        return 0

    results = []
    handled = set()
    replied = 0

    for sc in range(1, MAX_SCREEN + 1):
        # 只用双击推进，不滑动（用户 2026-11-02 明确要求）
        snap, pg = a.double_tap_tab("聊天", expect="chatlist")
        if snap is None:
            print("   双击未命中，回列表后重试")
            to_list(a)
            continue
        dots = [r for r in rows(snap)
                if 200 <= r.center[1] <= 1500 and r.has_dot and r.nickname not in handled]
        print("\n-- 第 %d 次双击 角标=%s 红点=%d %s"
              % (sc, badges(snap).get("聊天"), len(dots), [r.nickname for r in dots]))

        if dots:
            for r in dots:
                if replied >= MAX_REPLY:
                    print("   已达本次上限 %d 条，停止" % MAX_REPLY)
                    break
                handled.add(r.nickname)
                print("\n   >> 处理 %r" % r.blob[:46])
                out = flow.handle_one(a, db, r, dry_run=DRY)
                results.append(out)
                print("      side=%s 她最后: %r" % (out.side, (out.last_text or "")[:30]))
                if out.reply:
                    print("      回复: %r" % out.reply)
                if out.sent or (DRY and out.reply):
                    replied += 1
                if out.err:
                    print("      !! %s" % out.err)
                to_list(a)

            b = badges(a.snap()).get("聊天") or 0
            print("\n   本次处理完，角标=%s" % b)
            if b == 0:
                break
        else:
            print("   本次双击没出现新红点，继续双击")

    print("\n===== 汇总 =====")
    for o in results:
        tag = "已发" if o.sent else ("跳过" if o.side == "me" else ("待发" if o.reply else "失败"))
        print("  [%s] %-12s last=%r reply=%r %s"
              % (tag, o.nick[:12], (o.last_text or "")[:18], o.reply, o.err))
    snap = a.snap()
    print("\n  最终角标=%s  处理会话=%d  回复=%d"
          % (badges(snap).get("聊天"), len(results), replied))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
