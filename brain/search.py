# -*- coding: utf-8 -*-
"""搜索定位：用一句话 / 一个昵称找到会话并进去。

为什么需要它（用户 2026-11-02）：
  「已读未回」的会话**没有红点**，在 1100+ 条的列表里靠滚动找不现实。
  Soul 搜索框能直接搜聊天记录（placeholder 明写「搜索备注、昵称或者聊天记录」），
  实测一次命中并可直接点进去。

实测（96691646 号，2026-11-02）：
  - 搜索图标 res=c_ct_chat_fragment_search
  - 搜索框 cls=EditText，u2 send_keys 支持中文（**灌字前必须 clear_text**，
    否则会粘成「关键词关键词」导致搜不到）
  - 结果行 = 宽 900、高 ~190 的可点击 ViewGroup
  - 点结果行 → 直接进 ConversationActivity
"""
import threading
import time

from core.log import get_logger

log = get_logger("brain.search")

SEARCH_RES = "c_ct_chat_fragment_search"

# 🔴🔴 2026-11-08 02:26（P0 根因实锤，修「找不到搜索入口 63 次 / 没进搜索页 30 次」）
#
#   现象：会话列表页明明有搜索按钮（res=c_ct_chat_fragment_search, bounds=736,62~796,122,
#         clickable=true），但**点了完全没反应** —— 页面节点数只从 123 变 121，
#         Activity 仍是 MainActivity，EditText 恒为 None。
#         连 `adb shell input tap 766 92` 都不行，说明不是 u2 的问题，是**点击被吃了**。
#
#   根因：屏幕上盖着一个**全屏弹窗** `layout_love_bg`（bounds=[32,100][868,733]），
#         右上角有 `iv_love_close`（content-desc=关闭弹窗, bounds=784,112~856,184）。
#         弹窗从 y=100 开始，把顶栏按钮（y=62~122）整个罩住 —— 只有 y<100 那条窄缝能点到，
#         而按钮中心点 y=92 恰好…… 在缝里但弹窗的触摸层仍然抢走了事件。
#         实测：**关掉弹窗后，同一个按钮一次就点进搜索页了**（in_search_page=True）。
#
#   影响面：这不是偶发。Soul 的这类运营弹窗（love_bg / 匹配成功 / 活动推广）
#         是**周期性自动弹出的**，一旦弹出，所有依赖顶栏的操作全部失效：
#         搜索、群组、排序 —— 也就是「已读未回」整条链路 100% 瘫痪。
#         日志里 63 次「找不到搜索入口」+ 30 次「没进搜索页」+ 95 次搜索超时，
#         绝大部分就是它造成的（每次白烧 20~45s，一天几百次）。
#
#   修法：把「弹窗」当成**导航前置条件**，每次找搜索入口前先扫一遍并关掉。
#         只关"确定的弹窗"，绝不乱点（列表里也有 close 类的业务按钮，不能误触）。
POPUP_CLOSE_RIDS = (
    "iv_love_close",          # 实测：恋爱/活动弹窗关闭键
    "iv_close",               # 通用关闭
    "iv_dialog_close",
    "close_iv",
)
POPUP_CLOSE_DESCS = ("关闭弹窗", "关闭", "关闭广告")
# 弹窗容器特征（有其中之一才算弹窗，防止把普通页面当弹窗）
POPUP_CONTAINER_RIDS = ("layout_love_bg", "dialogContainer", "layout_dialog")


def _popup_nodes(snap):
    """返回 (是否检测到弹窗, 可点的关闭节点)。只认确定的弹窗。"""
    has_container = False
    for rid in POPUP_CONTAINER_RIDS:
        try:
            if snap.find_one(res=rid) is not None:
                has_container = True
                break
        except Exception:
            pass
    n = None
    for rid in POPUP_CLOSE_RIDS:
        try:
            n = snap.find_one(res=rid)
        except Exception:
            n = None
        if n is not None:
            break
    if n is None:
        for d in POPUP_CLOSE_DESCS:
            try:
                n = snap.find_one(desc=d)
            except Exception:
                n = None
            if n is not None:
                break
    # 有关闭键但没容器 → 也可能是个小弹层，仍然认（关闭键本身就够specific）
    return (has_container or n is not None), n


def dismiss_popups(actor, tries=3):
    """关掉挡住顶栏的弹窗。返回关掉的数量。

    🔴 2026-11-08：这是「搜索永远打不开」的根因修复，见 POPUP_CLOSE_RIDS 上面的长注释。
    宁可多扫两遍（每次 ~1.5s），也不能让一个弹窗把整条已读未回链路堵死。
    """
    closed = 0
    for _ in range(tries):
        try:
            snap = actor.snap(force=True)
        except Exception:
            break
        found, n = _popup_nodes(snap)
        if not found:
            break
        if n is None:
            # 有弹窗但找不到关闭键 → 用 back 试试（RN 弹层通常能被 back 关掉）
            log.info("[popup] 检测到弹窗但没有关闭键 → 按 back")
            try:
                # 2026-11-10：收口到 Hand.back 护栏版（弹窗会消费 back）
                actor.hand.back(settle=0.0, force=True)
            except Exception:
                pass
            time.sleep(1.2)
            closed += 1
            continue
        log.info("[popup] 检测到弹窗 → 点关闭 %r %r", n.text or "", n.bounds)
        try:
            actor.hand.tap_node(n, settle=1.5)
        except Exception as e:
            log.warning("[popup] 点关闭异常: %r", e)
            break
        closed += 1
        time.sleep(0.8)
    if closed:
        log.info("[popup] 共关闭 %d 个弹窗", closed)
    return closed

# 最近一次 search() 的结局语义，供调用方决定冷却强度：
#   "ok"       -> 有结果
#   "notfound" -> 页面明确显示「未找到相关结果」（真搜不到，长冷却）
#   "timeout"  -> 等满窗口仍无结果（接口慢/设备卡，短冷却重试，绝不能当搜不到）
LAST_REASON = "timeout"

# 🔴 2026-11-04（提速·熔断）：搜索页偶尔读不到任何结果行（a11y 树空/风控页），
#   代码无从区分「还在加载」和「通道坏了」，只能等满 max_wait=30s。
#   实测 19:32~19:34 连续 3 次「等满 30s 仍无结果」，一轮 6 个候选 = 白烧 250s。
#   max_wait 不能降（注释里有实测：正常出结果要 11.0~14.7s），
#   所以改成**连续失败才熔断**：连续 3 次超时 → 暂停 20 分钟；
#   任一次出结果/明确未找到 → 计数清零（说明通道是通的）。
_BREAKER = {"fails": 0, "until": 0.0}
BREAKER_N = 3          # 连续几次超时后熔断
BREAKER_MIN = 20.0     # 熔断时长（分钟）


def in_search_page(snap):
    """当前是否已经在搜索页（顶栏输入框 + 「取消」）。

    必须两条同时满足：会话页也有 EditText，但它在底部（y>1000）；
    搜索页的输入框在顶栏（实测 b=(124,83,731,138)），右侧有「取消」(790,67,862,155)。
    """
    box = snap.find_one(cls="EditText")
    if box is None or box.bounds[1] > 300:
        return False
    return (snap.find_one(desc="取消") is not None
            or snap.find_one(text="取消") is not None)


def _scroll_top(actor, rounds=5, preempt=None):
    """把会话列表滚回顶部。搜索框在列表**顶部**，列表停在中间/底部时找不到入口。

    🔴 2026-11-04（修「找不到搜索入口」）：pendingq.find_row 翻屏未命中后
      不回顶（上午为省 24s/人 删掉了回顶）→ 列表停在中间 → open_search 找不到
      顶部的搜索框 → 恒失败 → 该候选每轮白烧 40~50s 且永远回不了。
      这里只在「找不到入口」时才滚（失败路径 2~4s），不拖累正常路径。
    与 pendingq._swipe_once 同口径：duration 是**秒** + 线程 join 兜底。
    """
    try:
        d = actor.dev.u2()
    except Exception:
        return False
    for _ in range(max(1, rounds)):
        if preempt and preempt():
            return False
        box = {"ok": False}

        def _job():
            try:
                d.swipe(450, 400, 450, 1100, duration=0.35)   # 秒！手指下滑 = 看更上面
                box["ok"] = True
            except Exception:
                box["ok"] = False

        t = threading.Thread(target=_job, name="stswipe", daemon=True)
        t.start()
        t.join(6.0)
        if t.is_alive() or not box["ok"]:
            return False
        time.sleep(0.25)
    return True


def _find_search_entry(snap):
    """在会话列表页找「搜索入口」节点。找不到返回 None。

    🔴🔴 2026-11-08 12:36（实测抓到的真根因，修「找不到搜索入口 125 次」）

      改前只认三种：`res=c_ct_chat_fragment_search` / `desc=搜索` / `text=搜索`。
      现场 dump 实测（900x1600，Soul 6.41.0）会话列表顶部的搜索控件是：

          b=(24,152,784,224)  cls=android.widget.EditText
          rid=cn.soulapp.android:id/commonViewEt
          text='搜索备注、昵称或者聊天记录'     ← 注意是长句，不是「搜索」两个字

      ⇒ 上面三个条件**一个都匹配不上**，于是每轮都报「找不到搜索入口」，
        然后空滚 5 次 ≈13s 再失败。这不是偶发，是**必然失败**。

      现在按「命中优先级」多认几种形态（Soul 不同版本/不同 tab 下控件不一样）：
        ① 老的 resource-id（保留兼容）
        ② EditText 且 text 里含「搜索」—— 会话列表页顶栏的搜索框就是这个
        ③ text/desc 里含「搜索」的任意可点节点
        ④ 兜底：顶栏(y<=300)且 text 含「搜索」的 EditText
      都找不到才返回 None。

      为什么用「含」而不是「等于」：Soul 把 placeholder 写成了一句长提示，
      版本一换文案就变（「搜索备注、昵称或者聊天记录」/「搜索」/…），
      用「等于」等于把每次改版都变成一次线上故障。
    """
    # ① 老 resource-id
    n = snap.hit(res=SEARCH_RES)
    if n is not None:
        return n
    # ② desc/text 恰好是「搜索」
    n = snap.hit(desc="搜索") or snap.hit(text="搜索")
    if n is not None:
        return n
    # ③ 顶栏 EditText 且提示语含「搜索」（实测命中的就是这个）
    for node in snap.nodes:
        try:
            b = node.bounds
        except Exception:
            continue
        if b[1] > 300:                      # 只要顶栏的，排除会话页底部输入框
            continue
        txt = (node.text or "")
        if "搜索" in txt and (node.cls or "").endswith("EditText"):
            return node
    # ④ 任意含「搜索」的节点（desc 优先，再 text）
    for node in snap.nodes:
        d = (node.desc or "")
        t = (node.text or "")
        if "搜索" in d or "搜索" in t:
            try:
                if node.bounds[1] <= 300:
                    return node
            except Exception:
                continue
    return None


def open_search(actor, preempt=None):
    """从会话列表打开搜索页。返回 True/False。"""
    global LAST_REASON
    if preempt and preempt():
        LAST_REASON = "preempted"
        return False
    snap = actor.snap()
    if in_search_page(snap):
        log.info("已在搜索页（顶栏输入框 + 取消），直接复用，不找放大镜")
        return True
    # 🔴 2026-11-08（P0 根因）：先关弹窗！
    #   实测 layout_love_bg 从 y=100 盖到 y=733，把顶栏搜索键（y=62~122）整个罩住，
    #   点击被弹窗触摸层吃掉 → 无论点多少次都进不去搜索页。
    #   日志实证：63 次「找不到搜索入口」+ 30 次「没进搜索页」+ 95 次搜索超时主要是它。
    #   关掉弹窗后同一个按钮**一次就进得去**（已实测验证）。
    #   放在最前面（连"当前屏有没有入口"都没判之前），因为弹窗可能盖住任何页面。
    try:
        dismiss_popups(actor)
        snap = actor.snap(force=True)
    except Exception as e:
        log.warning("关弹窗异常（继续尝试搜索）: %r", e)
    if in_search_page(snap):
        return True
    if preempt and preempt():
        LAST_REASON = "preempted"
        return False
    n = _find_search_entry(snap)
    if n is None:
        # 🔴 2026-11-02：重启后第一轮落点常在「广场 / 会话内」，只在当前屏找必然失败
        #    （现网实测连续 6 次 return False，5 个待回候选全被跳过 = 不回她）。
        #    先强行导航回聊天列表，再找一次。
        from brain import nav
        log.info("当前屏没有搜索入口，先回聊天列表再找")
        try:
            snap, _pg = nav.to_chatlist(actor)
        except Exception as e:
            log.warning("回聊天列表异常: %r", e)
            snap = actor.snap(force=True)
            _pg = None
        # 🔴 2026-11-08（P0 修「找不到搜索入口 125 次」真正原因）：
        #   改前：这里拿到的 `_pg` **被完全丢弃** —— nav 返回 unknown 也当成功，
        #   接着往下走 `_scroll_top()`，页面根本不是会话列表，滑动手势无列表可滑，
        #   空滑 5 次 ≈13s（见 _scroll_top 的 rounds 默认 5 × join 6s + sleep 0.25），
        #   再叠加后面 3 轮 × 1.5s 等待，一次白烧 14~16s 才报「找不到搜索入口」。
        #   日志实证：125 次「找不到搜索入口」里 **69 次**前 6 行内有
        #   `[nav] unknown 第 1 次 → back`；典型 11-08 00:20:14 报「当前屏没有搜索入口」
        #   → 00:20:17 nav unknown → 00:20:20「回列表后仍没入口」→ 00:20:34 失败，共 20s。
        #   现在：nav 没真的回到 chatlist 就立刻认栽返回，不再空滑空等。
        if _pg is not None and _pg != "chatlist":
            log.warning("open_search: 回列表失败（pg=%s，不是 chatlist）→ 不再空滑空等", _pg)
            log.warning("找不到搜索入口")
            return False
        if preempt and preempt():
            LAST_REASON = "preempted"
            return False
        n = _find_search_entry(snap)
    if n is None:
        # 🔴 2026-11-04（修「找不到搜索入口」58% 失败）：见 _scroll_top 注释。
        log.info("回列表后仍没入口（列表可能停在中间）→ 滚回顶部再找")
        if _scroll_top(actor, preempt=preempt):
            try:
                snap = actor.snap(force=True)
            except Exception:
                snap = None
            if snap is not None:
                if preempt and preempt():
                    LAST_REASON = "preempted"
                    return False
                n = _find_search_entry(snap)
    if n is None and preempt and preempt():
        LAST_REASON = "preempted"
        return False
    if n is None:
        log.warning("找不到搜索入口")
        return False
    actor.hand.tap_node(n, settle=2.2)
    if preempt and preempt():
        LAST_REASON = "preempted"
        return False
    # 搜索页首帧慢（实测设备卡时要 2~4s），多等两轮再判定
    for _ in range(3):
        if preempt and preempt():
            LAST_REASON = "preempted"
            return False
        s = actor.snap(force=True)
        # 🔴 2026-11-03 修复 P1：判据必须排除「会话页底部输入框」。
        #    原来只判"有任意 EditText"→ 会话页也满足，关键词会灌进草稿框。
        #    但「取消」不是所有版本都有（实测严格版会把真搜索页也拒掉 →
        #    唤醒直接报「打不开搜索页」），所以退一步：**顶栏输入框**（y<=300）即可。
        box = s.find_one(cls="EditText")
        if in_search_page(s) or (box is not None and box.bounds[1] <= 300):
            return True
        time.sleep(1.5)
    log.warning("没进搜索页（顶栏输入框未出现）")
    return False


# 搜索结果里这些不是会话行（实测 2026-11-02）：
#   「搜索 XXX，探索更多话题、派对、群组等」= 更多搜索的入口，点进去是话题页不是会话
NOT_ROW_KEYS = ("探索更多话题", "更多搜索", "问题反馈", "搜索历史", "猜你想搜")


def results(actor, snap=None):
    """搜索结果里的**会话行**（大块可点击容器，排除「更多搜索」这类入口）。

    snap 传入则复用这一帧（重试循环里每次 dump 3.5~6s，不能白拉）。
    """
    s = snap if snap is not None else actor.snap()
    out = []
    for n in s.nodes:
        if not (n.clickable and n.visible):
            continue
        label = (n.label or "") + " " + (n.desc or "")
        if any(k in label for k in NOT_ROW_KEYS):
            continue
        if (180 < n.bounds[1] < 900
                and (n.bounds[2] - n.bounds[0]) > 500
                and (n.bounds[3] - n.bounds[1]) > 90):
            out.append(n)
    out.sort(key=lambda n: n.bounds[1])
    return out


def _wait_preempt(seconds, preempt):
    """Sleep in small slices so a new-message signal can interrupt search waits."""
    until = time.time() + max(0.0, float(seconds or 0))
    while time.time() < until:
        if preempt and preempt():
            return True
        time.sleep(min(0.25, max(0.01, until - time.time())))
    return False


def search(actor, dev, kw, wait=5.0, max_wait=30.0, preempt=None):
    """在搜索页灌关键词并**等结果真正出来**。返回命中的结果行数。

    🔴 关键（2026-11-02 实测）：灌字后页面会先显示一个**转圈的加载图标**，
      这时 UI 树里只有「取消 / 关键词」两个文本、没有任何结果行 ——
      原来等 2s 就判定「搜索无结果」，导致已读未回 3/3 全部误跳过。

    节奏：灌字后仍**先固定等 5 秒**（省两次 dump），但**总预算必须是 30 秒**。

    🔴 2026-11-02 10:20 现网日志实测（brain.search.log）：本接口出结果要
      11.0 / 11.2 / 11.4 / 11.5 / 12.5 / 12.7 / 14.3 / **14.7** 秒，
      而每次 dump 自身还要 2~6 秒。原来 5+10=15 秒的总预算等于把刀架在脖子上：
      14.7s 那次只差 0.3 秒就判失败 → 表现就是「灌字成功，还没出结果就退出了」。
      放宽到 30 秒后，正常命中仍在 11~15 秒返回，只有真慢才走满窗口。
    """
    global LAST_REASON
    LAST_REASON = "timeout"
    if time.time() < _BREAKER["until"]:
        # 🔴🔴 2026-11-08 13:1x（让日志说真话 —— reply-diagnostician 全量取证发现）
        #
        #   改前：这里直接 `return 0`，但 `LAST_REASON` 还停在函数开头设的
        #        "timeout"。上层 `pendingq.py` 读 `getattr(S,"LAST_REASON")` 记台账，
        #        于是**熔断早退被记成「搜索超时」**。
        #   实测代价（_team/reply_diag.md）：472 条 timeout 台账里
        #        **只有 207 条是真等满 30s**，另外 **265 条是熔断早退**。
        #        ⇒ 所有基于台账的调优（比如"要不要加大 max_wait"）都会误判方向。
        #        实测数据显示：真超时的 58 次里 57 次关键词**在会话里真实存在**，
        #        说明超时根本不是关键词问题；而熔断早退跟关键词毫无关系。
        #
        #   修法：熔断早退单独记 "breaker"，与真超时区分开。语义也正确 ——
        #        它压根没去搜，不该占用「超时」这个原因。
        LAST_REASON = "breaker"
        log.info("搜索通道熔断中（还剩 %.0f 分钟）→ 本次不搜，留给翻屏",
                 (_BREAKER["until"] - time.time()) / 60.0)
        return 0
    s = actor.snap()
    box = s.find_one(cls="EditText")
    if box is None:
        log.warning("搜索页没有输入框")
        return 0
    actor.hand.tap_node(box, settle=0.5)
    from core.device import note_action
    note_action()              # A2：下面全是绕过 Hand 的裸 u2 调用
    try:
        dev.u2().clear_text()
    except Exception as e:
        # 🔴 2026-11-03 修复 P1：清空失败还继续灌字 → 关键词粘成「kwkw」，
        #    必然搜不到；更糟的是会被上层当成"搜不到"记 12h 台账。
        log.warning("clear_text 异常: %r → 重置 u2 重试", e)
        try:
            dev.reset_u2()
            time.sleep(0.8)
            dev.u2().clear_text()
        except Exception as e2:
            # 🔴 2026-11-10（实测事故：clear_text 失败把 App 顶到桌面）
            #   23:13 现场探测：连搜第二个词时 AdbKeyboard 广播报
            #     Attempt to read from field ExtractedText.text on a null object reference
            #   （输入框已失焦）→ 紧接着整页变成桌面/游戏中心，Soul 被切到后台，
            #   那之后所有候选全部落空。AdbKeyboard 是靠广播改文本的，
            #   一旦输入法被换掉/焦点丢失就整条链路失效。
            #   兜底：重新点输入框拿回焦点 → 用 KEYCODE_DEL 逐字删（不依赖广播）。
            log.warning("clear_text 重试仍失败: %r → 改用「焦点 + DEL 键」兜底清空", e2)
            try:
                _b2 = actor.snap(force=True).find_one(cls="EditText")
                if _b2 is not None:
                    actor.hand.tap_node(_b2, settle=0.4)
                for _i in range(40):
                    dev.u2().press("KEYCODE_DEL")
                time.sleep(0.3)
                log.info("DEL 键兜底清空完成（40 次）")
            except Exception as e3:
                log.warning("DEL 键兜底也失败: %r → 放弃本次搜索", e3)
                LAST_REASON = "timeout"
                return 0
    time.sleep(0.3)
    try:
        dev.u2().send_keys(kw)
    except Exception as e:
        log.warning("灌关键词异常: %r", e)
        LAST_REASON = "timeout"
        return 0

    t0 = time.time()
    if _wait_preempt(wait, preempt):
        LAST_REASON = "preempted"
        log.info("搜索等待中检测到新消息 → 提前结束搜索，优先新消息")
        return -1
    while time.time() - t0 < max_wait:
        if preempt and preempt():
            LAST_REASON = "preempted"
            log.info("搜索轮询中检测到新消息 → 提前结束搜索，优先新消息")
            return -1
        # 🔴 2026-11-08（A2 帧复用的必要例外）：这里是**等异步加载**的轮询，
        #    屏幕会自己变（转圈 → 出结果），中间**没有任何动作**，
        #    所以动作代数守卫抓不到。必须 force 拿真帧，否则会一直复读
        #    灌字前那一帧，永远看不到结果 → 误判 timeout。
        snap = actor.snap(force=True)
        texts = " ".join(snap.texts())
        # 🔴 用户 2026-11-02 口径：出现「未找到相关结果」就放弃，不要再点任何东西。
        #    必须先判断这个再看结果行 —— 因为「未找到」页面里还有一行
        #    「搜索 XXX，探索更多话题、派对、群组等」，长得像结果行，点进去是话题页。
        # 只用完整短语：宽泛的「未找到」会误伤结果行正文（有人的消息里就带这三个字）
        if "未找到相关结果" in texts:
            # 🔴 2026-11-04（必回闭环）：**二次确认**再加一次看屏。
            #   实测 01:56~02:02 有一批搜索只用了 5.3s 就判「未找到」并罚 12 小时
            #   冷却（正常出结果是 5.7~6.3s）—— 灌字后第一帧很可能读到**上一轮**
            #   的「未找到」残留或转场帧。误判一次 = 那个人 12 小时没人回。
            #   多看一帧（0.2s dump）成本极低，能挡掉这类误判。
            time.sleep(1.5)
            _snap2 = actor.snap(force=True)
            if "未找到相关结果" not in " ".join(_snap2.texts()):
                log.info("首帧读到「未找到」但二次确认已消失（残留/转场）→ 继续等结果")
                continue
            LAST_REASON = "notfound"
            _BREAKER["fails"] = 0        # 有明确响应 = 通道正常
            _BREAKER["until"] = 0.0
            log.info("搜索 %r -> 未找到相关结果，放弃（%.1fs，已二次确认）",
                     kw, time.time() - t0)
            return 0
        rs = results(actor, snap=snap)
        if rs:
            LAST_REASON = "ok"
            _BREAKER["fails"] = 0
            _BREAKER["until"] = 0.0
            log.info("搜索 %r -> %d 条结果（%.1fs）", kw, len(rs), time.time() - t0)
            return len(rs)
        if _wait_preempt(1.2, preempt):
            LAST_REASON = "preempted"
            log.info("搜索结果轮询间隔检测到新消息 → 提前结束搜索，优先新消息")
            return -1

    LAST_REASON = "timeout"
    log.warning("搜索 %r -> 等满 %.0fs 仍无结果（超时，不等于未找到）", kw, max_wait)
    _BREAKER["fails"] += 1
    if _BREAKER["fails"] >= BREAKER_N:
        _BREAKER["until"] = time.time() + BREAKER_MIN * 60.0
        log.warning("搜索连续 %d 次超时 → 熔断 %.0f 分钟（翻屏照常，红点路径不受影响）",
                    _BREAKER["fails"], BREAKER_MIN)
    return 0


def enter_first(actor, tries=3, timeout=5.0, skip=0):
    """点搜索结果进会话。返回 (snap, page)。

    🔴 2026-11-04（必回闭环修复）：原来**永远只点 rs[0]**（第一条结果）。
      实测「那不知道」搜出 2 条、「打个招呼 后面靠聊出来的」搜出 3 条，
      目标人不在第一条 → 进错会话 → 身份校验必然失败 → 2 分钟后重试
      **还是点第一条** → 同一个会话连续失败 8 次、永远回不了还白烧时间。
      ⇒ 新增 `skip`：调用方按「该会话已失败几次」依次往后点第 2、3 条结果，
      多结果才有机会点中目标。skip 为主，tries 是「同一条结果点不动」的重试。

    🔴 2026-11-03 用户实测口径：
       「点了结果行之后，继续再点一次结果行就进入对话页了；
         但不是每次都这样，需要多次看屏确认。」
    ⇒ 原来「点一次 + wait_page(6s) → 没进就判 no_result」的写法是错的：
      点在结果行上有时只给了选中/涟漪反馈，没触发跳转；再点一次才进去。
    现在的做法（每一步都重新看屏，不靠固定 sleep 猜）：
       ① force 取树判页 → 已是 chat 就直接返回（可能上一次点已生效）
       ② 落到个人主页/话题页 → back 回来再看
       ③ 重新定位结果行（坐标以当前帧为准）→ 点 → wait_page 等转场
       ④ 没进就回到 ①，最多 tries 次；每次失败都打日志，便于事后判次数
    """
    from eyes.page import detect as _det

    snap = actor.snap(force=True)
    pg = _det(snap)
    for i in range(tries):
        if pg == "chat":
            if i:
                log.info("第 %d 次点击后进入会话", i)
            return snap, "chat"

        # 被弹到别的页面（个人主页 / 话题页 / 搜索详情）
        if pg not in ("chatlist", "unknown", "search", "chat"):
            log.info("点结果后落到 %s → 返回再试", pg)
            actor.hand.back(settle=1.2)
            snap = actor.snap(force=True)
            pg = _det(snap)
            if pg == "chat":
                return snap, "chat"

        rs = results(actor, snap=snap)
        if not rs:
            # 结果行消失有两种可能：正在转场进 chat / 真的没结果
            snap2, pg2 = actor.wait_page(("chat",), timeout=2.5)
            if pg2 == "chat":
                return snap2, "chat"
            log.warning("搜索页已无结果行（page=%s）", pg2)
            return snap2, pg2

        idx = min(max(0, int(skip or 0)), len(rs) - 1)
        if idx:
            log.info("搜索结果 %d 条 → 跳过前 %d 条，点第 %d 条 %s",
                     len(rs), idx, idx + 1, rs[idx].bounds)
        else:
            log.info("点搜索结果(第 %d/%d 次) %s", i + 1, tries, rs[idx].bounds)
        actor.hand.tap_node(rs[idx], settle=1.6)
        snap, pg = actor.wait_page(("chat",), timeout=timeout)
        if pg == "chat":
            return snap, "chat"
        log.info("第 %d 次点结果后 page=%s → 重新看屏再点", i + 1, pg)

    log.warning("点了 %d 次仍未进入会话（最后一次 page=%s）", tries, pg)
    return snap, pg


def leave(actor, tries=3):
    """从搜索页退回会话列表。**反复确认真的退出去了**。

    🔴 2026-11-02 血泪：只点一次「取消」并假设成功 → 实测有一次没点掉，
       页面永久停在搜索页（RnContainerActivity），detect 一直 unknown，
       daemon 每轮 blocked 空转 400+ 轮、4 小时没回任何消息；
       更糟的是后续灌字全灌进了搜索框（截图里搜索框还留着半句话）。
    """
    from brain import nav
    from eyes.page import detect

    for i in range(tries):
        snap = actor.snap(force=True)
        still = in_search_page(snap) or ("取消" in set(snap.texts()))
        if not still:
            break
        n = snap.hit(text="取消") or snap.hit(desc="取消")
        if n is not None:
            log.info("点「取消」退出搜索（第 %d 次）", i + 1)
            actor.hand.tap_node(n, settle=1.3)
        else:
            log.info("搜索页没有「取消」→ back（第 %d 次）", i + 1)
            actor.hand.back(settle=1.3)
    else:
        log.warning("试了 %d 次仍在搜索页 → 交给 nav 强制恢复", tries)
    return nav.to_chatlist(actor)
