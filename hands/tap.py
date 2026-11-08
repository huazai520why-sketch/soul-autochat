# -*- coding: utf-8 -*-
"""手：点击。只负责执行，不做判断（不 import eyes）。

坐标一律来自运行时节点几何，不写死任何屏幕位置。

🔴 两条设备侧铁律（2026-11-02 用户强调：**提速也要看实际情况，不要点太快**）：

1. **所有 u2 调用都要能扛住掉线**。
   实测 u2 的 device 端 server 会莫名退出（`RemoteDisconnected`），
   之后每一次 press/click 都抛异常，整轮业务全崩。这里统一重连一次再重试。

2. **慢设备要自动放慢**。
   同一个动作在设备空闲时 0.3s 就够，设备卡时（dump 2~4s）会出现
   「点了没反应 → 再点一次 → 变成双击」。所以 settle 按最近一次 dump 耗时放大：
       dump < 800ms   -> 原样
       800~2000ms     -> ×1.5
       > 2000ms       -> ×2.5（并记一条 warn，便于发现设备变卡）
"""
import time

from core.log import get_logger

log = get_logger("hands.tap")

from core.device import note_dump, slow_factor  # noqa: F401  (统一在 core.device 里维护)
from core.device import note_action


class Hand(object):
    def __init__(self, device):
        self.dev = device
        self._d = None

    @property
    def d(self):
        if self._d is None:
            self._d = self.dev.u2()
        return self._d

    # ---------- 容错执行 ----------
    def _do(self, name, *a, **kw):
        """执行一个 u2 动作；掉线就重连重试一次。

        🔴 2026-11-03 修复 P2：原来传的是绑定方法 `self.d.click`（求值时已绑定
        旧连接），掉线重连后 `self._d` 已置 None，但 fn 仍是旧连接的绑定方法 →
        重试仍打旧连接、第二次必继续失败。改成传**方法名**，
        每次 `getattr(self.d, name)` 重新取当前连接上的方法。

        🔴 2026-11-08（A2）：动作一旦发生，之前 dump 的 UI 帧就不可信了。
        这里统一 `note_action()` 让帧缓存作废 —— 包住所有走 Hand 的动作
        （tap/swipe/back/double_click）。绕过 Hand 直接调 u2 的地方
        （hands/pic.py、brain/search.py）在各自调用点补 note_action()。
        """
        note_action()
        try:
            return getattr(self.d, name)(*a, **kw)
        except Exception as e:
            log.warning("设备动作失败（%r）→ 重置 u2 重试", e)
            self.dev.reset_u2()
            self._d = None
            time.sleep(1.0)
            return getattr(self.d, name)(*a, **kw)

    def _settle(self, settle):
        """按设备快慢放大等待。"""
        if not settle:
            return
        time.sleep(settle * slow_factor())

    # ---------- 基础 ----------
    def tap_xy(self, x, y, settle=0.0):
        """按坐标点一次。settle>0 时点完等一会（按设备快慢自动放大）。"""
        self._do("click", int(x), int(y))
        self._settle(settle)
        return (int(x), int(y))

    def tap_node(self, node, settle=0.0):
        """点节点几何中心（不是写死坐标）。"""
        if node is None:
            raise ValueError("tap_node: node 为空")
        x, y = node.center
        log.debug("tap %r center=%s", (node.label or "")[:16], (x, y))
        return self.tap_xy(x, y, settle=settle)

    def tap_hit(self, snap, settle=0.0, **kw):
        """按语义（text/res/desc…）找到可点击目标并点它。找不到返回 None。"""
        n = snap.hit(**kw)
        if n is None:
            log.warning("tap_hit 未命中: %r", kw)
            return None
        self.tap_node(n, settle=settle)
        return n

    # ---------- 组合 ----------
    def back(self, settle=0.3):
        self._do("press", "back")
        self._settle(settle)

    def swipe(self, fx, fy, tx, ty, duration=0.3, settle=0.2):
        self._do("swipe", fx, fy, tx, ty, duration=duration)
        self._settle(settle)

    def press(self, key, settle=0.2):
        self._do("press", key)
        self._settle(settle)

    def double_click(self, x, y, interval=0.12, settle=0.8):
        self._do("double_click", int(x), int(y), interval)
        self._settle(settle)
