# -*- coding: utf-8 -*-
"""案情包：沿用旧脚本 `soul_pack`（E:\\soul2.1\\brain\\soul_pack.py）的存储格式。

为什么不另起一套（用户 2026-11-02「看旧脚本的案情包」）：
  旧案情包已经按 sid 分了 L0/L1/L2/L3/L4 五层，且**旧出话引擎会去读它**
  （`opening_line` 里 `PACK.read_l0/read_l4`，`brain_reply` 里 build_user_block）。
  新代码往别处写，等于引擎读不到；只有写回同一个 L4，主页资料才真正被用上。

L4 原文格式（旧脚本 `_dump_l4`）：
    # L4 她的资料（匹配时抓的静态信息 + 对话中确认的事实）
    ## 个人主页
    - 昵称：予安
    - 匹配度：96%
    - 引力签：德云社
    - 共同点：重庆、白羊座
    - IP属地：重庆
    - 灵魂画像：务实家 53天
    - 标签：职场打工人、已婚、音乐爱好者
    - 瞬间：有没有好看的动漫短剧推荐呀？？
"""
import os
import re
import sys

from core.log import get_logger
from brain.pack import store

log = get_logger("brain.casepack")

_PACK = store


def engine():
    """兼容旧调用点：返回 v3 存储模块。"""
    return _PACK


PROFILE_NOTE = "静态抓取（个人主页）；**与她在对话里说的不一致时，一律以对话为准**"


def has_profile(sid):
    """是否已有实义主页字段（昵称 / IP / 引力签 / 标签 任一）。"""
    if not sid:
        return False
    p = store.read_profile(sid)
    return any(p.get(k) for k in ("昵称", "IP属地", "引力签", "标签"))


def save_profile(sid, prof, tags=None, common=None):
    """把对方主页资料写进 L4「个人主页」段（合并，不覆盖已有非空项）。

    prof 来自 eyes.profile.read()。返回 True/False。
    """
    if not sid:
        return False
    prof = prof or {}
    # 🔴 2026-11-10（演示实弹污染 ×2）：点错头像/进错页面时，P.read 会把
    #    功能按钮文案当昵称写进档案（实测「切换用户」「我好睡得很[笑哭]」）。
    #    写前黑名单校验：昵称含按钮/导航词 → 判定进错页，整包不写。
    _BAD_NICK = ("切换用户", "加速", "关注后可邀请通话", "返回", "更多",
                 "文明聊天", "查看主页", "送TA", "桌球", "醒脑咖啡")
    _nick = (prof.get("nick") or "").strip()
    if _nick and any(b in _nick for b in _BAD_NICK):
        log.warning("主页昵称=%r 命中功能词黑名单 → 判定进错页面，拒绝写档案 sid=%s",
                    _nick, str(sid)[-8:])
        return False
    kv = {}
    if prof.get("nick"):
        kv["昵称"] = prof["nick"]
    if prof.get("match_pct"):
        kv["匹配度"] = str(prof["match_pct"])
    if prof.get("ip"):
        kv["IP属地"] = prof["ip"]
    if prof.get("soul"):
        kv["灵魂画像"] = ("%s %s" % (prof["soul"], prof.get("days") or "")).strip()
    t = prof.get("tags") or tags
    if t:
        kv["标签"] = "、".join(t[:8]) if isinstance(t, (list, tuple)) else str(t)
    if common:
        kv["共同点"] = common if isinstance(common, str) else "、".join(common)
    if prof.get("moments"):
        kv["瞬间"] = " ／ ".join(str(m)[:60] for m in prof["moments"][:3])
    if prof.get("follow") or prof.get("fans"):
        kv["关注数"] = "关注%s 被关注%s 礼物%s" % (
            prof.get("follow") or "-", prof.get("fans") or "-", prof.get("gifts") or "-")
    for k in ("引力签", "grav", "gravity"):
        v = prof.get(k)
        if v:
            kv["引力签"] = v if isinstance(v, str) else "、".join(v)
            break
    kv["信息来源"] = PROFILE_NOTE
    try:
        store.write_profile(sid, **kv)
        if prof.get("nick"):
            store.write_meta(sid, nick=prof["nick"])
        return True
    except Exception as e:
        log.warning("写主页失败: %r", e)
        return False


def ensure_profile(actor, sid, db=None):
    """没有个人主页档案的，趁现在在会话页进去补一次（用户 2026-11-02 要求）。

    主页是静态抓取，可能与她在对话里说的不一致 ——
    L4 里会带一行「与对话冲突时以对话为准」（PROFILE_NOTE）。
    返回是否真的补了。

    🔴 2026-11-03（用户现场「发出去之后还有一次瞎操作误点」）：
        发送后自动进主页，会在会话页多一次点击（点「查看主页」/头像/顶部昵称），
        而且「顶部昵称」兜底可能点空 → 旧代码盲按返回，把会话页退掉。
        默认**关闭**发送后建档；需要时设 `SOUL_PROFILE_AFTER_SEND=1`。
        匹配卡片那条路径（match.run_once）不受影响，仍会建档。
    """
    if os.environ.get("SOUL_PROFILE_AFTER_SEND", "0") != "1":
        return False
    if not sid or has_profile(sid):
        return False
    try:
        from brain import match as M      # 运行时导入，避开循环依赖
        prof, ok = M.visit_profile(actor)
        if not ok or not prof:
            return False
        save_profile(sid, prof)
        log.info("补建个人主页 sid=%s %r", sid, prof.get("nick"))
        # 🧠 主页刚补齐 → 让本地模型据此重算画像（用户 2026-11-02：
        #    「本地模型补对方人设 / 个人主页 / 出方案」）
        try:
            from brain import reply as _R
            _R.warm_local(sid, db, nick=prof.get("nick") or "")
        except Exception as _e:
            log.debug("本地分析投递异常（不影响回复）: %r", _e)
        return True
    except Exception as e:
        log.warning("补建档案异常（不影响回复）: %r", e)
        return False


def load(sid):
    """把 profile.json 渲染成文本（给 legacy 路径的 case 拼装用）。"""
    if not sid:
        return ""
    p = store.read_profile(sid)
    if not p:
        return ""
    order = ("昵称", "引力签", "共同点", "匹配度", "IP属地", "灵魂画像", "标签", "瞬间", "关注数")
    lines = ["## 个人主页"]
    for k in order:
        if p.get(k):
            lines.append("- %s：%s" % (k, p[k]))
    return "\n".join(lines)


def find_sid(db, text, device=None, tries=3):
    """找刚发出去那条消息的 sessionId。**查不到就返回 None，绝不猜**。

    两个实测教训（2026-11-02）：
      ① `db` 是脚本开头 open_account 拿的，之后没刷新，新消息还在设备上
         -> 每次重试都要重新拉库。
      ② 曾经「反查不到就退化为 session 表最新一条」—— 结果第 2 轮的新消息还没
         入库时拿到了第 1 轮的会话，把 B 的资料写进 A 的案情包（串号）。
         **案情包写错人比不写更糟**，所以只接受唯一文本命中。
    """
    import time

    kw = (text or "").strip()[:14]
    if len(kw) < 4:
        return None
    for i in range(tries):
        if device is not None and i > 0:
            try:
                from data import imdb
                db = imdb.open_account(device)
            except Exception as e:
                log.warning("重新拉库失败: %r", e)
        try:
            hit = db.sessions_for_texts([kw])
        except Exception as e:
            log.warning("反查 sid 异常: %r", e)
            hit = []
        if len(hit) == 1:
            return hit[0][0]
        if len(hit) > 1:
            log.warning("反查 %r 命中 %d 个会话，无法确定，放弃建档", kw, len(hit))
            return None
        time.sleep(2.0)
    log.warning("反查不到 %r 的会话（库可能还没同步），跳过建档", kw)
    return None
