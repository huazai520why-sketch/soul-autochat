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
# 2026-11-22 修复 F11：输入框 placeholder 集中维护。App 改文案后旧的单点字符串
#   `t == PLACEHOLDER` 失效，空框会被当 residual → 重复发送。判「框已清空」改为：
#   框内文本为空 OR 命中已知 placeholder 集合任一（以输入框节点 text 为唯一判据）。
PLACEHOLDERS = (
    PLACEHOLDER,
    "文明聊天，友善交友",        # 兼容去尾波浪号变体
    "文明聊天",                  # 兼容精简文案
    "友善交友",                  # 兼容精简文案
    "文明聊天，友善交友~",        # 全角标点变体
    # 🔴 2026-11-23（RESID-01，P0）：App 改版后新增占位符文案（382 次 residual-取证
    #   日志实锤：box 字段全是这三类，无一条真实残留）。旧白名单只有「文明聊天」系列，
    #   导致「发送成功、框已清空」被误判为 residual → 浪费匹配次数 + 下轮重发。
    "输入新消息",                # 00:35-13:00 段
    "发消息或按住说话",          # 13:16 后 chat 页
    "长按此处说话",              # 13:16 瞬间
)

# 🔴 2026-11-16 13:1x（P0 反转修正, 取证日志实锤）：她热聊/暧昧话题时 App 会在
#   输入框区域显示「对话由AI生成，非Soul立场」AI 免责声明条——box_text 把它
#   读成「输入框残留」→ 消息其实已发出（该会话 159 条/24h 全部落库 st3）→
#   误判 residual → 不记账重发（同话题 6 连发轰炸）+ per-sid 熔断锁死热聊会话 2h。
# 2026-11-19 修复 FLOW-11：扩为多文案元组（覆盖「AI生成」「由AI生成」等常见变体，
#   防 App 改文案后单点字符串失效）；并要求命中 banner 时同时校验框内长度
#   ≤ banner 长度阈值（真残留会远长于 banner），双条件才判「已清空」。
AI_BANNER_TEXTS = ("对话由AI生成", "由AI生成", "AI生成", "AI 免责", "非Soul立场")
# banner 命中时框内允许的最大长度：真免责条只有一两行（≤40 字符），
# 若框内文本远长于此，说明是「她正文里含 banner 字样」的真残留，不能判成功。
AI_BANNER_MAX_LEN = 40


def _ai_banner(t):
    """命中 AI 免责声明条 → 输入框本身已清空（视为发送成功）。

    2026-11-19 修复 FLOW-11：双条件判定——
      ① 文本命中 AI_BANNER_TEXTS 任一子串（兼容多种文案变体）；
      ② 且框内长度 ≤ AI_BANNER_MAX_LEN（真残留会远长于 banner）。
    只满足①不满足②（她正文恰好含 banner 字样）时不判成功，避免漏发。
    """
    t = (t or "").strip()
    if not t:
        return False
    if not any(k in t for k in AI_BANNER_TEXTS):
        return False
    return len(t) <= AI_BANNER_MAX_LEN


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
        """读输入框当前文本。返回 ""（空/命中 placeholder）或非空字符串（残留/已灌字）。
        2026-11-22 修复 F11：判空不再只 `t == PLACEHOLDER` 单点比较，改用 PLACEHOLDERS
        集合 + 框内文本长度为主判据——空串或命中集合内任一 placeholder 均返回 ""，
        App 改文案后不会把空框误判为 residual（重复发送风险）。
        """
        n = Input.box(snap)
        if n is None:
            return None
        t = (n.text or "").strip()
        # 框内已无字 OR 命中已知 placeholder → 视为已清空
        if not t or any(t == ph for ph in PLACEHOLDERS):
            return ""
        return t

    # ---------- 写 ----------
    def _reset(self):
        """u2 掉线时重置连接（下次 self.d 会重新取新连接）。"""
        try:
            self.dev.reset_u2()
        except Exception:
            pass
        self._d = None

    def clear(self):
        """清空输入框。返回 bool：成功（无异常）→ True；两次 clear_text 都抛异常 → False。

        🔴 2026-11-18（F-IN-01 P0）：原来失败只 log.warning 不返回状态，上层完全
          无感知 → type_and_verify 照旧灌字，清空失败时 send_keys 会**追加**到残留上，
          叠加成「残留+开场白」的拼接消息发出去。现在把成败结果返给调用方，由
          type_and_verify fail-closed（清空失败本轮就不发）。
        """
        try:
            self.d.clear_text()
            return True
        except Exception as e:
            # 🔴 2026-11-03 修复 P2：原来只打日志不重连，后续继续用失效连接。
            log.warning("clear_text 异常: %r → 重置 u2 重试", e)
            self._reset()
            try:
                self.d.clear_text()
                return True
            except Exception as e2:
                log.warning("clear_text 重试仍失败: %r", e2)
                return False

    def type_text(self, text, settle=1.0):
        """灌字。返回 True/False（以输入框实际文本为准，不看返回值）。

        🔴 2026-11-23 修复（send_keys OSError(22) 连续失败自愈）：
           u2 的 send_keys 偶发 OSError(22)（Invalid argument，Windows 下
           uiautomator2 与设备 socket 状态不同步），连续失败会让上层
           type_and_verify 重试同样失败 → 该轮整条发送被拖死。
           每次异常都重置 u2 连接 + 退避递增（0.5s/1.0s），避免同一条失效
           连接被反复猛撞；首败立即重试一次（保留原行为），仍败返回 False。
        """
        for _i, _wait in enumerate((0.5, 1.0)):
            try:
                self.d.send_keys(text)
                break
            except Exception as e:
                log.warning("send_keys 异常: %r → 重置 u2，退避 %.1fs 重试", e, _wait)
                self._reset()
                time.sleep(_wait)
                if _i == 0:
                    continue
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
            # 🔴 2026-11-12（F-04）：首轮也必须先清空。原来首轮只 tap 不 clear，
            #   若框内有残留，send_keys 会**追加**而非替换，校验用子串判定仍通过 →
            #   发出「残留+新文本」的拼接消息。现在每轮（含首轮）都先 clear。
            actor.hand.tap_node(n, settle=0.7)
            clear_ok = self.clear()         # 🔴 F-IN-01：接收清空结果，不再无感知
            if clear_ok is False:
                # 🔴 2026-11-18（F-IN-01 P0）：清空失败时灌字会**追加**到残留上 →
                #   发出「残留+新文本」拼接消息。fail-closed：本轮**跳过 send_keys、
                #   不发送**，直接进下一次 tries 重试（下一轮重新点框+清空）。
                log.warning("第%d次：清空输入框失败 → 本轮不发送，跳过灌字（fail-closed）",
                            i + 1)
                continue
            time.sleep(0.3)
            self.type_text(text, settle=0.9)
            snap2 = actor.snap()
            got = self.box_text(snap2)
            # 🔴 2026-11-18（F-IN-01 P0）：校验**等值优先**，子串仅作宽松兜底且只在
            #   clear() 明确返回 True（确认清空成功、无残留）时才允许 —— 这样
            #   「清空失败 + 残留」不会被 `text in got` 误判为通过。
            if got is not None and got == text.strip():
                self._snap = snap2          # 给 tap_send 复用
                try:
                    from core.device import action_gen as _ag
                    self._snap_gen = _ag()
                except Exception:
                    self._snap_gen = None
                return True, got
            if clear_ok and got and text.strip() in got:
                # 2026-11-19 修复 FLOW-12：子串兜底前再读一次框做残留确认。
                #   clear_ok=True 只代表 clear_text 没抛异常，不代表框真空了
                #   （可能静默失败）；此时 `text in got` 命中可能是「残留+新文本」
                #   拼接。现在去掉 text 后剩余部分必须为空/纯空白才放行，
                #   否则视为残留未清、本轮判失败（fail-closed）。
                _expect = text.strip()
                _rest = got.replace(_expect, "", 1).strip()
                if not _rest:
                    log.warning("第%d次灌字等值不匹配但为已确认清空后的子串命中（宽松兜底通过）："
                                "期望 %r 实际 %r", i + 1, text, got)
                    self._snap = snap2          # 给 tap_send 复用
                    try:
                        from core.device import action_gen as _ag
                        self._snap_gen = _ag()
                    except Exception:
                        self._snap_gen = None
                    return True, got
                log.warning("第%d次子串兜底拒绝（去掉期望文本后仍有残留 %r，疑似清空静默失败）："
                            "期望 %r 实际 %r", i + 1, _rest, text, got)
            log.warning("第%d次灌字未落地：期望 %r 实际 %r", i + 1, text, got)
        # 🔴 2026-11-14（F09）：失败返回读真实当前帧，避免复用 TTL 内旧帧误判。
        # 🔴 2026-11-18（F-IN-01）：若全因清空失败而跳过发送，同样走到这里返回
        #   (False, None)，上层按「明确没发」不记账、下轮重试。
        return False, self.box_text(actor.snap(force=True))

    def tap_send(self, actor, settle=1.2, snap=None):
        """点发送按钮。返回 True/False。

        优先用 type_and_verify 缓存的快照（里面已经有 btn_send），
        缓存没有才去重新 dump。
        🔴 2026-11-10（演示实弹发现）：btn_send 是灌字后才由 App 渲染出来的，
          设备负载高时渲染会晚于两次 dump（缓存+force 重找全空）→ 误判失败。
          实弹样本：13:17:16 等一束光 / 13:18:01 幸福约定，两次 dump 均无按钮。
          修复：找不到时等 0.8s 第三次 dump（给渲染一帧机会）；仍失败则读
          输入框区分「字还在（渲染慢）」与「字被吃（明确失败）」并打进日志。
        """
        s = snap or self._snap or actor.snap()
        if s is self._snap and s is not None:
            # 🔴 2026-11-15 上午复查（D7，P2）：缓存帧 freshness 守卫——灌字后若
            #   发生过其它动作（代数变化），缓存帧已过期，照旧点击=拿旧坐标乱戳。
            try:
                from core.device import action_gen as _ag
                if _ag() != getattr(self, "_snap_gen", None):
                    log.info("tap_send：灌字后动作代数变化 → 弃用缓存帧重取")
                    s = actor.snap(force=True)
            except Exception:
                pass
        btn = s.hit(res=SEND_RES)
        if btn is None:
            s = actor.snap(force=True)
            btn = s.hit(res=SEND_RES)
        if btn is None:
            time.sleep(0.8)
            s = actor.snap(force=True)
            btn = s.hit(res=SEND_RES)
        if btn is None:
            got = self.box_text(s)
            log.warning("找不到发送按钮（三次 dump 均无；输入框文本=%r）", got)
            return False
        log.info("点发送 %s", btn.bounds)
        self._last_btn = str(btn.bounds)   # 2026-11-16（取证）：residual 诊断用
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
          None 找不到输入框，无法确认 → **大概率已发，上层按已发记账防重复**
                （🔴 2026-11-15（P2-2）注释修正：原写「按失败处理」，但实现
                 实际返回 unknown，且 flow/pendingq/wake 调用方把 unknown 当
                 「已发出」记账 —— 注释与代码矛盾。此处改为与实现一致：unknown
                 = 大概率已发，上层按已发记账；若上层要防「未发却记账」，应在
                 上层用库落库校验（见 brain_flow P0-B3），不在本函数改语义。）
          非空 还有残留文本 → 失败

        🔴 2026-11-04（闭环修复）：把三态结论写进 `self.last_reason`，让上层能区分
          "ok"       确认已清空 = 确实发出去
          "unknown"  找不到输入框 = 无法确认（大概率已发，上层按已发记账防重复发送）
          "residual" 输入框还有字 = **明确没发出去**（上层必须不记账、下轮重试）
        之前上层只当布尔用 → 「输入框还有字=真没发」也被记成已回 = 永久漏回。
        """
        self.last_reason = "unknown"
        self.last_diag = None
        time.sleep(0.7)
        got = self.box_text(actor.snap(force=True))
        if _ai_banner(got):
            got = ""    # AI 声明条 ≠ 输入框残留（2026-11-16 实证）
        if got == "":
            self.last_reason = "ok"
            return True
        if got is None:
            # 再给一帧机会：发送瞬间的转场帧常常读不到输入框
            time.sleep(0.8)
            got = self.box_text(actor.snap(force=True))
            if _ai_banner(got):
                got = ""
            if got == "":
                self.last_reason = "ok"
                return True
            if got is None:
                # 2026-11-23 注释修正：语义是 unknown（找不到输入框=大概率已发，
                #   上层按已发记账防重复），原日志「按未发出处理」与实际语义矛盾。
                log.warning("发送校验：找不到输入框，无法确认是否发出 → unknown（大概率已发，上层按已发记账）")
                self.last_reason = "unknown"
                return False
        self.last_reason = "residual"
        t0 = time.time()
        _last_seen = "residual"   # 2026-11-15（D6）：记录轮询最后一次观测
        while time.time() - t0 < timeout:
            time.sleep(0.6)
            _got = self.box_text(actor.snap(force=True))
            if _ai_banner(_got):
                _got = ""
            if _got == "":
                self.last_reason = "ok"
                return True
            if _got is None:
                _last_seen = None   # 输入框消失=无法确认，别把 unknown 升级成 residual
        if _last_seen is None:
            self.last_reason = "unknown"
            log.warning("发送校验：超时时输入框已不在 → unknown（按已发记账防重复）")
            return False
        # 🔴 2026-11-16（取证）：residual=明确没发出，但为什么没发出？
        #   记录框内容/最近点过的发送按钮，供上层 residual 分支打出。
        self.last_diag = {"box": repr(_got)[:80],
                          "btn": getattr(self, "_last_btn", "?"),
                          "expect": repr((text or ""))[:40]}
        log.warning("[residual-取证] %s", self.last_diag)
        return False
