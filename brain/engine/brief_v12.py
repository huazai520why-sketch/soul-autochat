# -*- coding: utf-8 -*-
"""本轮简报（brief）：把「画像 + 军师」两步合成一次、且输出正面素材。

为什么要合并（2026-11-04 实测）：
  旧链路是 L0（画像，本地 ~7.6s/242 字）+ L1（方案，本地 ~20s/778 字），
  两份都进 system，然后：
  ① **两份会打架**：实测同一会话 L0 说「这一轮该：稳一稳」、L1 说「定档：撩」，
     两条同时进提示词，模型没有裁决规则 → 折中 → 四平八稳。
  ② **L1 的形态是禁令清单**：真实样本里 5 条全是「禁止再提…/禁止解释…/禁止问句…」，
     只有 1 个抽象方向「撩」。大模型对负面约束的遵守率远高于正面引导，
     "禁止解释"它一定执行，"撩"它不知道怎么执行 → 话被削平。
     4 个真实会话对照：有 L1 时 4/4 出安全句，无 L1 时 3/4 明显更有钩子。
  ③ **两步串行 = 27s**，占掉必回预算的一大半。

新版输出（≤240 字，一次调用）：
  ## 她的状态     一句：什么情绪 + 她想干什么
  ## 可接的点     从她原话里挑 1~2 个具体词，说明能往哪儿接
  ## 方向         稳一稳 / 撩一下 / 往前推一格（三选一，唯一裁决）
  ## 一个开口     一句她一句话就能答的具体问句，标明"可改"（她收尾时例外，给 8 字内收尾）
  ## 别踩         最多 1 条，只写真会翻车的

🔴 写作纪律：
  · 禁止写禁令清单（实测会把出话压平）。
  · 禁止给整段话术模板（会被照抄成口头禅，2026-10-12「啃冷馒头」×4 事故）。
  · 字数硬上限 240 字 —— 超了截断，别让它挤占档案的注意力。
"""
import io
import re

from brain.pack import store
from . import llm

MAX_CHARS = 260

# 简报指纹：记录这份简报是**针对哪条她消息**生成的。
# 为什么要它：出话时读的是磁盘上"上一次生成"的简报，天然滞后一轮
# （2026-11-05 实测 841526：她 22:37 说「是啊」，brief 还停在 22:24 的「再偷笑」）。
# 过期简报比没有简报更坏 —— 它会把模型往错的方向带。所以读的时候比对，
# 不匹配就当没有（prompt._brief_block）。
STAMP_RE = re.compile(r"^<!--\s*her:([0-9a-f]{8})\s*-->\s*\n?")


def her_stamp(her_msg):
    """她这条消息的指纹（去空白后 md5 前 8 位）。必须与 prompt 侧算法一致。"""
    import hashlib
    s = re.sub(r"\s+", "", str(her_msg or ""))
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]

SYS = (
    "你是聊天参谋。你看一段真实的男女聊天记录，为「我」（男）准备这一轮怎么接。\n"
    "只输出下面五个小节，纯文本，不要寒暄、不要解释你的思路、不要markdown代码块。\n"
    "\n"
    "## 她的状态\n"
    "一句话（不超过 30 字）：她现在什么情绪 + 她这句话想干什么（求安慰/试探/抱怨/敷衍/给信号）。\n"
    "\n"
    "## 可接的点\n"
    "1~2 条。每条格式：`- 「她原话里的一个词或半句」→ 顺着能问什么 / 能说什么`。\n"
    "必须是她**这条消息里真实出现过**的字词，不许自己造。\n"
    "\n"
    "## 一个开口\n"
    "写一句可以直接发的话（7~18 字，口语，像微信），后面加「（可改）」。\n"
    "**必须是问句**：她一句话就能答的具体问题（问事、问感受、问打算都行），"
    "不许「你觉得呢」「是吗」这种空问；问的事必须从她这条消息里长出来。\n"
    "先接住她那句，再问。\n"
    "**如果【这一轮的要求】写着「必须推进」**：开口要往私事上问"
    "（住哪一片 / 一个人还是有人陪 / 几点睡 / 平时都一个人在家），不能只是接她这句。\n"
    "例外：她这条是收尾（睡了/晚安/困了/不聊了/告辞）→ 换成一句 8 字以内的收尾，不要问句。\n"
    "\n"
    "## 别踩\n"
    "最多 1 条，只写这一轮真会翻车的那件事（比如她刚说累，别踩的可能是「别讲你自己的事」）。\n"
    "没有就写「无」。\n"
    "\n"
    "## 新事实\n"
    "只从**她这条消息**里提取关于她自己的事实（住哪/年纪/职业/家人/身体/喜好/在做什么）。\n"
    "**不许把我说的事写进来**（开网店、发货、电脑配件、装系统这些是我的，不是她的）；"
    "她只是在接我的话，不算她的事实。\n"
    "每条格式：`- 内容 | 原话片段`。原话片段必须是她消息里**逐字出现**的一段，不许改写。\n"
    "最多 2 条；没有就写「无」。不确定的一律不写——**宁缺勿错**。\n"
    "\n"
    "硬要求：\n"
    "· 全文不超过 240 字。\n"
    "· 不要写「禁止1/禁止2/禁止3」这种清单，最多一条。\n"
    "· 不要复述聊天记录，不要评价这段关系好不好。\n"
    "· 我的人设：%s，%s 岁，%s人。"
)


def _persona_line():
    from . import persona
    a = persona.ident()
    return a["name"], a["age"], a["city"]


def build_messages(sid, her_msg, turns_text="", max_turns=14):
    name, age, city = _persona_line()
    f = store.read_facts(sid)
    facts = "；".join(x.get("t") for x in f["hers"][:8] if x.get("t")) or "（无）"
    lines = [x for x in (turns_text or "").splitlines() if x.strip()]
    tail = "\n".join(lines[-max_turns:]) if lines else "（无历史）"
    # 关系档位由轮数算（stage），不是让本地模型裁决 —— 它只会给「稳一稳」。
    try:
        from brain import stage as _stage
        st = _stage.line(sid, her_msg)
    except Exception:
        st = ""
    user = (
        "【她刚发来的消息】\n%s\n\n"
        "【当前关系 / 这一轮的要求】\n%s\n\n"
        "【最近的对话（时间顺序）】\n%s\n\n"
        "【已知关于她的事实】\n%s\n"
        % (her_msg or "（无）", st or "（无档位信息，按普通轮给）", tail, facts)
    )
    sys = SYS % (name, age, city)
    return [{"role": "system", "content": sys},
            {"role": "user", "content": user}]


_SECTION = re.compile(r"^##\s*(.+?)\s*$", re.M)

WANT = ("她的状态", "可接的点", "一个开口", "别踩")


def _split_sections(t):
    """把模型输出切成 {小节名: 正文}。"""
    got = {}
    marks = list(_SECTION.finditer(t))
    for i, m in enumerate(marks):
        title = m.group(1).strip()
        body = t[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(t)].strip()
        for w in WANT + ("新事实",):
            if title.startswith(w):
                got[w] = body
                break
    return got


def _parse_facts(block, her_msg):
    """从「新事实」块抽 (内容, 原话片段)。原话片段必须真的出现在她这条消息里。"""
    out = []
    for ln in (block or "").splitlines():
        s = ln.strip()
        if not s or s == "无" or s.startswith("（"):
            continue
        s = re.sub(r"^[-*·]\s*", "", s)
        if "|" not in s:
            continue
        content, _, ev = s.partition("|")
        content, ev = content.strip(), ev.strip()
        if not content or not ev:
            continue
        # 证据必须逐字出现在她这条消息里 —— 模型改写过的就不算（防编造）
        if ev not in (her_msg or ""):
            continue
        out.append({"t": content[:40], "ev": ev[:60]})
    return out


def normalize(raw):
    """模型输出 → 规整的四个小节。缺节补空，多余内容丢掉，超长截断。"""
    t = str(raw or "").strip()
    if not t:
        return ""
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t, flags=re.M).strip()
    got = _split_sections(t)
    if not got:
        return ""
    out = []
    for w in WANT:
        body = (got.get(w) or "").strip()
        if not body:
            body = "无" if w == "别踩" else ""
        if not body:
            continue
        out.append("## " + w + "\n" + body)
    txt = "\n\n".join(out).strip()
    if len(txt) > MAX_CHARS:
        txt = txt[:MAX_CHARS].rsplit("\n", 1)[0]
    return txt


def generate(sid, her_msg, turns_text="", timeout=None):
    """调分析模型生成 brief，写入案情包。失败返回 ""（调用方按"没有简报"降级）。

    顺带做一件事：把「新事实」里**有原话出处**的条目写进 facts.json。
    这样事实档案是随对话长出来的，每条都能追到是哪句话说的 ——
    比一次性批量重建更可靠（批量只能从旧 L0 里捡，而旧 L0 大半是语气词）。
    """
    msgs = build_messages(sid, her_msg, turns_text)
    raw = llm.analyze(msgs, timeout=timeout or 40, max_tokens=700, temperature=0.4)
    txt = normalize(raw)
    if not txt:
        return ""
    try:
        store.write_brief(sid, "<!-- her:%s -->\n%s" % (her_stamp(her_msg), txt))
    except Exception:
        pass
    try:
        sec = _split_sections(str(raw or ""))
        for f in _parse_facts(sec.get("新事实", ""), her_msg):
            if store.add_fact(sid, f["t"], side="hers", ev=f["ev"], conf=0.9):
                llm.log.info("[事实] + %s（出处 %r）", f["t"][:20], f["ev"][:16])
    except Exception as e:
        llm.log.debug("事实写入失败: %r", e)
    return txt


if __name__ == "__main__":
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else ""
    her = sys.argv[2] if len(sys.argv) > 2 else "嗯，没有微信上加上"
    print(generate(sid, her, store.read_turns(sid, 3000)))
