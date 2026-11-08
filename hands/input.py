# -*- coding: utf-8 -*-
"""手：灌字与发送。只执行动作，不做判断。

实测（2026-11-02，900x1600，u2 3.7.1）：
- 输入框 res=et_sendmessage b=(118,1501,658,1561)，空时显示 placeholder「文明聊天，友善交友~」
- u2 `send_keys()` 原生支持中文，无需切语音/文字模式、无需第三方输入法
- **发送按钮灌字后才出现**：res=btn_send b=(750,1495,878,1567) text='发送'
  同时输入框右边界从 658 收缩到 594
- 清空后 placeholder 回来

旧架构（soul_send._input）那套「先切语音模式→点键盘图标→再灌字」的仪式，
在本环境不需要 —— 直接点框 + send_keys 即成功。
"""
import time

from core.log import get_logger

log = get_logger("hands.input")

BOX_RES = "et_sendmessage"
SEND_RES = "btn_send"
PLACEHOLDER = "文明聊天，友善交友~"


class Input(object):
    def __init__(self, device):
        self.dev = device
        self._d = None
        self._snap = None      # 最近一次灌字后的快照：tap_send 复用，省一次 dump
        # 🔴 2026-11-04：`sent_ok` 的三态结论（"ok"/"unknown"/"residual"），
        #   上层据此区分「无法确认（按已发记账）」和「明确没发（不记账、重试）」。
        self.last_reason = ""

    @property
    def d(self):
        if self._d is None:
            self._d = self.dev.u2()
        return self._d

    # ---------- 读 ----------
    @staticmethod
    def box(snap):
        return snap.find_one(res=BOX_RES)

    @staticmethod
    def box_text(snap):
        n = Input.box(snap)
        if n is None:
            return None
        t = (n.text or "").strip()
        return "" if t == PLACEHOLDER else t

    # ---------- 写 ----------
    def _reset(self):
        """u2 掉线时重置连接（下次 self.d 会重新取新连接）。"""
        try:
            self.dev.reset_u2()
        except Exception:
            pass
        self._d = None

    def clear(self):
        try:
            self.d.clear_text()
        except Exception as e:
            # 🔴 2026-11-03 修复 P2：原来只打日志不重连，后续继续用失效连接。
            log.warning("clear_text 异常: %r → 重置 u2 重试", e)
            self._reset()
            try:
                self.d.clear_text()
            except Exception as e2:
                log.warning("clear_text 重试仍失败: %r", e2)

    def type_text(self, text, settle=1.0):
        """灌字。返回 True/False（以输入框实际文本为准，不看返回值）。"""
        try:
            self.d.send_keys(text)
        except Exception as e:
            # 🔴 2026-11-03 修复 P2：原来只打日志返回 False，连接保持失效，
            #    后续 type_and_verify 重试也打同一失效连接。
            log.warning("send_keys 异常: %r → 重置 u2 重试", e)
            self._reset()
            try:
                self.d.send_keys(text)
            except Exception as e2:
                log.warning("send_keys 重试仍失败: %r", e2)
                return False
        if settle:
            time.sleep(settle)
        return True

    def type_and_verify(self, text, actor, tries=2):
        """点框 -> 清空 -> 灌字 -> 用 UI 树验证。返回 (ok, 实际文本)。

        🔴 提速（2026-11-02）：验证用的这份快照**同时缓存下来给 tap_send 用**。
        实测设备卡时单次 dump 要 2~4s，原来灌字验一次、找发送按钮再一次、
        发送后再轮询一次 = 3 次 dump ≈ 6~12s/人，全程一半时间耗在这。
        """
        for i in range(tries):
            snap = actor.snap()
            n = self.box(snap)
            if n is None:
                log.warning("第%d次：找不到输入框", i + 1)
                return False, None
            if i == 0:
                actor.hand.tap_node(n, settle=0.7)
            else:
                self.clear()
                time.sleep(0.3)
            self.type_text(text, settle=0.9)
            snap2 = actor.snap()
            got = self.box_text(snap2)
            if got and text.strip() in got:
                self._snap = snap2          # 给 tap_send 复用
                return True, got
            log.warning("第%d次灌字未落地：期望 %r 实际 %r", i + 1, text, got)
        return False, self.box_text(actor.snap())

    def tap_send(self, actor, settle=1.2, snap=None):
        """点发送按钮。返回 True/False。

        优先用 type_and_verify 缓存的快照（里面已经有 btn_send），
        缓存没有才去重新 dump。
        """
        s = snap or self._snap or actor.snap()
        btn = s.hit(res=SEND_RES)
        if btn is None:
            s = actor.snap(force=True)
            btn = s.hit(res=SEND_RES)
        if btn is None:
            log.warning("找不到发送按钮（可能没灌进字）")
            return False
        log.info("点发送 %s", btn.bounds)
        actor.hand.tap_node(btn, settle=settle)
        self._snap = None
        return True

    def sent_ok(self, actor, text, timeout=4.0):
        """发送后校验：**只有确认输入框已清空（placeholder 回来）才算成功**。

        🔴 2026-11-03 修复 P0（静默漏发）：
          `box_text()` 在找不到输入框时返回 None，旧写法 `if not got` 把 None
          当成"已清空"→ 页面跳走/被弹窗遮挡/树为空时，消息根本没发出去，
          上层却记「已发送」并写 L2、记 24h 唤醒台账，永不重试。
        三态语义：
          ""   输入框在且已清空 → 成功
          None 找不到输入框，无法确认 → 按**失败**处理（必回优先，下轮重试）
          非空 还有残留文本 → 失败

        🔴 2026-11-04（闭环修复）：把三态结论写进 `self.last_reason`，让上层能区分
          "ok"       确认已清空 = 确实发出去
          "unknown"  找不到输入框 = 无法确认（大概率已发，上层按已发记账防重复发送）
          "residual" 输入框还有字 = **明确没发出去**（上层必须不记账、下轮重试）
        之前上层只当布尔用 → 「输入框还有字=真没发」也被记成已回 = 永久漏回。
        """
        self.last_reason = "unknown"
        time.sleep(0.7)
        got = self.box_text(actor.snap(force=True))
        if got == "":
            self.last_reason = "ok"
            return True
        if got is None:
            # 再给一帧机会：发送瞬间的转场帧常常读不到输入框
            time.sleep(0.8)
            got = self.box_text(actor.snap(force=True))
            if got == "":
                self.last_reason = "ok"
                return True
            if got is None:
                log.warning("发送校验：找不到输入框，无法确认是否发出 → 按未发出处理")
                self.last_reason = "unknown"
                return False
        self.last_reason = "residual"
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.6)
            if self.box_text(actor.snap(force=True)) == "":
                self.last_reason = "ok"
                return True
        return False
