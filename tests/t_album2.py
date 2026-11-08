# -*- coding: utf-8 -*-
"""拉起 Soul -> 进会话 -> 更多/图片 -> 点「相机胶卷」-> 看图片列表。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes.page import detect  # noqa: E402
from hands import pic as P  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)
    time.sleep(1.0)

    snap = CL.to_list(a)
    print("page=%s" % detect(snap))
    if detect(snap) != "chatlist":
        return 1

    rows = [r for r in CL.rows(snap) if 200 <= r.center[1] <= 1500]
    tgt = None
    for r in rows:
        if "Soul通知" in r.blob or "新招呼" in r.blob:
            continue
        tgt = r
        break
    print("进 %r" % tgt.blob[:30])
    a.hand.tap_node(tgt.node, settle=1.8)
    a.wait_page(("chat",), timeout=6)

    s, ok = P.open_album(a)
    print("相册 ok=%s 图片=%d" % (ok, len(P.photos(s))))
    if not ok:
        return 2

    # 用户 2026-11-02：进相册后要点一下「相机胶卷」才会加载图片列表
    s = a.snap(force=True)
    f = s.hit(text="相机胶卷")
    print("点相机胶卷 %s" % ((f.bounds if f else None),))
    if f is not None:
        a.hand.tap_node(f, settle=2.0)

    s2 = a.snap(force=True)
    ps = P.photos(s2)
    print("\n图片数=%d" % len(ps))
    for i, n in enumerate(ps[:8], 1):
        print("   #%d %s" % (i, n.bounds))

    p, size, dt = dev.screencap_to(LOGS / "_album.png")
    print("截图 %s %d bytes" % (p.name, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
