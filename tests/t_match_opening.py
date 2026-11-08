# -*- coding: utf-8 -*-
"""匹配页：读对方资料 -> 生成开场白（不发送）。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import reply as R  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from eyes.page import detect  # noqa: E402


def collect(snap):
    """从匹配卡片里抽资料。返回 (nick, tags, common, extra)。"""
    texts = [n.label for n in snap.nodes if n.label]
    tags, common, extra = [], [], {}
    for i, t in enumerate(texts):
        t = t.strip()
        if t.startswith("Ta的引力签"):
            rest = t.split("：", 1)[-1].strip()
            if rest:
                tags += [x for x in re.split(r"[、,，/\s]+", rest) if x]
            elif i + 1 < len(texts):
                tags += [x for x in re.split(r"[、,，/\s]+", texts[i + 1]) if x]
        elif t.startswith("你们的共同点"):
            rest = t.split("：", 1)[-1].strip()
            common += [x for x in re.split(r"[、,，/\s]+", rest) if x]
        elif t.startswith("Ta的星座"):
            extra["星座"] = t.split("：", 1)[-1].strip()
        elif t.startswith("匹配度"):
            pass
        elif t.endswith("%") and t[:-1].isdigit():
            extra["匹配度"] = t
    # 昵称：匹配卡片上方那个较短的文本（排除按钮类）
    nick = ""
    for n in snap.nodes:
        t = (n.label or "").strip()
        if (n.center[1] < 140 and 1 <= len(t) <= 14
                and t not in ("手机信号满格。", "WLAN 信号满格。")
                and not t.startswith("正在充电") and not t[:2].isdigit()):
            nick = t
    return nick, tags, common, extra


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap()
    print("page=%s nodes=%d" % (detect(snap), len(snap.nodes)))
    if detect(snap) != "chat":
        print("当前不在聊天页")
        return 1

    nick, tags, common, extra = collect(snap)
    print("昵称=%r 引力签=%s 共同点=%s 其他=%s" % (nick, tags, common, extra))

    b = R.engine()
    if b is None:
        print("引擎未加载")
        return 2
    t0 = __import__("time").time()
    try:
        op, ms = b.opening_line(sid="", nick=nick, hist=[], tags=tags,
                                common=common, kind="match")
    except Exception as e:
        print("opening_line 异常 %r" % e)
        return 3
    print("\n开场白 (%.1fs): %r" % (__import__("time").time() - t0, op))

    # 再生成两条看多样性
    for i in range(2):
        try:
            op2, _ = b.opening_line(sid="", nick=nick, hist=[], tags=tags,
                                    common=common, kind="match")
            print("  备选%d: %r" % (i + 2, op2))
        except Exception as e:
            print("  备选%d 异常 %r" % (i + 2, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
