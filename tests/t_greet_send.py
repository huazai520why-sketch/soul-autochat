# -*- coding: utf-8 -*-
"""新招呼：点人 -> 进对话页 -> 发通用开场白 -> 返回列表验证红点。

对应页面：NewGreetingDetailActivity（「收到的新招呼 / 发消息后对话框将会被放出哦」）
每个人是一整行 ViewGroup(0, y, 900, y+153)，点它进对话页。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import match as M  # noqa: E402
from brain.act import Actor  # noqa: E402
from brain.nav import to_chatlist  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import badges, detect  # noqa: E402

DRY = "--dry" in sys.argv
MAX_PEOPLE = 3


def greet_rows(snap):
    """新招呼页里每个人的整行容器（宽 900、高 ~153 的可点击 ViewGroup）。"""
    out = []
    for n in snap.nodes:
        if not (n.clickable and n.visible):
            continue
        x1, y1, x2, y2 = n.bounds
        if (x2 - x1) >= 700 and 120 <= (y2 - y1) <= 220 and y1 > 150:
            out.append(n)
    out.sort(key=lambda n: n.bounds[1])
    return out


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    pg = detect(snap)
    print("起点 page=%s badges=%s" % (pg, badges(snap)))

    # 如果还在列表，先点「收到的新招呼」
    if pg == "chatlist":
        from brain import clear as CL
        tgt = None
        for r in CL.rows(snap):
            if "新招呼" in r.blob:
                tgt = r
                break
        if tgt is None:
            print("列表里没有新招呼行")
            return 1
        print("点「收到的新招呼」%s" % (tgt.node.bounds,))
        a.hand.tap_node(tgt.node, settle=2.5)
        snap = a.snap(force=True)
        pg = detect(snap)

    txt = "\n".join(snap.texts())
    if "新招呼" not in txt:
        print("当前不在新招呼页（page=%s）" % pg)
        return 2

    rows = greet_rows(snap)
    print("新招呼人数 %d: %s" % (len(rows), [r.bounds for r in rows]))
    if not rows:
        print("解析不到人")
        return 3

    done = 0
    tried = set()
    for i in range(1, MAX_PEOPLE + 1):
        # 每次重新取树：发完一个人，新招呼页会少一行（页面在转场，旧快照不可用）
        s = a.snap(force=True)
        if "新招呼" not in "\n".join(s.texts()):
            print("已不在新招呼页，结束")
            break
        cur = [r for r in greet_rows(s) if tuple(r.bounds) not in tried]
        if not cur:
            print("没有未处理的人了")
            break
        row = cur[0]
        tried.add(tuple(row.bounds))
        print("\n===== 第 %d 人 %s =====" % (i, row.bounds))
        a.hand.tap_node(row, settle=2.5)
        s2, pg2 = a.wait_page(("chat",), timeout=8.0)
        print("  落点 page=%s fg=%s" % (pg2, dev.current_app()[1].split(".")[-1]))
        if pg2 != "chat":
            print("  没进对话页，返回重试")
            a.hand.back(settle=1.5)
            continue

        text = M.pick_opener()
        print("  开场白 %r" % text)
        if DRY:
            print("  [dry] 不发")
        else:
            ok, why = M.send(a, dev, text)
            print("  发送 ok=%s %s" % (ok, why))
            if ok:
                done += 1
                time.sleep(0.8)

        # 返回新招呼页（会话内 back 安全），并等页面稳定
        a.hand.back(settle=1.5)
        for _ in range(4):
            s3 = a.snap(force=True)
            if "新招呼" in "\n".join(s3.texts()):
                break
            time.sleep(0.8)

    print("\n>> 回聊天列表")
    s5, pg5 = to_chatlist(a)
    print("page=%s badges=%s" % (pg5, badges(s5) if pg5 == "chatlist" else "-"))
    print("本轮发出去 %d 条" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
