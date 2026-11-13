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
import json
import os
import re
import tempfile
import time

from core.log import get_logger
from core.paths import LOGS, STATE
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

# 2026-11-13 用户口径：奇遇铃里的人要尽量清空，不再卡死在 3 人/天。
# 一轮仍只处理一小批，避免把回复/红点/匹配段整轮挤掉；后续轮次继续清。
def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except Exception:
        return int(default)


BELL_BATCH_MAX = max(1, _env_int("SOUL_BELL_BATCH_MAX", 8))
BELL_DAILY_MAX = max(BELL_BATCH_MAX, _env_int("SOUL_BELL_DAILY_MAX", 40))
BELL_LIST_LEDGER_TTL_S = 4 * 24 * 3600
BELL_FAIL_RETRY_S = 30 * 60

# 主页明确写了“不撩/不约”的人不再强开，避免把已经拒绝暧昧的人拉进来。
PROFILE_BLOCK_WORDS = ("不撩", "不约", "拒撩", "拒绝暧昧", "不网恋")


def _uid_key(uid):
    """只取账号 uid 的数字部分做文件名，避免空值/特殊字符。"""
    s = "".join(ch for ch in str(uid or "") if ch.isdigit())
    return s or "unknown"


def _ledger_file(uid):
    return STATE / ("bell_list_opened_%s.json" % _uid_key(uid))


def _row_key(nick, tag="", ts=""):
    """列表行的稳定键。昵称+标签+原始时间足以覆盖同一账号内的重复行。"""
    return "|".join(str(x or "").strip() for x in (nick, tag, ts))


def _log_ts(line, now=None):
    """解析日志行 `MM-DD HH:MM:SS`，返回秒级 epoch；失败返回 0。"""
    m = re.match(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", line or "")
    if not m:
        return 0
    now = now or time.localtime()
    try:
        return time.mktime((now.tm_year, int(m.group(1)), int(m.group(2)),
                            int(m.group(3)), int(m.group(4)), int(m.group(5)),
                            0, 0, -1))
    except Exception:
        return 0


def _bootstrap_nicks_from_log(uid, data):
    """首次升级时从当天日志补昵称台账，避免重发今天已经开场过的人。"""
    if _uid_key(uid) == "unknown":
        return
    nicks = data.setdefault("nicks", {})
    if nicks:
        return

    # 找本账号今天最后一次进入的时间点。日志缺切换记录时退回 0 点。
    cutoff = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    gp = LOGS / "guard.daemon.log"
    try:
        with open(gp, "rb") as f:
            f.seek(max(0, gp.stat().st_size - 500000))
            gl = f.read().decode("utf-8", "replace").splitlines()
        for line in gl:
            target = (("账号已变" in line or "已切号" in line)
                      and (("→ %s" % uid) in line or ("-> %s" % uid) in line))
            if target:
                ts = _log_ts(line)
                if ts > cutoff:
                    cutoff = ts
    except Exception as e:
        log.debug("奇遇铃台账 bootstrap 读 guard 日志失败: %r", e)

    bp = LOGS / "brain.bell.log"
    try:
        with open(bp, "rb") as f:
            bl = f.read().decode("utf-8", "replace").splitlines()
        for line in bl:
            if "稍后再聊已发" not in line:
                continue
            ts = _log_ts(line)
            if ts and ts >= cutoff:
                m = re.search(r"稍后再聊已发 '([^']+)'", line)
                if m:
                    nick = m.group(1).strip()
                    if nick:
                        nicks[nick] = {"at": ts, "status": "sent"}
    except Exception as e:
        log.debug("奇遇铃台账 bootstrap 读 bell 日志失败: %r", e)
    if nicks:
        log.info("奇遇铃台账首次迁移：从日志补入 %d 个已发昵称（uid=%s）", len(nicks), uid)


def _ledger_load(uid):
    path = _ledger_file(uid)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("opened"), dict):
            raise ValueError("bad ledger")
    except Exception:
        data = {"version": 1, "opened": {}}

    now = time.time()
    opened = data["opened"]
    for k, v in list(opened.items()):
        at = float((v or {}).get("at", 0) or 0)
        if not at or now - at > BELL_LIST_LEDGER_TTL_S:
            opened.pop(k, None)
    nicks = data.setdefault("nicks", {})
    for k, v in list(nicks.items()):
        at = float((v or {}).get("at", 0) or 0)
        if not at or now - at > BELL_LIST_LEDGER_TTL_S:
            nicks.pop(k, None)
    _bootstrap_nicks_from_log(uid, data)
    data["version"] = 2
    return data


def _ledger_save(uid, data):
    path = _ledger_file(uid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_bell_", suffix=".swp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
                f.write("\n")
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        log.warning("保存奇遇铃台账失败 uid=%s: %r", uid, e)


def _ledger_seen(uid, key, nick="", data=None):
    data = data or _ledger_load(uid)
    v = data.get("opened", {}).get(key)
    if v:
        if v.get("status") == "failed":
            if time.time() < float(v.get("retry_after", 0) or 0):
                return True
        else:
            return True
    nv = data.get("nicks", {}).get((nick or "").strip())
    if nv and nv.get("status") != "failed":
        return True
    return False


def bell_daily_count(uid, day=None):
    """按账号统计今天真实发出去的开场白数。"""
    day = day or time.strftime("%Y-%m-%d")
    data = _ledger_load(uid)
    n = 0
    for v in data.get("nicks", {}).values():
        if (v or {}).get("status") != "sent":
            continue
        at = float((v or {}).get("at", 0) or 0)
        if time.strftime("%Y-%m-%d", time.localtime(at)) == day:
            n += 1
    return n


def profile_block_reason(prof):
    """主页明确拒绝暧昧/约会时返回命中的词；普通“已婚”不单独命中。"""
    p = prof or {}
    bits = []
    for k in ("nick", "grav", "gravity", "soul"):
        if p.get(k):
            bits.append(str(p[k]))
    for k in ("tags", "moments"):
        v = p.get(k) or []
        if isinstance(v, (list, tuple)):
            bits.extend(str(x) for x in v)
        elif v:
            bits.append(str(v))
    txt = " ".join(bits)
    for w in PROFILE_BLOCK_WORDS:
        if w in txt:
            return w
    return ""


def _save_profile_after_send(actor, dev, db, prof, text, nick=""):
    """按刚发出的文本反查唯一 sid，再把主页写进案情包。"""
    if not db or not prof:
        return None
    try:
        from brain import casepack as CP
        sid = CP.find_sid(db, text, device=dev, tries=2)
        if sid:
            CP.save_profile(sid, prof)
            log.info("🔔 主页已写入案情包 %r sid=%s", nick or prof.get("nick") or "?", sid)
        else:
            log.warning("🔔 主页已抓到但反查不到唯一 sid，暂不写（宁可不写不可写错人）")
        return sid
    except Exception as e:
        log.warning("🔔 保存主页档案异常: %r", e)
        return None


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


# 🔴 2026-11-12（HY-11）：铃消失后 UI 树里还残留「同城奇遇 / 关闭弹窗」文本，
#   若每轮都去 OCR 找「立即私聊」，一次白烧 ~2.5s（实测）。这里做**最近一次
#   OCR 确实没找到按钮**的记忆：残留文本 + 刚 OCR 过且没按钮 → 直接判「已消失」
#   跳过 OCR，直到过了 RESIDUAL_SKIP_S 再给一次机会（铃真弹出时按钮会回来）。
#   只影响「省一次 OCR」，绝不改变 is_bell 的返回语义。
RESIDUAL_SKIP_S = float(os.environ.get("SOUL_BELL_RESIDUAL_SKIP", "30") or 30)
_RESIDUAL = {"ts": 0.0}


def is_bell(snap=None, dev=None):
    """当前是不是弹着奇遇铃。

    🔴 判据优先级（2026-11-02 实弹教训）：
      铃消失后，UI 树里**还残留**「同城奇遇 / 关闭弹窗」这些文本节点，
      只按树判断会一直报「有铃」，然后 OCR 又找不到按钮 → 空转。
      所以：**给了 dev 就以 OCR 找到「立即私聊」为准**（按钮存在才是真铃）；
      没给 dev 才退回树判断（供不需要点击的场合用）。

    🔴 2026-11-12（HY-11）：残留文本 + 最近一次 OCR 没找到按钮 → 直接 False，
      不再每次花 2.5s OCR（铃消失后残留可能持续好几个动作轮）。
    """
    import time as _t
    try:
        hinted = None
        if snap is not None:
            txt = " ".join(snap.texts())
            hinted = any(k in txt for k in BELL_HINTS)
            # 树里一点迹象都没有 -> 直接 False，不必花 2.5s 去 OCR
            if not hinted and dev is not None:
                return False
        if dev is not None:
            if hinted:
                # 残留文本但刚 OCR 过且没按钮 → 视为已消失，跳过本次 OCR
                if _t.time() - _RESIDUAL["ts"] < RESIDUAL_SKIP_S:
                    return False
            hit = find_button(dev)
            if hit is None:
                _RESIDUAL["ts"] = _t.time()   # 记住「这次没找到按钮」
            return hit is not None
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


def handle(actor, dev, dry_run=False, db=None):
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

        from brain import match as M
        try:
            said, bubbles = M.said_already(dev, s2)
        except Exception as e:
            log.warning("奇遇铃已有消息检查失败（按未发处理）: %r", e)
            said, bubbles = False, []
        if said:
            log.info("🔔 奇遇铃对象已有消息（气泡 %d 条）→ 不重复发", len(bubbles))
            actor.hand.back(settle=1.0)
            return True, "已有消息"

        # 用户口径：奇遇铃也要先看主页；主页明确“不撩/不约”的直接跳过。
        prof = None
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("🔔 铃对象主页: %r %r", prof.get("nick"), prof.get("tags"))
        except Exception as e:
            log.warning("铃对象建档异常（继续发送）: %r", e)
        block = profile_block_reason(prof)
        if block:
            log.info("🔔 跳过奇遇铃对象 %r：主页明确写「%s」", nick or "?", block)
            actor.hand.back(settle=1.0)
            return True, "主页拒绝暧昧(%s)" % block

        if dry_run:
            log.info("[dry] 已进铃会话，不发送")
            actor.hand.back(settle=1.0)
            return True, "dry"

        text = M.pick_opener()
        # 新会话开场白无 sid → 走 match.send 的 sid="" 分支，过闸但不占跟进额度
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("✓ 奇遇铃已发: %r", text)
            _save_profile_after_send(actor, dev, db, prof, text, nick)
        else:
            log.warning("奇遇铃发送失败: %s", why)

        actor.hand.back(settle=1.2)
        return ok, why
    except Exception as e:
        log.warning("奇遇铃处理异常（已兜住）: %r", e)
        try:
            actor.hand.back(settle=1.0)
        except Exception:
            pass
        return False, repr(e)


def _find_list_entry(snap):
    for n in snap.nodes:
        if not n.visible:
            continue
        if (n.text or "").strip() == "奇遇铃-稍后再聊":
            return n
    return None


def open_list(actor, max_scrolls=4):
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
    if detect(snap) != "chatlist":
        try:
            from brain import nav
            snap, pg = nav.to_chatlist(actor)
            if pg != "chatlist":
                return False, "不在会话列表(%s)" % pg
        except Exception as e:
            return False, "回会话列表失败: %r" % e

    node = _find_list_entry(snap)

    # 2026-11-13 实测：清完红点后列表常停在中间，入口明明存在却只搜当前屏
    # 会误报“没有入口”。先向下滑回顶部，再向上翻几屏；每次重新 dump。
    if node is None:
        for _ in range(max(1, max_scrolls)):
            try:
                actor.hand.swipe(450, 420, 450, 1340, duration=0.18, settle=0.5)
            except Exception:
                break
            snap = actor.snap(force=True)
            node = _find_list_entry(snap)
            if node is not None:
                break

    if node is None:
        for _ in range(max(1, max_scrolls)):
            try:
                actor.hand.swipe(450, 1320, 450, 520, duration=0.35, settle=0.7)
            except Exception:
                break
            snap = actor.snap(force=True)
            if is_bell_list(snap):
                return True, "已在稍后再聊列表"
            node = _find_list_entry(snap)
            if node is not None:
                break
            if detect(snap) != "chatlist":
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
    # 🔴 2026-11-10 §111（P0 误发）：同一行的「昵称 / 相同点：xxx / Ta距离Nkm」三个文本
    #   节点全部满足上面的筛选条件 → 被当成 3 个人 → 每个都点同一行、各发一条开场白
    #   （实测 16:35 给「陈陈星」连发 3 条：「我这边刚忙完…」「我可以先讲讲我自己…」
    #    「我这人话不多…」）。实测行高约 104px、真实两行中心相距 ~164px，
    #   所以按行中心 y 聚类（阈值 60），同一行只留**最靠上**的那个（主体昵称）。
    _picked = []
    for _n in sorted(nicks, key=lambda x: (x.bounds[1], x.bounds[0])):
        _cy = (_n.bounds[1] + _n.bounds[3]) // 2
        if any(abs(_cy - _p[0]) <= 60 for _p in _picked):
            continue
        _picked.append((_cy, _n))
    nicks = [x[1] for x in _picked]
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


def handle_list(actor, dev, dry_run=False, limit=None, db=None, uid="", max_scrolls=8):
    """把「奇遇铃-稍后再聊」里的人逐个聊起来。返回 (n_ok, 说明)。

    用户 2026-11-08：「奇遇铃 稍后再聊 里面有三个人等着对话啊，优先级奇遇铃不是最高吗」
    —— 这条链路必须并入奇遇铃最高优先级，且每个都要**发开场白 + 进主页建档**。

    2026-11-13 用户口径：这里的人要尽量清空，不再按 3 人/天硬截断。
    一轮只做一小批（BELL_BATCH_MAX），后续轮次继续；同一人用三态去重：
      ① 会话里已有我的气泡 → 不发；
      ② 持久台账记录已发/已跳过；
      ③ 发送失败冷 30 分钟再试。

    每处理一个：点行 → 确认进会话 → 已有消息检查 → 先看主页 → 发开场白
    → 反查唯一 sid 写案情包 → 返回列表。
    处理完一个后**重新 dump 列表**（行会消失/上移，不能缓存坐标）。
    """
    from brain import match as M

    limit = max(1, int(limit or BELL_BATCH_MAX))
    done = 0
    skipped = 0
    attempted = 0
    tried = set()
    scrolls = 0
    ledger = _ledger_load(uid)

    def _mark(key, status, nick="", tag="", row_ts="", retry_after=0):
        at = time.time()
        ledger["opened"][key] = {
            "at": at,
            "status": status,
            "nick": nick,
            "tag": tag,
            "row_ts": row_ts,
            "retry_after": retry_after,
        }
        if nick:
            ledger.setdefault("nicks", {})[nick] = {
                "at": at,
                "status": status,
                "retry_after": retry_after,
            }
        _ledger_save(uid, ledger)

    max_loops = max(12, limit * 4 + max_scrolls)
    for _ in range(max_loops):
        if done >= limit:
            break
        snap = actor.snap(force=True)
        if not is_bell_list(snap):
            if done == 0:
                return 0, "不在稍后再聊列表(%s)" % detect(snap)
            break

        rows = bell_list_rows(snap)
        unseen = []
        for r in rows:
            key = _row_key(r[0], r[3], r[4])
            if key in tried or _ledger_seen(uid, key, nick=r[0], data=ledger):
                continue
            unseen.append((r, key))

        if not unseen:
            if scrolls >= max_scrolls:
                break
            before = tuple(_row_key(r[0], r[3], r[4]) for r in rows)
            try:
                # 手指上滑 = 看列表更靠下的人。动作后强制重取，不能复用旧帧。
                actor.hand.swipe(450, 1320, 450, 620, duration=0.35, settle=0.8)
            except Exception as e:
                log.warning("奇遇铃列表滚动异常: %r", e)
                break
            s2 = actor.snap(force=True)
            if not is_bell_list(s2):
                break
            after = tuple(_row_key(r[0], r[3], r[4]) for r in bell_list_rows(s2))
            scrolls += 1
            if before and before == after:
                log.info("奇遇铃列表已到底（滚动 %d 次无变化）", scrolls)
                break
            continue

        (nick, cx, cy, tag, ts), key = unseen[0]
        tried.add(key)
        attempted += 1
        log.info("🔔 稍后再聊：%r（%s %s）→ 点进会话", nick, tag, ts)
        actor.hand.tap_xy(450, cy, settle=2.5)
        s2 = actor.snap(force=True)
        pg = detect(s2)
        if pg != "chat":
            log.warning("点 %r 后没进会话（page=%s）→ 跳过", nick, pg)
            _mark(key, "failed", nick, tag, ts, time.time() + BELL_FAIL_RETRY_S)
            skipped += 1
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue

        try:
            said, bubbles = M.said_already(dev, s2)
        except Exception as e:
            log.warning("稍后再聊已有消息检查失败（按未发处理）: %r", e)
            said, bubbles = False, []
        if said:
            log.info("🔔 稍后再聊 %r 已有我的消息（气泡 %d 条）→ 不重复发", nick, len(bubbles))
            _mark(key, "already", nick, tag, ts)
            skipped += 1
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

        prof = None
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("🔔 稍后再聊主页 %r: %s", nick, prof.get("nick"))
        except Exception as e:
            log.warning("稍后再聊主页异常（继续发送）: %r", e)
        block = profile_block_reason(prof)
        if block:
            log.info("🔔 跳过稍后再聊 %r：主页明确写「%s」", nick, block)
            _mark(key, "blocked", nick, tag, ts)
            skipped += 1
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue

        text = M.pick_opener()
        # 新会话开场白无 sid → 走 match.send 的 sid="" 分支，过闸但不占跟进额度
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("✓ 稍后再聊已发 %r: %r", nick, text)
            _mark(key, "sent", nick, tag, ts)
            _save_profile_after_send(actor, dev, db, prof, text, nick)
        else:
            log.warning("稍后再聊发送失败 %r: %s", nick, why)
            _mark(key, "failed", nick, tag, ts, time.time() + BELL_FAIL_RETRY_S)
            skipped += 1
        if ok:
            done += 1
        try:
            actor.hand.back(settle=1.2)
        except Exception:
            pass
    return done, "稍后再聊已发 %d 人 / 跳过 %d / 检查 %d / 滚动 %d" % (
        done, skipped, attempted, scrolls)
