# -*- coding: utf-8 -*-
"""动作编排：**每一个动作之后必须重新取树并确认当前页面**。

这是硬约束（用户 2026-11-02 明确指出）：
双击 tab / 滑动列表之后不重新确认，就不知道自己在哪个页面，
后续所有定位都建立在错误的前提上。

用法：
    a = Actor(dev)
    a.tap_tab("聊天", expect="chatlist")
    a.swipe_down()                 # 自动 dump + 报页面
    print(a.page(), a.digest())
"""
import time

from core.log import get_logger
from eyes import popup as P
from eyes.chatlist import rows
from eyes.page import badges, detect
from eyes.uitree import Screen
from hands.tap import Hand

log = get_logger("brain.act")


class Actor(object):
    """动作编排。

    🔴 2026-11-08（A2 帧复用，用户授权自主实施）：
      `snap()` 原来默认 `force=True` —— 于是**每个动作前后各 dump 一次全树**，
      单次 p50=3.65s，等于 7.3s/动作。而 `_after()` 刚刚 dump 过的那一帧，
      在下一个动作的定位阶段（几秒内）仍然新鲜。

      现在把「读」拆成两种语义，铁律只保在后者：
        · `snap()`       动作前定位用 → 允许复用上一动作 `_after()` 的新鲜帧
                         （ttl 内 + Activity 未变；守卫在 Screen 里）
        · `snap(force=True)`  动作后确认用 → 永远重取（`_after`/`wait_page` 走这条）
      用户 2026-11-02 的硬约束「每个动作之后必须重新取树并确认当前页面」
      **完全没有被削弱**：动作后那条路径一次都没少。

      另一个收益来自 `type_and_verify` → `tap_send` 这条链：它们本来就靠
      `_snap` 手工传帧省 dump，现在 `snap()` 自己就会复用，天然少一次。
    """

    # 帧复用窗口。实测转场 1~2s，取 1.2s：既够覆盖「动作后 → 下一个动作前」
    # 这段连续的定位过程，又不会跨过一次真实转场。
    FRAME_TTL = 1.2

    def __init__(self, device, settle=0.7):
        self.dev = device
        self.scr = Screen(device, ttl=self.FRAME_TTL)
        self.hand = Hand(device)
        self.settle = settle
        self.last_page = None
        self.last_sig = None

    # ---------- 读 ----------
    def snap(self, force=False):
        """取一帧。force=True 只给「动作后确认」用，定位阶段用默认值即可。

        ⚠️ 默认值从 True 改成 False 是 A2 的核心；Screen 内部有 Activity 守卫，
           页面一旦换了 Activity 立刻作废重取，不会拿旧帧点错坐标。
        """
        s = self.scr.get(force=force)
        self.last_page = detect(s)
        self.last_sig = s.signature()
        return s

    def page(self, snap=None):
        if snap is None:
            self.snap()
            return self.last_page
        return detect(snap)

    def digest(self, snap=None, n=3):
        """一行摘要：页面 + 红点 + 前 n 行会话，用于日志定位。"""
        s = snap or self.snap()
        page = detect(s)
        parts = ["page=%s" % page, "sig=%s" % s.signature()]
        bd = badges(s)
        if bd:
            parts.append("badges=%s" % bd)
        if page == "chatlist":
            rs = [r for r in rows(s) if 200 <= r.center[1] <= 1500][:n]
            if rs:
                parts.append("top=%r" % (rs[0].blob[:40]))
        return " ".join(parts)

    # ---------- 动作（全部带后置确认） ----------
    def _after(self, before_page, expect, action):
        snap = self.snap(force=True)          # 关键：强制重新取树
        after_page = detect(snap)
        if expect and after_page != expect:
            log.warning("%s: 期望 %s 实际 %s | %s", action, expect, after_page,
                        self.digest(snap))
        else:
            log.info("%s: %s -> %s", action, before_page, after_page)
        p = P.detect(snap)
        if p is not None:
            log.info("%s: 出现弹窗 %s", action, [b[0] for b in p.buttons])
        return snap, after_page

    def wait_page(self, pages, timeout=4.0):
        """等页面变成期望值之一，返回 (snap, page)。

        必需：进入会话时有 1~2s 转场，此时 detect() 会返回 unknown，
        直接判定会误报「不是 chat 页」并退出，导致漏回（2026-11-02 实测）。
        """
        if isinstance(pages, str):
            pages = (pages,)
        t0 = time.time()
        last = None
        snap = None
        while time.time() - t0 < timeout:
            snap = self.snap(force=True)
            last = detect(snap)
            if last in pages:
                return snap, last
            time.sleep(0.35)
        return snap or self.snap(), last

    def tap_text(self, text, expect=None, settle=None):
        snap = self.snap()
        before = detect(snap)
        n = snap.hit(text=text)
        if n is None:
            log.warning("tap_text %r 未命中", text)
            return None, before
        self.hand.tap_node(n, settle=self.settle if settle is None else settle)
        snap, pg = self._after(before, expect, "tap_text(%s)" % text)
        # 同 tap_tab：点后校验失败 → 新帧重新定位再点一次（只一次）
        if expect and pg != expect and snap is not None:
            n2 = snap.hit(text=text)
            if n2 is not None:
                log.warning("tap_text(%s) 点后仍是 %s → 重新定位再点一次", text, pg)
                self.hand.tap_node(n2, settle=self.settle if settle is None else settle)
                snap, pg = self._after(pg, expect, "tap_text(%s) retry" % text)
        return snap, pg

    def tap_tab(self, name, expect=None, settle=None):
        """点底栏 tab（只认 y>=1500，避免命中页面顶部的同名标签）。"""
        snap = self.snap()
        before = detect(snap)
        n = snap.tab(name)
        if n is None:
            log.warning("tap_tab %r 未命中（不在主框架？page=%s）", name, before)
            return None, before
        self.hand.tap_node(n, settle=self.settle if settle is None else settle)
        snap, pg = self._after(before, expect, "tap_tab(%s)" % name)
        # 🔴 2026-11-08 21:4x（用户口径「操作层乱点」的硬化）：
        #   原来点完只**记一条 warning**，页面没动就交给上层自己重试；
        #   上层往往已经拿着旧坐标走下一步了 → 表现为「乱点」。
        #   现在：期望页没到 → 用**新帧**重新定位同语义节点，再点一次（只一次）。
        #   只对「导航类」点击生效（tab/text），发送按钮那类不在此列，不会重复发消息。
        if expect and pg != expect:
            n2 = snap.tab(name) if snap is not None else None
            if n2 is not None:
                log.warning("tap_tab(%s) 点后仍是 %s → 重新定位再点一次", name, pg)
                self.hand.tap_node(n2, settle=self.settle if settle is None else settle)
                snap, pg = self._after(pg, expect, "tap_tab(%s) retry" % name)
        return snap, pg

    def double_tap_tab(self, name, expect=None, settle=None):
        """双击底栏 tab：把列表跳到下一个有红点的锚点（清红点/找行用）。

        🔴 2026-11-04 修正：旧注释「列表向下滚一小段，不是跳红点」是错的——
        clear.sweep / pendingq 都依赖「双击=跳到有红点的行」这个语义（见两处调用注释）。
        同时把裸调 self.dev.u2().double_click 改成走 Hand.double_click，
        补上掉线重连容错（其他动作全走 Hand._do，就这里裸调）。
        """
        snap = self.snap()
        before = detect(snap)
        n = snap.tab(name)
        if n is None:
            # 🔴 2026-11-08（可诊断性修复）：
            #   改前：`log.warning("double_tap_tab %r 未命中", name)` —— 不带 page。
            #   后果：现网 72 次「未命中」里只有 1 条能看出当时在哪个页面
            #   （11-06 23:13:29 `期望 chatlist 实际 unknown | page=unknown …`，
            #   因为只有走 _after() 才打摘要，而这里提前 return 了）。
            #   真因是「页面不在 chatlist 时底栏整个不渲染」——实测 20 次连续 dump
            #   有 13 次 main_tab_msg/recycler_view/c_ct_chat_fragment_search 全缺失。
            #   这里照抄同文件 tap_tab（act.py:111）的写法，把 page 和 digest 一起打出来，
            #   以后再出现未命中，日志能直接看出是页面问题还是坐标问题。
            log.warning("double_tap_tab %r 未命中（page=%s）| %s",
                        name, before, self.digest(snap))
            return None, before
        x, y = n.center
        self.hand.double_click(x, y, interval=0.12,
                               settle=(self.settle if settle is None else settle))
        return self._after(before, expect, "double_tap_tab(%s)" % name)

    def swipe(self, fx, fy, tx, ty, duration=0.25, expect=None, settle=0.5):
        snap = self.snap()
        before = detect(snap)
        self.hand.swipe(fx, fy, tx, ty, duration=duration, settle=settle)
        return self._after(before, expect, "swipe")

    def swipe_up(self, expect=None):
        """列表向下翻（手指上滑）。"""
        return self.swipe(450, 1250, 450, 450, expect=expect)

    def swipe_down(self, expect=None):
        """列表向上翻（手指下拉），用于回到顶部。"""
        return self.swipe(450, 450, 450, 1350, duration=0.18, settle=0.35,
                          expect=expect)

    def back(self, expect=None):
        snap = self.snap()
        before = detect(snap)
        self.hand.back()
        return self._after(before, expect, "back")
