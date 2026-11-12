# -*- coding: utf-8 -*-
"""主动开场白（wake / first / match）—— 由 2.1 `soul_brain.opening_line` 移植。

为什么单独一个模块：它跟「接她的话」是两种任务。
  接话有她这句可以做锚点；开场没有锚点，模型容易编场景
  （实测编出过「考她这行」「许愿送东西」），所以规矩完全不一样：
  只能用资料里原样出现的信息、我自己的籍贯工作不许说成她的、不约见面、
  不查户口、资料词不许出现在句子里。

保留的两道去重闸（2026-10-26 §39.7-2 落地，别删）：
  ① prompt 里列出最近用过的开头，明令换一个；
  ② 出句后按「前 3~5 字」查重（短句前 3 字、长句前 5 字），命中就重写（最多 3 次）；
     3 次都撞 → **照发**（宁可发，不可不发；退回模板群发才是最伤账号，见 A3 注释）。
  开头历史落盘 `memory/_open_heads.json`，重启不丢；唤醒与匹配共用同一份。
"""
import io
import json
import os
import re
import threading
import time

from brain.pack import store
from . import llm

HEAD_KEEP = 12
_HEAD_FILE = os.path.join(str(store.MEM), "_open_heads.json")
_head_lock = threading.Lock()

_EMOJI_RE = re.compile("[" "\U0001F300-\U0001FAFF" "\u2600-\u27BF" "\uFE0F" "]")

OPEN_IDENT = (
    "【我是谁 —— 这只是我自己的背景，不是她的信息】\n"
    "男方，32 岁，重庆綦江三江人，自己开网店（卖数码小件、帮人装系统修电脑），住三江家里。\n\n"
    "⚠️ 她的情况只能来自下面「她这个人」和「她的资料」两段。\n"
    "资料里没写的（她在哪个区、做什么工作、是不是老乡、有没有孩子…）一律不许"
    "当成她的事说出来；也不许用「你是 / 你在 / 咱俩都是」这类说法替她断言。"
)

OPEN_RULES = (
    "硬规矩（违反任何一条整句作废）：\n"
    "1) 只能用下面资料里**原样出现过的信息**，资料里没有的一律不许编"
    "（不许猜她的宠物、家人、职业细节、住哪儿）；\n"
    "2) **「我」的籍贯/工作/年龄是我的事，不是她的事**：不许说成她的、也不许拿去问她"
    "（禁止：「你也在开网店吗」「你也是綦江的」「咱俩都开网店」）；\n"
    "3) {limit} 字以内（含标点），一句，口语，像随手打的；**宁短不长**，"
    "超过 {limit} 字整句作废，不要为了完整而堆字；\n"
    "4) 不许「你好/在吗/交个朋友/认识一下/美女/小姐姐」；\n"
    "5) 不查户口：不问年龄、工作、住址、收入；\n"
    "6) 不约见面、不说「一起」「出来」「过来」；\n"
    "7) 「资料」「引力签」「共同点」「标签」这些词是给我看的，**绝不许**出现在句子里；\n"
    "8) 表情一律不要（它占字数，这次不加）；\n"
    "9) **不许出现平台动作与平台名**：Soul / 匹配 / 匹配到 / 加个好友 / 关注一下 —— "
    "真人是不会这么说话的（实测出过「在 Soul 匹配到了，咱都有个重庆」，一句就露馅）；\n"
    "10) 只输出这一句本身：不要引号、不要解释、不要换行。"
)

OPEN_TASK = {
    "wake": "你们之前聊过，现在已经冷了几天，最后一条是我说的、她没接。换个新话题自然开口一句。",
    "first": "这是你跟她说的第一句话，她还没跟你说过话。",
    "match": "你们刚在 Soul 上匹配上，这是你要发的第一句话。",
}

# 平台动作/资料术语：出现在句子里就整句重写
_PLATFORM = ("Soul", "soul", "SOUL", "匹配", "加个好友", "关注一下",
             "引力签", "共同点", "资料", "标签", "主页")

# 🔴 2026-11-08 04:16（核对时发现的编造问题）
#   实测发出过「你平也爱减肥吗金牛座？」—— 她的资料里**没有任何星座信息**，
#   模型自己编了个「金牛座」塞进句尾。这属于「编造她的信息」，比套话更伤：
#   她一看就知道你在瞎猜/群发。
#   做法：命中即整句重写（与 _PLATFORM 同一处理等级）。
#   只收「强编造」词，避免误伤正常表达（"车/房/学历"太泛，不收）。
_ZODIAC = ("白羊", "金牛", "双子", "巨蟹", "狮子", "处女", "天秤", "天蝎",
           "射手", "摩羯", "水瓶", "双鱼")
_FABRICATE = ("星座", "血型", "属相", "生肖", "三围", "月薪", "年薪", "存款")


# ────────────────────── 开头去重 ──────────────────────
def head_key(t):
    """开头特征：剥掉标点/表情后的前 3 个字符；候选句较长时再拼上第 4~5 字。

    🔴🔴 2026-11-08 04:12（核对时发现的真 bug）
      改前取**前 2 个字**，导致大量**不同**的开头被判成重复：
        「你平时…」→ '你平'
        「你平也…」→ '你平'   ← 误判！两者是不同的句子
        「你也…」  → '你也'
        「你也觉得…」→ '你也'  ← 同样误判
      实测后果（04:08 日志）：
        [开场] 第1次撞开头「你平」，重写: '你平在重庆也减肥吗？'
        [开场] 第2次含平台词 ['引力签']，重写: '看你引力签，永远在减肥。'
        [开场] 三次都撞开头「你平」，仍发出: '你平也爱减肥吗金牛座？'
      → 连续两次「撞开头」其实是**误判**，把本来不同的句子逼成了畸形句，
        最后发出「你平也爱减肥吗金牛座？」这种明显不通的话。
      改后取前 3 个字：既保留「防雷同」的作用，又不会把不同句子判成同一句。

    🔴🔴 2026-11-12（A3 修复，日志 361 次「撞开头→重写」）：前 3 字区分度仍不够 ——
      「你/我/现在/今天」这类高频起头极易碰撞（「你平时…」vs「你也…」同属「你」字头）。
      修法（最小侵入）：**保留前 3 字为主键**；候选句去掉标点后 **>8 字** 时，
      额外拼上第 4~5 字（s[:5]），提高区分度。短句（≤8 字）仍用前 3 字
      （短句本身撞头概率低，且「嗯/哈/好」这类极短应答不该因多拼字被误判）。
      历史文件里已存的旧 key（前 3 字）不会与新 key 精确相等，属可接受的
      「换新格式」迁移（旧 key 仅影响一次碰撞判定，之后新 key 入池）。
      注意：`head_ban_line()` 里给模型的提示文案要同步改成「前 3~5 个字」。
    """
    s = _EMOJI_RE.sub("", t or "")
    s = re.sub(r"[\s，。！？、~～…\.\!\?,\-—：:；;\"'“”‘’()（）【】\[\]]+", "", s)
    if len(s) > 8:
        return s[:5]
    return s[:3]


def head_load(scope="open"):
    try:
        with io.open(_HEAD_FILE, "r", encoding="utf-8") as f:
            v = json.load(f)
        return [str(x) for x in (v or [])][-HEAD_KEEP:]
    except Exception:
        return []


def head_save(v):
    try:
        os.makedirs(os.path.dirname(_HEAD_FILE), exist_ok=True)
        tmp = _HEAD_FILE + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(v[-HEAD_KEEP:], f, ensure_ascii=False)
        os.replace(tmp, _HEAD_FILE)
    except Exception:
        pass


def head_add(t):
    k = head_key(t)
    if not k:
        return
    with _head_lock:
        v = head_load()
        v.append(k)
        head_save(v)


def head_dup(key, heads):
    return bool(key) and len(key) >= 2 and (key in (heads or []))


def head_ban_line(n=8):
    h = head_load()[-n:]
    if not h:
        return ""
    return ("\n【⛔ 开头撞车】这些开头最近已经回过了，这次必须换一个"
            "（前 3~5 个字都不许重复）：" + "、".join(h))


# ────────────── 畸形句判定（2026-11-08 13:0x 新增） ──────────────
#
#   背景：04:14 用「撞开头」兼职拦畸形句，导致两个问题——
#     ① 撞开头本身只是「不够新鲜」，被当成「发错」处理 → 大量合格句被丢弃
#        （11-08 全天「空」候选 30 次，全废 14 次，退回模板群发 26 次）；
#     ② 真正的畸形句（「你平也爱减肥吗金牛座？」）却没被直接识别出来。
#
#   所以把「畸形」独立成一个判据，只拦**明显不像真人说话**的句子。
#   宁可漏判（放过一句略怪的），也不误杀（丢掉一句正常的）—— 因为
#   漏判的代价只是「这句不够好」，误杀的代价是「退回模板群发」。
_AWK_PATTERNS = (
    r"^你平",              # 「你平」= 「你平时」被截断（实测最典型的畸形）
    r"^看你[^\s，。]{0,2}[，。]",   # 「看你，」这种半截话
    r"[吗呢吧啊][吗呢吧啊]",        # 「吗吧」「呢啊」语气词连用
    r"(.)\1{2,}",          # 同一字连续 3 次以上
    r"^[，。、！？]",         # 标点开头
    # 🔴 2026-11-08 13:0x：原来还有一条 `[，。、]$`（悬空结尾），**实测误杀严重** ——
    #   中文句子正常就该以「。」结尾（「重庆这地方确实挺有魅力的。」），
    #   这条规则把**所有正常句号结尾**都判成畸形。已删除。
    #   真正的「只剩标点」由下面的 `len(t) < 3` 和「标点开头」覆盖。
)


def _looks_awkward(s):
    """句子是否**明显畸形**（不像真人说话）。True = 畸形，不要发。

    只拦「一眼假」的形态；语义好不好、够不够有趣**不在这里判**
    （那是打分器的事）。避免把「撞开头」和「畸形」混为一谈。

    设计原则：**宁可漏判，不可误杀**。
      漏判 → 发一句略怪的话（代价小）；
      误杀 → 丢弃合格句 → 退回模板群发（11-08 实测模板句发了 26 次，代价大）。
    所以这里只保留「结构上不可能正常」的规则，凡是正常中文会出现的形态一律不拦。
    """
    t = (s or "").strip()
    if not t:
        return True
    if len(t) < 3:                      # 「嗯」「啊」这种单独发出去很怪
        return True
    for pat in _AWK_PATTERNS:
        try:
            if re.search(pat, t):
                return True
        except Exception:
            continue
    # 中英混排/乱码残留（实测模型偶尔吐半个英文单词）
    if re.search(r"[A-Za-z]{4,}", t):
        return True
    return False


# ────────────────────── 开场生成 ──────────────────────
def _profile_text(sid, tags=None, common=None):
    parts = []
    if tags:
        parts.append("引力签：" + "、".join(str(x) for x in tags if str(x).strip())[:120])
    if common:
        parts.append("共同点：" + "、".join(str(x) for x in common if str(x).strip())[:60])
    if parts:
        return "\n".join(parts)
    if sid:
        p = store.read_profile(sid)
        order = ("昵称", "引力签", "共同点", "匹配度", "IP属地", "标签", "瞬间")
        rows = ["%s：%s" % (k, p[k]) for k in order if p.get(k)]
        if rows:
            return "\n".join(rows)[:500]
    return "（没有她的资料）"


def _facts_text(sid):
    if not sid:
        return ""
    f = store.read_facts(sid)
    rows = [x.get("t") for x in f["hers"][:8] if x.get("t")]
    return "；".join(rows)


def opening_line(sid="", nick="", hist=None, tags=None, common=None,
                 kind="wake", limit=18):
    """主动发起一句话（纯本地模型）。返回 (文本, 耗时毫秒)；失败返回 ("", 0)。"""
    t0 = time.time()
    prof = _profile_text(sid, tags, common)
    facts = _facts_text(sid)
    ctx = "".join(
        ("我: " if str((h or {}).get("role")) == "me" else "她: ")
        + str((h or {}).get("text") or "")[:60] + "\n"
        for h in (hist or [])[-8:])

    heads = head_load()
    ban = ""
    if heads:
        ban = ("\n\n【这些开头最近刚用过，这次必须换一个开头，一个字都不许重复】\n"
               + "、".join(heads[-8:]))

    sys_p = "%s\n%s\n\n%s" % (
        OPEN_IDENT,
        OPEN_RULES.format(limit=limit),
        OPEN_TASK.get(kind, OPEN_TASK["wake"]))
    usr_p = ("【她这个人（之前分析过的）】\n%s\n\n"
             "【她的资料】\n%s\n\n"
             "【你们最近聊到的】\n%s%s"
             % (facts or "（还没分析过，只有下面的资料）",
                prof, ctx or "（没聊过）", ban))
    msgs = [{"role": "system", "content": sys_p},
            {"role": "user", "content": usr_p}]

    # 🔴🔴 2026-11-08 04:18（核对时发现的死循环）
    #   实测（04:14 日志）：加了「编造」检查后，本地小模型**反复生成同一类句子**：
    #     第1次编造 ['星座'] → '听说下，土象星座挺稳的。'
    #     第2次含平台词 ['资料'] → '看你资料是土象星座挺稳当的'
    #     第3次编造 ['星座'] → '看来你也是土象星座吧'
    #   三次全废 → 退回兜底。下一句又从头来一遍（因为 ban 提示没进 prompt）。
    #   ⇒ 一个候选能白烧 3~6 次模型调用（每次 0.5~1.5s），且**永远出不来**。
    #
    #   修法：把「这次被拒的原因」**累积成负面提示**，下一轮直接写进 user prompt，
    #        让模型知道"这些方向已经试过了，别再写"。
    #        同时记 `_rej_words`，用于最后一次机会时做**硬性删除**兜底。
    _rej_words = []
    _rej_note = ""

    for attempt in range(3):
        _msgs = list(msgs)
        if _rej_note:
            _msgs = msgs + [{"role": "user", "content": _rej_note}]
        # 🔴 2026-11-12（GL-04 修复）：旧代码直接调 llm.ollama_chat，不走
        #   llm.analyze() 的方舟回落分支 → 本地 Ollama 不可用时开场白连撞/回落
        #   固定模板（实测 68 次）。改为走 llm.analyze()：内部先试本地 Ollama，
        #   失败且 SOUL_ANALYZE_FALLBACK_ARK=1 时自动回落到方舟出话模型，
        #   不新增密钥、不改变调用语义。若方舟也不可用，analyze 返回 None，
        #   与旧行为一致（continue → 兜底）。
        raw = llm.analyze(_msgs, timeout=40, max_tokens=120,
                          temperature=0.78 + 0.06 * attempt)
        if not raw:
            continue
        c = raw.split("\n")[0].strip().strip('"“”\'‘’')
        c = re.sub(r"^(回复|开场白|消息)[:：]\s*", "", c)
        c = _EMOJI_RE.sub("", c).strip()
        c = re.sub(r"\s+", " ", c).strip()
        noemo = re.sub(r"\[[^\]]{1,4}\]", "", c).strip()
        cand = ""
        if c and len(c) <= limit + 2:
            cand = c
        elif noemo and len(noemo) <= limit + 2:
            cand = noemo
        if not cand:
            llm.log.warning("[开场] 第%d次不合格（%d 字 > %d）: %r",
                            attempt + 1, len(c), limit + 2, c[:40])
            _rej_note = ("\n【上次不合格】你写的是 %r，长度不符合要求（不超过 %d 字），"
                         "请重新写一句更短的。" % (c[:30], limit))
            continue
        # 平台动作/资料词一律不接受（真人不会这么说）
        bad = [x for x in _PLATFORM if x in cand]
        if bad:
            llm.log.warning("[开场] 第%d次含平台词 %s，重写: %r",
                            attempt + 1, bad, cand[:40])
            _rej_words.extend(bad)
            _rej_note = ("\n【上次不合格】你写的是 %r，里面出现了平台术语 %s，"
                         "真人聊天不会这么说，请完全不要提这些词。"
                         % (cand[:30], "、".join(bad)))
            continue
        # 🔴 2026-11-08 04:16：编造她的信息（星座/血型/收入…）一律不接受。
        #   实测漏出过「…金牛座？」，她资料里根本没星座 —— 一看就是群发瞎猜。
        fab = [x for x in _FABRICATE if x in cand]
        if not fab:
            # 星座名要精确匹配（「金牛」也可能指别的东西，但出现在开场白里
            # 几乎一定是编的星座）—— 且她资料里若真有该词则放行
            _pool = (prof or "") + (facts or "")
            fab = [z for z in _ZODIAC if z in cand and z not in _pool]
        if fab:
            llm.log.warning("[开场] 第%d次编造她的信息 %s，重写: %r",
                            attempt + 1, fab, cand[:40])
            _rej_words.extend(fab)
            _rej_note = ("\n【上次不合格】你写的是 %r，里面出现了 %s —— "
                         "她的资料里**根本没有这些信息**，属于编造，绝对不许写。"
                         "请只根据她真实有的资料（上面给的）来写。"
                         % (cand[:30], "、".join(fab)))
            continue
        k = head_key(cand)
        if head_dup(k, heads):
            if attempt < 2:
                llm.log.warning("[开场] 第%d次撞开头「%s」，重写: %r",
                                attempt + 1, k, cand[:30])
                # 🔴🔴 2026-11-08 13:0x（对话层优化：把「失败」变成「可用的提示」）
                #   改前：这里只 `continue`，**不告诉模型为什么被拒** ——
                #        下一轮它只能瞎猜，实测连续 3 次撞同一个开头（「听说」「你也」），
                #        3 次耗尽 → 候选记「空」→ 退回兜底句。
                #        11-08 全天「空」候选 **30 次**，是最大的一类作废原因。
                #   改后：把「这个开头已经用过了」写进 _rej_note，并**明确要求换角度**。
                _rej_note = ("\n【上次不合格】你写的是 %r，开头「%s」今天已经用过很多次了，"
                             "换一个**完全不同的开头**，不要再用「%s」这几个字起头。"
                             "换个角度：直接说她资料里某个具体的东西，或者问一个具体问题。"
                             % (cand[:30], k, k))
                continue
            # 🔴🔴 2026-11-12（A3 修复，推翻 13:0x 的「畸形→放弃」处置）：
            #   13:0x 判断「三次都撞开头且句子畸形 → 放弃（return "", 0）」方向对，
            #   但**代价算错了**。实测上层对 "" 的处理（grep 确认）：
            #     · wake.py:411-428  `opening_line` 返回 "" → `plan()` **跳过该候选**
            #       （本轮不发，等下一轮，可能反复空烧）；
            #     · match.py:392-413 `opening_line` 返回 "" → 全废 → `_fallback()`
            #       **退回模板群发**（同一句反复群发，实测累计 26 次 —— 最伤账号）。
            #   畸形句（如「你平也爱减肥吗金牛座？」）确实不好，但**只在「撞开头」
            #   已耗尽 3 次**这一条路径上才可能走到这里 —— 此时发一句略怪的话，
            #   代价（她看一眼觉得怪）**远小于**退回模板群发（同句刷屏、一眼看穿是机器）。
            #   所以：**不再 return "", 0**，改为照发 cand（即使畸形也发）。
            #   仍然坚持的底线：平台词/编造/超长 —— 那些才是真「发错」，一律不发；
            #   只有「撞开头+畸形」这一种情况被放宽（宁可发，不可模板群发）。
            if _looks_awkward(cand):
                llm.log.warning("[开场] 三次撞开头且句子畸形，照发（畸形优于模板群发）: %r",
                                cand[:30])
            else:
                llm.log.info("[开场] 三次撞开头「%s」但句子通顺 → 照发（比模板群发好）: %r",
                             k, cand[:30])
            head_add(cand)
            ms = int((time.time() - t0) * 1000)
            return cand, ms
        head_add(cand)
        ms = int((time.time() - t0) * 1000)
        llm.log.info("[开场] %s %s字 %.1fs: %s", kind, len(cand), ms / 1000.0, cand)
        return cand, ms
    return "", 0


__all__ = ["opening_line", "head_key", "head_load", "head_save", "head_add",
           "head_dup", "head_ban_line", "OPEN_IDENT", "OPEN_RULES", "OPEN_TASK"]
