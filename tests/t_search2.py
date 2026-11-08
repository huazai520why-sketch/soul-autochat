# -*- coding: utf-8 -*-
"""搜索历史对话（用 nav 回列表，不按返回键）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else "那你脑补的时候"


def main():
    dev = Device.get()
    a = Actor(dev)

    nav.ensure_app(dev)
    snap, pg = nav.to_chatlist(a)
    print("起点 page=%s" % pg)
    if pg != "chatlist":
        print("回不到会话列表")
        return 1

    n = snap.hit(res="c_ct_chat_fragment_search") or snap.hit(desc="搜索")
    if n is None:
        print("找不到搜索图标")
        return 2
    print("点搜索 %s" % (n.bounds,))
    a.hand.tap_node(n, settle=1.8)

    s2 = a.snap()
    box = s2.find_one(cls="EditText")
    if box is None:
        print("搜索页无输入框（page=%s nodes=%d）" % (detect(s2), len(s2.nodes)))
        return 3
    print("输入框 %s" % (box.bounds,))
    a.hand.tap_node(box, settle=0.7)
    dev.u2().clear_text()
    time.sleep(0.3)
    dev.u2().send_keys(KEY)
    time.sleep(2.5)

    s3 = a.snap()
    texts = s3.texts()
    print("\n搜索 %r -> page=%s nodes=%d" % (KEY, detect(s3), len(s3.nodes)))
    for t in texts[:20]:
        print("   %s" % t[:44])

    notfound = any("未找到" in t for t in texts)
    print("\n结论: %s" % ("未找到相关结果" if notfound else "有结果"))

    # 收集可能是会话行的节点（有头像+昵称）
    rows = [x for x in s3.nodes if x.visible and x.clickable and x.bounds[1] > 150]
    print("可点击候选 %d 个" % len(rows))
    for x in rows[:8]:
        print("   %-14s b=%-22s %r"
              % ((x.cls or "").split(".")[-1], x.bounds, (x.label or "")[:20]))
    return 0 if not notfound else 4


if __name__ == "__main__":
    sys.exit(main())
