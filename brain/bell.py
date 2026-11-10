# -*- coding: utf-8 -*-
"""奇遇铃：全局最高优先级（旧架构链路里的第 ① 位）。

旧口径（soul_daemon + 用户 2026-09-29 铁律）：
  ① 奇遇铃  全局最高：弹铃**立刻中断**当前动作（回消息/匹配/唤醒），处理完再回原流程
  ② 处理新消息 / 消除红点
  ③ 唤醒老友
  ④ 匹配

🔴 2026-11-02 实弹实测（关键）：
  铃是**自绘弹窗**，UI 树里根本没有「立即私聊」按钮节点 ——
  树里只有「关闭弹窗 / 同城奇遇 / 脉脉的同游乐土 / 有趣的灵魂等你发现」这些文本。
  所以：
    · **判据**：UI 树出现「同城奇遇 / 关闭弹窗 / 奇遇铃」→ 可能是铃（快，0 成本）
    · **定位按钮必须用 OCR**：截图里「立即私聊」在 (450, 653)，OCR 一次 ~2s
  实弹截图对照：
      x=171 y=143  'Soul奇遇铃同城奇遇'
      x=450 y=298  '脉脉的同游乐土'      ← 对方昵称
      x=450 y=431  '有趣的灵魂等你发现'
      x=450 y=653  '立即私聊'            ← 按钮中心

处理动作：点「立即私聊」→ **已在该人会话页，直接发**（旧架构栽在"先回列表找人"）→ 通用开场白 → 建档。
"""
from core.log import get_logger
from eyes import ocr
from eyes.page import detect

log = get_logger("brain.bell")

BELL_BTN = "立即私聊"
BELL_HINTS = ("奇遇铃", "同城奇遇", "关闭弹窗")

# 🔴 2026-11-08 11:2x（用户：「奇遇铃 稍后再聊 里面有三个人等着对话啊 优先级奇遇铃不是最高吗」）
#
#   实弹实测：点会话列表里「奇遇铃-稍后再聊」这一行，进的是
#     cn.soulapp.android/.component.chat.lovebelll.LoveBellChatListActivity
#   页面结构（900x1600，2026-11-08 实测 dump）：
#     标题「奇遇铃-稍后再聊」/ 右上「更多奇遇」/ 提示「仅保留最近3天你直接关闭的用户哦」
#     行：昵称(160~310, y=240~281) + 标签「同城的他，去打个招呼」或「同城奇遇」+ 时间(810, ...)
#   点行 → 直接进 ConversationActivity（对方会话页，还没任何消息）→ 灌开场白即可。
#
#   为什么必须做：这条链路是**奇遇铃的一部分**，而用户口径「奇遇铃全局最高优先级」。
#   原来 bell.is_bell 只认弹窗里的「立即私聊」按钮，对「稍后再聊」列表完全无感
#   ⇒ 3 个已经送到嘴边的人一直没人理（实测列表里 3 行，时间 10:26 / 09:53 / 09:48）。
BELL_LIST_HINTS = ("奇遇铃-稍后再聊", "更多奇遇")
BELL_ROW_TAGS = ("同城奇遇", "同城的他，去打个招呼")
BELL_LIST_SKIP = ("奇遇铃-稍后再聊", "更多奇遇", "头像", "关闭弹窗",
                  "仅保留最近3天你直接关闭的用户哦")


def _ocr_hit(dev, keyword):
    """截屏 OCR 找含关键字的文本块，返回 (x, y, text) 或 None。"""
    try:
        png = dev.screencap()
        for it in ocr.read(png):
            if keyword in it.text:
                return it.cx, it.cy, it.text
    except Exception as e:
        log.warning("OCR 扫描异常: %r", e)
    return None


def is_bell(snap=None, dev=None):
    """当前是不是弹着奇遇铃。

    🔴 判据优先级（2026-11-02 实弹教训）：
      铃消失后，UI 树里**还残留**「同城奇遇 / 关闭弹窗」这些文本节点，
      只按树判断会一直报「有铃」，然后 OCR 又找不到按钮 → 空转。
      所以：**给了 dev 就以 OCR 找到「立即私聊」为准**（按钮存在才是真铃）；
      没给 dev 才退回树判断（供不需要点击的场合用）。
    """
    try:
        hinted = None
        if snap is not None:
            txt = " ".join(snap.texts())
            hinted = any(k in txt for k in BELL_HINTS)
            # 树里一点迹象都没有 -> 直接 False，不必花 2.5s 去 OCR
            if not hinted and dev is not None:
                return False
        if dev is not None:
            return find_button(dev) is not None
        return bool(hinted)
    except Exception as e:
        log.warning("铃识别异常（按无铃处理）: %r", e)
    return False


def find_button(dev):
    """OCR 找「立即私聊」按钮。返回 (x, y, text) 或 None。"""
    return _ocr_hit(dev, BELL_BTN)


def find_nick(dev):
    """OCR 读铃上的对方昵称（按钮上方那一行大字）。

    实弹布局：昵称 y≈298，按钮 y≈653。取「按钮上方 80~450px 之间、
    长度 2~16、不是固定文案」的那一行。
    """
    try:
        png = dev.screencap()
        items = ocr.read(png)
    except Exception:
        return ""
    btn_y = None
    for it in items:
        if BELL_BTN in it.text:
            btn_y = it.cy
            break
    if btn_y is None:
        return ""
    skip = ("在线", "奇遇铃", "同城奇遇", "有趣的灵魂", "Soul")
    cands = [it for it in items
             if 60 < btn_y - it.cy < 450
             and 2 <= len(it.text.strip()) <= 16
             and not any(s in it.text for s in skip)]
    if not cands:
        return ""
    # 最靠近按钮的那一行（y 最大）
    cands.sort(key=lambda it: -it.cy)
    return cands[0].text.strip()


def handle(actor, dev, dry_run=False):
    """处理一个奇遇铃。返回 (ok, 说明)。

    绝不抛异常出去 —— 铃处理失败不能拖垮主流程。
    """
    try:
        hit = find_button(dev)
        if hit is None:
            log.warning("认出疑似铃，但 OCR 找不到「立即私聊」（可能已消失）")
            return False, "找不到按钮"
        bx, by, _ = hit
        nick = find_nick(dev)
        log.info("🔔 奇遇铃：对方=%r，按钮=(%d,%d)", nick or "?", bx, by)

        actor.hand.tap_xy(bx, by, settle=2.5)
        s2, pg = actor.wait_page(("chat",), timeout=8.0)
        if pg != "chat":
            log.warning("点立即私聊后没进会话（%s）", pg)
            return False, "没进会话(%s)" % pg

        if dry_run:
            log.info("[dry] 已进铃会话，不发送")
            actor.hand.back(settle=1.0)
            return True, "dry"

        from brain import match as M
        text = M.pick_opener()
        # 新会话开场白无 sid → 走 match.send 的 sid="" 分支，过闸但不占跟进额度
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("✓ 奇遇铃已发: %r", text)
        else:
            log.warning("奇遇铃发送失败: %s", why)

        # 建档（同匹配流程）
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("🔔 铃对象主页: %r %r", prof.get("nick"), prof.get("tags"))
        except Exception as e:
            log.warning("铃建档异常（不影响回复）: %r", e)

        actor.hand.back(settle=1.2)
        return ok, why
    except Exception as e:
        log.warning("奇遇铃处理异常（已兜住）: %r", e)
        try:
            actor.hand.back(settle=1.0)
        except Exception:
            pass
        return False, repr(e)


def open_list(actor):
    """从会话列表点进「奇遇铃-稍后再聊」。返回 (ok, 说明)。

    实测（2026-11-08 11:24）：会话列表里有一行
        奇遇铃-稍后再聊 / 有新朋友等你和Ta开启对话 / 10:26
    点它 → LoveBellChatListActivity。
    ⚠️ 注意它**不是** chatlist.Row（没有 /name、/time res-id 的普通行结构也可能有），
       所以这里不走 chatlist.rows()，直接在树里按文本找节点，稳且不受行高闸影响。
    """
    try:
        snap = actor.snap(force=True)
    except Exception as e:
        return False, repr(e)
    if is_bell_list(snap):
        return True, "已在稍后再聊列表"
    node = None
    for n in snap.nodes:
        if not n.visible:
            continue
        if (n.text or "").strip() == "奇遇铃-稍后再聊":
            node = n
            break
    if node is None:
        return False, "会话列表没有「奇遇铃-稍后再聊」入口"
    log.info("🔔 会话列表发现「奇遇铃-稍后再聊」→ 点进去")
    actor.hand.tap_node(node, settle=2.5)
    s2 = actor.snap(force=True)
    if not is_bell_list(s2):
        return False, "点进去后不是稍后再聊页(%s)" % detect(s2)
    return True, "已进入稍后再聊列表"


def preempt(actor, dev=None):
    """长动作之间插一句检查：有铃就先处理。返回是否处理了。"""
    dev = dev or actor.dev
    try:
        if not is_bell(actor.snap(force=True), dev=dev):
            return False
    except Exception:
        return False
    log.info("⚡ 检测到奇遇铃 → 中断当前动作先处理")
    ok, why = handle(actor, dev)
    return ok


# ---------------- 奇遇铃「稍后再聊」列表（2026-11-08 新增） ----------------
def is_bell_list(snap):
    """当前屏是不是「奇遇铃-稍后再聊」列表页。

    实测特征（2026-11-08 11:24 dump）：标题「奇遇铃-稍后再聊」+ 右上「更多奇遇」，
    且列表行带「同城奇遇 / 同城的他，去打个招呼」标签。
    判据取「标题 + 更多奇遇」两条同时命中，避免和普通会话列表混淆。
    """
    try:
        txt = " ".join(snap.texts())
    except Exception:
        return False
    return all(k in txt for k in BELL_LIST_HINTS)


def bell_list_rows(snap):
    """解析「稍后再聊」列表，返回 [(nick, cx, cy, tag, time_str)]（自上而下）。

    实测行结构（900x1600）：
        头像 (32,232,136,336) desc=头像
        昵称 (160,240,310,281)  e.g. 傻子看傻子
        标签 (318,246,542,274)  e.g. 同城的他，去打个招呼 / 同城奇遇
        时间 (810,244,868,277)  e.g. 10:26
    行中心 y 取昵称中心；点击点取整行中心（x=450, y=昵称 y）。
    """
    out = []
    nodes = [n for n in snap.nodes if n.visible]
    nicks = [n for n in nodes
             if n.text.strip()
             and n.text.strip() not in BELL_LIST_SKIP
             and not any(t in n.text for t in BELL_ROW_TAGS)
             and 150 <= n.bounds[0] <= 400
             and 2 <= len(n.text.strip()) <= 16
             and n.bounds[3] - n.bounds[1] < 60]
    for n in nicks:
        t = n.text.strip()
        cy = (n.bounds[1] + n.bounds[3]) // 2
        tag = ""
        ts = ""
        for m in nodes:
            if abs(((m.bounds[1] + m.bounds[3]) // 2) - cy) > 45:
                continue
            mt = m.text.strip()
            if any(x in mt for x in BELL_ROW_TAGS):
                tag = mt
            elif m.bounds[0] >= 780 and mt:
                ts = mt
        out.append((t, (n.bounds[0] + n.bounds[2]) // 2, cy, tag, ts))
    out.sort(key=lambda x: x[2])
    return out


def handle_list(actor, dev, dry_run=False, limit=3):
    """把「奇遇铃-稍后再聊」里的人逐个聊起来。返回 (n_ok, 说明)。

    用户 2026-11-08：「奇遇铃 稍后再聊 里面有三个人等着对话啊，优先级奇遇铃不是最高吗」
    —— 这条链路必须并入奇遇铃最高优先级，且每个都要**发开场白 + 进主页建档**。

    每处理一个：点行 → 确认进会话（page=chat）→ 发开场白 → visit_profile 建档 → 返回列表。
    处理完一个后**重新 dump 列表**（行会消失/上移，不能缓存坐标）。
    """
    from brain import match as M

    done = 0
    tried = set()
    for _ in range(max(1, limit)):
        snap = actor.snap(force=True)
        if not is_bell_list(snap):
            if done == 0:
                return 0, "不在稍后再聊列表(%s)" % detect(snap)
            break
        rows = [r for r in bell_list_rows(snap) if r[0] not in tried]
        if not rows:
            break
        nick, cx, cy, tag, ts = rows[0]
        tried.add(nick)
        log.info("🔔 稍后再聊：%r（%s %s）→ 点进会话", nick, tag, ts)
        actor.hand.tap_xy(450, cy, settle=2.5)
        s2 = actor.snap(force=True)
        pg = detect(s2)
        if pg != "chat":
            log.warning("点 %r 后没进会话（page=%s）→ 跳过", nick, pg)
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue
        if dry_run:
            log.info("[dry] 已进 %r 会话，不发送", nick)
            actor.hand.back(settle=1.2)
            done += 1
            continue
        text = M.pick_opener()
        # 新会话开场白无 sid → 走 match.send 的 sid="" 分支，过闸但不占跟进额度
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("✓ 稍后再聊已发 %r: %r", nick, text)
        else:
            log.warning("稍后再聊发送失败 %r: %s", nick, why)
        # 🔴 用户 2026-11-08：「怎么不进入她的主页建档呢」——
        #   发完必须进主页抓资料，否则后续回复没有画像依据（已婚/职场等边界）。
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("🔔 稍后再聊建档 %r: %s", nick, prof.get("nick"))
            else:
                log.info("🔔 稍后再聊 %r 建档未成（无主页入口）", nick)
        except Exception as e:
            log.warning("稍后再聊建档异常（不影响回复）: %r", e)
        if ok:
            done += 1
        try:
            actor.hand.back(settle=1.2)
        except Exception:
            pass
    return done, "稍后再聊处理 %d 人" % done
