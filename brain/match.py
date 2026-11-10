# -*- coding: utf-8 -*-
"""星球灵魂匹配：读资料 -> 出开场白 -> 发送 -> 匹配下一个 / 回星球重新匹配。

硬规则（用户 2026-11-02 定）：
  1. **每次匹配后必须先把开场白发出去，再点「匹配下一个」**，否则这一天的
     匹配次数就白费了。
  2. 匹配页**不一定有**「匹配下一个」按钮；没有时就退回星球页重新「开始匹配」。
  3. 开场白用**通用开场白**（用户 2026-11-02 定），不用引擎现生成。

为什么不再用旧引擎生成匹配开场白（engine_gen=True 仍保留）：
  实测 `opening_line(kind="match")` 在没有对方资料时会把我自己的信息
  （江华 / 綦江三江 / 开网店卖数码）当成她的编出去，4 条候选全废：
    「这三江偶尔也会想起你。」「看你在三江卖数码挺巧的。」
  匹配次数按天限量，宁可发一句稳的通用句，也不能浪费一次匹配。
"""
import re
import time

from core.log import get_logger
from eyes.page import detect

log = get_logger("brain.match")

NEXT_TEXT = "匹配下一个"      # 实测 res=tv_rem b=(168,88,288,121) click=True
LIMIT = 20                    # 与旧引擎 opening_line 默认一致
# 🔴 2026-11-08（_report/14 实测：match 开场白问句率 31.3%）
#   目标线：硬问句 ≤12%（对齐回复侧 12.5% 的水平，不再做「问句优先」）。
OPEN_ASK_RATE = 0.12

# 匹配卡片/会话题里的固定文案，抽昵称时必须排除
UI_TEXTS = {
    "头像", "查看主页", "匹配度", "关注", "聊天设置", "发送", "语音", "表情", "更多",
    "早上好", "交换答案", "桌球", "礼物", "一起听", "AI助手", "文明聊天，友善交友~",
    "关注后可邀请通话", "手机信号满格。", "WLAN 信号满格。",
}

# 「你也在…吗」这类把自己的信息套到她身上（旧引擎 _OPEN_RULES 第 2 条本就禁止，
# 但实测仍会漏出来，这里作为硬拦）
BAD_RE = (
    re.compile(r"你也[在是做搞]"),
    re.compile(r"你也是"),
    re.compile(r"咱俩都"),
    re.compile(r"我们都"),
    re.compile(r"^看到你"),
    re.compile(r"^听说"),
)

# 疑问标记：开场白最好是能让她接话的问句
# ⚠️ 保留原名给旧调用方；语义已经反转 —— 现在问句是**减分项**，
#    见 ASK_HARD 与 score() 的注释（2026-11-08 降问句率）。
ASK_RE = re.compile(r"[？?]|吗|呢|不|啥|什么|怎么|咋|几|哪|多少|有没有")

# 🔴 2026-11-08（依据 _report/14 实测：match 开场白问句率 31.3%，目标 <12%）
#
#   旧逻辑是「问句优先」：`score()` 里 `if ASK_RE.search(text): s += 3`，
#   且 `opening()` 一旦拿到「合格且是问句」就 `return` 提前收工。
#   结果全是查户口：`你是开网店的吗？` `你也住重庆吗？` `你在重庆打拼吗`。
#   审计实测这些句子的问句率是回复侧（12.5%）的 2.5 倍。
#
#   为什么问句不是好事（数据）：报告-11 的保持热度 offer型 37.5% / probe型 25.9%，
#   而 match 开场白这些问句全是 **probe 型（要她提供信息）**，
#   在陌生场景等于第一次说话就查户口 —— 反问压力大、回复率低。
#
#   新策略：**陈述句优先**。陈述句自带一个可接的话头，她愿意接就接，
#   不愿接也没压力。只保留少量「给得起东西」的 offer 型问句（要不要/我请你这种）。
#   `ASK_HARD` 才是「硬问句」判据（真正的疑问句），比 ASK_RE 窄：
#   ASK_RE 会把「不」「几」「哪」这种字面也当问句，用来压分太粗暴。
#   ⚠️ 2026-11-08 二次修正：初版漏了「干啥/咋样/在哪/多少」这类**无问号疑问句**
#   （`匹配到你了，平时这个点都在干啥` 被误判成陈述句，还拿了 +3）。
#   现在把疑问词补全，但**只认出现在后半句/句尾的**，避免「不知不觉」这类误伤。
ASK_HARD = re.compile(
    r"[？?]\s*$"
    r"|(?:吗|呢|么|不|没)\s*$"
    r"|(?:什么|啥|怎么|咋|哪|为什么|为啥|多少|几[点个岁]|多久|干什么|干啥)"
    r"(?:呢|啊|呀|嘛|了)?\s*$"
    r"|(?:在|做|干|是|有|要|想|会|能|爱|喜欢|选|看|吃|玩|听)(?:什么|啥|哪|几)"
)
# 低压力问句：问她**此刻状态**（不涉及身份/工作/住址/年龄/作息规律），比查户口轻一档
# ⚠️ 2026-11-08 二次修正：初版含「这个点」，把 `匹配到你了，平时这个点都在干啥`
#    也放进了轻罚档（那分明是在盘问作息规律 = 查户口）。已收窄到「此刻状态」。
SOFT_ASK_RE = re.compile(r"刚忙完|闲着呢|这会儿.*还是|在忙啥|追啥剧")
# offer 型问句白名单：问的是「我给得起什么」，不是「你身上有什么信息」
OFFER_RE = re.compile(r"要不要我|我帮你|我给你|我陪你|我请你|我带你去|够不够|好不好")

# 这些词是给我看的，不许出现在句子里（旧引擎 _OPEN_RULES 第 7 条）
META_WORDS = ("引力签", "共同点", "资料", "标签", "匹配度", "星球", "礼仪分", "星座")

# 🔴 我自己的专属信息（取自 soul_rules.PERSONA：江华/綦江三江/开网店卖数码）。
#   实测旧引擎会把「我」的信息当成「她」的资料编出去：
#     资料里只有引力签「只想找个人聊聊天」，却生成「这三江偶尔也会想起你。」
#     「看你在三江卖数码挺巧的。」——她根本不知道三江是什么。
#   规则：这些词**只有在她资料里原样出现过**时才允许使用（比如共同点写了重庆）。
MY_WORDS = ("江华", "三江", "綦江", "重庆", "网店", "闲鱼", "抖店", "数码",
            "cpu", "内存", "ssd", "显示器", "快递", "软路由", "重装系统", "电脑配件")


def my_words():
    """开场白禁用词：从人设的 ban 字段取，单一来源。

    两个账号共用同一份人设（用户 2026-11-05 口径），不再按账号切身份；
    原来硬编码在 match.py，改人设时容易漏改 —— 现在统一读 persona.IDENT["ban"]。
    MY_WORDS 保留为同内容的兜底常量（人设模块取不到时用）。
    """
    try:
        from brain.engine.persona import ident
        w = ident().get("ban")
        if w:
            return tuple(w)
    except Exception:
        pass
    return MY_WORDS

# 全废时的安全兜底（不含任何具体信息，不会崩）
# 🔴 2026-11-08（_report/14：match 开场白问句率 31.3% → 目标 <12%）：
#   旧 3 条全是查户口问句（「你这会儿在忙吗」「平时这个点都在干啥」），
#   而且它们是**兜底**——一旦用上就是「四条候选全废」，此时更需要一句稳的
#   陈述句把场面撑住，而不是再抛一个她不一定要接的问题。
#   新 3 条全部改为**陈述型 + 自带话头**，零问号，且不查户口。
FALLBACK = (
    "刚匹配到，先过来打个招呼",
    "刚刷到你，我这边正闲着",
    "刚匹配上，我这会儿刚忙完手头的事",
)

# ══════════ 通用开场白库（用户 2026-11-02 定：匹配场景直接用通用句）══════════
# 依据网上通行的「通用安全开场白」原则：不查户口（不问年龄/工作/住址/照片）、
# 低压力、留一个能接的话头、不夸长相、不上来倒苦水。
# 为什么不用引擎现生成：实测 `opening_line(kind="match")` 在没有对方资料时，
# 会把我自己的信息（江华/三江/卖数码）当成她的编出去，4 条全废；
# 而匹配次数是按天限量的，宁可发一句稳的通用句，也不能浪费一次匹配。
#
# 🔴 2026-11-08（_report/14：match 开场白问句率 31.3%，是回复侧 12.5% 的 2.5 倍）
#   库结构重排：**陈述句打头**，问句只留少量「给得起东西」的 offer 型。
#   记录用（48h 实测 67 条 match 开场白）：
#     · 查户口问句：`你也住重庆吗？` `你在重庆打拼吗` `你是做上班族的吗？`
#       `声控是啥意思？` `观自在是啥意思啊？` `舞跳得好看吗` `你装系统吗`
#     · 这些是 **probe 型**（要她提供信息），陌生场景第一次说话就查户口。
#   陈述句的好处：自带话头、零回答压力，愿意接就接，不接也不尴尬。
OPENERS = (
    # A 陈述式破冰（**主力，无问号**）
    "刚匹配到，过来打个招呼",
    "刚点完匹配就碰上你了，缘分哈",
    "突然跳出来一个我，惊不惊喜",
    "我先开口了，你别嫌我烦哈",
    "我刚闲着没事，碰上一个你",
    "猜你是那种话不多但挺有意思的人",
    "这会儿手头没事，正好碰上你",
    "刚刷到你，我这会儿正好闲着",
    "我这边刚忙完，顺手点了下匹配",
    "我平时话不算多，但不怕冷场",
    # ⚠️ 以下两条被 check() 拦过，已替换：
    #    "咱俩这匹配度，先聊两句试试水"   → 含元词「匹配度」(META_WORDS)
    #    "今天重庆的天气挺舒服的…"        → 含我的专属词「重庆」(my_words)
    "先随便说两句，合不合拍聊了才知道",
    # B 陈述式抛话头（把信息给出去，她自己会接）
    "我先说，我今天过得还行",
    "我这会儿刚泡了杯茶，坐着发呆",
    "我这人话不多，但接得住话",
    "刚吃完饭，正愁没人说说话",
    "我这边窗子开着，风还挺凉",
    # C offer 型（问的是「我给得起什么」，不是「你身上有什么信息」）
    "要不要聊聊今天最烦的一件事",
    "要是你也不困，咱俩说两句",
    "我可以先讲讲我自己，你听着就行",
    # D 少量低压力问句（**允许保留，占比控制在 1/5 以内**）
    "你这会儿是刚忙完还是闲着呢",
    "这会儿在忙啥呢",
    "最近在追啥剧没",
)


def read_card(snap):
    """从匹配卡片里抽资料，返回 dict(nick, tags, common, extra)。"""
    nodes = [n for n in snap.nodes if n.label]
    texts = [n.label.strip() for n in nodes]
    tags, common, extra = [], [], {}

    for i, t in enumerate(texts):
        if t.startswith("Ta的引力签"):
            rest = t.split("：", 1)[-1].strip() if "：" in t else ""
            if not rest and i + 1 < len(texts):
                rest = texts[i + 1]
            tags += [x for x in re.split(r"[、,，/;；\s]+", rest) if x]
        elif t.startswith("你们的共同点"):
            rest = t.split("：", 1)[-1].strip() if "：" in t else ""
            if not rest and i + 1 < len(texts):
                rest = texts[i + 1]
            common += [x for x in re.split(r"[、,，/;；\s]+", rest) if x]
        elif t.startswith("Ta的星座"):
            extra["星座"] = t.split("：", 1)[-1].strip()
        elif re.fullmatch(r"\d{1,3}%", t):
            extra["匹配度"] = t
        elif t.startswith("Ta的礼仪分"):
            extra["礼仪分"] = re.sub(r"^Ta的礼仪分[：:]\s*", "", t)

    # 昵称：卡片区（140~560）里最靠上的一行短文本，排除页面固定文案
    nick = ""
    for n in sorted([x for x in nodes if 140 < x.center[1] < 560],
                    key=lambda x: (x.center[1], x.center[0])):
        t = n.label.strip()
        if not (1 <= len(t) <= 14):
            continue
        if t in UI_TEXTS or t.startswith("关注后") or "匹配" in t:
            continue
        nick = t
        break
    return {"nick": nick, "tags": tags, "common": common, "extra": extra}


def _lcs(a, b):
    """最长公共子串长度（a/b 都很短，DP 足够）。"""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def check(text, tags=None, common=None, limit=LIMIT):
    """废句校验。返回 (ok, reason)。ok=False 必须重写。"""
    t = (text or "").strip()
    if not t:
        return False, "空"
    if len(t) > limit:
        return False, "超长 %d 字" % len(t)
    if len(t) < 3:
        return False, "太短"
    for r in BAD_RE:
        if r.search(t):
            return False, "套话/编造: %s" % r.pattern
    for w in META_WORDS:
        if w in t:
            return False, "出现元词 %s" % w
    # 复述：与引力签/共同点有 >=4 字连续重合，等于把她的标签念回去
    for src in list(tags or []) + list(common or []):
        s = (src or "").strip()
        if len(s) >= 4 and _lcs(t, s) >= 4:
            return False, "复述资料 %r" % s
    # 把我自己的信息当成她的（她资料里没出现过的我的专属词，一律不许提）
    pool = " ".join([str(x) for x in (list(tags or []) + list(common or []))]).lower()
    low = t.lower()
    for w in my_words():
        if w in low and w not in pool:
            return False, "套我的信息 %r" % w
    # 括号表情太长（旧引擎已剥，这里兜底）
    if re.search(r"\[[^\]]{3,}\]", t):
        return False, "表情过长"
    return True, ""


def score(text, tags=None, common=None):
    """越像「能接话的开场」分越高。

    🔴 2026-11-08（_report/14 实测修复）：
      改前 —— `if ASK_RE.search(text): s += 3`：**问句加分**，
      于是选出来的开场白全是查户口（问句率实测 31.3%）。
      改后 —— **陈述句优先**：
        · 硬问句（真疑问句）      −3
        · offer 型问句（我请你…）  +1（问的是我给得起的东西，可以留）
        · 陈述句 + 自带话头        +2
        · 结尾是句号/感叹的纯陈述  +1（不再是 −2，陈述句现在就该被选上）
      依据：报告-11 保持热度 offer 37.5% > probe 25.9% > 陈述 7.3%；
      match 旧库里的问句全部落在 **probe（要她提供信息）** 那一档，
      是三种里最差的一类，而旧代码偏偏给 probe 加分。
    """
    t = (text or "").strip()
    s = 0
    hard_ask = bool(ASK_HARD.search(t)) or t.endswith(("？", "?"))
    if hard_ask:
        if OFFER_RE.search(t):
            s += 1                     # offer 型：给得起东西，允许问
        elif SOFT_ASK_RE.search(t) and not re.search(r"你(?:是|做|住|在).{0,6}(?:吗|哪|什么|啥)", t):
            s -= 1                     # 低压力问句（问她此刻状态）：轻罚，可保留
        else:
            s -= 3                     # 查户口问句：重罚
    else:
        s += 2                         # 陈述句：本策略的主力
        if t.endswith(("。", "！", "!")):
            s += 1
    n = len(t)
    if 6 <= n <= 16:
        s += 1
    elif n > LIMIT:
        s -= 5
    # 太平、没有具体画面的泛句降权（「过来打个招呼」这类必须有别的分撑住）
    if not re.search(r"[你我他她咱]|今天|这会儿|刚", t):
        s -= 1
    return s


def _ask_rate_ok(pool, limit=0.12):
    """诊断用：这一池句子的硬问句比例是不是压到了目标线以下。"""
    if not pool:
        return True
    n = sum(1 for t in pool if ASK_HARD.search(t) or t.endswith(("？", "?")))
    return (float(n) / len(pool)) <= limit


def _ask_ratio_used(used):
    """最近记录里硬问句占多少（用于配额判定）。"""
    tail = list(used or [])[-10:]
    if not tail:
        return 0.0
    n = sum(1 for t in tail if ASK_HARD.search(t or "") or (t or "").endswith(("？", "?")))
    return float(n) / len(tail)


def _should_ask_now(used):
    """这一次要不要允许用问句开场（严格限量）。

    规则：最近 10 条开场白里的问句比例 < OPEN_ASK_RATE(12%) 才允许插一条。
    这样问句率在结构上被钉在 12% 以下，而不是靠库里数量比例"碰运气"。
    """
    import random
    if _ask_ratio_used(used) >= OPEN_ASK_RATE:
        return False
    return random.random() < OPEN_ASK_RATE


def pick_opener(avoid_recent=12):
    """从通用开场白库挑一条，避开最近用过的。

    🔴 2026-11-08（_report/14：match 开场白问句率 31.3% → 目标 <12%）：
      改前是**纯随机** `random.choice(pool)` —— 库里问句占大头，
      抽出来自然就是查户口。现在改成**先分池、再在陈述池里随机**：
        · 陈述池 = 非硬问句  → 默认从这里抽（这就是 88% 以上的出话）
        · 问句池 = 硬问句    → 只有陈述池被"最近用过"掏空时才回落，
                                并用 _OPEN_ASK_QUOTA 控制占比
      保留随机性（避免每天同一句），但**结构上**保证问句不再是主力。
    """
    import json
    import random

    used = []
    try:
        used = json.loads(_head_file().read_text("utf-8"))
    except Exception:
        used = []

    def _is_ask(x):
        return bool(ASK_HARD.search(x)) or x.endswith(("？", "?"))

    def _fresh(pool, n):
        return [t for t in pool if t not in used[-n:]]

    stmt_pool = [t for t in OPENERS if not _is_ask(t)]
    ask_pool = [t for t in OPENERS if _is_ask(t)]

    # 主力：陈述池里挑没用过的
    pool = _fresh(stmt_pool, avoid_recent)
    if not pool:                       # 陈述句全用过了 -> 只避开最近 5 条
        pool = _fresh(stmt_pool, 5) or stmt_pool
    # 交叉：每 OPEN_ASK_EVERY 次允许插一条问句（让库不呆板，但严格限量）
    if ask_pool and _should_ask_now(used):
        ap = _fresh(ask_pool, avoid_recent) or ask_pool
        if ap:
            pool = ap

    t = random.choice(pool) if pool else (FALLBACK[0])
    try:
        used = (used + [t])[-40:]
        _head_file().write_text(json.dumps(used, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("记开场白失败: %r", e)
    return t


def opening(b, card, limit=LIMIT, tries=4, engine_gen=False):
    """出开场白。返回 (text, tries_log)。

    默认（engine_gen=False，用户 2026-11-02 口径）用**通用开场白库**：
    匹配次数按天限量，通用句稳、0 延迟、不会编造，比等引擎 6s 更划算。
    engine_gen=True 时才走旧引擎个性化生成（带三道废句闸 + 兜底）。
    """
    if not engine_gen:
        t = pick_opener()
        return t, [(t, True, "通用库", 3)]

    tags, common = card.get("tags") or [], card.get("common") or []
    nick = card.get("nick") or ""
    cands = []
    for i in range(tries):
        try:
            t, _ms = b.opening_line(sid="", nick=nick, hist=[], tags=tags,
                                    common=common, kind="match", limit=limit)
        except Exception as e:
            log.warning("opening_line 第%d次异常: %r", i + 1, e)
            continue
        t = (t or "").strip()
        ok, why = check(t, tags, common, limit)
        sc = score(t, tags, common) if ok else -99
        cands.append((t, ok, why, sc))
        log.info("候选%d %r ok=%s %s score=%d", i + 1, t[:26], ok, why, sc)
        # 🔴 2026-11-08（_report/14 修复）：这里原来是
        #     `if ok and ASK_RE.search(t): return t`  → **问句一出现就提前收工**，
        #   这正是查户口开场白的直接来源（实测 `你是开网店的吗？` 就是这么出去的）。
        #   现在反过来：**拿到合格陈述句就提前收工**（陈述句是本策略的主力），
        #   问句只在没有陈述句时靠 score 参与比较。
        if ok and not ASK_HARD.search(t) and not t.endswith(("？", "?")) and sc >= 3:
            return t, cands            # 合格陈述句且分数够 → 直接用
    good = [c for c in cands if c[1]]
    if good:
        good.sort(key=lambda c: -c[3])
        return good[0][0], cands
    return _fallback(), cands


# ---------------- 执行 ----------------
def _head_file():
    from core.paths import STATE
    return STATE / "match_heads.json"


def _fallback():
    """全废兜底：挑一条最近没用过的通用开场。"""
    import json
    used = []
    try:
        used = json.loads(_head_file().read_text("utf-8"))
    except Exception:
        used = []
    pick = None
    for t in FALLBACK:
        if t not in used:
            pick = t
            break
    pick = pick or FALLBACK[0]
    try:
        used = (used + [pick])[-6:]
        _head_file().write_text(json.dumps(used, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("记兜底句失败: %r", e)
    log.warning("四条候选全废，改用兜底句 %r", pick)
    return pick


def _local_opener(card):
    """本地模型生成开场白（用户 2026-11-04 定：废弃固定池子，改本地模型生成）。

    引擎不可用 / 生成全废时才退回 _fallback 兜底（3 条安全句）。
    opening(engine_gen=True) 内部已带三道废句闸（check）——历史问题「把我的信息
    （江华/三江/卖数码）当成她的编出去」会被 MY_WORDS 闸拦掉，不会漏出去。

    🔴 2026-11-08（_report/14：实测 67 条 match 开场白里问句率 31.3%）：
      模型几乎每次都优先吐问句（`你是开网店的吗？` `你也住重庆吗？` `观自在是啥意思啊？`），
      而 `check()` 只拦「编造/套信息/复述资料」，**不拦问句** → 全部放行。
      这里加最后一道**问句配额闸**：
        · 模型出的是硬问句，且最近 10 条里问句已到 OPEN_ASK_RATE → 丢弃，改走
          `pick_opener()` 的陈述池（结构上保证问句不超标）
        · offer 型问句（「要不要聊聊…」）不受限：它问的是我给得起的东西
      这是**本文件内**的策略修正，不动 brain/engine/opener.py（别人的写域）。
    """
    try:
        from brain import reply as _R
        b = _R.engine()
        if b is not None and hasattr(b, "opening_line"):
            t, _ = opening(b, card, engine_gen=True)
            t = (t or "").strip()
            if t:
                is_ask = bool(ASK_HARD.search(t)) or t.endswith(("？", "?"))
                if is_ask and not OFFER_RE.search(t):
                    try:
                        import json
                        used = json.loads(_head_file().read_text("utf-8"))
                    except Exception:
                        used = []
                    if _ask_ratio_used(used) >= OPEN_ASK_RATE:
                        log.info("开场白问句配额已满 → 弃用模型问句 %r，改用陈述库", t[:24])
                        return pick_opener()
                return t
    except Exception as e:
        log.warning("本地开场白生成异常，退回兜底: %r", e)
    return _fallback()


def send(actor, dev, text, sid=""):
    """灌字 -> 发送 -> 校验输入框。返回 (ok, 说明)。"""
    from hands.input import Input

    # 🔴 2026-11-03 修复：匹配开场白原来只 note_sent() 不检查上限，
    #    与唤醒一起构成"限流盲区"（小时上限对这两条链路无效）。
    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            return False, "本小时发送已达上限"
    except Exception:
        pass

    # 跟进阶梯发送闸：sid 为空（奇遇铃 / 匹配 / 新招呼等新会话开场白）
    # 过闸放行，但不占 2/6 条跟进额度；将来调用方拿到 sid 传进来即自动受约束。
    try:
        from brain import sendgate as SG
        _d = SG.allow(sid, 1)
        if not _d.ok:
            log.info("跟进阶梯拦截 sid=%s state=%s（%s）", sid, _d.state, _d.reason)
            return False, "跟进阶梯拦截(%s)" % _d.state
    except Exception:
        pass

    # 发送前先声明：这一段库写入都是我自己的
    try:
        from data import watch as _W
        _W.mark_self_write(20.0)
    except Exception:
        pass

    inp = Input(dev)
    ok, got = inp.type_and_verify(text, actor)
    if not ok:
        inp.clear()
        return False, "灌字失败(实际 %r)" % (got,)
    if not inp.tap_send(actor, settle=1.6):
        inp.clear()
        return False, "找不到发送按钮"
    if not inp.sent_ok(actor, text, timeout=6):
        return False, "发送后输入框未清空"
    # 开场白也是自己写的库变化，必须抑制（否则匹配刚发完就被自己的写入打断）
    try:
        from data import watch as _W
        _W.mark_self_write(6.0)
    except Exception:
        pass
    try:
        from brain import ratelimit as _RL
        _RL.note_sent()
    except Exception:
        pass
    if sid:
        try:
            from brain import sendgate as SG
            SG.note_sent(sid, 1)
        except Exception:
            pass
    return True, "已发送"


def next_one(actor, waits=(1.0, 1.0, 1.0)):
    """点「匹配下一个」→ 等 1s → 重新识屏；还在匹配就再等 1s，**最多 3 次**。

    用户 2026-11-02 明确的口径。不能一次等到 14s：
    匹配换人通常 1~2s 就完成，等太久会卡在无效轮询上；
    也不能只看一次：设备卡时 dump 本身要 2.3s，第一次识屏可能还在转场。
    """
    snap = actor.snap()
    n = snap.find_one(text=NEXT_TEXT)
    if n is None:
        return snap, "no_button"
    before = snap.signature()
    actor.hand.tap_node(n, settle=0.2)

    for i, w in enumerate(waits):
        time.sleep(w)
        s = actor.snap(force=True)
        sig, pg = s.signature(), detect(s)
        if sig != before and (pg == "chat" or has_card(s)):
            log.info("第%d次识屏确认已换人 (sig %s -> %s)", i + 1, before, sig)
            return s, "chat"
        log.info("第%d次识屏还没换（page=%s sig=%s）", i + 1, pg, sig)

    s = actor.snap(force=False)
    return s, detect(s)


# 匹配额度用完的提示（实测弹层原文：「今日免费匹配机会已用完 (50/50)」）
QUOTA_HINT = "匹配机会已用完"


def quota_out(snap):
    """当前是不是弹着「今日免费匹配机会已用完」的遮罩。

    🔴 2026-11-02 实测：额度 50/50 用完后，点「开始匹配」只会从底部升起这个
       半屏弹层（卖次数卡 + 做任务），**页面永远进不到会话页**。原来的实现
       一路等到 25~50 秒超时，每次白烧半分钟（用户看到的「匹配空烧」）。
    """
    try:
        return QUOTA_HINT in " ".join(snap.texts())
    except Exception:
        return False


def start_match(actor, max_wait=25):
    """回星球页点「开始匹配」，等到会话页。返回 (snap, page)。

    用户 2026-11-02：匹配页有时候没有「匹配下一个」，那就退回星球页重新匹配。
    """
    from brain import nav

    nav.ensure_app(actor.dev)
    snap, pg = nav.to_tab(actor, "星球")
    if pg != "planet":
        return snap, pg                      # 回不到星球页，由上层记失败

    n = snap.hit(text="开始匹配")
    if n is None:
        return snap, "no_start"
    log.info("点开始匹配 %s", n.bounds)
    actor.hand.tap_node(n, settle=2.0)

    # 🔴 点之前先看一眼（有的版本额度用完会直接在星球页弹层）
    if quota_out(snap):
        log.warning("今日匹配额度已用完（点之前就看到了）→ 不点，直接放弃")
        return snap, "no_quota"

    # 等进入会话页（中间有匹配动画，实测 3~5s）
    # 🔴 原来等 50s：一旦匹配页没响应，一轮就白烧 50 秒（用户 2026-11-02：匹配在空烧）。
    #    25s 足够覆盖动画 + 慢设备；超时就当失败，交给上层退避。
    t0 = time.time()
    while time.time() - t0 < max_wait:
        s = actor.snap(force=True)
        # 额度用完：第一轮就能看出来，立刻关掉弹层别等
        if quota_out(s):
            log.warning("今日匹配额度已用完 → 关掉弹层，今天不再匹配")
            actor.hand.back(settle=1.3)
            return s, "no_quota"
        pg2 = detect(s)
        if pg2 == "chat":
            return s, pg2
        if has_card(s):
            return s, "chat"
        time.sleep(1.2)
    return actor.snap(force=True), "timeout"


def run_once(actor, dev, db, dry_run=False, preempt=None):
    """处理**当前**匹配会话：建档 -> 发通用开场白 -> 存旧案情包。

    daemon 每轮调它一次，再调 advance() 前进。返回 dict：
        {ok, sent, text, prof, sid, err}
    铁律：没发成功不点「匹配下一个」（会白费一次匹配次数）。
    """
    from brain import casepack as CP

    out = {"ok": False, "sent": False, "text": "", "prof": None, "sid": None,
           "err": "", "preempted": "", "skip_said": False}

    # 🔴 从这一刻起我造成的库变化都不算「新消息」（进会话/发开场白都会写库），
    #    否则下面 preempt 检查必然命中，匹配永远发完一句就退。
    try:
        from data import watch as _W
        _W.mark_self_write(40.0)
    except Exception:
        pass

    snap = actor.snap(force=True)
    if detect(snap) != "chat":
        out["err"] = "不在会话页(%s)" % detect(snap)
        return out

    card = read_card(snap)
    said, bs = said_already(dev, snap)
    if said:
        log.info("该会话已说过话（气泡 %d 条），跳过发送", len(bs))
        out["ok"] = True
        out["err"] = "已说过话"
        # 🔴 2026-11-03 修复 P1：抢占留会话后二次进入，需前进不重发
        #    （daemon 据此调 advance，而不是把「已说过话」当失败卡死）。
        out["skip_said"] = True
        return out

    # ① 进对方主页建档
    prof = None
    try:
        prof, pok = visit_profile(actor)
        if pok:
            out["prof"] = prof
            log.info("主页建档 %s", prof)
    except Exception as e:
        log.warning("主页建档异常（继续发开场白）: %r", e)

    # ② 发开场白（用户 2026-11-04 定：本地模型生成，废弃固定池子）
    text = _local_opener(card)
    out["text"] = text
    log.info("开场白 %r", text)
    if dry_run:
        out["ok"] = True
        return out

    ok, why = send(actor, dev, text)
    if not ok:
        out["err"] = why
        log.warning("发送失败: %s", why)
        return out
    out["sent"] = True
    out["ok"] = True

    # ③ 落旧案情包 L4
    if prof:
        try:
            sid = CP.find_sid(db, text, device=dev)
            if sid:
                CP.save_profile(sid, prof, tags=card["tags"], common=card["common"])
                out["sid"] = sid
                log.info("案情包已写 sid=%s", sid)
                # 🧠 新匹配的人：立刻让本地模型出画像/方案（用户 2026-11-02）
                #    这样她第一次回话时，出话层已经有「她是什么人」可用，
                #    不用等她聊十句才开始建模。
                try:
                    from brain import reply as _R
                    _R.warm_local(sid, db, her_msg="", nick=prof.get("nick") or "")
                except Exception as _e:
                    log.debug("本地分析投递异常（不影响开场白）: %r", _e)
            else:
                log.warning("反查不到 sid，跳过建档（宁可不写，不可写错人）")
        except Exception as e:
            log.warning("写案情包异常: %r", e)

    # ④ 🔴 抢占检查（用户 2026-11-02）：「匹配中有新消息也要退出来，
    #    但是退出之前一定要把开场白发了来」——所以检查点放在**发完之后**。
    #    命中就不 advance，把这个会话留着（下次 run_once 会判"已说过话"再前进），
    #    这样既不浪费匹配次数，又能立刻回去处理新消息/铃。
    if preempt is not None:
        try:
            why = preempt()
            if why:
                log.info("⚡ 开场白已发，但检测到 %s → 不前进，立刻回去处理", why)
                out["preempted"] = why
        except Exception as e:
            log.warning("抢占检查异常（按不抢占处理）: %r", e)
    return out


def advance(actor):
    """不再预开下一张匹配卡（2026-11-03 修复：省一半匹配额度）。

    原实现：点「匹配下一个」/「开始匹配」会把下一个人加载到屏幕上，
    但下一轮 `cycle` 开头 `nav.to_chatlist` 立刻把这张卡顶掉 ——
    开场白一句都发不出去，而这次匹配**已经扣了额度**。
    实测一次发送消耗 2 次匹配机会（50/50 实际只能用约 25 人）。

    现在只做占位、不点任何按钮，交给下一轮 `start_match` 正常匹配（1 次/句）。
    返回 (snap, page, how)，how 固定 "defer"；现有调用方都不使用返回值。
    """
    snap = actor.snap()
    log.info("不预开下一张匹配卡（省额度）→ 下一轮正常匹配")
    return snap, "defer", "defer"


def visit_profile(actor, settle=2.5):
    """进对方个人主页抓资料，再返回会话页。返回 (prof, ok)。

    用户 2026-11-02：**匹配到人要先建对方主页档案**（存进旧案情包 L4），
    后续回复/画像才有依据（已婚/职场打工人这类标签直接决定话术边界）。

    入口：会话页右上「查看主页」(725,219,900,288)，或对方头像 userAvatar。
    """
    from eyes import profile as P

    snap = actor.snap()
    n = snap.hit(text="查看主页")

    if n is None:
        # ② 对方头像（userAvatar）
        av = [x for x in snap.nodes
              if x.clickable and ("userAvatar" in (x.res_id or "") or (x.desc or "") == "头像")]
        if av:
            av.sort(key=lambda x: x.center[0])
            n = av[0]

    if n is None:
        # ③ 会话页顶部的对方昵称（实测 y≈105、x≈450）——普通会话页没有「查看主页」，
        #    但点昵称能进主页；这一步让「聊天时补建档案」真正可行。
        skip = ("返回", "关注", "聊天设置", "更多", "搜索", "通讯录",
                "8小时前", "刚刚在线", "在线")
        cands = [x for x in snap.nodes
                 if x.label and x.clickable and x.center[1] < 170
                 and 150 < x.center[0] < 800
                 and x.label.strip() not in skip
                 and 1 <= len(x.label.strip()) <= 16
                 and "TextView" in (x.cls or "")        # 🔴 只认文本节点，别点到容器
                 and ":" not in x.label and "：" not in x.label]  # 时间/副标题排除
        if cands:
            # 🔴 原来取 cands[0]（文档顺序，可能是顶栏某个容器）；改成从上到下、从左到右
            cands.sort(key=lambda x: (x.center[1], x.center[0]))
            n = cands[0]
            log.info("用顶部昵称 %r 进主页", n.label)

    if n is None:
        log.info("会话页没有进主页的入口（普通会话），跳过建档")
        return None, False

    log.info("进对方主页 %s", n.bounds)
    actor.hand.tap_node(n, settle=settle)
    s = actor.snap(force=True)

    txt = "\n".join(s.texts())
    if not any(k in txt for k in ("灵魂画像", "Ta的展品馆", "IP属地", "被关注")):
        log.warning("点了查看主页但没进主页（page=%s）", detect(s))
        # 🔴 2026-11-03：只有真的离开了会话页才 back。点空时（仍停在 chat）
        #    盲按返回会把会话页退到列表 —— 这就是用户看到的「瞎操作」。
        if detect(s) != "chat":
            actor.hand.back(settle=1.2)
        return None, False

    prof = P.read(s)
    log.info("主页资料: %s", P.summary(prof))

    actor.hand.back(settle=1.5)                  # 主页返回是安全的（不是主框架 root）
    s2, pg = actor.wait_page(("chat",), timeout=6.0)
    if pg != "chat":
        log.warning("从主页返回后页面=%s", pg)
    return prof, True


def has_card(snap):
    """当前会话页是不是「刚匹配、还没说话」的资料卡。

    实测匹配卡上一定会有「匹配度」+ 百分比；引力签/星座不一定显示（有人在星球
    里没填），所以不能只靠那两项。
    """
    txt = "\n".join(snap.texts())
    if "匹配度" in txt:
        return True
    if "Ta的引力签" in txt or "Ta的星座" in txt:
        return True
    return False


CARD_AREA_BOTTOM = 640   # 匹配资料卡（含兴趣标签云）占据的纵向区域，实测底部 ~600

# 🔴🔴 2026-11-08 11:3x（P0·用户：「进入对话页那么久了 开场白还发不出去」）
#
#   【实测根因】生产日志里连续 6+ 次出现：
#       「该会话已说过话（气泡 3 条），跳过发送」
#       「该匹配会话已说过话 → 前进到下一个人（不重发）」
#   而那一屏**明明是全新匹配卡**（树里有「匹配度 96%」「查看主页」「灵感回复可提升回复率哦」，
#   一条消息都没有）。于是每一张新卡都被判「已说过话」→ 开场白一次都不发 → 匹配额度白烧。
#
#   为什么 OCR 会判成「我发过」：全新卡下面有一整块 **灵感回复建议**（Soul 给的快捷句），
#   实测 11:32 的 OCR：
#       (76,1216) '你好／可以认识吗'   (79,1275) '✨带个目的，直球破冰吧'
#       (76,1358) '嗨，你好／在干嘛呀？'  (102,1141) '灵感回复可提升回复率哦'
#   这些**不在 a11y 树里**（intree=False），所以「树里有 → 剔除」这一招对它们无效；
#   而资料卡区域过滤只挡了 y<640，它们全在 y=1100~1400 ⇒ 漏进来。
#   只要其中任意一条的 OCR 框右边界 >= 700（实测 '派对大厅>'/'狼人魅影' 这类右侧元素
#   和长句建议句都会），side_of() 就判成 me ⇒ said_already=True。
#
#   【修法·两层，都是硬判据不是调阈值】
#     ① **树标记优先**：全新卡一定有「灵感回复可提升回复率哦」，
#        而发过话之后这个标记会变成「内容由AI生成，仅供参考」（11:26 发完后实测）。
#        ⇒ 见到前者就 100% 说明「一句都没发过」，直接返回 False，连 OCR 都不用跑（省 2s）。
#     ② 有卡时，把「灵感回复/建议句」所在的 y>=1100 整段排除出气泡判定。
#        真正的消息气泡在卡上出现在 y≈680~900（实测我发的那句在 714）。
CARD_FRESH_MARK = "灵感回复可提升回复率哦"
CARD_REPLY_MARK = "内容由AI生成"
SUGGEST_Y_TOP = 1100     # 卡上「灵感回复」建议区上界（实测 1123~1400）


def said_already(dev, snap=None):
    """当前会话里我是否已经发过消息。返回 (bool, bubbles)。

    Soul 的气泡不在 a11y 树里，只能截图 OCR 看左右（x2>=700 = 我）。
    但匹配资料卡上的文字会混进 OCR，实测两类误判：
      ① 「95%」「查看主页」这类右侧元素 -> 被当成我方气泡
      ② 兴趣标签云「美食音乐追剧阅读」「）（街头文化」被合并识别成一行、
         落到右侧 x=447..811 -> 也被当成我方气泡
    两个干净判据：
      ① 卡片文字全都在 UI 树里，真正的消息气泡不在树里 -> 按文本剔除
      ② 资料卡区域（y < CARD_AREA_BOTTOM）里的东西一律不是消息 -> 按区域剔除
    """
    from eyes import chat as C

    if snap is None:
        from eyes.uitree import Screen
        snap = Screen(dev).get(force=True)
    tree = set(t.strip() for t in snap.texts() if t and t.strip())
    card = has_card(snap)

    # ① 全新匹配卡：树里有「灵感回复可提升回复率哦」⇒ 一句都没发过（见上方长注释）
    if card and CARD_FRESH_MARK in tree:
        return False, []

    png = dev.screencap()
    bs = C.bubbles(png)
    real = []
    for b in bs:
        t, side, it = b
        if t.strip() in tree:
            continue
        if card and it.cy < CARD_AREA_BOTTOM:
            continue
        # ② 卡上的「灵感回复」建议区（y>=1100）不是消息，一律排除
        if card and it.cy >= SUGGEST_Y_TOP:
            continue
        real.append(b)
    return any(side == "me" for _t, side, _it in real), real
