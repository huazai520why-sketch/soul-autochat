# -*- coding: utf-8 -*-
"""导航：统一的「回到某个 tab」入口。

铁律（用户 2026-11-02 指出）：
  **主框架内永远点底栏 tab，不要按返回键。**
  在 me/广场/星球页按 back 会直接把 App 退出到桌面，而不是留在 App 内。

只有「会话内 / 子页面」（没有底栏）才 back 一次，且**绝不连续 back**。
"""
import os
import time

from core.log import get_logger
from core.paths import SOUL_PKG
from eyes.page import detect

log = get_logger("brain.nav")

MAIN = ("chatlist", "me", "square", "planet")

# 上次真正重启 App 的时间（restart_app 节流用）
_LAST_RESTART = {"t": 0.0}


def in_soul(device):
    pkg, _act = device.current_app()
    return SOUL_PKG in (pkg or "")


def at_main(device):
    """当前是否在 Soul 主 Activity（MainActivity = 有底栏的那一层）。

    🔴 2026-11-08 22:44 生产实证（H5 支付页卡死）：
      原来 goto_main() 只用 in_soul()（**判包名**）就算成功。可 H5Activity /
      RnContainerActivity 都属于 cn.soulapp.android —— 于是
      `am start -n MainActivity` 根本没把 H5 页顶掉时函数照样 return True，
      上层以为「已回首页」，日志里「强制回首页(am start)」连喊 4/5/6 次全是空转。
      实测现场：mCurrentFocus=cn.soulapp.android.h5.activity.H5Activity，
      页面是「我的超级星人铭牌」¥198 订阅页，连按两次 back 都退不掉。
      ⇒ 成功判据必须是 Activity，不是包名。
    """
    pkg, act = device.current_app()
    return SOUL_PKG in (pkg or "") and "MainActivity" in (act or "")


def ensure_app(device, wait=18):
    """确保 Soul 在前台，不在就拉起（app_start，不是返回键）。"""
    if in_soul(device):
        return True
    log.info("Soul 不在前台（%s），拉起", device.current_app()[0])
    try:
        device.u2().app_start(SOUL_PKG, wait=True)
    except Exception as e:
        log.warning("app_start 失败 %r", e)
        device.sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % SOUL_PKG, timeout=30)
    t0 = time.time()
    while time.time() - t0 < wait:
        if in_soul(device):
            time.sleep(1.5)
            return True
        time.sleep(1.0)
    return False


SOUL_MAIN = "%s/cn.soulapp.android.component.startup.main.MainActivity" % SOUL_PKG


def goto_main(device, wait=10):
    """强制回到 Soul 主界面（首页那层）。

    为什么需要：Soul 有些页面是 React Native 容器（RnContainerActivity，
    比如「瞬间」/活动页）**或 H5 网页页（H5Activity）**，
    **按返回键不一定退出**、detect 一直是 unknown。
    只靠 back 会原地打转 —— 实测卡了 400+ 轮、每轮 17s，消息全都没人回。

    🔴 2026-11-08 22:44（H5 支付页卡死实证，两处必修）：
      ① 必须带 `--activity-clear-top`。不带时 `am start -n MainActivity`
         只是把**整个任务**提到前台，叠在 MainActivity 之上的
         H5Activity / RnContainerActivity 仍在最上层 → 页面没变
         → 上层反复重试（实测 22:11 / 22:40 两轮各连喊 3~4 次）。
         带 clear-top 实测 2.5~5.5s 后 mCurrentFocus 变为 MainActivity。
      ② 成功判据改成 at_main()（看 Activity），不能只看包名 —— 见 at_main docstring。
    """
    try:
        device.text("am start -n %s --activity-clear-top" % SOUL_MAIN, timeout=30)
    except Exception as e:
        log.warning("am start 失败: %r", e)
        return False
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            if at_main(device):
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


def restart_app(device, wait=25):
    """强制重启 Soul（force-stop + 拉起）。卡死时的最后手段。

    🔴 2026-11-08 21:0x（空烧放大器）：加了**全局节流**。
      实测 20:00-20:52 里 `restart_app()` 被每一轮调用一次（约 45s 一次，
      一小时 60+ 次 force-stop + 冷启），既没修好问题又让设备一直在启动态，
      任何页面判断都拿不到稳定帧。现在最短 4 分钟内只允许重启一次，
      其余情况只 `am start` 回首页（便宜、不打断 App 状态机）。
    """
    gap = float(os.environ.get("SOUL_RESTART_MIN_GAP", "240") or 240)
    if time.time() - _LAST_RESTART["t"] < gap:
        log.warning("重启过于频繁（%.0fs 内已重启过）→ 改为仅回首页",
                    time.time() - _LAST_RESTART["t"])
        goto_main(device)
        return False
    _LAST_RESTART["t"] = time.time()
    log.warning("强制重启 Soul")
    try:
        device.text("am force-stop %s" % SOUL_PKG, timeout=20)
    except Exception:
        pass
    time.sleep(1.5)
    return ensure_app(device, wait=wait)


def to_tab(actor, name="聊天", tries=8):
    """回到指定底栏 tab。返回 (snap, page)。

    步骤：等页面稳定 -> 有底栏就点 tab -> 会话内才 back（最多 2 次）-> 真退出了才拉起 App。
    注意：back 后页面会有一段转场（detect 返回 unknown），必须等稳定再判断，
    否则会误判「回不去」而 app_start，结果 Soul 又恢复到原会话，死循环。

    🔴 2026-11-06（生产 128 轮 blocked 教训）：升级梯子原来只挂在 unknown 分支，
    但 greeting（新招呼页）是**聊天 tab 的子状态**——是「已知页」，
    单击当前 tab 永远无效（实测 tap_tab(聊天): greeting -> greeting 连续 30+ 次、
    一天 524 次无效点击），而它永远进不了 unknown 分支 → 任何恢复手段都轮不到。
    现在点 tab 后页面不动也爬梯子（dead 计数）：
        单击 → 双击（跳红点语义，用户 2026-11-06 确认）→ back（仅 greeting 子页）
        → am start 回首页 → 重启 App
    🔴 铁律不破：me/square/planet 等主框架页绝不 back（会退出 App）。

    🔴 2026-11-08（用户授权全量重构）：新增**只增不减**的 `fails` 兜底计数器。
       生产日志实证：`unknown 第 1/2/3 次` = 123/1/1，`强制回首页` = 1，`重启 App` = 0，
       升级梯子从没爬上去过。原因是 stuck/dead 都会被页面抖动清零
       （实测 20 次连续 dump 有 13 次关键 res 全缺失 = 页面一直在转场），
       于是每次都被判成「情况变了，重新从第 1 级爬」。
       现在 fails 不看页面变没变，只数「这一趟 to_tab 已经失败了几次」：
       第 4 次强制 am start，第 7 次重启 App。
    """
    dev = actor.dev
    want = "chatlist" if name == "聊天" else {"自己": "me", "广场": "square", "星球": "planet"}.get(name)
    backs = 0
    stuck = 0      # unknown 连续次数（卡在 RN 容器页时用来升级恢复手段）
    dead = 0       # tab 存在但点了页面不动 的连续次数（greeting 等子状态专用）
    prev_pg = None
    # 🔴 2026-11-08（生产日志实证：升级梯子从没爬上去过）：
    #   全日志 `unknown 第 1/2/3 次` = 123/1/1，`强制回首页` = 1，`重启 App` = 0。
    #   根因是 stuck/dead 这两个计数器**在页面抖动时会被清零**：
    #     · `stuck` 只要 pg != "unknown" 就归零（nav.py 上一行）
    #     · `dead` 只要 pg 变了就归零（nav.py 下一行）
    #   而真实故障场景恰恰是页面在 chat / unknown / greeting 之间来回抖
    #   （实测 20 次连续 dump 里 13 次关键 res 全缺失，页面一直在转场），
    #   于是每次都被判成「情况变了，重新从第 1 级爬」→ 永远只 back 一下就出循环。
    #   修法：另加一个**只增不减**的 fails 计数器，按它强制升级。
    #   它不替代 stuck/dead（细粒度手段仍然优先），只在细粒度手段连续无效时才兜底。
    #
    # 🔴🔴 2026-11-08 01:25 紧急修正（上线 10 分钟就把生产打死，必须记住这个教训）：
    #   第一版写成「fails >= 7 → restart_app() 然后 fails = 0」—— **这是个无限循环**。
    #   实测日志：连续 4/5/6 次 am start → 第 7 次重启 App → 归零 → 又从 4 开始
    #   → 再重启 …… 设备被丢在桌面 launcher 上（mCurrentFocus=app.lawnchair），
    #   Soul 一直没起来，daemon 每轮 blocked，8 分钟一条消息没回。
    #   正确做法：**重启 App 在一次 to_tab 调用里只允许一次**，且重启后必须重新等
    #   Soul 起来（restart_app 内部已 ensure_app），失败就老实退出循环让上层决定。
    restart_done = False
    # 🔴🔴 2026-11-08 01:58 生产崩溃修复：
    #   上一版加了 `fails += 1` / `fails >= 7` 的判断，却**忘了初始化 fails**，
    #   于是每次调用 to_tab 第一轮就抛
    #     UnboundLocalError: cannot access local variable 'fails'
    #   daemon 的 cycle() 里 nav.to_chatlist() 第一行就炸，被上层 `单轮异常` 捕获，
    #   结果**每一轮都在同一个地方崩**——等于整个机器人停摆（01:56 日志实证）。
    #   教训：新增计数器必须和初始化一起写，改完必须跑一次真实调用路径，
    #   不能只 py_compile（语法过了，运行时才炸）。
    fails = 0
    # 🔴 2026-11-08 02:28（同 P0 根因的连带修复）：
    #   运营弹窗（layout_love_bg 等）会盖住顶栏，导致「点底栏 tab 也没反应」，
    #   表现出来和「回不到 chatlist」一模一样 —— 而 to_tab 只会傻傻重试/重启 App。
    #   所以开头先把弹窗清掉。只清一次（清完再判断页面），避免每轮多花 1.5s。
    try:
        from brain.search import dismiss_popups as _dp
        _dp(actor, tries=2)
    except Exception:
        pass
    try:
        snap0, pg0 = actor.wait_page(("chatlist", "chat", "greeting", "me", "square", "planet"), timeout=1.5)
        if want and pg0 == want:
            return snap0, pg0
    except Exception:
        pass

    for _ in range(tries):
        snap, pg = actor.wait_page(("chatlist", "chat", "greeting", "me", "square", "planet"), timeout=2.5)
        if want and pg == want:
            return snap, pg
        fails += 1
        if pg != "unknown":
            stuck = 0
        if pg != prev_pg:
            dead = 0           # 页面变了：重新从单击爬梯
            prev_pg = pg

        # ── 兜底升级：只增不减，页面怎么抖都不会被清零 ──────────────
        # 第 4 次失败起强制 am start 回首页；第 7 次起重启 App（**整趟只一次**）。
        #
        # 🔴🔴 2026-11-08 23:5x（生产实证的「瞎操作」头号根因，务必别把顺序改回去）：
        #   这段兜底原来无条件排在「点底栏 tab」那套细粒度阶梯**前面**，于是：
        #     iter1 square → 点 tab → 还是 square
        #     iter2 square → 双击   → 还是 square
        #     iter3 square → am start
        #     iter4 fails=4 → 命中这里 → goto_main() → continue  ← **从此再也点不到 tab**
        #     iter5/6      → 继续 am start
        #     iter7 fails=7 → 重启 App → 落地还是 square（MainActivity 冷启固定落广场）
        #     iter8         → "重启后仍回不到" → 放弃
        #   而「放弃」之后调用方只点了一次底栏就回去了（日志 22:12:05 放弃 → 22:12:07 到达）。
        #   统计代价：nav_back 725、am_start 465、**restart 279**（每次 20~40s ≈ 2~3 小时停机）、
        #   放弃 137，全部由这个「兜底抢跑」造成。
        #   ⇒ 当前页是**主框架页且底栏在**时，说明这是可恢复状态，细粒度阶梯优先，
        #     兜底阈值抬高到一趟里基本触发不到（tries=8 < 10），由 dead>4 那道重启收尾。
        _main_ok = (pg != "unknown") and (snap.tab(name) is not None)
        _hard = 10 if _main_ok else 4
        _fatal = 14 if _main_ok else 7
        if fails >= _fatal:
            if restart_done:
                # 已经重启过一次还是回不去 → 不再折腾设备，直接交还给上层。
                log.warning("[nav] 重启后仍回不到 %s（当前 %s）→ 放弃本次导航", want, pg)
                break
            log.warning("[nav] 连续 %d 次回不到 %s（当前 %s）→ 重启 App（本次仅此一次）",
                        fails, want, pg)
            restart_done = True
            restart_app(dev)
            # ⚠️ 不归零 fails：保持高位，若下一轮仍失败会立刻命中 restart_done 分支退出。
            continue
        if fails >= _hard:
            log.warning("[nav] 连续 %d 次回不到 %s（当前 %s）→ 强制回首页(am start)",
                        fails, want, pg)
            goto_main(dev)
            backs = 0
            continue

        if pg == "unknown":
            # 🔴 2026-11-08 22:44（实证：卡在「我的超级星人铭牌」¥198 订阅页出不来）
            #   H5Activity 是 WebView 全屏页：没有底栏、没有 et_sendmessage →
            #   detect() 永远 unknown；更致命的是它**吞返回键**（实测连按 2 次 back，
            #   mCurrentFocus 仍是 H5Activity），所以下面整条 back 梯子对它完全无效，
            #   只会在「unknown 第 1/2/3 次 → am start → 重启 App」里空烧一整轮。
            #   这时唯一有效的手段是 clear-top 回家，放在点 tab / back 之前先判。
            try:
                _pkg, _act = dev.current_app()
            except Exception:
                _act = ""
            if "H5Activity" in (_act or ""):
                log.warning("[nav] 卡在 H5 网页页（%s，吞返回键）→ clear-top 回主界面", _act)
                goto_main(dev)
                stuck = 0
                # 🔴 2026-11-08 23:0x：这里必须也让 fails 前进，否则 clear-top 反复无效时
                #   只会在本分支里空转 tries(8) 次 × goto_main(wait=10s) ≈ 80s，
                #   永远爬不到上面的 fails>=7 → restart_app 那道最后的梯子。
                #   fails 是「这一趟 to_tab 失败了几次」，H5 卡死算失败，语义一致。
                fails += 1
                continue
            # 🔴 2026-11-08 21:0x（「乱点 / 误退 App」的根因）：
            #   底栏还在 = 仍在主框架，此时按 back 会把 Soul 直接退到桌面
            #   （用户 2026-11-02 定的铁律），旧代码 unknown 分支第一件事就是 back，
            #   于是越修越乱：实测 20:00-20:52 每轮都走「unknown 第1/2次 → back」
            #   → 桌面 → am start → 又 unknown。现在底栏在就点目标 tab，绝不 back。
            if snap.tab(name) is not None:
                log.info("[nav] unknown 但底栏还在（仍在主框架）→ 点 %s，不 back", name)
                snap, pg = actor.tap_tab(name, settle=1.5)
                if want and pg == want:
                    return snap, pg
                continue
            # 搜索页(RnContainerActivity)等浮层：有「取消」就先退出去
            from eyes import popup as P
            p = P.detect(snap)
            if p is not None and p.buttons:
                label, node = p.buttons[0]
                log.info("[nav] 点 %r 退出当前层", label)
                actor.hand.tap_node(node, settle=1.3)
                stuck = 0
                continue
            # 🔴 搜索页（RnContainerActivity + 顶栏输入框 + 「取消」）：
            #    实测点过取消没生效时会永久停在搜索页，之后所有灌字都灌进搜索框、
            #    detect 一直 unknown → daemon 每轮 blocked 空转（17:18 那次的根因）。
            #    unknown 时第一件事就是把「取消」点掉。
            # 匹配额度用完的半屏弹层（盖住底栏，不关掉就永远回不到列表）
            if "匹配机会已用完" in " ".join(snap.texts()):
                log.info("[nav] 匹配额度弹层 → back 关闭")
                actor.hand.back(settle=1.3)
                stuck = 0
                continue
            cn = snap.hit(text="取消") or snap.hit(desc="取消")
            if cn is not None:
                log.info("[nav] unknown 但看到「取消」→ 点掉退出浮层")
                actor.hand.tap_node(cn, settle=1.4)
                stuck = 0
                continue
            stuck += 1
            # 🔴 2026-11-08 23:5x（「误退 App」的第二条根因）：
            #   Activity 仍是 MainActivity = 人还在主框架里，只是 detect() 没认出来
            #   （转场中 / 弹窗盖住 / 改版后 res-id 变了）。这时按 back 就是把 Soul
            #   直接退到桌面 —— 日志 157 次「Soul 不在前台（app.lawnchair）」全这么来的，
            #   随后 am start → 落广场 → 回不到 chatlist → 重启，一整条雪崩。
            #   ⇒ 主框架内绝不 back（用户 2026-11-02 定的铁律），改 am start clear-top。
            if "MainActivity" in (_act or ""):
                # 一次 to_tab 里最多「1 次 clear-top + 1 次重启」：
                # 实测这个分支若每轮都发 am start，单次导航会连发 6 次（≈60s 白等）。
                if stuck == 0:
                    log.warning("[nav] unknown 但 Activity 仍在 MainActivity（主框架内）"
                                "→ 不 back，改 am start clear-top")
                    goto_main(dev)
                    stuck = 1
                else:
                    log.warning("[nav] 主框架内 unknown 且 clear-top 无效（第 %d 次）"
                                "→ 重启 App 收尾", stuck)
                    restart_app(dev)
                    stuck = 0
                continue
            # 🔴 不能只等：RnContainerActivity（瞬间/活动页）不会自己退出，
            #    实测原地等了 400+ 轮、每轮 17s。分级升级恢复手段：
            if stuck <= 2:
                log.info("[nav] unknown 第 %d 次 → back", stuck)
                actor.hand.back(settle=1.2)
            elif stuck <= 4:
                log.warning("[nav] unknown 第 %d 次 → 强制回首页(am start)", stuck)
                goto_main(dev)
            else:
                log.warning("[nav] unknown 第 %d 次 → 重启 App", stuck)
                restart_app(dev)
                stuck = 0
            continue

        if not in_soul(dev):
            log.warning("[nav] App 不在前台，拉起")
            ensure_app(dev)
            continue

        if snap.tab(name):
            if dead == 0:
                log.info("[nav] 点底栏 %s（当前 %s）", name, pg)
                snap, pg = actor.tap_tab(name, settle=1.5)
                if pg == want:
                    return snap, pg
                dead += 1
                continue
            if dead == 1:
                # 双击 = 跳红点/新消息（用户 2026-11-06 确认的语义）。
                # greeting 子状态下单击无效，双击大概率直接跳出并落到红点行。
                log.info("[nav] 单击 %s 无效（%s 不动）→ 双击", name, pg)
                snap, pg = actor.double_tap_tab(name, settle=1.5)
                if pg == want:
                    return snap, pg
                dead += 1
                continue
            if dead == 2 and pg == "greeting":
                # greeting 本质是子页面，back 是它的原生出口。
                # 🔴 只对 greeting 用 back —— me/square/planet 按 back 会退出 App。
                log.info("[nav] 双击无效（greeting 是子页）→ back 退子页")
                actor.hand.back(settle=1.5)
                dead += 1
                continue
            if dead <= 4:
                log.warning("[nav] 连续无效（当前 %s）→ 强制回首页(am start)", pg)
                goto_main(dev)
                dead += 1
                continue
            log.warning("[nav] 全部手段无效（当前 %s）→ 重启 App", pg)
            restart_app(dev)
            dead = 0
            continue

        # 没有底栏 = 会话内/子页面，只 back，且限次
        if backs < 2:
            backs += 1
            log.info("[nav] 无底栏（%s），back 第 %d 次", pg, backs)
            actor.hand.back(settle=1.5)
        else:
            log.warning("[nav] back 已达上限，拉起 App")
            ensure_app(dev)

    snap = actor.snap(force=True)
    return snap, detect(snap)


def to_chatlist(actor):
    return to_tab(actor, "聊天")


ROOT_PAGES = ("chatlist", "me", "square", "planet")


def back_safe(actor, settle=1.2):
    """页面感知的安全返回：根页绝不按 back。

    ?? 2026-11-10 15:50 实测：
      列表页 Activity = MainActivity，单次 back 直接把 Soul 退出到桌面。
      hands.Hand.back 已有护栏（重页不按 + 退出自愈），这里再按**页面**判一层：
        chatlist/me/square/planet 这类根页，back 一定是退出 App，直接跳过。

    返回 "root"（已在根页未按）/ "ok"（返回了一级）/ "relaunch"（兜底拉起过）。
    """
    dev = actor.dev
    if not in_soul(dev):
        ensure_app(dev)
        return "relaunch"
    try:
        snap = actor.snap(force=True)
        pg = detect(snap)
    except Exception:
        pg = "unknown"
    if pg in ROOT_PAGES:
        log.info("[nav] 已在根页 %s，跳过 back（防退到桌面）", pg)
        return "root"
    if pg == "unknown" and at_main(dev):
        log.info("[nav] unknown 且 Activity 是 MainActivity，跳过 back")
        return "root"
    ok = actor.hand.back(settle=settle)
    return "ok" if ok else "relaunch"
