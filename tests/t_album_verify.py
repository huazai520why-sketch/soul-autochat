# -*- coding: utf-8 -*-
"""重启 Soul -> 进会话 -> 开相册 -> 看第一张是不是 soul 图（截图确认）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS, SOUL_PKG  # noqa: E402
from eyes.page import detect  # noqa: E402
from hands import pic as P  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    print("重启 Soul 刷新相册")
    dev.sh("am force-stop %s" % SOUL_PKG, timeout=30)
    time.sleep(1.5)
    dev.u2().app_start(SOUL_PKG, wait=True)
    time.sleep(3.0)

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
    print("相册 ok=%s 图片数=%d" % (ok, len(P.photos(s))))
    for i, n in enumerate(P.photos(s)[:8], 1):
        print("   #%d %s" % (i, n.bounds))

    p, size, dt = dev.screencap_to(LOGS / "_album.png")
    print("截图 %s %d bytes" % (p.name, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
