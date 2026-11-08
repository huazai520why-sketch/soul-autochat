# -*- coding: utf-8 -*-
"""清红点：对当前屏所有带红点的会话，逐个进入 -> 确认 chat -> 返回 -> 确认 chatlist。

只进入不发言。每步都重新取树确认页面（不靠假设）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import detect  # noqa: E402

MAX_ROW = 10


def dot_rows(snap):
    return [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]


def main():
    a = Actor(Device.get())

    snap = a.snap()
    print("== 开始 ==")
    print("  %s" % a.digest(snap))
    before = dot_rows(snap)
    print("  带红点 %d: %s" % (len(before), [r.nickname for r in before]))
    if not before:
        print("  没有红点，结束")
        return 0

    handled = set()
    ok_cnt = 0
    for i in range(MAX_ROW):
        snap = a.snap()
        if detect(snap) != "chatlist":
            print("  ! 当前不是列表页（%s），中止" % detect(snap))
            break
        todo = [r for r in dot_rows(snap) if r.nickname not in handled]
        if not todo:
            break
        r = todo[0]
        name = r.nickname
        print("\n  [%d] 进入 %r  (红点=%s, y=%d)" % (i + 1, name, r.badge, r.center[1]))

        a.hand.tap_node(r.node, settle=1.6)
        snap2, pg = a._after("chatlist", "chat", "enter")
        if pg != "chat":
            print("     进入失败，实际页面 %s，跳过" % pg)
            handled.add(name)
            continue
        print("     %s" % a.digest(snap2))

        a.hand.back(settle=1.3)
        snap3, pg3 = a._after("chat", "chatlist", "back")
        if pg3 != "chatlist":
            print("     返回后不是列表（%s），中止" % pg3)
            break
        handled.add(name)
        ok_cnt += 1
        left = [x.nickname for x in dot_rows(snap3)]
        print("     返回OK，剩余红点行: %s" % (left or "无"))
        time.sleep(0.4)

    print("\n== 收尾识屏 ==")
    snap = a.snap()
    print("  %s" % a.digest(snap))
    left = dot_rows(snap)
    print("  处理成功 %d 个，当前屏剩余红点 %d: %s"
          % (ok_cnt, len(left), [r.nickname for r in left] or "无"))
    if detect(snap) == "chatlist":
        for r in rows(snap):
            mark = " [红点 %d]" % r.badge if r.badge else ""
            print("   y=%-5d %r%s" % (r.center[1], r.blob[:60], mark))
    return 0


if __name__ == "__main__":
    sys.exit(main())
