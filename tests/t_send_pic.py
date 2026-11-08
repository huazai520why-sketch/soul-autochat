# -*- coding: utf-8 -*-
"""随便找个人发一张图。用法: python tests/t_send_pic.py [序号]"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import clear as CL  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import SOUL_PKG  # noqa: E402
from eyes.page import detect  # noqa: E402
from hands import pic as P  # noqa: E402

IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 1


def back_to_list(a, dev):
    """回到会话列表：先 back 几次，不行就 app_start。"""
    for _ in range(3):
        s = a.snap(force=True)
        if detect(s) == "chatlist":
            return s
        a.hand.back(settle=1.2)
    dev.u2().app_start(SOUL_PKG, wait=True)
    time.sleep(2.0)
    return CL.to_list(a)


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = back_to_list(a, dev)
    print("当前 page=%s" % detect(snap))
    if detect(snap) != "chatlist":
        print("回不到列表")
        return 1

    rows = [r for r in CL.rows(snap) if 200 <= r.center[1] <= 1500]
    target = None
    for r in rows:
        if "Soul通知" in r.blob or "新招呼" in r.blob:
            continue
        target = r
        break
    if target is None:
        print("没有合适的会话")
        return 3

    print("进 %r" % target.blob[:36])
    a.hand.tap_node(target.node, settle=1.8)
    s, pg = a.wait_page(("chat",), timeout=6)
    print("落点 page=%s" % pg)
    if pg != "chat":
        return 4

    # 先看一眼相册里有几张
    s2, ok = P.open_album(a)
    if not ok:
        print("打不开相册")
        return 5
    ps = P.photos(s2)
    print("\n相册图片数 = %d" % len(ps))
    for i, n in enumerate(ps[:6], 1):
        print("   #%d %s" % (i, n.bounds))
    a.hand.back(settle=1.5)          # 退回会话页

    print("\n>> 发第 %d 张" % IDX)
    ok, why = P.send_from_chat(a, dev, index=IDX)
    print("\n结果: ok=%s %s" % (ok, why))
    print("收尾 page=%s fg=%s" % (detect(a.snap(force=True)),
                                  dev.current_app()[1].split(".")[-1]))
    return 0 if ok else 6


if __name__ == "__main__":
    sys.exit(main())
