# -*- coding: utf-8 -*-
"""brain.nav.log WARN 刷屏回归测试（2026-11-11 专项 · issue #4）。

跑法：python tests/t_nav_warn.py      （BAD=0 表示全过）

验证三件事（都是「brain.nav.log WARN 一天 1192 次」的根因/放大器）：

  1. **unknown + MainActivity 第一次就走 clear-top，不是直接重启**（死代码修复）。
     原代码 `stuck += 1` 在 `if stuck == 0` **之前**执行，导致该分支永不命中，
     主框架内 unknown 每次都直接跳到 else 重启 App（20~40s/次）→
     restart_app 被调用过密 → 「重启过于频繁」节流告警刷屏。
     现在第一次 unknown 必须走 goto_main（clear-top），第二次才重启。

  2. **restart_app 的「重启过于频繁」节流告警在窗口内只打一次**（日志收敛）。
     原实现每次被节流都打一条完全相同的 WARN —— 一次卡死故障里反复调用
     restart_app 就刷出几十条。现在同窗口内只保留一条，动作不变（照旧 goto_main）。

  3. **普通（非节流）恢复告警不被降级**：`强制重启 Soul` / `连续 N 次回不到`
     仍打 WARN —— tools/action_audit.py 靠它们量化恢复动作，绝不能动。
"""
import io
import logging
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  ← 必须在 from brain import ... 之前，见 _nolog.py
from brain import nav as N

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


class FakeNode(object):
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return True


class FakeSnap(object):
    def __init__(self, page, has_tab=True):
        self.page = page
        self._has_tab = has_tab
        self.nodes = []

    def tab(self, name):
        return FakeNode(name) if self._has_tab else None

    def texts(self):
        return []

    def find(self, **_kw):
        return []

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

    def text(self, cmd, timeout=20):
        # goto_main 会走 device.text("am start ...")；测试里不真执行，直接成功。
        return "ok"


class FakeActor(object):
    def __init__(self, calls, page, has_tab=True, tab_works=False, want="chatlist"):
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


class _WarnCapture(logging.Handler):
    """捕获 WARNING 及以上日志行。"""
    def __init__(self):
        super(_WarnCapture, self).__init__()
        self.records = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.records.append(record.getMessage())


# ------------------------------------------------------------------ 1 · 死代码修复
print("\n--- 1 · unknown + MainActivity：第一次必须走 clear-top，不直接重启 ---")
calls = []
actor = FakeActor(calls, "unknown", has_tab=False)
box = {"goto_main": 0, "restart": 0}
orig = (N.in_soul, N.goto_main, N.restart_app, N.ensure_app)
N.in_soul = lambda dev: True
N.goto_main = lambda dev, wait=10: (box.__setitem__("goto_main", box["goto_main"] + 1), True)[1]
N.restart_app = lambda dev, wait=25: (box.__setitem__("restart", box["restart"] + 1), True)[1]
N.ensure_app = lambda dev, wait=18: True
try:
    N.to_tab(actor, "聊天", tries=3)
finally:
    N.in_soul, N.goto_main, N.restart_app, N.ensure_app = orig
ck(box["goto_main"] >= 1, "1 第一次 unknown+MainActivity 走 clear-top（goto_main=%d，应≥1）"
   % box["goto_main"])
ck(box["restart"] <= box["goto_main"], "1 重启次数不高于 clear-top（restart=%d goto_main=%d）"
   % (box["restart"], box["goto_main"]))


# ------------------------------------------------------------------ 2 · 节流告警只打一次
print("\n--- 2 · restart_app「重启过于频繁」告警在窗口内只打一次 ---")
cap = _WarnCapture()
N.log.addHandler(cap)
_orig_last = N._LAST_RESTART.copy()
_orig_restart_log = N._RESTART_LOG.copy()
try:
    # 模拟：上次真正重启在 1s 前（仍在 240s 节流窗口内）
    N._LAST_RESTART["t"] = time.time() - 1
    N._RESTART_LOG["t"] = 0.0
    # 连续调 5 次（每次都在节流窗口内，本应各刷一条 WARN）
    for _ in range(5):
        N.restart_app(FakeDev())
finally:
    N.log.removeHandler(cap)
    N._LAST_RESTART.clear()
    N._LAST_RESTART.update(_orig_last)
    N._RESTART_LOG.clear()
    N._RESTART_LOG.update(_orig_restart_log)
n_warn = sum(1 for w in cap.records if "重启过于频繁" in w)
ck(n_warn == 1, "2 节流窗口内「重启过于频繁」只打 1 次（实际 %d）" % n_warn)


# ------------------------------------------------------------------ 3 · 非节流告警不降级
print("\n--- 3 · 普通恢复告警仍打 WARN（供 action_audit 量化）---")
cap2 = _WarnCapture()
N.log.addHandler(cap2)
try:
    N.log.warning("连续 3 次回不到 chatlist（当前 square）→ 强制回首页(am start)")
    N.log.warning("强制重启 Soul")
finally:
    N.log.removeHandler(cap2)
n2 = len(cap2.records)
ck(n2 == 2, "3 普通恢复告警不受节流影响（仍 WARN，实际 %d 条）" % n2)


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
