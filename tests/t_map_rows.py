# -*- coding: utf-8 -*-
"""回聊天页 -> 列出红点行 -> 用当前账号的库匹配 session -> 判断最后一条是谁发的。

只读，不进入任何会话。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import current_uid, open_account  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402


def fix_to_list(a):
    for _ in range(4):
        snap = a.snap()
        if detect(snap) == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None and (p.primary or p.secondary):
            btn = (p.primary or p.secondary)[0]
            print("   处理弹窗 %r" % btn[0])
            a.hand.tap_node(btn[1], settle=1.5)
            continue
        print("   page=%s，点聊天 tab" % detect(snap))
        a.tap_tab("聊天", settle=1.2)
    return a.snap()


def score(row_blob, s):
    """行预览与库中 last_text 的重合度（取最长公共子串长度近似）。"""
    t = (s.last_text or "").strip()
    if not t:
        return 0
    best = 0
    for L in range(min(10, len(t)), 3, -1):
        for i in range(0, len(t) - L + 1):
            if t[i:i + L] in row_blob:
                best = max(best, L)
    return best


def main():
    dev = Device.get()
    a = Actor(dev)

    print("== 回聊天页 ==")
    a.tap_tab("聊天", settle=1.5)
    snap = fix_to_list(a)
    print("   %s" % a.digest(snap))
    ds = [r for r in rows(snap) if 200 <= r.center[1] <= 1500 and r.has_dot]
    print("   红点行 %d: %s" % (len(ds), [r.nickname for r in ds]))
    if not ds:
        print("   当前屏无红点")
        for r in rows(snap)[:6]:
            print("     y=%-5d %r" % (r.center[1], r.blob[:56]))

    print("\n== 当前账号 ==")
    print("   device uid = %s" % current_uid(dev))
    db = open_account(dev)
    print("   lib uid    = %s  未读会话 %d" % (db.uid, len(db.sessions(unread_only=True))))
    pend = [s for s in db.sessions(unread_only=True) if not s.is_official]

    print("\n== 红点行 -> 库中会话 匹配 ==")
    for r in ds:
        blob = r.blob
        cands = sorted(((score(blob, s), s) for s in pend), key=lambda x: -x[0])
        top = [(sc, s) for sc, s in cands if sc >= 4][:3]
        print("\n   行 y=%d %r" % (r.center[1], blob[:56]))
        if not top:
            print("      !! 未匹配到库中会话")
            continue
        for sc, s in top:
            last = db.last_message(s.session_id)
            who = "?" if last is None else (
                "我" if str(last.sender) == str(db.uid) else "对方")
            print("      分=%-2d uid=%-10s unread=%-2s %s 最后[%s]: %r"
                  % (sc, s.to_uid, s.unread, s.time_str, who, (s.last_text or "")[:22]))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
