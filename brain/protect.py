# -*- coding: utf-8 -*-
"""平台「男性聊天保护」发送闸 —— 2026-11-22（PLAT-01/02）

## 平台规则（实测原文，设备库 chatmsg.msgType=35，2026-11-22）

    type    = male_chat_protect_tips
    content = "未获回复前最多发送2条消息，可以送礼获得会话置顶和额外通知，
               加速对方查看消息哦～"

第 3 条起服务端拒收：本地落 `msgStatus=5`（气泡上的红色感叹号），
同时插一条上述系统提示。当天实测命中 11 次 / 7 个会话 / 12 条 st=5。

## 为什么要加这道闸

`brain/match.py send()` 的 4 个调用方（bell:435 / bell:775 / clear:519 /
match:948）**一律传 sid=""**，而 `sendgate.allow("")` 直接返回
「无主会话（开场白），不纳入跟进额度」→ 匹配 / 奇遇铃 / 新招呼这条链路
完全不受跟进阶梯约束。2026-11-22 实测：24 个会话我方发了 3~6 条、她 0 条，
其中 7 个会话被平台拦下。

## 设计要点

1. `guard()`  —— 发送前裁决：她最后一条之后我方已发 >= LIMIT 条 → 拒绝。
   sid 为空时用 `guess_sid()` 兜底（最近 180s 内我方最后一条消息所在会话）；
   猜不到就是「新会话第 1 条」，放行 —— 绝不误拦开场白。
2. `verify()` —— 发送后复核：该会话已出现 platform 提示 → 判为被拒收，
   调用方据此停止记账，避免「已发」台账继续骗自己。
3. `ui_blocked()` —— 进会话就能判：页面文本里已有那句提示 → 直接不发，
   省掉一次注定失败的灌字 + 一次额度消耗。

所有函数 **fail-open**：任何异常降级放行，绝不掐死必回链路。
"""

from __future__ import annotations

import time

from core.log import get_logger

log = get_logger(__name__)

LIMIT = 2                                  # 平台硬规则：未获回复前最多 2 条
TIP_MARKS = ("未获回复前最多发送", "立即加速", "male_chat_protect")

# 进程内「当前会话」缓存：发送成功后刷新，供紧接着的下一次发送裁决。
_LAST_SID = {"sid": "", "ts": 0.0}


def _ctx(dev):
    """返回 (my_uid, db_name)；拿不到就 ("", "")。"""
    from data import imdb as IM
    uid = str(IM.current_uid(dev) or "")
    name = IM._db_name_for_uid(dev, uid) if uid else ""
    return uid, (name or "")


def _q(dev, name, sql):
    from data import imdb as IM
    try:
        return IM._dev_sql(dev, name, sql) or []
    except Exception as e:
        log.debug("protect 查询失败（降级）: %r", e)
        return []


def _esc(s):
    return str(s or "").replace("'", "''")


def _recent_sid(dev, within_s):
    uid, name = _ctx(dev)
    if not uid or not name:
        return ""
    since = int((time.time() - within_s) * 1000)
    rows = _q(dev, name,
              "select sessionId from chatmsg where msgType=1 and senderId='%s' "
              "and localTime>=%d order by localTime desc limit 1" % (uid, since))
    return str(rows[0][0]) if rows else ""


def guess_sid(dev, within_s=180):
    """当前会话猜测（仅 sid 为空的链路用）。猜不到返回 ""。"""
    if _LAST_SID["sid"] and (time.time() - _LAST_SID["ts"]) <= within_s:
        return _LAST_SID["sid"]
    return _recent_sid(dev, within_s)


def remember(dev, sid="", within_s=90):
    """发送后刷新「当前会话」缓存，返回最新 sid（可能为空）。"""
    sid = str(sid or "") or _recent_sid(dev, within_s)
    if sid:
        _LAST_SID["sid"] = sid
        _LAST_SID["ts"] = time.time()
    return sid


def stats(dev, sid):
    """返回 (她最后一条之后我方已发条数, 该会话平台限发提示数)；不可读返回 None。"""
    uid, name = _ctx(dev)
    if not uid or not name or not sid:
        return None
    sid_e = _esc(sid)
    her = _q(dev, name,
             "select ifnull(max(localTime),0) from chatmsg where msgType=1 "
             "and sessionId='%s' and senderId<>'%s'" % (sid_e, _esc(uid)))
    her_ts = int(her[0][0] or 0) if her else 0
    mine = _q(dev, name,
              "select count(*) from chatmsg where msgType=1 and sessionId='%s' "
              "and senderId='%s' and localTime>%d" % (sid_e, _esc(uid), her_ts))
    tips = _q(dev, name,
              "select count(*) from chatmsg where msgType=35 and sessionId='%s' "
              "and localTime>%d and msgContent like '%%male_chat_protect%%'" % (sid_e, her_ts))
    n_mine = int(mine[0][0] or 0) if mine else 0
    n_tips = int(tips[0][0] or 0) if tips else 0
    return n_mine, n_tips


def guard(dev, sid="", n_lines=1):
    """发送前裁决。返回 (ok, 说明)。"""
    try:
        if not sid:
            sid = guess_sid(dev)
            if not sid:
                return True, "新会话第 1 条（无在途会话）"
        st = stats(dev, sid)
        if st is None:
            return True, "库不可读，降级放行"
        mine, tips = st
        tail = str(sid)[-8:]
        if tips > 0:
            return False, "平台已限发：她未回复且已出现限发提示(sid=...%s)" % tail
        if mine + max(1, int(n_lines)) > LIMIT:
            return False, "她未回复，我方已发 %d/%d 条上限(sid=...%s)" % (mine, LIMIT, tail)
        return True, "未获回复 %d/%d(sid=...%s)" % (mine, LIMIT, tail)
    except Exception as e:
        log.debug("protect.guard 异常降级放行: %r", e)
        return True, "保护闸异常降级放行: %r" % (e,)


def verify(dev, sid=""):
    """发送后复核。返回 (ok, 说明)。"""
    try:
        sid = sid or _LAST_SID["sid"]
        if not sid:
            return True, "无 sid，跳过复核"
        st = stats(dev, sid)
        if st is None:
            return True, "库不可读，跳过复核"
        mine, tips = st
        if tips > 0:
            return False, "平台限发(未获回复最多%d条)→本条被拒" % LIMIT
        return True, "ok(%d/%d)" % (mine, LIMIT)
    except Exception as e:
        return True, "复核异常降级: %r" % (e,)


def ui_blocked(actor):
    """当前会话页是否已显示平台限发提示（进了会话就能判，最省事）。"""
    try:
        s = actor.snap(force=True)
        txt = "\n".join(s.texts())
        return any(m in txt for m in TIP_MARKS)
    except Exception:
        return False
