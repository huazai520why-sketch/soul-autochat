# -*- coding: utf-8 -*-
"""扫剩余红点：回到顶部起，逐屏下翻，找带红点的行并清掉，直到角标归零或扫完 N 屏。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402

MAX_SCREENS = 10


def dot_rows(snap):
    return [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]


def goto_top(a, max_try=25):
    prev = None
    for _ in range(max_try):
        snap, pg = a.swipe_down(expect="chatlist")
        if pg != "chatlist":
            return None
        rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
        cur = rs[0].blob if rs else ""
        if cur == prev:
            return snap
        prev = cur
    return a.snap()


def clear_visible(a, handled):
    """把当前屏所有红点会话清掉。返回处理数。"""
    n = 0
    for _ in range(6):
        snap = a.snap()
        if detect(snap) != "chatlist":
            return n
        todo = [r for r in dot_rows(snap) if r.nickname not in handled]
        if not todo:
            return n
        r = todo[0]
        print("     进入 %r 红点=%s" % (r.nickname, r.badge))
        a.hand.tap_node(r.node, settle=1.6)
        snap2, pg = a._after("chatlist", "chat", "enter")
        handled.add(r.nickname)
        if pg != "chat":
            print("       未进入（%s），跳过" % pg)
            continue
        a.hand.back(settle=1.2)
        snap3, pg3 = a._after("chat", "chatlist", "back")
        if pg3 != "chatlist":
            print("       返回异常（%s）" % pg3)
            return n
        n += 1
    return n


def main():
    a = Actor(Device.get())
    handled = set()

    snap = a.snap()
    print("== 起始 ==")
    print("  %s" % a.digest(snap))
    print("  角标 聊天=%s" % badges(snap).get("聊天"))

    print("\n== 回到顶部 ==")
    snap = goto_top(a)
    if snap is None:
        print("  回顶异常")
        return 1
    print("  %s" % a.digest(snap))

    total = 0
    for i in range(MAX_SCREENS):
        print("\n-- 第 %d 屏 --" % (i + 1))
        ds = dot_rows(snap)
        print("   红点行 %d %s" % (len(ds), [r.nickname for r in ds] or ""))
        if ds:
            total += clear_visible(a, handled)
            snap = a.snap()
            bd = badges(snap).get("聊天")
            print("   处理后角标 聊天=%s" % bd)
            if not bd:
                print("   角标已归零")
                break
        else:
            snap, pg = a.swipe_up(expect="chatlist")
            if pg != "chatlist":
                print("   翻页后页面异常 %s" % pg)
                break

    print("\n== 结果 ==")
    snap = a.snap()
    print("  %s" % a.digest(snap))
    print("  本轮清理 %d 个会话" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
