# -*- coding: utf-8 -*-
"""探路：会话列表 -> 点放大镜 -> 搜索页结构（有无 a11y 树 / 输入框）+ 试搜一句。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.page import detect  # noqa: E402

KEY = "那你脑补的时候"


def show(tag, snap):
    print("\n[%s] page=%s nodes=%d 有文本=%d"
          % (tag, detect(snap), len(snap.nodes), len([n for n in snap.nodes if n.label])))
    for n in snap.nodes[:0]:
        pass
    items = [n for n in snap.nodes if n.label]
    for n in items[:20]:
        print("   y=%-5d %-12s res=%-18s %r"
              % (n.center[1], (n.cls or "").split(".")[-1],
                 (n.res_id or "").split("/")[-1], n.label[:30]))
    if not items:
        print("   (无文本节点 —— 可能又是自绘/无 a11y 树)")


def main():
    dev = Device.get()
    a = Actor(dev)

    snap = a.snap()
    for _ in range(3):
        if detect(snap) == "chatlist":
            break
        print("  当前 page=%s，返回一层" % detect(snap))
        a.hand.back(settle=1.0)
        snap = a.snap()
    if detect(snap) != "chatlist":
        a.tap_tab("聊天", settle=1.5)
        snap = a.snap()

    print("== 找搜索入口 ==")
    cand = [n for n in snap.nodes if n.label and ("搜索" in n.label or "搜索" in (n.desc or ""))]
    for n in cand:
        print("   %-12s b=%s res=%s %r"
              % ((n.cls or "").split(".")[-1], n.bounds,
                 (n.res_id or "").split("/")[-1], n.label[:16]))
    if not cand:
        print("   树里没有搜索节点，打印顶部区域节点：")
        for n in snap.nodes:
            if n.bounds[1] < 200 and n.visible:
                print("      %-12s b=%s res=%s %r"
                      % ((n.cls or "").split(".")[-1], n.bounds,
                         (n.res_id or "").split("/")[-1], n.label[:16]))
        return 1

    t = cand[0]
    print("\n>> 点搜索 %s" % (t.bounds,))
    a.hand.tap_node(t, settle=1.8)
    snap2 = a.snap()
    show("搜索页", snap2)

    png = dev.screencap()
    (LOGS / "_search_page.png").write_bytes(png)
    bs = ocr.read(png)
    print("\n   OCR 兜底识别 %d 条：" % len(bs))
    for it in bs[:14]:
        print("      y=%-5d %r" % (it.cy, it.text[:28]))

    print("\n>> 尝试灌入关键词 %r" % KEY)
    box = snap2.find_one(res="et_sendmessage") or snap2.find_one(cls="EditText")
    if box is None:
        print("   树里找不到搜索输入框，改用 OCR 位置上找")
    else:
        print("   输入框 %s" % (box.bounds,))
        a.hand.tap_node(box, settle=0.8)
        dev.u2().clear_text()
        time.sleep(0.4)
        dev.u2().send_keys(KEY)
        time.sleep(2.0)
        snap3 = a.snap()
        show("搜索中", snap3)
        png2 = dev.screencap()
        (LOGS / "_search_result.png").write_bytes(png2)
        for it in ocr.read(png2)[:16]:
            print("      y=%-5d %r" % (it.cy, it.text[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
