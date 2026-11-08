# -*- coding: utf-8 -*-
"""循环清角标：双击聊天 -> 识屏 -> 清当前屏红点 -> 再双击 ... 直到聊天角标归零。

安全边界：只进入「带红点」的会话并立即返回，不发送任何内容。
终止：角标为 0，或达到 MAX_ROUND 轮，或页面异常。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402

MAX_ROUND = 15


def dots(snap):
    return [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]


def first_line(snap):
    rs = [r for r in rows(snap) if 200 <= r.center[1] <= 1500]
    return rs[0].blob[:44] if rs else "-"


def badge_chat(snap):
    return badges(snap).get("聊天") or 0


def fix_page(a):
    """确保停在会话列表；遇到弹窗点主按钮。"""
    for _ in range(3):
        snap = a.snap()
        if detect(snap) == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None:
            btn = (p.primary or p.secondary)
            if btn:
                print("       处理弹窗: %s" % btn[0][0])
                a.hand.tap_node(btn[0][1], settle=1.2)
                continue
        print("       不在列表页(%s)，按返回" % detect(snap))
        a.hand.back(settle=1.0)
    return a.snap()


def clear_screen(a, handled):
    """清掉当前屏所有红点会话，返回清理个数。"""
    n = 0
    for _ in range(8):
        snap = a.snap()
        if detect(snap) != "chatlist":
            break
        todo = [r for r in dots(snap) if r.nickname not in handled]
        if not todo:
            break
        r = todo[0]
        print("       进入 %r 红点=%s" % (r.nickname, r.badge))
        a.hand.tap_node(r.node, settle=1.6)
        snap2, pg = a._after("chatlist", "chat", "enter")
        handled.add(r.nickname)
        if pg != "chat":
            print("         未进入（%s），跳过" % pg)
            fix_page(a)
            continue
        a.hand.back(settle=1.2)
        _, pg3 = a._after("chat", "chatlist", "back")
        if pg3 != "chatlist":
            print("         返回异常（%s）" % pg3)
            fix_page(a)
        n += 1
    return n


def main():
    a = Actor(Device.get())
    handled = set()

    snap = a.snap()
    print("== 起始 角标聊天=%s 第一行=%r" % (badge_chat(snap), first_line(snap)))

    for rd in range(1, MAX_ROUND + 1):
        if badge_chat(a.snap()) == 0:
            print("\n角标已归零（第 %d 轮前检查）" % rd)
            break

        print("\n-- 第 %d 轮 --" % rd)
        snap, pg = a.double_tap_tab("聊天", expect="chatlist")
        if snap is None:
            print("   双击未命中，重试")
            fix_page(a)
            continue
        print("   双击后 角标=%s 第一行=%r 红点=%d %s"
              % (badge_chat(snap), first_line(snap), len(dots(snap)),
                 [r.nickname for r in dots(snap)]))

        if dots(snap):
            cnt = clear_screen(a, handled)
            print("   清理 %d 个" % cnt)

        snap = a.snap()
        b = badge_chat(snap)
        print("   本轮结束 角标=%s 第一行=%r" % (b, first_line(snap)))
        if b == 0:
            print("\n角标归零，完成")
            break
        time.sleep(0.3)

    print("\n== 收尾 ==")
    snap = a.snap()
    print("  %s" % a.digest(snap))
    print("  角标聊天=%s  当前屏红点=%d" % (badge_chat(snap), len(dots(snap))))
    print("  累计进入会话 %d 个" % len(handled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
