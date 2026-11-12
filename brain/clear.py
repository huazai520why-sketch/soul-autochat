# -*- coding: utf-8 -*-
"""清红点（= 进会话、判末条、该回就回）。

🔴 用户 2026-11-02 的硬口径：
  「清红点**不是进入返回**，是**进入然后回消息**」
  「进入对话框后，如果最后一条是对方发来的，那么一定要做回复」

所以本模块不是「点进去再退出来」，而是
    双击聊天 tab（跳红点锚点）→ 逐个进带红点的会话 → handle_one（必回判断）→ 回来

旧架构对应：`eyes/soul_clear_unread.py` + daemon 的 `do_reply`。
"""
import os
import re
import time
import threading

from brain import flow
from core.log import get_logger
from eyes import popup as P
from eyes.chatlist import rows
from eyes.page import badges, detect

log = get_logger("brain.clear")

LIST_TOP, LIST_BOTTOM = 200, 1500     # 会话行有效纵向范围
MAX_ENTER = 8                         # 单次 sweep 最多进几个人

# 🔴 清红点**只用双击**，绝不滑动（用户 2026-11-02 反复强调，不止十次）。
#   双击的实测语义：跳到下一个有红点的位置；没有红点就原地不动；
#   在红点区间内一次推进约 1 行。所以它是「红点导航键」，
#   位置不对就多点几次，**不许改用滑动去找**。
MAX_DOUBLE = 5                        # 双击上限（用户 2026-11-02：5 次足够清完）


# 列表里这些**不是真人会话**：点进去不是聊天页（实测「瞬间」是功能入口，
# 有红点但永远进不到 chat 页 → 每轮 23s 空转，实测连续空转 47 轮）。
# 🔴 2026-11-04（用户：「切号完成后应优先处理红点」）：切号后新号列表顶部
#    有「Soul通知」「Soul空间站」等系统号/功能入口带红点，进不去 chat 页
#    → 白烧 20s 还把「假红点」计数顶满 → 冷却 15 分钟 → 真人红点被耽误。
#    「锦鲤驾到」是官方营销号（chat 页但最后一条是系统推送/我发的），同病。
# 🔴 2026-11-04（必回漏点修复）：「锦鲤驾到」原以为营销号，实测是**真人**
#    （nick 表 uid=*** name=锦鲤驾到，我们能跟她正常来回，她今天还发了
#     「上班不多」）。把她写进黑名单等于「永不回复」，直接违背必回。
#    真正该拦的是**功能入口**：瞬间/Soul通知/Soul空间站 在 nick 表里根本不存在，
#    说明它们不是真人会话。官方营销号另有号段闸 SKIP_UID_PREFIX(2042683)
#    + Session.is_official（文案命中≥2 个营销词）。
NOT_CHAT_NICKS = ("瞬间", "Soul通知", "Soul空间站")

# 🔴 2026-11-12（§118 工单 P1）：「奇遇铃-稍后再聊」列表行是**功能入口**，
#    不是真人会话。点进去是 LoveBellChatListActivity（稍后再聊列表页），
#    不是 ConversationActivity → 通用「进会话」路径 100% 校验失败白烧
#    （实测 brain.flow.log 全天 24 次「进入后不是 chat 页: unknown」）。
#    只在「奇遇铃-稍后再聊」入口行点击前识别跳过，交给 bell 专用路径处理。
#    `nick` 形如「奇遇铃-稍后再聊」或「奇遇铃 稍后再聊」等。
_BELL_ROW_RE = re.compile(r"奇遇铃.{0,4}稍后")


def dots(snap):
    """当前屏带红点的会话行（过滤掉不是聊天的功能入口）。

    ⚠️⚠️ 2026-11-12（HY-12）：**本函数在 Soul 6.41.0 上实测恒空，仅作兜底**。
      目标来源已改为库（`_lib_unread_sids`），屏幕红点判据保留只为万一某天
      res-id `unread_msg_number` 回来了也不漏。任何依赖 dots() 计数/结果的
      逻辑都应按「恒空」来写，别把它当主判据。

    ⚠️⚠️ 2026-11-08 实测：**这个函数在当前 Soul 6.41.0 上恒返回空**。
      `Row.has_dot` 依赖行内 res-id `unread_msg_number`（chatlist.py:63），
      而连续 4 轮 dump 里该 id **出现 0 次**（全屏只有底栏的 me_red_point /
      red_text / square_red_point）。库未读的 10 条 lastMsgText 拿去屏上
      textContains 反查 → **命中 0/10**（列表被滚到 8 天前，她的话没渲染）。
      ⇒ 清红点若以本函数为唯一目标源，整条链路**空转**。

    保留本函数（有调用点，且是唯一能识别「收到的新招呼」这类聚合行的地方），
    但**目标来源改为库**：见 `sweep()` 里的 `_lib_targets()`。
    """
    out = []
    for r in rows(snap):
        if not (LIST_TOP <= r.center[1] <= LIST_BOTTOM):
            continue
        if not r.has_dot:
            continue
        if (r.nickname or "").strip() in NOT_CHAT_NICKS:
            continue
        out.append(r)
    return out


def _lib_unread_sids(db):
    """库里的未读会话 sid（**替代屏幕红点**的目标源，0.05s）。

    🔴 2026-11-08（库直读 P0）：`dots()` 恒空 → 目标必须从库来。
      实测同一瞬间：库 11 个未读会话 / 50 条未读，屏上 10 行 0 个红点。
    """
    try:
        from data import pending as _P
        return _P.unread_sids(db)
    except Exception as e:
        log.debug("库未读清单不可用: %r", e)
        return []


def pending_summary(db):
    """daemon 日志用：「现在有几个人在等我回」。库不可用返回 '待回 ? 人'。"""
    try:
        from data import pending as _P
        return _P.summary(db)
    except Exception as e:
        log.debug("待回统计不可用: %r", e)
        return "待回 ? 人（库不可用）"


def count_pending(db, real_total=True, max_age_h=None):
    """待回人数；库不可用返回 -1。

    real_total=True（默认）= **真实待回总量**（含冷却中/已回过未回写），
      用于「还有没有人等」的闸 —— 不能用「本轮可处理数」当闸，
      否则冷却期一过就误判「没人等」→ 触发假红点冷却。
    real_total=False = 本轮真能处理的人数。

    🔴 2026-11-08 03:50（P0 死锁）：新增 max_age_h 透传给 data.pending.count_pending。
      红点闸门必须按「还回得掉的人」计（24h 内），否则 7 天窗口的僵尸积压
      会让这个函数恒 > 0 → 匹配永远被挡（实测连续匹配刚起步就被打断）。
    """
    try:
        from data import pending as _P
        try:
            return _P.count_pending(db, real_total=real_total, max_age_h=max_age_h)
        except TypeError:
            return _P.count_pending(db, real_total=real_total)
    except Exception as e:
        log.debug("待回计数不可用: %r", e)
        return -1


def should_reply_list(db, limit=0):
    """「该回谁」清单（库判定，完全不看屏）。返回 [PendingItem, ...]。"""
    try:
        from data import pending as _P
        return _P.should_reply(db, limit=limit)
    except Exception as e:
        log.warning("库判定待回失败: %r", e)
        return []


def badge_chat(snap):
    return badges(snap).get("聊天") or 0


def _blob_key(txt):
    """列表预览比对串：去掉 [表情]；洗成空（纯表情/语音）就退回原文。

    与 `ensure_fresh._key` 同一口径 —— 那条路径已在生产验证过（能判「列表是否跟上库」）。
    """
    raw = (txt or "").strip()
    t = re.sub(r"\[[^\]]{1,6}\]", "", raw).strip()[:8]
    return t or raw[:8]


def _rows_for_lib(snap, db, lib_sids, handled=None, limit=0):
    """把**库里的未读 sid** 映射成屏幕上的会话行（库定目标，屏幕定坐标）。

    🔴 2026-11-08（库直读 P0 的「定位层」）：
      库能 0.05s 说出「该回谁」，但点击仍然需要一个屏幕节点。
      映射方式沿用 `ensure_fresh` 已在生产验证的办法：**用库里的 lastMsgText
      前缀去匹配行 blob**（列表预览就是 lastMsgText 原文，短消息不截断）。
      这比 `flow.sid_from_row()` 便宜得多（那个每行要跑 4 条 SQL），
      而且方向是反的：库已知答案，屏幕只需认领。

    返回 [(row, sid), ...]，按 lib_sids 的顺序（= 库的优先级）。
    屏上找不到的 sid 会被跳过（说明列表没滚到那里 → 由调用方刷新/翻屏）。
    """
    handled = handled or set()
    if not lib_sids or db is None:
        return []
    rows_ = [r for r in rows(snap)
             if LIST_TOP <= r.center[1] <= LIST_BOTTOM
             and (r.nickname or "").strip() not in NOT_CHAT_NICKS]
    if not rows_:
        return []
    out, used = [], set()
    for sid in lib_sids:
        if limit and len(out) >= limit:
            break
        try:
            dig = db.session_digest(sid) or {}
            key = _blob_key(dig.get("text"))
        except Exception:
            continue
        if not key:
            continue
        for r in rows_:
            if id(r) in used:
                continue
            if (r.nickname or "") in handled:
                continue
            if key in (r.blob or ""):
                used.add(id(r))
                out.append((r, sid))
                break
    return out


def _prune_dead_lib_sids(db, lib_sids, claimed):
    """剔除设备库里**已不存在**的未读 sid，避免每轮反复空转。

    🔴 2026-11-12（HY-01）：清红点目标来自库（_lib_unread_sids），但屏上认领不到时
      若静默落空，会反复走「双击跳锚点」分支空转（实测：库 5 个未读 / 屏红点 0 /
      进 0 人）。这里只剔除**设备库已查不到**的 sid —— 人已删号/会话已消失，
      它们永远不会再被认领到，留着只会每轮白烧。
      仍存活但只是没渲染到当前屏的 sid **保留**（真实目标，列表刷新后能认领），
      不误杀、不改变真实待回口径。
    """
    if not lib_sids or db is None:
        return
    removed = []
    for sid in list(lib_sids):
        if sid in claimed:
            continue
        try:
            if db.session(sid) is None:
                lib_sids.remove(sid)
                removed.append(sid)
        except Exception:
            continue
    if removed:
        log.info("剔除设备库已不存在的未读 sid %s（避免反复空烧）", removed)


def to_list(actor, tries=3):
    """确保停在会话列表；有弹窗点主按钮。

    🔴 2026-11-09（用户「操作层乱点」的第二处根因，实证 23:59:17~27）：
       10 秒内盲点「聊天」tab 6 次全部未命中，每次还跟着按一次 back。
       detect=unknown 时 UI 树里**根本没有底栏**，Actor.tap_tab 走
       `n is None` 分支直接返回 `(None, unknown)`；旧代码不看这个信号，
       照样 hand.back() → 页面仍是 unknown → 下一轮再点，形成白点循环。
       而 unknown 页按 back 还有把 App 退到桌面的风险（日志 157 次
       「Soul 不在前台」即此类）。

       改法与 brain/nav.py 同口径：
         ① 点前先确认底栏存在，没有就**不点**（不产生无效手势）；
         ② 明确在会话页 chat → back 一次（快且不会退到桌面）；
         ③ 其余无底栏页 → am start --activity-clear-top 回主框架，**绝不 back**；
         ④ 恢复只做一次，仍不行就交回上层（sweep 有 detect!=chatlist 保护，
            会跳过本轮，不会拿 unknown 快照乱点、更不会误发消息）。
    """
    from brain.nav import goto_main      # 局部导入：规避 clear ↔ nav 的 import 时序
    recovered = False
    for _ in range(tries):
        snap = actor.snap()
        pg = detect(snap)
        if pg == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None:
            btn = (p.primary or p.secondary)
            if btn:
                log.info("处理弹窗: %s", btn[0][0])
                actor.hand.tap_node(btn[0][1], settle=1.2)
                continue

        # 底栏都不在 → 这一下 tab 必然点不中，绝不盲点
        if snap is None or snap.tab("聊天") is None:
            if pg == "chat":
                log.info("[clear] 在会话页，back 回列表")
                actor.hand.back(settle=1.0)
                continue
            if recovered:
                log.warning("[clear] 恢复后仍无底栏(%s) → 放弃本轮，不空烧", pg)
                return snap if snap is not None else actor.snap()
            recovered = True
            log.warning("[clear] 无底栏(%s) → 不盲点 tab / 不 back，"
                        "am start clear-top 回主框架", pg)
            try:
                goto_main(actor.dev)
            except Exception as e:
                log.warning("[clear] clear-top 恢复失败（交回上层跳过本轮）: %r", e)
                return snap if snap is not None else actor.snap()
            continue

        log.info("不在列表页(%s)，点底栏聊天", pg)
        snap2, pg2 = actor.tap_tab("聊天", settle=1.2)
        if pg2 == "chatlist":
            return snap2
        # 点了没到：不 back，下一轮重新取树再判（页面可能正在切换）
    return actor.snap()


def _pull_down(actor, n=1, budget=12.0):
    """在会话列表顶部下拉刷新，**秒级超时、绝不阻塞主流程**。

    🔴 2026-11-04 事故（必须保留这段说明，否则会被人「优化」回去）：
      08:20:50 的这次下拉刷新**卡了整整 10 分钟** —— uiautomator2 的 HTTP 请求
      默认要等 600s 才抛 TimeoutError。整轮 cycle 被它拖死，那 10 分钟里
      她 08:12「没忙什么」/ 08:17「[疑惑][疑问]」两条新消息一条没处理，
      而且失败后紧接着又重试 #2，等于无限挂起。
      所以：① client 超时压到 8s ② 整个手势再套线程 join(budget) 兜底
      ③ 失败即返回 False，由 ensure_fresh 放弃本轮（宁可列表旧，也不能必回停摆）。
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("下拉刷新取 u2 失败: %r", e)
        return False
    # 🔴 2026-11-04（duration 单位事故，这就是 08:20 卡 10 分钟的真因）：
    #   u2 的 duration 是**秒**（源码 steps = int(duration * 200)，每 step 约 5ms）。
    #   原来传 duration=700 → 等价 **700 秒**的手势，线程 join(12s) 后放弃，
    #   但手势还在设备上跑，整机点击全部排队 —— 表现为「整轮停摆 10 分钟」。
    #   另：`d._client.timeout` 在 u2 3.7.1 里不存在（空操作），已删。

    box = {"ok": False, "err": None}

    def _job():
        try:
            for _ in range(max(1, n)):
                d.swipe(450, 380, 450, 1200, duration=0.55)   # 秒！
                time.sleep(0.8)
            box["ok"] = True
        except Exception as e:      # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_job, name="pulldown", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("下拉刷新手势超时（>%.0fs），放弃本次刷新，不阻塞主流程", budget)
        return False
    if not box["ok"]:
        log.warning("下拉刷新手势失败: %r", box["err"])
        return False
    return True


def _to_top(actor, rounds=4, budget=12.0):
    """把会话列表滚回**顶部**（用户 2026-11-04 口径：先回顶再清当前屏红点）。

    🔴 为什么必须有：清红点原来是「在当前屏找红点」——如果列表停在中间，
      顶部那些刚来的红点（最新消息都在最上面）根本不在视野里，
      本轮就会「没红点可清 → 双击 → 也跳不到」直接空转。
    实现与 _pull_down 一致：u2 手势 + 线程 join 兜底，失败立刻返回 False。
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("回顶取 u2 失败: %r", e)
        return False
    box = {"ok": False}
    stop = {"hit": False}

    def _job():
        try:
            for _ in range(max(1, rounds)):
                if stop["hit"]:
                    break
                d.swipe(450, 380, 450, 1250, duration=0.5)   # 秒！手指下滑 = 看更上面
                time.sleep(0.5)
                # 顶部再滑也不动时，再加滑一次就是浪费 —— 由调用方按行指纹判断
            box["ok"] = True
        except Exception:
            box["ok"] = False

    t = threading.Thread(target=_job, name="totop", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("回顶手势超时（>%.0fs），放弃本次", budget)
        return False
    return box["ok"]


def ensure_fresh(actor, db, rounds=1):
    """确保会话列表 UI 跟库同步，返回最新的一次 snap。

    🔴 2026-11-04 实测（402857053，07:50）：db 里 session 最新 07:27，
      而列表首行还停在 05:10 —— UI 落后 2.5 小时。后果是三个入口一起失灵：
        · 角标=4 而行内红点 0 个 → clear 进 0 人
        · 双击「跳红点」跳不动（列表里没有那些行）
        · find_row 全落空 → 退化去搜索，而搜索也没有这些消息的索引

    🔴 2026-11-04 二修（09:34 语音事故）：判据原来只要求「未读里任意一条命中」，
      两处漏：
        ① 语音/纯表情的 lastText（'[语音]'）被表情正则洗成空串后**直接跳过**；
        ② 只要有一条老未读命中就判「已跟上」，哪怕**最新那条根本不在屏上**。
      实测 uid=*** 09:34:36 的语音因此 12 分钟没人管（屏上没红点、也没人刷新）。
      现在：洗成空串就退回原文参与匹配；并硬校验「库里最新的会话必须在当前屏」。

    判据：库里有未读会话，但当前屏上一行都对不上 / 缺最新会话 → 判定过期。
    对得上就什么都不做（不额外增加手势，避免打断正常流程）。
    """
    if db is None:
        return actor.snap()
    try:
        unread = [s for s in db.sessions(unread_only=True, include_official=False)
                  if (s.last_text or "").strip()][:8]
        newest = [s for s in db.sessions(limit=3, include_official=False)
                  if (s.last_text or "").strip()][:1]
    except Exception:
        return actor.snap()
    if not unread and not newest:
        return actor.snap()

    def _key(txt):
        """列表预览用的比对串：去掉 [表情]；洗成空（纯表情/语音）就退回原文。"""
        raw = (txt or "").strip()
        t = re.sub(r"\[[^\]]{1,6}\]", "", raw).strip()[:8]
        return t or raw[:8]

    for i in range(max(1, rounds)):
        snap = actor.snap(force=True)
        if detect(snap) != "chatlist":
            return snap
        blob = "\n".join((r.blob or "") for r in rows(snap))
        hit = 0
        for s in unread:
            t = _key(s.last_text)
            if t and t in blob:
                hit += 1
        # 硬校验：库里最新的那条会话必须出现在当前屏（否则红点也不会渲染）
        if newest:
            t0 = _key(newest[0].last_text)
            if t0 and t0 not in blob:
                log.info("列表缺最新会话（库里最新 %r 不在屏上）→ 判定过期", t0)
                hit = 0
        if hit:
            log.info("列表已跟上库（未读 %d 个，命中 %d 个）", len(unread), hit)
            return snap
        log.warning("列表比库旧（未读 %d 个，屏上没有最新那条）→ 下拉刷新 #%d",
                    len(unread), i + 1)
        if not _pull_down(actor):
            # 🔴 2026-11-04：手势失败就放弃本轮（原来还会再 #2 次，每次可能挂 10 分钟）。
            #    列表旧只是定位变难，还能走搜索兜底；把整轮拖死等于必回停摆。
            log.warning("下拉刷新不可用 → 本轮放弃刷新，继续用当前列表")
            break
        time.sleep(1.2)
    return actor.snap(force=True)


def handle_greeting(actor, dev, dry_run=False, max_people=4):
    """处理「收到的新招呼」（NewGreetingDetailActivity）。

    用户 2026-11-02：这条系统消息**点进去还要再点一次**才进对话页。
    页面结构（实测）：
        「收到的新招呼」/「发消息后对话框将会被放出哦」
        每人一整行 ViewGroup(0, y, 900, y+153) —— 点它进 ConversationActivity
    注意：**发消息后这个人才会被放进正常会话列表**，所以必须发，不能只点开退出。
    返回发出的条数。
    """
    from brain import match as M

    snap = actor.snap(force=True)
    if "收到的新招呼" not in "\n".join(snap.texts()):
        return 0

    done, tried = 0, set()
    for _ in range(max_people):
        s = actor.snap(force=True)
        if "收到的新招呼" not in "\n".join(s.texts()):
            break
        rows_ = [n for n in s.nodes
                 if n.clickable and n.visible
                 and (n.bounds[2] - n.bounds[0]) >= 700
                 and 120 <= (n.bounds[3] - n.bounds[1]) <= 220
                 and n.bounds[1] > 150
                 and tuple(n.bounds) not in tried]
        if not rows_:
            break
        rows_.sort(key=lambda n: n.bounds[1])
        n = rows_[0]
        tried.add(tuple(n.bounds))
        log.info("新招呼 -> 点第 %s 行", n.bounds)
        actor.hand.tap_node(n, settle=2.5)
        s2, pg = actor.wait_page(("chat",), timeout=8.0)
        if pg != "chat":
            log.warning("没进对话页（%s），返回", pg)
            actor.hand.back(settle=1.5)
            continue

        text = M.pick_opener()
        if dry_run:
            log.info("[dry] 会发 %r", text)
        else:
            # 新会话开场白无 sid → 走 match.send 的 sid="" 分支，过闸但不占跟进额度
            ok, why = M.send(actor, dev, text)
            log.info("新招呼发送 %r -> %s %s", text, ok, why)
            if ok:
                done += 1
                time.sleep(0.8)

        actor.hand.back(settle=1.5)
        for _ in range(4):                      # 等回到新招呼页
            s3 = actor.snap(force=True)
            if "收到的新招呼" in "\n".join(s3.texts()):
                break
            time.sleep(0.8)

    return done


def sweep(actor, db, dry_run=False, max_enter=MAX_ENTER, dev=None, budget_s=240.0):
    """清一轮红点（进会话 + 必回）。返回 dict(entered, replied, left, results)。"""
    out = {"entered": 0, "replied": 0, "left": None, "results": []}

    snap = to_list(actor)
    if detect(snap) != "chatlist":
        log.warning("回不到会话列表，跳过清红点")
        out["left"] = -1
        return out
    # 🔴 2026-11-04：列表 UI 会落后于库（实测落后 2.5h）→ 红点/行定位全失灵。
    #    对不上就下拉刷新一次，不额外增加手势开销。
    # 🔴 2026-11-04（修顺序·下拉刷新必须在列表顶部才有效）：原来先 ensure_fresh
    #    （下拉刷新）再 _to_top（回顶）——但下拉刷新要列表在顶部才触发，在中间 swipe
    #    只是把列表往下滚、不触发刷新，两个无效下拉刷新每轮白烧 ~20s。
    #    改成先回顶（最新消息上屏）再 ensure_fresh 检查：命中就完全不刷。
    try:
        if _to_top(actor, rounds=3):
            snap = actor.snap(force=True)
    except Exception as e:
        log.warning("回顶失败（继续用当前屏）: %r", e)
    snap = ensure_fresh(actor, db)

    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            log.warning("本小时发送已达上限 → 本轮不清红点（避免封号）")
            out["left"] = badge_chat(actor.snap())
            return out
    except Exception:
        pass

    handled = set()
    handled_sids = set()   # 已处理的库 sid（库直读路径用；与 handled 昵称集合并行）
    doubles = 0
    stall = 0          # 连续几次双击「角标和红点都没变化」→ 判定推不动，提前收工
    idle = 0           # 连续几次进会话都无需回复 -> 判定假红点
    her_stuck = 0      # 连续几次「末条是她但发不出」-> 也要熔断，否则无限进同一人
    interrupted = False  # 本轮是否被「库有变化」打断（打断 ≠ 假红点）
    t_budget = time.monotonic()   # 用户 2026-11-02：一分钟内没进展就进下一步流程
    reuse_snap = False   # 双击分支已拿到最新快照 -> 下一轮别再 dump 一次

    # 🔴🔴 2026-11-08（库直读 P0）：清红点的**目标来源**从「屏幕上找红点行」
    #   改为「库里查未读会话」。原因（实测，探针 L/M/N）：
    #     ① `Row.has_dot` 依赖的 `unread_msg_number` 在 dump 里连续 4 轮 **0 个节点**
    #        → dots() 恒空 → 原逻辑「没红点就双击跳锚点」→ 空转到 MAX_DOUBLE 收工。
    #     ② 同一瞬间库有 11 个未读会话 / 50 条未读，屏上 10 行 0 个红点。
    #   现在：库给 sid 清单（0.05s），屏幕只负责「把这行找到并点进去」。
    #   屏幕红点仍保留做**兜底**（万一某天 res-id 回来了，也不会漏）。
    lib_sids = _lib_unread_sids(db)
    if lib_sids:
        log.info("清红点目标来自库：%d 个未读会话（屏幕红点数=%d）",
                 len(lib_sids), len(dots(snap)))
    else:
        log.info("库未读清单为空/不可用 → 退回屏幕红点判据（实测多半也是 0）")

    while out["entered"] < max_enter:
        if time.monotonic() - t_budget > budget_s and out["entered"] > 0:
            log.info("清红点已用 %.0fs（>%.0fs 预算）→ 本轮先停，剩下的下一轮继续",
                     time.monotonic() - t_budget, budget_s)
            break
        if time.monotonic() - t_budget > budget_s * 2:
            log.warning("清红点 %.0fs 一个人都没进去 → 直接收工（异常）",
                        time.monotonic() - t_budget)
            break
        if reuse_snap:
            reuse_snap = False
        else:
            snap = actor.snap()
        if detect(snap) != "chatlist":
            snap = to_list(actor)
            if detect(snap) != "chatlist":
                break

        todo = [r for r in dots(snap) if r.nickname not in handled]
        # 🔴🔴 2026-11-08（库直读 P0）：**库判定优先，屏幕红点兜底**。
        #   改前：只认 dots(snap)（行内 unread_msg_number）—— 实测 4/4 轮 0 个节点
        #        → todo 恒空 → 走「双击跳锚点」分支 → 空转到 MAX_DOUBLE 收工。
        #   改后：先用库里的未读 sid 清单映射成屏幕行（库定目标、屏幕定坐标）；
        #        库拿不到 / 屏上认领不到，才退回原红点判据。
        #   ⚠️ MAX_DOUBLE=5 与「只双击不滑动」是用户铁律，本改动**未触碰**。
        _want = [s for s in lib_sids if s not in handled_sids]
        lib_pairs = _rows_for_lib(snap, db, _want, handled=handled)
        if lib_pairs:
            r = lib_pairs[0][0]
            _sid_hint = lib_pairs[0][1]
            log.info("库定目标 sid=%s → 屏上第 %d 行 %r（库剩余 %d 个未读）",
                     _sid_hint, r.center[1], r.nickname,
                     len([s for s in lib_sids if s not in handled_sids]))
        else:
            # 🔴 2026-11-12（HY-01）：本次「认领不到」的库目标里，设备库已查不到
            #   的 sid 直接剔除（幽灵会话，永远不会被认领到，留着每轮白烧）；
            #   仍存活但只是没渲染到当前屏的**保留**（列表刷新后能认领）。
            #   handled_sids = 本轮已处理过的，不算「认领不到」，跳过不剔。
            _prune_dead_lib_sids(db, lib_sids, handled_sids)
            r = todo[0] if todo else None
            _sid_hint = None
        if r is None:
            b = badge_chat(snap)
            if b == 0:
                break
            # 当前屏没红点但角标还有 -> 双击跳锚点（用户定的清红点手段）
            if doubles >= MAX_DOUBLE:
                log.info("双击 %d 次仍没找到红点（角标=%s），本轮放弃", doubles, b)
                break
            doubles += 1
            # 🔴 2026-11-04（提速·bug）：这里原来用 len(dots(snap))（**未过滤** handled），
            #   而下面 nd 用的是**过滤后**的数量 —— 口径不一致 → 屏上只要有「刚回过的人」
            #   的红点残留，before=(1,1)/after=(1,0) 恒不等 → stall 每次被清零 →
            #   熔断永不触发，必须耗满 MAX_DOUBLE=5 次（实测白烧 63s）。
            #   改成与 nd 同口径。
            before_key = (b, len([r for r in dots(snap) if r.nickname not in handled]))
            snap, pg = actor.double_tap_tab("聊天", expect="chatlist", settle=1.0)
            if snap is None:
                break
            nd = len([r for r in dots(snap) if r.nickname not in handled])
            nb = badge_chat(snap)
            log.info("双击第%d次 -> 角标=%s 红点=%d", doubles, nb, nd)
            if (nb, nd) == before_key:
                stall += 1
                if stall >= 3:
                    log.info("连续 %d 次双击无进展（角标=%s 红点=%d）→ 判定推不动，本轮收工",
                             stall, nb, nd)
                    break
            else:
                stall = 0
            # double_tap_tab 返回的就是双击后的新列表快照 → 下一轮直接用它，
            # 不再在循环开头重新 dump（省一次 3s）
            reuse_snap = True
            continue

        handled.add(r.nickname)
        if _sid_hint:
            handled_sids.add(_sid_hint)

        # 特例：「收到的新招呼」是系统聚合行，点进去还要再点一次人
        if "新招呼" in r.blob:
            log.info("遇到「收到的新招呼」，走二级路径")
            n = handle_greeting(actor, actor.dev, dry_run=dry_run)
            out["replied"] += n
            out["entered"] += 1
            snap = to_list(actor)
            reuse_snap = True      # to_list 已给新快照，别再 dump 一次
            continue

        # 🔴 2026-11-04（兜底）：官方/营销号（周报、活动推送等）在列表里也有红点，
        #    昵称不一定在 NOT_CHAT_NICKS 黑名单里。进会话前用列表行预览文本反查
        #    sid，能判定是官方号就直接跳过——不进、不空转、不计假红点。
        #    反查不到（预览截断/不唯一）则按原逻辑走，不会误伤真人。
        # 🔴 2026-11-08（库直读）：**库已经给了 sid 就直接用**，不再反查。
        #    sid_from_row 每行要跑 4 条 SQL（session 精确/前缀 + chatmsg 精确/前缀），
        #    而库直读路径上 sid 本来就是已知答案 —— 反查纯属白烧，还会因
        #    「嗯」「是的」这类短文本撞车返回 None（实测这就是走慢路径 OCR 的来源）。
        _sid = _sid_hint
        if _sid:
            log.debug("库直读路径：sid=%s 已知，跳过文本反查", _sid)
        else:
            try:
                _sid = flow.sid_from_row(db, r)
            except Exception as _e:
                log.debug("行文本反查失败: %r", _e)
                _sid = None
        try:
            _sess = db.session(_sid) if _sid else None
            if _sess is not None and _sess.is_official:
                log.info("跳过官方/营销号 %r（不进会话、不计假红点）", r.nickname)
                reuse_snap = True  # 没做任何 UI 动作，列表没变
                continue
        except Exception as _e:
            log.debug("官方号预判失败（继续原逻辑）: %r", _e)

        # 🔴 2026-11-12（§118 工单 P1）：「奇遇铃-稍后再聊」列表行是**功能入口**，
        #    不是真人会话。点进去是 LoveBellChatListActivity（稍后再聊列表页），
        #    不是 ConversationActivity → 通用「进会话」路径 100% 校验失败白烧。
        #    点击前识别跳过（reuse_snap=True：没做任何 UI 动作，列表没变），
        #    只允许 bell 专用路径进。默认开；设 SOUL_SKIP_BELL_ROW=0 可关。
        # 🔴 2026-11-12（HY-07）：判据改用整行文本 r.blob，不再只认 r.nickname。
        #    r.nickname 在 chatlist 修昵称识别后才可靠；早期帧里该行的 name res-id
        #    缺失时 nickname 会退化成消息预览（如「有新朋友等你和Ta开启对话」），
        #    正则匹配不到 → 跳过失效 → 白烧。blob 含昵称+预览+标签，覆盖全部形态。
        _bell_hit = (os.environ.get("SOUL_SKIP_BELL_ROW", "1") == "1" and (
            _BELL_ROW_RE.search(str(r.blob or ""))
            or _BELL_ROW_RE.search(str(r.nickname or ""))))
        if _bell_hit:
            log.info("跳过「奇遇铃-稍后再聊」行：它是入口不是会话，只允许 bell 专用路径进")
            reuse_snap = True
            continue

        log.info("进会话 %r 红点=%s", r.nickname, r.badge)
        # 🔴 2026-11-10（昵称缓存的主要来源）：
        #   清红点这条路**定位最可靠**（库定 sid + 屏上行，100% 能进），
        #   而且进之前屏幕上有真实昵称。原来只有 pendingq 成功后才 remember_nick，
        #   而 pendingq 恰恰是最缺昵称的那条路 —— 形成「越缺越补不上」的死循环。
        #   这里每进一个人就落盘一个 sid→昵称，pendingq 下一轮就能用昵称直接定位。
        try:
            from brain.pendingq import remember_nick as _RN
            if _sid:
                _RN(_sid, r.nickname)
        except Exception as _e_rn:
            log.debug("记昵称失败（不影响进会话）: %r", _e_rn)
        # 🔴 2026-11-03 修复 P0（空烧根因）：进会话那一下 App 会**标已读并写库**。
        #    这里不先声明「这段写入是我自己造成的」，循环末尾的 _W.urgent() 会
        #    把自己打断 → 统计成「进 1 人 / 回 0 条」→ 兜底再判「假红点」。
        #    实测一天 48 次中断、32 次误判。窗口 20s 覆盖进入+判定+出话。
        try:
            from data import watch as _W0
            _W0.mark_self_write(20.0)
        except Exception:
            pass
        # 单人异常不能中止整轮清扫（否则本轮剩余红点全放弃）
        try:
            res = flow.handle_one(actor, db, r, dry_run=dry_run)
        except Exception as e:
            log.warning("[%s] 进会话处理异常（跳过此人，继续本轮）: %r", r.nickname, e)
            out["entered"] += 1
            try:
                actor.hand.back(settle=1.0)
            except Exception:
                pass
            continue
        out["results"].append(res)
        # 计数必须在「可能 break 的检查」之前 —— 否则中断时人会漏计
        # （实测日志出现「进 0 人」但实际进了并回了消息）
        out["entered"] += 1
        if res.sent or (dry_run and res.reply):
            out["replied"] += 1
            idle = 0
            her_stuck = 0
        else:
            # 🔴 2026-11-02 实测：UI 树里的「红点」会误判（某行的装饰 FrameLayout
            #    被当成红点），进会话后发现最后一条是我发的 → 什么都没发就退出。
            #    角标是 0 却每轮 23s 空转 47 轮。这里连续 2 次空转就判「假红点」，
            #    连同冷却 15 分钟，交给 pendingq（查库）继续兜底，不会漏消息。
            # 🔴 2026-11-03：末条是「她」却没发出话 —— 那不是假红点，是真·待回。
            #    实测 11-02 20:10 / 20:17 / 11-03 夜间 61 次：她发来消息 → 进会话即已读、
            #    角标归零 → 程序判「最后一条是我发的」没发 → 记成假红点 → 冷却 15 分钟 → 漏回。
            if getattr(res, "side", "?") == "her":
                her_stuck += 1
                log.warning("[%s] 末条是她但没发出话（第 %d 次）→ 不判假红点，留给已读未回",
                            getattr(res, "nick", "?") or "?", her_stuck)
                if her_stuck >= 3:
                    log.warning("连续 %d 次「末条是她但发不出」→ 本轮先停，交给已读未回",
                                her_stuck)
                    break
            else:
                idle += 1
                if idle >= 2:
                    _FAKE_DOT["until"] = time.time() + FAKE_DOT_COOL_S
                    log.warning("连续 %d 次进会话都无需回复 → 判定假红点，"
                                "清红点冷却 %.0f 分钟", idle, FAKE_DOT_COOL_S / 60.0)
                    break
        if res.err:
            log.warning("[%s] %s", res.nick, res.err)

        # 🔴 2026-11-04（用户口径·连续清红点）：原来一有库变化就 break，回去
        #    重新 to_list 回顶 + ensure_fresh（每轮白烧 20~30s 固定开销），实际每轮
        #    只能进 1~2 人。红点循环处理的就是最新消息（新消息必然带红点），继续在
        #    本循环里 snap 就能看到新红点行 —— 不必 break 回去重来。
        #    interrupted 仍置 True（供下面「别误判假红点」用），只是不再 break。
        try:
            from data import watch as _W
            if _W.urgent():
                interrupted = True
                log.info("⚡ 库有变化（可能新消息）→ 继续本屏清扫（新红点下一圈可见）")
                _W.consume()
        except Exception:
            pass

        # 🔔 旧架构铁律「挡路了也要先奇遇铃」：每回完一个人就瞄一眼铃，
        #    有就立刻插队处理（一轮回 5 个人要 80s，铃可能中途弹出来）。
        try:
            from brain import bell as _BELL
            _dev = dev or actor.dev
            if _BELL.is_bell(actor.snap(force=True), dev=_dev):
                log.info("⚡ 回复途中来了奇遇铃 → 中断清扫先处理")
                _ok, _why = _BELL.handle(actor, _dev)
                log.info("⚡ 铃处理 ok=%s %s", _ok, _why)
                snap = to_list(actor)
                continue
        except Exception as e:
            log.warning("轮内铃检查异常（继续清扫）: %r", e)

        snap = to_list(actor)
        time.sleep(0.3)

    snap = actor.snap()
    out["left"] = badge_chat(snap) if detect(snap) == "chatlist" else None
    # 🔴 2026-11-08（改动 4：给 daemon 一个「该回人数」指标）
    #   用户要能一眼看出「现在有 27 个人在等我回」。库判定，不依赖屏幕。
    #   放进 out 里让调用方（daemon）直接取用，同时打一行日志。
    # 🔴 2026-11-12（HY-04）：sweep 结束日志的 count_pending 原来**没传 max_age_h**
    #   且用默认 real_total=True（7 天窗口 + 含已回/冷却）→ 虚高 → 假红点兜底
    #   `_pend <= 0` 几乎不成立。改传 real_total=False + max_age_h=STALE_GIVEUP_H，
    #   与候选队列同一口径（只数「本轮真能处理」的），兜底才能正确生效。
    try:
        from brain import pendingq as _PQG
        _max_age = _PQG.STALE_GIVEUP_H
    except Exception:
        _max_age = None
    out["pending"] = count_pending(db, real_total=False, max_age_h=_max_age)
    log.info("清红点结束：进 %d 人 / 回 %d 条 / 剩余角标=%s / %s",
             out["entered"], out["replied"], out["left"], pending_summary(db))

    # 🔴 兜底收敛：进了人却一条没发、角标还是 0 → UI 树里的「红点」是误判
    #    （实测「瞬间」这类功能入口、或装饰 FrameLayout 被当成红点）。
    #    不设冷却的话每轮 23s 白转，用户明确要求「不要一直停在那里不动」。
    # 🔴 2026-11-03 修复 P2：此兜底原先会把「末条是她但发不出」（真待回，her_stuck>0）
    #    也判成假红点 → 冷却 15 分钟 → 漏回。加 her_stuck==0 条件：只有全程
    #    「末条是我/无需回复」才算假红点；有真待回就交给已读未回兜底。
    # 🔴 2026-11-03 修复：被新消息打断 ≠ 假红点。原来只要「进了人、没发话、角标归零」
    #    就判假红点并冷却 15 分钟；而"被打断"正好落进这个分支（实测 32 次/日）。
    # 🔴🔴 2026-11-08（库直读 P0，必须同时修）：上面 `(out["left"] or 0) <= 0` 用的是
    #    底栏「聊天」角标 —— 实测该角标**恒为 0**（lead 复现：badges={'广场': 7}，
    #    聊天 tab 完全无角标）。于是「进了人、没发话」必然被判「假红点」→ 冷却 15 分钟
    #    → 而这 15 分钟里库里可能还有 27 个人在等。加库判定：库说还有人等，就**不许**
    #    判假红点（冷却会把真待回一起冻住）。
    _pend = out.get("pending", -1)
    if (out["entered"] > 0 and out["replied"] == 0 and her_stuck == 0
            and not interrupted and (out["left"] or 0) <= 0
            and _pend <= 0):
        _FAKE_DOT["until"] = time.time() + FAKE_DOT_COOL_S
        log.warning("进了 %d 人一条没发、角标=0、库无待回 → 判定假红点，清红点冷却 %.0f 分钟",
                    out["entered"], FAKE_DOT_COOL_S / 60.0)
    elif out["entered"] > 0 and out["replied"] == 0 and _pend > 0:
        log.info("进了 %d 人没发话，但库里还有 %d 个待回 → **不判假红点**（不冷却）",
                 out["entered"], _pend)
    return out


# 假红点冷却（连续进会话都无需回复 → UI 树里的「红点」是误判）
_FAKE_DOT = {"until": 0.0}

FAKE_DOT_COOL_S = 900          # 冷却 15 分钟


def fake_dot_cooling():
    """是否还在「假红点」冷却期。"""
    return time.time() < _FAKE_DOT["until"]


def has_dot_now(actor, db=None):
    """当前是否还有聊天红点（用于「有红点就不匹配」的闸）。

    🔴 2026-11-03 修复 P0：冷却原来只在 `角标<=0` 时生效，而"角标虚高"
      （App 侧累计未读，本号长期有）恰恰是最常见的情形 ⇒ 冷却形同虚设，
      每轮继续双击 5 次找不存在的红点。现在冷却期内**只认当前屏真实行内红点**；
      看不见就交给 pendingq（按库判"末条是她"，不依赖红点），不会漏消息。

    🔴🔴 2026-11-08 修复 P0（库直读，实测复现）：
      【改前】`d = len(dots(snap))` —— 而行内红点 res-id `unread_msg_number`
        在 dump 里连续 4 轮 **0 个节点**（全屏只有底栏 me_red_point / red_text /
        square_red_point），且底栏「聊天」角标也恒为 0（lead 实测 badges={'广场':7}）。
        ⇒ 本函数**恒返回 (False, 0, 0)** = 「没有红点」→ 上层以为清完了。
        实测同一瞬间库里还有 11 个未读会话 / 4 个必须回 / 23 个已读未回。
      【改后】传入 db 时以**库**为准（`data.pending.count_pending`，0.05s）：
        有真人待回就算有红点。db 为 None 时退回旧行为（屏幕判据）保持兼容。
      【兼容】签名只加了可选参数 `db=None`，所有现有调用点 `has_dot_now(actor)` 不变。

    返回 (是否有红点: bool, 角标: int, 屏幕红点数: int)。
    """
    snap = actor.snap()
    if detect(snap) != "chatlist":
        snap = to_list(actor)
    b = badge_chat(snap)
    d = len(dots(snap))
    # ---- 库判定优先（库不可用/没传 db 才看屏幕）----
    # 🔴🔴 2026-11-08 03:50（P0 死锁·最后一处漏网）
    #
    #   改前：`count_pending(db)` 用的是 **7 天窗口 + 含冷却 + 含已回**（real_total=True），
    #        实测恒为 63~65 人。而真正能回的候选（candidates 按 STALE_GIVEUP_H=24h 淘汰后）
    #        只剩 6 个。两边口径差 10 倍 ⇒ 这函数恒返回 True。
    #
    #   后果（日志实证，连续匹配刚修好又被它挡住）：
    #     `⚡ 连续匹配途中出现红点 → 立刻停下回去回复（已匹配 0 个）`
    #     —— 每轮匹配刚起步就被打断，一次都没匹配成。
    #
    #   改后：与候选队列同一口径（只数 24h 内、不含冷却/已回的真人），
    #        这样「有人真的在等我回」才挡匹配，僵尸积压不再挡。
    _max_age = None
    try:
        from brain import pendingq as _PQG
        _max_age = _PQG.STALE_GIVEUP_H
    except Exception:
        _max_age = None
    try:
        # 🔴 2026-11-12（HY-03）：count_pending 默认 real_total=True（含已回过/冷却）
        #   → 恒 >0 → 上层「有红点就不匹配」永远挡匹配。改 real_total=False：
        #   只数本轮真能处理的（与候选队列同口径），僵尸积压不再挡匹配。
        n_lib = count_pending(db, real_total=False, max_age_h=_max_age) if db is not None else -1
    except TypeError:
        # 兼容旧签名（count_pending(db) 没有 max_age_h / real_total）
        n_lib = count_pending(db) if db is not None else -1
    if n_lib >= 0:
        if n_lib > 0:
            # 库里有真人待回 → 一定「有红点」，不管屏幕渲染成什么样
            return True, b, d
        # 库说 0 个人等 → 即使底栏角标虚高也不算（角标是 App 侧累计值，会虚高）
        return False, b, d
    # ---- 库不可用：退回屏幕判据（实测多半失效，但总比崩好）----
    if fake_dot_cooling():
        return d > 0, b, d
    return (b > 0 or d > 0), b, d
