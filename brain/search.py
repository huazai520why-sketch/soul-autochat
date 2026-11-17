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
import re
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


# 🔴 2026-11-17（新版 UI 实测）：搜索框从「聊天」页搬到了「通讯录」页。
#   「聊天」页顶栏现在只有「状态 / 通讯录|聊天 / 群组或好友」，一个搜索控件都没有，
#   上面 _find_search_entry 的四级兜底**必然全落空** —— 这才是
#   「找不到搜索入口」「搜索入口打不开」反复出现、每个候选白烧 40~50s 的真根因。
CONTACTS_TAB = "通讯录"


def _find_entry_via_contacts(actor, snap=None, preempt=None):
    """新版 UI：搜索框在「通讯录」页。切过去再找一次，找不到返回 None。

    实测（900x1600）「通讯录」页顶栏的控件和 11-08 记录完全一致：
        b=(24,152,784,224)  cls=android.widget.EditText
        text='搜索备注、昵称或者聊天记录'   （rid 为空）
    ⇒ 匹配规则一个字都不用改，只是**页面换了一个**。

    只在「当前屏没有入口」时调用：
      · 老版本第一屏就能命中 → 根本不会进来，行为完全不变；
      · 在会话内 / 广场（底部导航被隐藏）→ 找不到「通讯录」节点 → 返回 None，
        继续走原来的「回聊天列表」兜底路径，不会比以前更差。
    """
    global LAST_REASON
    if snap is None:
        try:
            snap = actor.snap()
        except Exception:
            return None
    tab = None
    try:
        tab = snap.hit(text=CONTACTS_TAB) or snap.hit(desc=CONTACTS_TAB)
    except Exception as e:
        log.debug("找「通讯录」Tab 异常: %r", e)
    if tab is None:
        return None
    try:
        actor.hand.tap_node(tab, settle=1.8)
    except Exception as e:
        log.warning("点「通讯录」Tab 失败（继续走回列表兜底）: %r", e)
        return None
    if preempt and preempt():
        LAST_REASON = "preempted"
        return None
    try:
        snap2 = actor.snap(force=True)
    except Exception:
        return None
    n = _find_search_entry(snap2)
    if n is not None:
        log.info("聊天页没有搜索入口（新版 UI）→ 切「通讯录」页找到了")
    return n


def open_search(actor, preempt=None):
    """从会话列表打开搜索页。返回 True/False。"""
    global LAST_REASON
    if preempt and preempt():
        LAST_REASON = "preempted"
        return False
    snap = actor.snap()
    if in_search_page(snap):
        log.info("已在搜索页（顶栏输入框 + 取消），直接复用，不找放大镜")
        _remember_snap(snap)          # 供 enter_suggested 复用，省一次 dump
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
        _remember_snap(snap)
        return True
    if preempt and preempt():
        LAST_REASON = "preempted"
        return False
    n = _find_search_entry(snap)
    if n is None:
        # 🔴 2026-11-17（新版 UI 根因）：先试「通讯录」页再走回列表的老兜底。
        #   聊天页顶栏已无任何搜索控件，回列表/滚顶部再找必然还是空转 14~16s。
        n = _find_entry_via_contacts(actor, snap=snap, preempt=preempt)
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
            _remember_snap(s)         # 供 enter_suggested 复用，省一次 dump
            return True
        time.sleep(1.5)
    log.warning("没进搜索页（顶栏输入框未出现）")
    return False


# 🔴 2026-11-17 09:30（用户拍板：先点「猜你想搜」，命中就免输入）
#
#   现场实测（900x1600，证据图 `_ops/m_searchpage.png`）：搜索页**未输入任何字**的
#   首帧，「猜你想搜」已经直接列出待回候选，并标注「你们聊得很不错,对方在等你聊天」：
#       小孩姐 / 雾漫汀兰 / 后来 / 爱啾啾啾斯坦
#   —— 这些正是已读未回名单里的人，**根本不用输入就能点进去**。
#
#   为什么必须走这条路（§42 根因 B）：只要往搜索框灌任何文字，`send_keys` 和
#   AdbKeyboard 的 `ADB_INPUT_TEXT` 广播**都一样**会让 Soul 整页关闭搜索，退回
#   聊天列表/通讯录 → 后面 max_wait=30s 全在错页面上空等 → timeout →
#   连 3 次熔断 20 分钟。实测连「小孩姐」这种 6 分钟前刚聊过、确定存在的人
#   也照样超时 ⇒ 灌字路径在当前版本**结构性不可用**。
#
#   ⇒ 先在本帧按昵称找可点行，命中直接 tap：**零输入、零搜索、零超时**。
#     找不到才退回原来的灌字搜索（不拖累命中的人）。
SUGGEST_MIN_W = 400          # 行宽下限：整行才够宽，「搜索历史」小标签远小于此
SUGGEST_MIN_H = 56           # 行高下限：排除标签/按钮
SUGGEST_MAX_H = 420          # 行高上限：再高就是「整个区块/整页」了，不是一行
SUGGEST_MAX_UP = 10          # 沿 parent 上溯的层数上限
SUGGEST_SKIP_KEYS = ("搜索历史", "猜你想搜", "取消", "清除", "删除")

# 🔴 2026-11-17（帧复用，让「猜你想搜」的**失败路径零成本**）：
#   `open_search()` 判定「已进搜索页」时手里本来就有一帧（它就是靠这帧判的），
#   而一帧 dump 要 1.5~4.7s。如果这里不接过来、`enter_suggested()` 再抓一次，
#   那么**没进猜你想搜名单的人**每人白白多花 2~5s —— 16 个候选就是 30~80s，
#   正好把命中省下的钱赔回去。
#   ⇒ open_search 成功时把这帧存下来，enter_suggested 直接复用（限 20s 内）。
_LAST_SNAP = {"snap": None, "ts": 0.0}
SNAP_REUSE_SEC = 20.0


def _remember_snap(snap):
    try:
        _LAST_SNAP["snap"] = snap
        _LAST_SNAP["ts"] = time.time()
    except Exception:
        pass


def _recent_snap(max_age=SNAP_REUSE_SEC):
    s = _LAST_SNAP.get("snap")
    if s is None:
        return None
    if time.time() - float(_LAST_SNAP.get("ts") or 0.0) > max_age:
        return None
    return s


def _kw_key(s):
    """关键词归一：去所有空白 + 去首尾标点。

    昵称里常带空格 / 全角标点（「小孩 姐」「后来。」），逐字比对会漏；
    中间标点不动（是昵称本身的一部分）。
    """
    t = re.sub(r"\s+", "", str(s or ""))
    _P = r"[\s，。！？、,.!?~～…\-—_：:；;\"'（）()\[\]【】]+"
    t = re.sub("^" + _P, "", t)
    t = re.sub(_P + "$", "", t)
    return t


def _row_box(node):
    """从文字节点上溯到「整行容器」（400 <= 宽、56 <= 高 <= 420）。

    🔴 必须不要求 clickable：实测（900x1600，11-17 09:27）
       猜你想搜的行容器 `w=900 h=192` 是 **clickable=false**，
       行内可点的只有 头像(116x115) / 昵称文字(118x49) / 私聊(149x67)。
    🔴 必须有高度上限：否则「小标签里的文字」会一路爬到**整页根节点**（900x1600），
       然后把这个页面上任意一个「私聊」按钮配给它 —— 等于瞎点。
    实测参考：猜你想搜行 900x192、搜索历史区块 900x463（后者应被排除）。
    """
    p = getattr(node, "parent", None)
    for _ in range(SUGGEST_MAX_UP):
        if p is None:
            return None
        try:
            b = p.bounds
            h = b[3] - b[1]
            if (b[2] - b[0]) >= SUGGEST_MIN_W and SUGGEST_MIN_H <= h <= SUGGEST_MAX_H:
                return p
        except Exception:
            return None
        p = getattr(p, "parent", None)
    return None


def _chat_button(snap, row):
    """行内「私聊」按钮 —— 唯一明确表示「打开会话」的可点控件。

    为什么不用「头像/昵称」：那两处点下去是**个人主页**，不是会话；
    点进去 page != chat，还得 back 出来，等于白烧 5s 并可能把页面弄乱。
    「私聊」是行尾一个语义明确的按钮（实测 b=(753,1094,821,1140)）。
    同一行内取最靠右的那个（行尾），并按垂直中心是否落在行内来归属行。
    """
    try:
        ry0, ry1 = row.bounds[1], row.bounds[3]
    except Exception:
        return None
    best = None
    for n in snap.nodes:
        try:
            if not (n.clickable and n.visible):
                continue
            txt = (n.text or "") + (n.desc or "")
            if "私聊" not in txt:
                continue
            b = n.bounds
            if not (ry0 <= (b[1] + b[3]) // 2 <= ry1):
                continue
            if best is None or b[0] > best.bounds[0]:
                best = n
        except Exception:
            continue
    return best


def _rows_ready(snap):
    """页面上是否已经渲染出「人」的行（用来区分「还没加载」和「就是没有这个人」）。

    刚进搜索页时实测只有 40 个节点（只有「猜你想搜」标题），名单是**异步加载**的；
    这时立刻判「没命中」会白丢机会。反之若名单已出、只是没有目标人，
    就该立刻返回，绝不能再等 —— 那是每个候选白烧 2~4s。
    """
    cnt = 0
    for nd in snap.nodes:
        try:
            t = (nd.text or "").strip()
        except Exception:
            continue
        if not (2 <= len(t) <= 14):
            continue
        if any(k in t for k in ("搜索", "取消", "猜你想搜", "查看更多", "历史", "私聊")):
            continue
        if _row_box(nd) is not None:
            cnt += 1
            if cnt >= 3:
                return True
    return False


def _has_suggest_section(snap):
    """本帧有没有「猜你想搜」这个区块。

    没有就**立刻返回**，一秒都不等：老版本 UI / 账号被风控时本来就没有这块，
    干等等于给每个候选白加 3~4s。
    """
    for nd in snap.nodes:
        try:
            if "猜你想搜" in ((nd.text or "") + (nd.desc or "")):
                return True
        except Exception:
            continue
    return False


_SUG_MISS_LOGGED = {"n": 0}


def find_suggested(snap, kws):
    """在搜索页首帧（未输入）里按关键词找「猜你想搜」里的人。

    返回 (chat_btn, kw, row_label)；没命中返回 (None, None, "")。

    匹配口径（**必须靠 parent 上溯**，不能只看可点节点自己的 text）：
      · 行容器自己**没有文字**，昵称在子 TextView 里，且行容器不可点；
      · 「搜索历史」的小标签自己也带文字，但不是会话行。
    ⇒ 找「text/desc 含关键词的节点」→ 上溯到整行容器 → 再取该行的「私聊」按钮。
      没有「私聊」按钮的行（例如搜索历史头像）**不点**：点头像/昵称是进个人主页。
    排序：关键词优先级（昵称在前）> 完全相等（不是子串）> 屏幕位置靠上。
    """
    keys = []                     # [(归一后的 key, 原始词)] —— 原始词给上层做身份校验用
    for k in (kws or []):
        kk = _kw_key(k)
        if len(kk) >= 2 and all(kk != x[0] for x in keys):
            keys.append((kk, str(k)))
    if not keys:
        return None, None, ""
    cands = []
    for node in snap.nodes:
        try:
            t_txt = _kw_key(node.text)
            t_desc = _kw_key(node.desc)
        except Exception:
            continue
        txt = t_txt or t_desc
        if not txt:
            continue
        for idx, (kk, orig) in enumerate(keys):
            if kk not in txt:
                continue
            row = _row_box(node)
            if row is None:
                break
            try:
                label = " ".join(x for x in ((row.label or ""), (row.desc or ""))
                                 if x).strip()
                top = row.bounds[1]
            except Exception:
                break
            if any(k in label for k in SUGGEST_SKIP_KEYS):
                break
            btn = _chat_button(snap, row)
            if btn is None:
                break
            cands.append((idx, 0 if txt == kk else 1, top, btn, orig, label or txt))
            break
    if not cands:
        return None, None, ""
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    _, _, _, btn, kk, label = cands[0]
    return btn, kk, label



def enter_suggested(actor, kws, preempt=None, wait_rows=4.5):
    """在搜索页首帧直接点「猜你想搜」里的人进会话。

    返回 (snap, page, kw)：`page == "chat"` 才算命中，其它 page 原样返回给调用方
    处置；没命中/没尝试返回 None。

    为什么不做成「返回 True/False」：调用方需要区分
      · 压根没人可点（None）→ 照常走灌字搜索；
      · 点了但没进会话（page != chat）→ 搜索页多半已经没了，走搜索只会空等，
        应当直接按「进不去」处理，别记成搜索超时。

    名单是**异步加载**的：刚 open_search 成功时实测只有 40 个节点（只有标题），
    所以这里小步轮询等名单出现；一旦名单已出却没有目标人，立刻返回（不等）。
    """
    if preempt and preempt():
        return None
    snap = _recent_snap()          # 优先复用 open_search 判页时那一帧（省 1.5~4.7s）
    if snap is None:
        try:
            snap = actor.snap(force=True)
        except Exception as e:
            log.debug("猜你想搜：取帧失败 %r", e)
            return None
    t_end = time.time() + max(0.0, float(wait_rows))
    btn = kw = None
    label = ""
    if not _has_suggest_section(snap):
        # 本帧没有「猜你想搜」区块（老版本 UI / 被风控）→ 立刻走灌字搜索，不等
        log.debug("猜你想搜：本页没有该区块 → 直接走搜索")
        return None
    while True:
        btn, kw, label = find_suggested(snap, kws)
        if btn is not None:
            break
        if _rows_ready(snap):
            if _SUG_MISS_LOGGED["n"] < 3:
                _SUG_MISS_LOGGED["n"] += 1
                log.info("猜你想搜：名单已出但无目标人（kw=%r）→ 转灌字搜索（前 3 次打印）",
                         list(kws or [])[:3])
            return None
        if time.time() >= t_end:
            log.debug("猜你想搜：等名单超时（%.1fs）→ 转灌字搜索", wait_rows)
            return None
        if _wait_preempt(1.2, preempt):
            return None
        try:
            snap = actor.snap(force=True)
        except Exception:
            return None
    if preempt and preempt():
        return None
    log.info("猜你想搜命中 %r（%s）→ 点「私聊」，不输入 b=%s",
             kw, (label or "")[:18], tuple(btn.bounds))
    # 🔴 2026-11-17 09:37（真机实测）：**第一下点击会被输入法/焦点收走**。
    #   现场取证（`_ops/probe_sug5.txt`，900x1600）：
    #     tap1 → page=unknown（页面没变，还在搜索页）
    #     tap2 → page=chat，标题正是「半夏」 → 进会话了
    #   所以这里必须允许点两下；只点一下的表现就是「点了没反应」。
    pg = None
    snap2 = None
    for attempt in (1, 2):
        try:
            actor.hand.tap_node(btn, settle=1.8 if attempt == 1 else 2.2)
        except Exception as e:
            if attempt == 1:
                log.warning("点「私聊」失败: %r → 退回灌字搜索", e)
                return None
            break
        snap2, pg = actor.wait_page(("chat",), timeout=4.0 if attempt == 1 else 7.0)
        if pg == "chat":
            if attempt == 2:
                log.info("第 2 次点击后进入会话（第 1 次被键盘/焦点收走，属正常）")
            log.info("✓ 猜你想搜直接进会话（零输入、零搜索）kw=%r", kw)
            return snap2, pg, kw
        if preempt and preempt():
            return snap2, pg, kw
        # 页面可能轻微位移（键盘收起），按关键词重新定位一次再点
        btn2, kw2, _lab2 = find_suggested(snap2, [kw])
        if btn2 is None:
            log.info("第 %d 次点击后没进会话（page=%s），且行已不在本帧 → 放弃", attempt, pg)
            return snap2, pg, kw
        btn = btn2
    log.info("点了「私聊」但没进会话（page=%s）kw=%r", pg, kw)
    return snap2, pg, kw


# 搜索结果里这些不是会话行（实测 2026-11-02）：
#   「搜索 XXX，探索更多话题、派对、群组等」= 更多搜索的入口，点进去是话题页不是会话
NOT_ROW_KEYS = ("探索更多话题", "更多搜索", "问题反馈", "搜索历史", "猜你想搜")


class _Row(object):
    """搜索结果里的一行（新版 UI 没有整行容器，只能自己拼出来）。"""
    __slots__ = ("node", "bounds", "label")

    def __init__(self, node, bounds, label):
        self.node = node
        self.bounds = bounds
        self.label = label

    def __repr__(self):
        return "<Row %s %r>" % (tuple(self.bounds), self.label[:16])


def results(actor, snap=None):
    """搜索结果里的**会话行**。

    🔴🔴 2026-11-17 09:41（新版结果页实测，修「搜索永远 0 条结果 → 30s 超时」）
       旧版：一行 = 一个可点的 900x190 容器，所以老实现按「可点 + 宽>500 + 高>90」筛。
       新版（Soul 6.41，900x1600，实测 dump 见 `_ops/probe_res.txt`）：
           **根本没有整行容器**，每行只有三个可点/文字节点：
             头像(c=1 116x116, l=38) / 昵称(c=0 108x49, l=182) / 私聊(c=1 149x68, l=713)
             外加一行灰字「7天内活跃」
       ⇒ 老实现筛出来的 count=0，于是每次都「等满 30s 仍无结果」→ timeout → 熔断。
       新实现：**以「私聊」按钮为核心拼行**（每个私聊按钮 = 一行，垂直归属按中心点），
       行标签取该行内的昵称等文字。点这一行 = 点私聊 = 直接进会话（已实测）。
       老版布局没有「私聊」按钮，会自动落到下面的兼容分支，行为不变。
    """
    s = snap if snap is not None else actor.snap()
    nodes = s.nodes

    # ① 新版：以「私聊」按钮拼行
    rows = []
    for n in nodes:
        try:
            if not (n.clickable and n.visible):
                continue
            txt = ((n.text or "") + (n.desc or "")).strip()
            if "私聊" not in txt:
                continue
            b = n.bounds
            y0, y1 = b[1] - 60, b[3] + 60
            parts = []
            for m in nodes:
                try:
                    mb = m.bounds
                    if not (y0 <= (mb[1] + mb[3]) // 2 <= y1):
                        continue
                    mt = (m.text or m.desc or "").strip()
                    if not mt or "私聊" in mt or mt == "头像":
                        continue
                    parts.append(mt)
                except Exception:
                    continue
            label = " ".join(list(dict.fromkeys(parts)))
            rows.append(_Row(n, (0, y0, 900, y1), label))
        except Exception:
            continue
    if rows:
        rows.sort(key=lambda r: r.bounds[1])
        return rows

    # ② 老版：整行可点容器（保留兼容）
    out = []
    for n in nodes:
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
    # 🔴🔴 2026-11-17 09:39（真机实测，这才是「灌字必失败」的真根因）
    #
    #   实测：`tap_node(box)` **第一下会被输入法/焦点收走**（页面毫无变化），
    #   输入框根本没拿到焦点 → 后面 `clear_text` / `send_keys` / AdbKeyboard 广播
    #   全部落空，Soul 还会因此把搜索页关掉，于是我们 30s 全在错的页面上空等。
    #   对照实验（`_ops/probe_type.txt`）：点 **两下** 输入框后再灌字，
    #   页面稳在搜索页、2.5s 内就出结果（「小孩姐 / 私聊 / 7天内活跃」）。
    #   ⇒ 必须点两下。第二下才是真正拿焦点的那一下。
    actor.hand.tap_node(box, settle=0.6)
    actor.hand.tap_node(box, settle=0.6)
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
    # 🔴 2026-11-17 09:45（止血）：灌字后若**页面已经不是搜索页**，说明 Soul 把
    #   搜索页关掉了（旧版本一输入就关；本次修了焦点后应极少发生，但仍需兜底）。
    #   这时再等满 30s 纯属浪费，还会被记成 timeout 去污染熔断与台账。
    #   连续 2 帧都不在搜索页且没有结果行 → 立刻放弃（约 5s 而不是 30s）。
    _gone = 0
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
        # 没结果行：先判「是不是已经不在搜索页了」（见上面 _gone 的说明）
        if not in_search_page(snap):
            _gone += 1
            if _gone >= 2:
                LAST_REASON = "timeout"
                log.warning("搜索 %r -> 灌字后已不在搜索页（%.1fs）→ 立即放弃，不等满 %.0fs",
                            kw, time.time() - t0, max_wait)
                return 0
        else:
            _gone = 0
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
        # 🔴 2026-11-17：新版结果行是**自拼的 _Row**（以「私聊」按钮为核心），
        #   点它要落到 .node（私聊按钮）上，而不是 _Row 对象本身。
        actor.hand.tap_node(getattr(rs[idx], "node", rs[idx]), settle=1.6)
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
    # 🔴 2026-11-17 09:52（修「回列表白烧 45s」）：新版搜索是从**「通讯录」页**进来的，
    #   点「取消」只会退回通讯录，而 detect() 认不出通讯录（unknown）→ nav 连续
    #   4~5 次「回不到 chatlist」→ 强制 am start 回首页，再重新点聊天：
    #   实测 09:51:44→09:52:31 整整 47s 全耗在这上面，一个候选的时间就这么没了。
    #   ⇒ 退出搜索后先看一眼：不是列表页就**直接点「聊天」Tab**（一下就好）。
    try:
        snap = actor.snap(force=True)
        if detect(snap) != "chatlist":
            tab = None
            for nd in snap.nodes:
                try:
                    t = (nd.text or "") or (nd.desc or "")
                    if t.strip() != "聊天":
                        continue
                    if nd.bounds[1] > 300:        # 只认顶栏的 Tab，别点进某个会话
                        continue
                    tab = nd
                    break
                except Exception:
                    continue
            if tab is not None:
                actor.hand.tap_node(tab, settle=1.2)
                log.info("退出搜索后不在列表页（%s）→ 点「聊天」Tab 回列表", detect(snap))
    except Exception as e:
        log.debug("leave: 点「聊天」Tab 失败（交给 nav）: %r", e)
    return nav.to_chatlist(actor)
