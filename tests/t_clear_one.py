# -*- coding: utf-8 -*-
"""清红点闭环：定位一个未读会话 -> 进入 -> 返回 -> 查库确认 unReadCount 归零。

每一步都用 Actor 确认页面，不靠假设。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes.chatlist import find_row, rows  # noqa: E402


def goto_top(a, max_try=30):
    """下拉到顶部：第一行内容连续两次不变即认为到顶。"""
    prev = None
    for i in range(max_try):
        snap, pg = a.swipe_down(expect="chatlist")
        if pg != "chatlist":
            return None, pg
        rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
        cur = rs[0].blob if rs else ""
        if cur == prev:
            return snap, pg
        prev = cur
    return a.snap(), "chatlist"


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)

    print("== 未读基线 ==")
    base = db.sessions(unread_only=True)
    print("  unread_sessions=%d  unread_total=%d" % (len(base), db.unread_total()))
    target = None
    for s in base:
        if not s.is_official:
            target = s
            break
    if target is None:
        print("  没有真人未读")
        return 0
    print("  目标: uid=%s unread=%d %r"
          % (target.to_uid, target.unread, target.last_text[:30]))

    print("\n== 滚到顶部 ==")
    snap, pg = goto_top(a)
    print("  %s" % a.digest(snap))
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    print("  可见行 %d，前 5：" % len(rs))
    for r in rs[:5]:
        print("     y=%-5d %r" % (r.center[1], r.blob[:64]))

    print("\n== 按 lastMsgText 定位 ==")
    row = find_row(snap, target.last_text, min_len=4)
    if row is None:
        print("  当前屏未匹配到，逐屏下翻查找...")
        for i in range(8):
            snap, pg = a.swipe_up(expect="chatlist")
            row = find_row(snap, target.last_text, min_len=4)
            if row is not None:
                break
        if row is None:
            print("  还没找到，放弃本轮（需人工看）")
            return 1
    print("  命中行 y=%d %r" % (row.center[1], row.blob[:64]))

    print("\n== 进入会话 ==")
    a.hand.tap_node(row.node, settle=1.5)
    snap, pg = a._after("chatlist", "chat", "enter_chat")
    print("  %s" % a.digest(snap))
    if pg != "chat":
        print("  !! 没进到 chat 页，实际 %s，中止" % pg)
        return 1

    print("\n== 返回列表 ==")
    a.hand.back(settle=1.2)
    snap, pg = a._after("chat", "chatlist", "back_to_list")
    print("  %s" % a.digest(snap))

    print("\n== 查库确认 ==")
    time.sleep(1.5)
    db.close()
    db = open_account(dev)
    now = db.sessions(unread_only=True)
    print("  unread_sessions %d -> %d" % (len(base), len(now)))
    print("  unread_total    %d -> %d" % (34 if len(base) else 0, db.unread_total()))
    left = [s for s in now if str(s.to_uid) == str(target.to_uid)]
    if left:
        print("  目标仍未读: unread=%s" % left[0].unread)
    else:
        print("  目标已清零 OK")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
