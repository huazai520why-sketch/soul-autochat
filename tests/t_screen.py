# -*- coding: utf-8 -*-
"""只读识屏：识别当前屏幕内容，不做任何点击/滑动。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes import popup as P  # noqa: E402
from eyes.chatlist import rows  # noqa: E402
from eyes.page import badges, detect  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    scr = Screen(dev)

    t0 = time.time()
    snap = scr.get(force=True)
    dt = (time.time() - t0) * 1000

    print("== 当前屏幕 ==")
    print("  time        %s" % time.strftime("%H:%M:%S"))
    print("  page        %s" % detect(snap))
    print("  signature   %s" % snap.signature())
    print("  nodes       %d (visible %d)" % (len(snap.nodes), len(snap.labeled())))
    print("  dump        %.0f ms" % dt)
    print("  badges      %s" % (badges(snap) or "-"))
    print("  foreground  %s / %s" % dev.current_app())

    p = P.detect(snap)
    if p is not None:
        print("  POPUP       按钮=%s 文本=%r"
              % ([b[0] for b in p.buttons], p.texts[:5]))

    tabs = snap.tabs()
    if tabs:
        print("  底栏        %s" % ", ".join(
            "%s@%s" % (k, v.center) for k, v in tabs.items() if v))

    if detect(snap) == "chatlist":
        rs = rows(snap)
        dots = [r for r in rs if r.has_dot]
        print("\n-- 会话行（%d，带红点 %d） --" % (len(rs), len(dots)))
        for r in rs:
            mark = " [红点 %d]" % r.badge if r.badge else (" [红点]" if r.has_dot else "")
            print("   y=%-5d %r%s" % (r.center[1], r.blob[:66], mark))
    else:
        print("\n-- 可见文本 --")
        for i, t in enumerate(snap.texts()[:22]):
            print("   %02d %s" % (i, t[:50]))


if __name__ == "__main__":
    sys.exit(main())
