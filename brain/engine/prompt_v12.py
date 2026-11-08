# -*- coding: utf-8 -*-
"""提示词组装（v10）。

与旧 V9 的差别只有三处，但都是实测出来的病根：

① **档案里的「事实」分两栏**：`她说过` / `我说过`。
   旧版把两者混成一行「事实：」，实测把「我开网店卖电脑配件」写成了她的事实
   （prompt 自己标注"违反即整份画像作废"级），模型于是跟她说"守店的是你"。

② **「这一轮」给正面素材，不给禁令清单**。
   旧版 L1 的形态是【定档：撩】+【绝对别做 1~5 条禁令】。实测 4 个真实会话：
   有 L1 时 4/4 出安全句、无 L1 时 3/4 明显更好 —— 因为大模型对负面约束的遵守率
   远高于正面引导，"禁止解释/禁止问句"它一定执行，"撩"它不知道怎么做，
   结果话被削得越来越安全，每个坑都躲开了，也没踩到任何一个点。
   新版 brief 给的是：她这句里能接的具体词 + 一个可改写的开口。

③ **方向只认一处**。旧版 L0（画像）说「稳一稳」、L1（军师）说「撩」，
   两条都进 system，模型没有裁决规则只能折中 → 四平八稳。
   新版写明「方向只看【这一轮】这一段，档案里的判断不参与本轮决定」。

顺序（稳定 → 易变，为了前缀缓存命中；2026-11-03 实测该排法命中率 59%→77%）：
    人设（稳） → 档案（慢变） → 这一轮（每轮变） → 现在（每轮变） → 输出（稳）
"""
import os
import re
import time

from . import persona
from . import llm
from brain.pack import store

L2_MAX_AGE_H = float(os.environ.get("SOUL_L2_MAX_AGE_H", "6") or 6)
L2_KEEP = int(os.environ.get("SOUL_L2_KEEP", "20") or 20)
TURNS_INJECT_CHARS = int(os.environ.get("SOUL_PACK_L2_CHARS", "12000"))

OUTPUT_SPEC = (
    "【输出】只输出要发给她的那一两句话：口语、像人话、一条 7~20 字；两句就分两行，"
    "别堆成一大段。不要解释、不要编号、不要分析、不要引号。\n"
    "· 这一轮必须带一个具体问题（她一句话就能答的），整轮只有一个问句；"
    "上一条你已经在问，这条就不许再问。\n"
    "· 她末条是收尾（睡了/晚安/困了/不聊了/拜拜/去忙了）→ 只发一条，8 字以内，不提问。\n"
    "档案里的信息只当背景，别当面点破（不许说「你主页写着…」），"
    "也不许把没聊过的事说成她说过；她提过的细节隔几轮可以自然带一句，同一件只提一次。"
)


# ────────────────────────── 档案 ──────────────────────────
def _profile_block(sid):
    p = store.read_profile(sid)
    if not p:
        return ""
    order = ("昵称", "引力签", "共同点", "匹配度", "IP属地", "标签", "瞬间", "灵魂画像")
    lines = []
    for k in order:
        v = p.get(k)
        if v:
            lines.append("- %s：%s" % (k, v))
    if not lines:
        return ""
    return ("## 她的主页（匹配时抓的静态信息；与她在对话里说的冲突时，以对话为准）\n"
            + "\n".join(lines))


def _facts_block(sid):
    f = store.read_facts(sid)
    hers = [x.get("t") for x in f["hers"] if x.get("t")]
    mine = [x.get("t") for x in f["mine"] if x.get("t")]
    if not hers and not mine:
        return ""
    out = ["## 已知事实（分清楚是谁的）"]
    if hers:
        out.append("### 她的（她自己说过的）")
        out += ["- " + t for t in hers[:20]]
    if mine:
        out.append("### 我的（我自己说过的，**不是她的**，别安到她头上）")
        out += ["- " + t for t in mine[:12]]
    return "\n".join(out)


def _age_note(turns_text):
    """L2 时效兜底：末条距今太久时只注入最近 N 行并显式标注。

    旧版血泪：某个会话长期没被处理，几天前的话题被模型当成刚刚发生
    （实测：L2 停在 10-27「炒面」→ 输出「想尝一口」）。
    """
    lines = [x for x in turns_text.splitlines() if x.strip()]
    if not lines:
        return "", 0.0
    m = re.match(r"^- (\d{2})-(\d{2}) (\d{2}):(\d{2})", lines[-1])
    if not m:
        return turns_text, 0.0
    now = time.localtime()
    try:
        ts = time.mktime((now.tm_year, int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)), 0, 0, 0, -1))
        if ts > time.time() + 86400:                      # 跨年
            ts = time.mktime((now.tm_year - 1, int(m.group(1)), int(m.group(2)),
                              int(m.group(3)), int(m.group(4)), 0, 0, 0, -1))
        age_h = (time.time() - ts) / 3600.0
    except Exception:
        age_h = 0.0
    if age_h > L2_MAX_AGE_H:
        n = min(L2_KEEP, len(lines))
        head = ("（注意：你俩上一次说话是 **%.0f 小时前**；下面只保留最近 %d 行，"
                "更早的省略了，不要把它当成刚刚发生的事。）\n" % (age_h, n))
        return head + "\n".join(lines[-n:]), age_h
    return turns_text, age_h


def _turns_block(sid, hist=None):
    t = store.read_turns(sid, limit_chars=TURNS_INJECT_CHARS)
    if t:
        body, age_h = _age_note(t)
        return "## 你俩的对话（时间顺序，最近的在最后）\n" + body, age_h
    if hist:
        buf = []
        for h in hist:
            role = "我" if (h or {}).get("role") == "me" else "她"
            txt = str((h or {}).get("text") or "").strip()
            if txt:
                buf.append("- %s: %s" % (role, txt))
        if buf:
            return "## 你俩的对话（时间顺序，最近的在最后）\n" + "\n".join(buf), 0.0
    return "", 0.0


# ────────────────────────── 这一轮 ──────────────────────────
_BRIEF_DROP = re.compile(r"^\s*(?:[-*·]|\d+[.、])\s*")


def _brief_block(sid, her_msg=""):
    """把 brief.md 渲染成「这一轮」段。没有 / 过期就返回空（不硬编）。"""
    from .brief import STAMP_RE, her_stamp
    raw = store.read_brief(sid)
    if not raw:
        return ""
    m = STAMP_RE.match(raw)
    if m:
        raw = raw[m.end():]
        # 不是针对她这条消息生成的 → 当没有。过期简报比没有简报更坏：
        # 它会把「这一轮该说什么」指向上一轮的话题（2026-11-05 实测）。
        if her_msg and m.group(1) != her_stamp(her_msg):
            return ""
    body = raw.strip()
    if not body:
        return ""
    return ("【这一轮·素材】\n"
            "下面是参谋给的素材，用得上就用，用不上就丢，**方向不由它决定** —— "
            "往哪走看【当前关系】那一段。\n"
            "「一个开口」只是示范，**必须用你自己的话重写**，照抄原句视为不合格。\n"
            + body)


# ────────────────────────── 现在 ──────────────────────────
def _now_block():
    try:
        from brain import env
        return (env.now_bg() or "").strip()
    except Exception:
        pass
    # 兜底：至少给时间，不编天气
    return "【现在】%s · %s" % (
        time.strftime("%m月%d日 %H:%M"), _weekday_cn())


def _weekday_cn():
    return "周" + "一二三四五六日"[time.localtime().tm_wday]


# ────────────────────────── 组装 ──────────────────────────
def build(her_msg, sid="", hist=None, restart_h=0.0):
    """返回 (system, user, meta)。meta 只用于日志排查，不进 prompt。"""
    restart = float(restart_h or 0.0) > 0.0
    rdays = max(1.0, float(restart_h or 0.0) / 24.0)

    blocks = list(persona.system_blocks())

    arch = []
    if sid:
        b = _profile_block(sid)
        if b:
            arch.append(b)
        b = _facts_block(sid)
        if b:
            arch.append(b)
        # 重新开场：不注入旧对话（留着它模型必然接着几天前的话头说＝翻旧账）
        if not restart:
            b, age_h = _turns_block(sid, hist)
            if b:
                arch.append(b)
    elif hist:
        b, age_h = _turns_block("", hist)
        if b:
            arch.append(b)

    blocks.append("【她的档案】\n" + ("\n\n".join(arch) if arch else
                                     ("（暂无档案；按她的类型判断，别问具体经历）" if restart
                                      else "（暂无档案，按她这句话判断）")))

    brief_len = 0
    if not restart and sid:
        b = _brief_block(sid, her_msg)
        if b:
            blocks.append(b)
            brief_len = len(b)
        # 关系档位放在简报之后 —— 它是**本轮方向**的唯一来源，离她的消息越近权重越高。
        # 2026-11-05：原来放在简报之前，实测模型只照简报的「一个开口」走，
        # 「必须推进」那条被当背景忽略，308 轮的会话照旧原地陪聊。
        try:
            from brain import stage
            st = stage.line(sid, her_msg)
            if st:
                blocks.append(st)
        except Exception:
            pass

    now = _now_block()
    if now:
        blocks.append(now)

    if restart:
        blocks.append(
            "【重新开场·这一轮不是接她的话】\n"
            "你俩上一次说话是 %.0f 天前，中间断了很久 —— 她那条旧消息不用回、也不要提。\n"
            "· 像重新认识一样，主动起一个新由头，让她好接。\n"
            "· 由头只许用你确实在过的日子，不许编某天某地的具体事件。\n"
            "· 一句，10~22 字，末尾带一个一句话就能答的小问题，别连着问两个。\n"
            "· 不许出现：好久不见 / 这么久没联系 / 最近怎么样 / 还记得我吗 / "
            "上次说到 / 你之前说 / 抱歉刚看到 / 在吗。" % rdays)
        user = ("【这一轮不是接她的话】\n"
                "（你俩上一次说话是 %.0f 天前；她那条旧消息不用回、也不要提。"
                "现在你要主动重新起一句话。）" % rdays)
    else:
        user = "【她刚发来的消息】\n" + (her_msg or "")

    blocks.append(OUTPUT_SPEC)
    system = "\n\n".join(x for x in blocks if x and x.strip())

    meta = {"sys_len": len(system), "user_len": len(user),
            "brief_len": brief_len, "restart": restart,
            "arch_blocks": len(arch)}
    return system, user, meta


__all__ = ["build", "OUTPUT_SPEC", "L2_MAX_AGE_H", "L2_KEEP"]
