# -*- coding: utf-8 -*-
"""brain.search.log WARN 降噪回归测试（2026-11-11 专项 · issue #7）。

跑法：python tests/t_search_warn.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.search.log` WARN 一天 662 次（阈值 500）。
逐条审查 brain/search.py 的 log.warning 调用点，把**已被兜住/中间态**的
路径降为 INFO/DEBUG，保留真正故障（终端失败、需要上层动作）的 WARN。

与 brain/flow.py（issue #5）、data/imdb.py（issue #3）、brain/nav.py（issue #4）
的降噪口径一致：**降级的都是"有兜底/重试链中间态/常态"的路径**，真正的
终端失败（找不到搜索入口、没进搜索页、熔断、灌字放弃）一个不降。

降为 INFO（已兜住的降级/中间态，不是故障）：
  - [popup] 点关闭异常（只让本次关弹窗放弃，open_search 会继续）
  - 关弹窗异常（继续尝试搜索）
  - 回聊天列表异常（下面 snap(force) 兜底再找一次）
  - open_search: 回列表失败（pg 非 chatlist → 已认栽提前返回，不再空滑空等）
  - clear_text 异常 → 重置 u2 重试（重试链中间态）
  - 搜索等满仍无结果（单次超时 ≠ 通道坏，熔断那条才 WARN）

保留 WARN（真实故障 / action_audit 计数依赖）：
  - 找不到搜索入口（action_audit「搜索打不开」类别，不能动）
  - 没进搜索页 / 搜索页没有输入框 / clear_text 重试仍失败 / 灌关键词异常
  - 搜索连续 N 次超时 → 熔断（通道坏了，真信号）
  - 搜索页已无结果行 / 点了 N 次仍未进入会话 / 试了 N 次仍在搜索页

纯日志级别调整，无行为变更。py_compile + 本测试验证。
"""
import logging
import os
import sys
import time
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  ← 必须在 from brain import ... 之前，见 _nolog.py
from brain import search as S  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


# ---------------------------------------------------------------- 1 · 降级点已生效
print("\n--- 1 · 关键降级点已改为 INFO/DEBUG ---")
src = Path(S.__file__).read_text("utf-8")

# 每条降级文案必须是 log.info / log.debug，不能再是 log.warning
DOWNGRADED = [
    ("[popup] 点关闭异常", "点关闭异常应降 INFO"),
    ("关弹窗异常（继续尝试搜索）", "关弹窗异常应降 INFO"),
    ("回聊天列表异常", "回聊天列表异常应降 INFO"),
    ("open_search: 回列表失败", "回列表失败说明应降 INFO"),
    ("clear_text 异常: %r → 重置 u2 重试", "clear_text 重试中间态应降 INFO"),
    ("等满 %.0fs 仍无结果", "单次超时应降 INFO"),
]
for text, why in DOWNGRADED:
    # 找到这条文案在源码里所在行
    found = None
    for line in src.splitlines():
        if text in line:
            found = line
            break
    ck(found is not None, "1 源码含降级文案：%s" % why)
    if found:
        ck(("log.info(" in found) or ("log.debug(" in found),
           "1   %s 已非 warning" % why)
        ck("log.warning(" not in found, "1   %s 无残留 warning" % why)

# ---------------------------------------------------------------- 2 · 真信号保留 WARN
print("\n--- 2 · 真正故障仍保留 WARN ---")
KEEP = [
    ("找不到搜索入口", "终端失败（action_audit 计数）保留 WARN"),
    ("没进搜索页", "点了入口没进搜索页保留 WARN"),
    ("搜索页没有输入框", "搜索页无输入框保留 WARN"),
    ("clear_text 重试仍失败", "灌字放弃保留 WARN"),
    ("灌关键词异常", "灌字异常保留 WARN"),
    ("搜索连续 %d 次超时 → 熔断", "熔断（通道坏）保留 WARN"),
    ("点了 %d 次仍未进入会话", "进会话失败保留 WARN"),
    ("试了 %d 次仍在搜索页", "退出失败保留 WARN"),
]
for text, why in KEEP:
    found = None
    for line in src.splitlines():
        if text in line and "log." in line:
            found = line
            break
    ck(found is not None, "2 源码含保留文案：%s" % why)
    if found:
        ck("log.warning(" in found, "2   %s 仍为 warning" % why)

# ---------------------------------------------------------------- 3 · 行为验证：熔断 WARN 保留
print("\n--- 3 · 熔断是唯一保留的「超时链」WARN ---")
# 单次超时走 INFO，连续 N 次触发熔断才 WARN —— 验证 search() 超时路径的
# 日志级别区分。用假 actor/dev 直接驱动 search() 走到超时。
class _Cap(logging.Handler):
    def __init__(self):
        super(_Cap, self).__init__()
        self.records = []

    def emit(self, rec):
        self.records.append((rec.levelno, rec.getMessage()))


class _N:
    """占位 node，仅需可被 tap_node 接收。"""
    bounds = (100, 100, 500, 200)
    text = ""
    label = ""
    desc = ""
    cls = "EditText"
    clickable = True
    visible = True


class _Snap:
    """模拟搜索页：只有一个 EditText，永不返回结果。"""
    def __init__(self, nodes=None):
        self.nodes = nodes or [_N()]
        self._texts = ["取消"]

    def find_one(self, cls=None, res=None, desc=None, text=None):
        if cls == "EditText":
            return _N()
        return None

    def find(self, **_kw):
        return []

    def hit(self, **_kw):
        return None

    def texts(self):
        return list(self._texts)


class _U2:
    def clear_text(self):
        pass

    def send_keys(self, kw):
        pass


class _Dev:
    def u2(self):
        return _U2()

    def reset_u2(self):
        pass


class _Hand:
    def tap_node(self, node, settle=1.0):
        pass


class _Actor:
    def __init__(self, snap):
        self.snap_obj = snap
        self.hand = _Hand()
        self._i = 0

    def snap(self, force=False):
        # 前几帧返回搜索页（有输入框），随后永不出现结果行
        self._i += 1
        return self.snap_obj


orig_breaker = dict(S._BREAKER)
orig_reason = S.LAST_REASON
cap = _Cap()
S.log.addHandler(cap)
try:
    # 模拟连续 3 次超时 → 应触发熔断 WARN
    S._BREAKER.update({"fails": 2, "until": 0.0})
    S.search(_Actor(_Snap()), _Dev(), "测试关键词", wait=0.0, max_wait=0.0)
finally:
    S.log.removeHandler(cap)
    S._BREAKER.clear()
    S._BREAKER.update(orig_breaker)
    S.LAST_REASON = orig_reason

warns = [m for lv, m in cap.records if lv >= logging.WARNING]
infos = [m for lv, m in cap.records if lv < logging.WARNING]
ck(any("熔断" in w for w in warns),
   "3 连续超时触发熔断 WARN（实际 warning=%r）" % [w[:30] for w in warns])
ck(any("仍无结果" in m for m in infos),
   "3 单次超时走 INFO 不 WARN（实际 info=%r）" % [m[:30] for m in infos])


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(1 if BAD else 0)
