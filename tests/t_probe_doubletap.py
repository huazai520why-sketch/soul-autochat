# -*- coding: utf-8 -*-
"""探针：会话列表结构 + 双击聊天 tab 的真实行为。

验证目标（用户 2026-11-01 观察）：
  双击底部「聊天」tab = 列表跳到「有新消息红点」的会话行，且**不进入会话**。
本脚本先在列表顶部记录状态，再下滑几次，然后双击，看是否跳回。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402
from hands.tap import Hand  # noqa: E402

LIST_TOP, LIST_BOT = 300, 1450     # 会话列表可视区（避开顶部栏与底栏）


def list_rows(snap):
    """把列表区节点按行聚类，返回 [(y, [labels])]。"""
    items = [n for n in snap.labeled()
             if LIST_TOP < n.center[1] < LIST_BOT and n.label]
    items.sort(key=lambda n: n.center[1])
    rows, cur, cy = [], [], None
    for n in items:
        y = n.center[1]
        if cy is None or abs(y - cy) <= 28:
            cur.append(n)
            cy = y if cy is None else (cy + y) // 2
        else:
            rows.append((cy, cur))
            cur, cy = [n], y
    if cur:
        rows.append((cy, cur))
    return rows


def show(tag, snap):
    print("\n[%s] page=%s  nodes=%d" % (tag, detect(snap), len(snap.nodes)))
    for y, ns in list_rows(snap)[:10]:
        labels = " | ".join(n.label[:14] for n in ns)
        print("   y=%-5d %s" % (y, labels[:96]))


def ensure_chatlist(scr, hand):
    snap = scr.get(force=True)
    p = P.detect(snap)
    if p is not None:
        print("  处理弹窗: %s" % [b[0] for b in p.buttons])
        if p.primary:
            hand.tap_node(p.primary[0][1], settle=1.2)
        snap = scr.get(force=True)
    if detect(snap) != "chatlist":
        print("  不在会话列表，点聊天 tab")
        hand.tap_hit(snap, text="聊天", settle=1.2)
        snap = scr.get(force=True)
        p = P.detect(snap)
        if p is not None and p.primary:
            hand.tap_node(p.primary[0][1], settle=1.2)
            snap = scr.get(force=True)
    return snap


def main():
    dev = Device.get()
    scr = Screen(dev)
    hand = Hand(dev)

    print("== 会话列表 + 双击测试 ==")
    snap = ensure_chatlist(scr, hand)
    show("顶部初始", snap)

    # 下滑 3 次，离开顶部
    print("\n  下滑 3 次...")
    for _ in range(3):
        hand.swipe(450, 1250, 450, 450, duration=0.28, settle=0.6)
    snap = scr.get(force=True)
    show("下滑后", snap)

    # 双击聊天 tab（必须用 tab()，不能用 hit()：顶部有同名「聊天」标签）
    tab = snap.tab("聊天")
    if tab is None:
        print("  !! 找不到底栏聊天 tab")
        return 1
    x, y = tab.center
    print("\n  双击底栏聊天 tab center=%s bounds=%s" % ((x, y), tab.bounds))
    d = dev.u2()
    t0 = time.time()
    d.double_click(x, y, 0.12)
    time.sleep(1.2)
    print("  双击完成 %.2fs" % (time.time() - t0))

    snap2 = scr.get(force=True)
    show("双击后", snap2)
    print("\n  页面变化: page=%s" % detect(snap2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
