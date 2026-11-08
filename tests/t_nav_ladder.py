# -*- coding: utf-8 -*-
"""to_tab 导航阶梯的行为测试（纯假对象，不碰设备）。

来源：2026-11-08 生产日志实证的「瞎操作」——
  `连续 4/5/6 次回不到 chatlist（当前 square）→ 强制回首页 → 重启 App`
而紧接「放弃本次导航」之后，调用方只点了一次底栏就回去了。
根因：fails 兜底排在「点底栏 tab」细粒度阶梯之前，把唯一有效动作短路了。

本测试锁死三件事：
  ① 主框架页 + 底栏在 → 必须**点 tab**，不得 am_start / 重启；
  ② 点 tab 反复无效 → 由 dead 阶梯收尾（允许重启一次），且**绝不 back**；
  ③ unknown 但 Activity 仍是 MainActivity → **绝不 back**（会把 App 退到桌面），改 am start。

跑法：python tests/t_nav_ladder.py
"""
import io
import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  ← 必须在 from brain import ... 之前，见 _nolog.py
from brain import nav as N


class FakeNode(object):
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return True


class FakeSnap(object):
    def __init__(self, page, has_tab=True):
        self.page = page
        self._has_tab = has_tab
        self.nodes = []          # popup.detect() 要遍历；空列表 = 识别不到弹窗

    def tab(self, name):
        return FakeNode(name) if self._has_tab else None

    def texts(self):
        return []

    def find(self, **_kw):
        return []          # 真 Snapshot.find() 返回列表，popup.detect() 会直接遍历

    def hit(self, **_kw):
        return None


class FakeHand(object):
    def __init__(self, calls):
        self.calls = calls

    def back(self, settle=1.0):
        self.calls.append("back")

    def tap_node(self, node, settle=1.0):
        self.calls.append("tap_node")


class FakeDev(object):
    def __init__(self, act="cn.soulapp.android.component.startup.main.MainActivity"):
        self.act = act

    def current_app(self):
        return ("cn.soulapp.android", self.act)


class FakeActor(object):
    """wait_page 固定返回当前页；tap_tab 按 tab_works 决定是否切换到目标页。"""

    def __init__(self, calls, page, has_tab=True, tab_works=True, want="chatlist"):
        self.calls = calls
        self.dev = FakeDev()
        self.hand = FakeHand(calls)
        self.page = page
        self.has_tab = has_tab
        self.tab_works = tab_works
        self.want = want

    def _snap(self):
        return FakeSnap(self.page, self.has_tab)

    def wait_page(self, pages, timeout=2.5):
        return self._snap(), self.page

    def snap(self, force=False):
        return self._snap()

    def tap_tab(self, name, settle=1.5):
        self.calls.append("tap_tab:%s" % name)
        if self.tab_works:
            self.page = self.want
        return self._snap(), self.page

    def double_tap_tab(self, name, settle=1.5):
        self.calls.append("double_tap:%s" % name)
        return self._snap(), self.page


def run_case(name, page, has_tab, tab_works, act=None, want="chatlist", tries=8):
    calls = []
    actor = FakeActor(calls, page, has_tab, tab_works, want)
    if act:
        actor.dev.act = act
    box = {"goto_main": 0, "restart": 0, "ensure": 0, "in_soul": 0}

    orig = (N.in_soul, N.goto_main, N.restart_app, N.ensure_app)
    N.in_soul = lambda dev: (box.__setitem__("in_soul", box["in_soul"] + 1), True)[1]
    N.goto_main = lambda dev, wait=10: (box.__setitem__("goto_main", box["goto_main"] + 1), True)[1]
    N.restart_app = lambda dev, wait=25: (box.__setitem__("restart", box["restart"] + 1), True)[1]
    N.ensure_app = lambda dev, wait=18: (box.__setitem__("ensure", box["ensure"] + 1), True)[1]
    try:
        snap, got = N.to_tab(actor, "聊天", tries=tries)
    finally:
        N.in_soul, N.goto_main, N.restart_app, N.ensure_app = orig
    return {"case": name, "result": got, "calls": calls, **box}


def main():
    bad = 0
    print("=" * 74)

    # ① 生产实测场景：在 square、底栏在、点 tab 就回得去
    r = run_case("square+底栏+点tab有效", "square", True, True)
    ok = r["result"] == "chatlist" and r["goto_main"] == 0 and r["restart"] == 0
    print("[%s] ① square 点 tab 有效 → result=%s goto_main=%d restart=%d calls=%s"
          % ("ok  " if ok else "FAIL", r["result"], r["goto_main"], r["restart"], r["calls"]))
    if not ok:
        bad += 1

    # ② 点 tab 一直无效（弹窗盖住底栏）→ 允许重启一次，但绝不 back
    r = run_case("square+底栏+点tab无效", "square", True, False)
    ok = ("back" not in r["calls"]) and r["restart"] <= 1 and r["goto_main"] <= 3
    print("[%s] ② 点 tab 无效 → restart=%d goto_main=%d back=%d（应为 0）"
          % ("ok  " if ok else "FAIL", r["restart"], r["goto_main"], r["calls"].count("back")))
    if not ok:
        bad += 1

    # ③ unknown + 仍在 MainActivity → 绝不 back，改 am start
    r = run_case("unknown+MainActivity", "unknown", False, False,
                 act="cn.soulapp.android.component.startup.main.MainActivity")
    ok = r["calls"].count("back") == 0 and r["goto_main"] >= 1
    print("[%s] ③ unknown+MainActivity → back=%d（应为 0）goto_main=%d"
          % ("ok  " if ok else "FAIL", r["calls"].count("back"), r["goto_main"]))
    if not ok:
        bad += 1

    # ④ 对照：unknown + 非 MainActivity（真在子页）→ 应该 back
    r = run_case("unknown+ChatActivity", "unknown", False, False,
                 act="cn.soulapp.android.chat.ui.ChatActivity")
    ok = r["calls"].count("back") >= 1
    print("[%s] ④ unknown+ChatActivity → back=%d（应 ≥1，说明没把 back 一刀切掉）"
          % ("ok  " if ok else "FAIL", r["calls"].count("back")))
    if not ok:
        bad += 1

    print("=" * 74)
    print("BAD = %d" % bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
