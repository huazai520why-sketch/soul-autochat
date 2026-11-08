# -*- coding: utf-8 -*-
"""验证：搜索 -> 点结果行 -> 是否进入会话（不发送）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402

KEY = "那你脑补的时候"


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)
    snap, pg = nav.to_chatlist(a)
    print("起点 %s" % pg)
    if pg != "chatlist":
        return 1

    a.hand.tap_node(snap.hit(res="c_ct_chat_fragment_search") or snap.hit(desc="搜索"), settle=1.8)
    s2 = a.snap()
    box = s2.find_one(cls="EditText")
    if box is None:
        print("无输入框")
        return 2
    a.hand.tap_node(box, settle=0.7)
    dev.u2().clear_text()
    time.sleep(0.3)
    dev.u2().send_keys(KEY)
    time.sleep(2.5)

    s3 = a.snap()
    # 找「聊天记录」下的结果行：y 在 200~600 的大块 ViewGroup
    rows = [n for n in s3.nodes
            if n.clickable and n.visible and 200 < n.bounds[1] < 700
            and n.bounds[2] - n.bounds[0] > 500 and n.bounds[3] - n.bounds[1] > 100]
    print("结果行候选 %d:" % len(rows))
    for n in rows:
        print("   b=%s desc=%r" % (n.bounds, (n.desc or "")[:40]))
    if not rows:
        print("没有结果行")
        return 3

    target = rows[0]
    print("\n>> 点结果行 %s" % (target.bounds,))
    a.hand.tap_node(target, settle=2.5)

    s4, pg4 = a.wait_page(("chat",), timeout=6.0)
    print("落点 page=%s" % pg4)
    if pg4 == "chat":
        txts = [n.label for n in s4.nodes if n.label][:10]
        print("会话页文本: %s" % [t[:20] for t in txts])
        print(">>> 进入会话成功")
    else:
        print(">>> 没进入会话，当前 %s" % pg4)
        print("   文本: %s" % [t[:16] for t in s4.texts()[:10]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
