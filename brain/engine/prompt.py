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
    人设（稳） → 规则（稳） → 档案（慢变） → 这一轮（每轮变） → 现在（每轮变） → 输出（稳）

2026-11-05：本文件只做**组装**。人设正文在 persona.py，规则正文（含输出规格）
在 rules.py；这里除段落表头/兜底文案外不再写规则条款。
"""
import os
import re
import time

from . import rules
from . import llm
from brain.pack import store

L2_MAX_AGE_H = float(os.environ.get("SOUL_L2_MAX_AGE_H", "6") or 6)
L2_KEEP = int(os.environ.get("SOUL_L2_KEEP", "20") or 20)
TURNS_INJECT_CHARS = int(os.environ.get("SOUL_PACK_L2_CHARS", "12000"))

# 2026-11-05：规则正文已统一收进 rules.py，这里只保留别名，
# 让外部 `from prompt import OUTPUT_SPEC` 的老调用点继续可用（内容逐字未改）。
OUTPUT_SPEC = rules.OUTPUT_SPEC


# ── 动态推进警报（2026-11-07 用户拍板 B：48h 实测 61 个深聊仅 2 次推进）──
# 🔴 2026-11-08 重写（用户授权 + 实证）：
#   旧版触发条件是 `len(my) >= 8` —— 数的是**我方**条数。
#   于是「我说了 8 句」就算热会话，直接推「加个好友」，
#   完全不管她这 8 轮里只回了「嗯」「哦」「好」。
#   实测（账号1 全量 8497 条她的回复）：
#     · 她 ≤4 字占 52.8%，≤8 字占 83%
#     · 她主动开过场的会话只有 12/945 = 1.3%
#     · 她高质量回复（≥10 字或带问句）只占 17.9%
#   新判据：**只看她的投入**，不看我说了多少。
_ADV_RE = re.compile(r"微信|加.{0,2}好友|电话|见面|过来耍|找你玩|出来耍|出去玩|带你去|约你")
_SIG_RE = re.compile(
    r"一个人|无聊|没人陪|没人聊|周末|没事做|住哪|你在哪|离得近|想去|出去玩|睡不着|在家吗|在家么|在干啥|干嘛呢")
# 「她投入」的正向信号：她说得长、她反问、她主动给信息
_HER_RICH_RE = re.compile(r"[？?]|我(?:觉得|今天|昨天|最近|家|妈|爸|工作|朋友|想吃|想去|喜欢)")
# 「她敷衍」的信号：整条就是这几个字
_HER_COLD = {"嗯", "嗯嗯", "哦", "哦哦", "好", "好的", "好吧", "好嘛", "行", "是", "是的",
             "对", "对啊", "没有", "没", "不知道", "哈", "哈哈", "哈哈哈", "哈哈哈哈",
             "呵", "呵呵", "切", "唉", "额", "呃", "噢", "噢噢", "嗯呐", "在", "。"}


def her_stats(turns_body):
    """从对话记录里算她的投入度。返回 dict（全是 0~1 的分量 + 原始计数）。

    这是全项目**唯一**一处真正度量「她付出了多少」的地方。
    2026-11-08 之前，代码里没有任何一处统计她的投入 —— 所有「推进」判据
    都在数我方说了几句、过了几轮，这就是「聊了很久没进展」的制度性原因。
    """
    lines = [l for l in (turns_body or "").splitlines() if l.startswith("- ")]
    her, mine = [], []
    for l in lines:
        body = l[2:].strip()
        # 行格式实为 `- MM-DD HH:MM 我: 内容` / `- MM-DD HH:MM 她: 内容`
        # （store.read_turns 写的时间戳在前），所以不能 startswith，
        # 必须找 ` 我: ` / ` 她: ` 这个分隔。
        if " 她: " in body:
            her.append(body.split(" 她: ", 1)[1].strip())
        elif " 她：" in body:
            her.append(body.split(" 她：", 1)[1].strip())
        elif " 我: " in body:
            mine.append(body.split(" 我: ", 1)[1].strip())
        elif " 我：" in body:
            mine.append(body.split(" 我：", 1)[1].strip())
        elif body.startswith("她:") or body.startswith("她："):
            her.append(body[2:].strip())
        elif body.startswith("我:") or body.startswith("我："):
            mine.append(body[2:].strip())
    if not her:
        return {"n_her": 0, "n_mine": 0, "avg_len": 0.0, "ask_rate": 0.0,
                "cold_rate": 0.0, "rich_rate": 0.0, "score": 0.0}
    n = len(her)
    lens = [len(x) for x in her]
    avg_len = sum(lens) / float(n)
    ask = sum(1 for x in her if re.search(r"[？?]", x)) / float(n)
    cold = sum(1 for x in her if x.strip() in _HER_COLD) / float(n)
    rich = sum(1 for x in her if len(x) >= 10 or _HER_RICH_RE.search(x)) / float(n)
    # 分数：字数 0.35 / 反问 0.25 / 内容 0.25 / 不敷衍 0.15
    score = (0.35 * min(1.0, avg_len / 12.0)
             + 0.25 * min(1.0, ask / 0.20)
             + 0.25 * min(1.0, rich / 0.30)
             + 0.15 * (1.0 - cold))
    return {"n_her": n, "n_mine": len(mine), "avg_len": avg_len, "ask_rate": ask,
            "cold_rate": cold, "rich_rate": rich, "score": round(score, 3)}


def _her_block(her_msg, turns_body):
    """按她的投入度给本轮**硬方向**。这是「她付出」这件事唯一落地的地方。

    分档阈值来自实测分布（账号1）：
      score < 0.30 → 冷（她那 52.8% 的 ≤4 字回复基本都落这档）
      0.30~0.50   → 温（正常能聊，但没给额外东西）
      0.50~0.70   → 热（她开始给内容/反问）
      >= 0.70     → 燃（她会主动、会说长句 —— 实测这类会话占比极低，正是要争取的）
    """
    s = her_stats(turns_body)
    cur = (her_msg or "").strip()
    cur_cold = bool(cur) and (cur in _HER_COLD or len(cur) <= 3)
    # 本轮她这条本身是冷的 → 拉低一档（当场反应比历史均值更重要）
    sc = s["score"]
    if cur_cold and sc > 0.0:
        sc = max(0.0, sc - 0.15)
    if s["n_her"] == 0:
        # 没有历史：只看她这一条
        sc = 0.25 if cur_cold else (0.55 if len(cur) >= 10 else 0.40)

    if sc < 0.30:
        return (
            "【她现在的状态·冷】她的投入很低（她平均 %.1f 字，敷衍率 %.0f%%）。\n"
            "这一轮**只做三件事**：接住她那句 + 一句短的（≤10 字）+ 不提问、不提新话题。\n"
            "· 禁止：追问、连问、换话题、讲你自己的事、给建议。\n"
            "· 她只回一个字，你就回一句同样轻的；她要是没话，就让对话停在那儿 —— "
            "**停住不是失败，硬聊才是**。\n"
            "· 你的投入必须比她少或持平，绝不许比她多。"
            % (s["avg_len"], s["cold_rate"] * 100))
    if sc < 0.50:
        return (
            "【她现在的状态·温】她在正常聊（她平均 %.1f 字，反问率 %.0f%%），但没多给东西。\n"
            "这一轮：接住她这句 + 说一句你自己的真感受（不是查户口）。\n"
            "· 可以带一个问题，但**只能一个**，而且要是她一句话就能答的具体事。\n"
            "· 不要连问，不要一次抛两个话题。她答得短就收住，别追。"
            % (s["avg_len"], s["ask_rate"] * 100))
    if sc < 0.70:
        return (
            "【她现在的状态·热】她开始给东西了（她平均 %.1f 字，有内容的回复占 %.0f%%，反问率 %.0f%%）。\n"
            "这一轮：接住 + 回一句带**你这个人**的话（态度、判断、偏好），再顺势把话题往她身上带一层。\n"
            "· 可以试探她对你的态度（她怎么看、喜不喜欢、会不会）。\n"
            "· 仍然只一件事，别贪。"
            % (s["avg_len"], s["rich_rate"] * 100, s["ask_rate"] * 100))
    return (
        "【她现在的状态·燃】她在主动给你东西（她平均 %.1f 字，有内容 %.0f%%，反问 %.0f%%）。\n"
        "这是**最该往前走**的时候，别浪费在闲聊上：\n"
        "· 她刚给的那个信号，接住并往上带一格（暧昧层：距离/时间/想象）。\n"
        "· 她要是已经在给台阶（一个人/无聊/住哪/睡不着），就把台阶铺好 —— "
        "「那你哪天过来耍」这类，**她动身，你不跑**。\n"
        "· 一次只走一格，她退了立刻收回。"
        % (s["avg_len"], s["rich_rate"] * 100, s["ask_rate"] * 100))


def _advance_block(her_msg, turns_body):
    """热会话 + 最近没推过 + 有由头 → 注入一格推进警报。

    🔴 2026-11-08：触发条件从「我方 >= 8 条」改成「**她**投入够 + 有由头」。
    高精度低召回：任一判据不满足就不注。
    """
    if not turns_body:
        return ""
    s = her_stats(turns_body)
    # 她必须真的在投入（不是我说了 8 句就算热）
    if s["score"] < 0.50 or s["n_her"] < 8:
        return ""
    lines = [l for l in turns_body.splitlines() if l.startswith("- ")]
    my = [l for l in lines if " 我: " in l or " 我：" in l]
    her = [l for l in lines if " 她: " in l or " 她：" in l]
    if _ADV_RE.search("\n".join(my[-6:])):
        return ""                       # 最近推过：歇 6 条我方消息（约半天），拒绝≠冻结
    recent_her = (her_msg or "") + "\n" + "\n".join(her[-6:])
    if not _SIG_RE.search(recent_her):
        return ""                       # 没由头不硬推
    return (
        "【推进警报·这个会话该带一格了】\n"
        "她已经在投入（平均 %.1f 字，有内容 %.0f%%），你一直接得住 —— "
        "再停在吃了吗几点睡这种循环里就没下文了。\n"
        "· 这轮先接住她这句，收尾时贴着话题带一格具体下一步：\n"
        "  「那加个好友」「你哪天过来耍」这类，给台阶不给压力，由头贴她刚说的那句。\n"
        "· 只带这一格；她不接就退回正常聊，之后一段时间不再提。"
        % (s["avg_len"], s["rich_rate"] * 100))




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


# ────────────────────── 昼夜模式（用户 2026-11-08 定，v2 按实测校准） ──────
# 用户原话：「对话层要学会勾引对方 聊骚 当然因为平台限制可以委婉一点
#            当然聊骚一定是在晚上 白天禁止」
#
# 🔴 2026-11-08 v2：窗口从「22~05 一刀切」改成**三级**。依据 _report/11 实测
#   （她 12002 条 / 我 14184 条，剔除告别句后统计「她可接的话里带张力的比例」）：
#     05–21 白天        5.0%
#     17–20 全天最冷    3.4%~4.1%  ← 单独标出来，这几个小时连暧昧都别开
#     21–23             6.9%（22 点 592 条里 16 条是「晚安」、23 点 387 条里 11 条
#                        → 这两小时是**铺垫期**，不是强度期）
#     00–05             **9.9%**（凌晨 3~4 点峰值 10.7%）← 真正的甜点
#   旧版 22~05 覆盖对了大半（8.9%），但错在两处：
#     ① 把 22~24 和 00~05 混为一谈 —— 前者每 37 条就有 1 条「晚安」，
#        她说要走的时候你还上强度，等于自己撞墙；
#     ② 白天写「她开黄腔就挡回去」—— 语料里白天她极少开黄腔，8249 条可接话里
#        带张力的约 409 条，且多数是「好累/无聊/心情不好」这类**情绪缺口不是性**。
#        挡回去会显得冷。正确姿势是**具体关心一句 + 不推进**。
#
# 为什么必须代码判定而不是写进提示词让模型看时间：
#   模型对「现在几点」没有可靠概念（_now_block 里的时间它经常忽略），
#   而「白天说了荤话」的代价是账号风险 + 对方反感，不能赌。
PHASE_DAY = "day"          # 05~21 白天：禁一切性暗示
PHASE_WARM = "warm"        # 21~23 预热层：只许时间层 + 情绪层
PHASE_TENSION = "tension"  # 23~05 张力层：可暗示，仍禁动作句

WARM_START = int(os.environ.get("SOUL_WARM_START", "21") or 21)
TENSION_START = int(os.environ.get("SOUL_TENSION_START", "23") or 23)
NIGHT_END = int(os.environ.get("SOUL_NIGHT_END", "5") or 5)
# 全天最冷的四小时（17~20 点，张力占比 3.4%~4.1%）：连暧昧都别开
DEAD_START = int(os.environ.get("SOUL_DEAD_START", "17") or 17)
DEAD_END = int(os.environ.get("SOUL_DEAD_END", "21") or 21)

# 兼容旧名（gate.py:328 等处按这个口径判「白天禁止暗示」）
NIGHT_START = WARM_START


def _hour_of(ts=None):
    return time.localtime(ts).tm_hour if ts else time.localtime().tm_hour


def phase(ts=None):
    """当前时段：day / warm / tension。跨零点用「h >= 23 or h < 5」判。"""
    h = _hour_of(ts)
    if h >= TENSION_START or h < NIGHT_END:
        return PHASE_TENSION
    if WARM_START <= h < TENSION_START:
        return PHASE_WARM
    return PHASE_DAY


def is_night(ts=None):
    """现在是不是「夜间」（预热层 + 张力层，即 21~05）。

    ⚠️ 语义：这条只回答「白天禁令是否解除」，**不回答「能不能上强度」**。
    能不能上强度看 `is_tension_time()`。gate.py 用本函数判白天拦截，
    所以两者不能合并 —— 合并会让 21~23 也放行强张力词。
    """
    return phase(ts) != PHASE_DAY


def is_tension_time(ts=None):
    """现在是不是可以走「张力层」（23~05）。预热层 21~23 返回 False。"""
    return phase(ts) == PHASE_TENSION


def is_dead_spot(ts=None):
    """是不是全天最冷的 17~20 点（张力占比 3.4%~4.1%，别撩）。"""
    h = _hour_of(ts)
    return DEAD_START <= h < DEAD_END


# ── 夜间句式清单（_report/11 §5 的 25 条，全部从真实语料改写）──
# 标 ▲ = 由她的原话反推；标 ● = 从我保持热度的成功案例里抽的骨架。
# 这些**不是让模型照抄**，是给它一个「这个长度、这个落点」的锚。
_T_SENTENCES = {
    PHASE_WARM: (
        "A 时间层 / 情绪层（21–23 点只用这两组）\n"
        "· 这个点才闲下来吧 ▲\n"
        "· 今天是不是挺累的 ▲\n"
        "· 我这边也静下来了 ●\n"
        "· 我先说，我今天也睡不着 ●（先自曝，不问她）\n"
        "· 你那边也这么静吗 ●"
    ),
    PHASE_TENSION: (
        "A 时间层（任何夜间都能用）\n"
        "· 这个点还醒着 ▲    · 我这边也静下来了 ●    · 睡不着就别硬躺 ▲\n"
        "· 你那边也这么静吗 ●    · 我先说，我今天也睡不着 ●\n"
        "B 场景层（把她报的场景接过来，加一个「人」）\n"
        "· 床够宽不 ▲    · 被窝暖好了没 ▲    · 那我给你把被子拉好 ●\n"
        "· 一个人躺着，脑子是不是特别吵 ▲    · 我也躺着，隔着一屏 ●\n"
        "C 张力层（她先给了张力才能用）\n"
        "· 别这么说话，我容易当真 ★    · 跟你聊久了有点上头 ★\n"
        "· 哪里痒 ●    · 你再说一遍，我记着 ●    · 这话我只听你讲过 ●\n"
        "· 你这个小坏心思，我记下了 ●\n"
        "D 认下她的「惩罚/试探」（不要躲，不要问）\n"
        "· 记着这笔，见面一起算 ▲    · 那你倒是来 ▲\n"
        "· 我就在这儿，你要怎么处置都行 ●    · 想得美哦，我就在这儿跟你贫两句 ●\n"
        "E 俏皮短回（≤6 字，用来「不接也不退」）\n"
        "· 你敢。▲    · 少来。▲    · 喔豁。▲    · 你说的哈。●    · 那我可记住了。●"
    ),
}

# 灭火 Top5（我的原话，在她正热的时候说的；n=次数）—— 写进负面清单当反例，
# 不写成「不许说」的清单（列举会提高出现率，见 gate.py 头注释 10-28 事故），
# 而是写成「这种话的毛病在哪」，让模型理解判据。
_FIRE_KILL = (
    "· **别拿「我在」当话**：「在呢，刚看到你说的」实测 17 次，是头号灭火句 —— "
    "她给你张力，你回一句零信息的「我在」，等于把话头掐了。\n"
    "· **别把她拉回刷手机**：「你也在刷这个 咱俩挺闲啊」9 次 —— 张力被拉平成「都很闲」。\n"
    "· **别在这时候递简历**：「厂里上班 普工 两班倒」5 次 —— 她要的是「你对我」，"
    "不是「你是什么人」。\n"
    "· **别把球踢回去**：「那你想聊点啥子撒」4 次 —— 这是让她干活。\n"
    "· **别自我评价**：「我这人嘴笨 但不会让你冷场」4 次 —— 同上，主语是你自己。"
)


def _night_block(her_msg=""):
    """昼夜/时段段。这一段是**硬方向**，优先于 stage/她的状态。

    三级（依据 _report/11 §4 的张力浓度实测）：
      · day    05–21：禁一切性暗示；她讲累/无聊 → **具体关心一句，不推进，不挡回去**
      · warm   21–23：只许时间层 + 情绪层（这两小时张力只有 6.9%，且「晚安」密集）
      · tension 23–05：才许场景层 + 张力层（00–05 是 9.9%，凌晨 3–4 点 10.7% 峰值）
    全程：**动作句永远禁止**（gate._SOLICIT_RE 直接作废）。
    """
    ph = phase()
    dead = is_dead_spot()

    if ph == PHASE_DAY:
        s = ("【现在是白天·禁止任何性暗示】\n"
             "白天只说人话：接她的话、聊具体的事、说你自己在干啥。\n"
             "· **一句荤的都不许有**：不提身体、不提睡、不提床、不暗示晚上、不开黄腔、不试探。\n"
             "· 连「这么晚还不睡」这种时间层暗示也不行 —— 白天说这句很怪。\n"
             "· 她白天说「好累 / 无聊 / 心情不好 / 没人陪」→ 这是**情绪缺口，不是性**。"
             "正确接法是**具体关心一句、不推进**（「今天跑了几趟」「那你早点歇」），"
             "**不要挡回去**（「大白天的说啥呢」这种会显得冷），也不要顺着往暧昧带。\n"
             "· 白天的目标是「让她觉得跟你聊天轻松、有事可聊」，不是撩。\n")
        if dead:
            s += ("⚠️ 现在是 **17–20 点，全天最冷的四小时**（她带张力的比例只有 3.4%~4.1%，"
                  "她在下班/带娃/做饭）。**这几个小时别撩、连暧昧都别开**，"
                  "只接具体的事、说具体的关心，一句就够。\n")
        return s

    if ph == PHASE_WARM:
        return (
            "【现在是 21–23 点·预热层，只许时间和情绪】\n"
            "这两小时她开始松下来了，但她随时可能说「要睡了」—— 所以是**铺垫，不是强度**。\n"
            "· **只许两层**：时间层（这个点才闲下来 / 还没睡）和情绪层（今天累不累 / 谁惹你了）。\n"
            "· **身体词、床、被窝、勾引、想你、抱 — 一个都不许出现**，"
            "说了就是越级，她会觉得你急。\n"
            "· 她要是自己报了场景（躺下了 / 在床上 / 一个人），接住那句，"
            "但**只接情绪和时间**，不接身体。\n\n"
            + _T_SENTENCES[PHASE_WARM] + "\n\n"
            "· 长度 4~12 字，一条只做一件事。\n"
        )

    # ── 张力层 23–05 ──
    s = ("【现在是深夜·可以带张力，但仍只走暗示层】\n"
         "这个点还醒着的两个人，说话本来就不一样。允许你往暧昧走：\n"
         "· 时间层 → 距离层 → 张力层，**一级一级来**，一级只走一格。\n"
         "· **她的荤话从来不是直给的**，是「场景 + 反问 + 表情」三件套，零露骨字。"
         "她的真实原话长这样：\n"
         "    「咋的，你还打算过来跟我睡呀」  「我在床上躺着呢」\n"
         "    「你腰子好我允许你一个个试」    「你咋不说我明目张胆勾引」\n"
         "    「那你喜欢么[坏笑]」           「反正你过来我要打你屁股」\n"
         "  → 你要学的是这个句式：**报一个场景 / 反问一句 / 丢一个表情**，"
         "把话留在半空等她接；**不是加修饰词，更不是加露骨词**。\n"
         "· 她反问 → **必须回答，不要反问她**（「你敢？」→ 答「还敢？我怕你真让我过去」）。\n"
         "· 她否认（「我对男人不感兴趣」）→ 那是在测你反应，**别当真**，"
         "playful 顶回去（「想得美哦，我就在这儿跟你贫两句」是唯一实测不掉温的接法）。\n"
         "· 她说「打你屁股」这类惩罚 → **顺着认下来**，别躲别问（「记着这笔，见面一起算」）。\n"
         "**永远不写动作句**（过来/开房/陪我睡/发张照）—— 那不是暧昧，是招嫖，平台直接封。\n"
         "· 她只回一个字、岔开话题、或者说要睡了 → **立刻收回**，不解释、不追问、不硬撩。\n"
         "· 荤话由她先起头你再接；她没起头，你最多停在时间层和场景层。\n\n"
         + _T_SENTENCES[PHASE_TENSION] + "\n\n"
         + _FIRE_KILL + "\n"
         "· 长度 **4~14 字**（她 p50 只有 4 字，你写 20 字就是在写小作文），一条只做一件事。\n"
         "· **问句只许 offer 型**（问号前是「我能给你什么」：要不要我…/够不够/暖好没），"
         "`commit` 型（你会不会…/你是不是特别…/你觉得…）一律不许 —— "
         "实测保持热度 offer 37.5% vs commit 11.1%。\n"
         "· **别只发陈述句**：单独陈述句保持热度只有 7.3%（全表最低）。"
         "陈述句后面要跟一个 offer 或一个软 probe。\n"
         "· 她只回 ≤3 字 → **立刻停，不要再补第二条**（「在呢」「刚看到」这类补话是头号灭火句）。\n")
    return s


# ────────────────────────── 组装 ──────────────────────────
def build(her_msg, sid="", hist=None, restart_h=0.0):
    """返回 (system, user, meta)。meta 只用于日志排查，不进 prompt。"""
    restart = float(restart_h or 0.0) > 0.0
    rdays = max(1.0, float(restart_h or 0.0) / 24.0)
    turns_body = ""

    # 固定前缀 = 人设 1 块 + 规则 5 块，由 rules.system_blocks() 按原顺序拼好
    # （与拆分前的 persona.system_blocks() 逐字等价）。
    blocks = list(rules.system_blocks())

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
                turns_body = b
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
        # 🔴 2026-11-08：她的投入度**先于**关系档位注入。
        #   旧版只有 stage.line()（按轮数），320 轮的会话照样判「推进档」，
        #   而她只回「嗯」—— 方向完全错。现在先给她当前状态（冷/温/热/燃），
        #   再给关系档位；两者冲突时以她的状态为准（下面明确写进提示词）。
        try:
            hb = _her_block(her_msg, turns_body)
            if hb:
                blocks.append(hb)
        except Exception as e:
            log_ = None
            try:
                from . import llm as _L
                _L.log.warning("her_block 生成失败: %r", e)
            except Exception:
                pass
        # 关系档位放在简报之后 —— 它是**本轮方向**的来源之一，离她的消息越近权重越高。
        try:
            from brain import stage
            st = stage.line(sid, her_msg)
            if st:
                blocks.append(st)
                # 🔴 2026-11-08：两段方向打架时的裁决规则，必须明写。
                #   旧版 prompt 注释里提过「方向只认一处」，但 stage 是按轮数的，
                #   而她的状态是按投入的 —— 320 轮 + 只回「嗯」时两者直接冲突，
                #   模型没有裁决规则只能折中 → 四平八稳（这正是 v10 记录过的老毛病）。
                blocks.append(
                    "【方向冲突怎么办】上面「她的状态」和「当前关系」档位不一致时，"
                    "**一律以「她的状态」为准**。\n"
                    "轮数只说明你俩聊了多久，不代表她投入了多少 —— "
                    "聊了 300 轮但她只回「嗯」，那是冷，不是热。")
        except Exception:
            pass
        try:
            adv = _advance_block(her_msg, turns_body)
            if adv:
                blocks.append(adv)
        except Exception:
            pass

        # 🔴 2026-11-08（用户定）：昼夜模式 —— **硬规则，最后注入，权重最高**。
        #   白天禁止一切性暗示，夜间才允许张力。必须由代码按本机时间判，
        #   不能交给模型自己看时间（模型对"现在几点"没有可靠概念）。
        #   放在 ADVANCE 之后，是为了让它在冲突时压过"暧昧升级"的默认倾向。
        try:
            nb = _night_block(her_msg)
            if nb:
                blocks.append(nb)
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
        user = ("【现在主动重新起一句话】\n"
                "（按上面【重新开场】那段的要求办：一句、10~22 字、末尾带小问题；"
                "她那条旧消息不回也不提。）")
    else:
        user = "【她刚发来的消息】\n" + (her_msg or "")

    blocks.append(OUTPUT_SPEC)
    system = "\n\n".join(x for x in blocks if x and x.strip())

    meta = {"sys_len": len(system), "user_len": len(user),
            "brief_len": brief_len, "restart": restart,
            "arch_blocks": len(arch)}
    # 🔴 2026-11-08：把她的投入度打进 meta，daemon 日志一眼能看到
    #   「这个会话她是冷还是热」，不用再靠翻 320 轮对话猜。
    try:
        meta["her"] = her_stats(turns_body)
    except Exception:
        pass
    return system, user, meta


__all__ = ["build", "OUTPUT_SPEC", "L2_MAX_AGE_H", "L2_KEEP", "her_stats"]
