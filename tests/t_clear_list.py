# -*- coding: utf-8 -*-
"""锁住 clear.to_list 的操作层行为：无底栏时绝不盲点 tab、绝不 back。

生产实证（2026-11-09 00:0x 拉取 daemon 重启后的净增量日志）：
    23:59:17~27 十秒内 `tap_tab '聊天' 未命中（page=unknown）` ×6
    + `不在列表页(unknown)，点底栏聊天` ×6，每次还跟着按一次 back。
根因：unknown 页 UI 树里没有底栏，Actor.tap_tab 返回 (None, unknown)，
旧 to_list 不检查就 back → 页面仍是 unknown → 下一轮再点。

本测试用假 Actor/Snapshot 重放这些页面序列，断言修复后的手势序列：
    无底栏 → 0 次 tab 点击、0 次 back、最多 1 次 clear-top 恢复。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brain import clear


class Snap:
    def __init__(self, has_tab):
        self._has_tab = has_tab

    def tab(self, name):
        return object() if self._has_tab else None

    def texts(self):
        return []

    def find(self, **_kw):
        return []          # 真 Snapshot.find() 返回列表

    def hit(self, **_kw):
        return None


class Hand:
    def __init__(self):
        self.backs = 0
        self.tap_nodes = 0

    def back(self, **_kw):
        self.backs += 1

    def tap_node(self, *a, **_kw):
        self.tap_nodes += 1


class Actor:
    def __init__(self, has_tab_seq, tap_result="chatlist"):
        self._seq = list(has_tab_seq)
        self.tap_result = tap_result
        self.hand = Hand()
        self.dev = object()
        self.taps = []
        self._n = 0

    def snap(self):
        i = min(self._n, len(self._seq) - 1)
        self._n += 1
        return Snap(self._seq[i])

    def tap_tab(self, name, **_kw):
        self.taps.append(name)
        return Snap(True), self.tap_result


def _run(actor, pages, popup=None, tries=3):
    """pages: detect() 返回值序列（用尽后复用最后一个）。返回 goto_main 次数。"""
    seq = list(pages)
    pops = [popup] + [None] * 10

    def fake_detect(_snap):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    def fake_popup(_snap):
        return pops.pop(0) if len(pops) > 1 else pops[0]

    with patch.object(clear, "detect", side_effect=fake_detect), \
         patch.object(clear.P, "detect", side_effect=fake_popup), \
         patch("brain.nav.goto_main") as gm:
        clear.to_list(actor, tries=tries)
    return gm.call_count


def check(name, cond, detail):
    if cond:
        print("[OK] %-46s %s" % (name, detail))
        return 0
    print("[BAD] %-46s %s" % (name, detail))
    return 1


def main():
    bad = 0

    # ① 生产事故原样重放：unknown + 无底栏
    a = Actor([False])
    gm = _run(a, ["unknown"])
    bad += check("① unknown 无底栏 → 不盲点", a.taps == [],
                 "taps=%s" % a.taps)
    bad += check("① unknown 无底栏 → 不 back", a.hand.backs == 0,
                 "backs=%d" % a.hand.backs)
    bad += check("① 恢复只做一次不空烧", gm == 1,
                 "goto_main=%d" % gm)

    # ② 已知主框架页 square：一次点 tab 就回 chatlist
    a = Actor([True])
    gm = _run(a, ["square"])
    bad += check("② square 有底栏 → 点一次 tab 成功", a.taps == ["聊天"],
                 "taps=%s" % a.taps)
    bad += check("② 不 back / 不恢复", a.hand.backs == 0 and gm == 0,
                 "backs=%d goto_main=%d" % (a.hand.backs, gm))

    # ③ 明确的会话页：back 一次回列表（快且不会退到桌面）
    a = Actor([False, True])
    gm = _run(a, ["chat", "chatlist"])
    bad += check("③ chat 页 → back 一次且不点 tab",
                 a.hand.backs == 1 and a.taps == [] and gm == 0,
                 "backs=%d taps=%s goto_main=%d" % (a.hand.backs, a.taps, gm))

    # ④ 点了没到：不 back，最多 tries 次，不再叠加恢复动作
    a = Actor([True], tap_result="square")
    gm = _run(a, ["square"], tries=3)
    bad += check("④ 点后仍未到 → 不 back、有上限",
                 a.hand.backs == 0 and len(a.taps) == 3 and gm == 0,
                 "taps=%d backs=%d goto_main=%d" % (len(a.taps), a.hand.backs, gm))

    # ⑤ 弹窗优先处理（原行为必须保留）
    pop = SimpleNamespace(primary=("确定", object()), secondary=None)
    a = Actor([False])
    gm = _run(a, ["unknown"], popup=pop, tries=1)
    bad += check("⑤ 弹窗优先 → 点主按钮不点 tab",
                 a.hand.tap_nodes == 1 and a.taps == [] and a.hand.backs == 0 and gm == 0,
                 "tap_nodes=%d taps=%s backs=%d goto_main=%d"
                 % (a.hand.tap_nodes, a.taps, a.hand.backs, gm))

    print("=== BAD = %d ===" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
