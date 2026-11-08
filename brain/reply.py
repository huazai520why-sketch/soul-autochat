# -*- coding: utf-8 -*-
"""回复生成：直接复用旧引擎（E:\\soul2.1\\brain\\soul_brain.brain_reply）。

为什么不重写（用户 2026-11-02 明确「回复层尽量按旧脚本」）：
- 旧引擎里是 v5b 的整套对话设计（人设 4961 字、技能库、L0~L4 记忆、禁编造、
  承诺硬拦、防复读、关系档案），重写等于把这些历史结论全部推翻重来。
- 实测可直接 import 并使用：`brain_reply(her_msg="你好呀")` 2.3s 出话。

注意：
- 必须传**真实 sid**（形如 402857053500884668），因为引擎用 sid 去
  memory 里读该联系人的账号/人设/关系档案；假 sid 会走空档并可能返回 None。
- 旧引擎自身有顶层兜底，异常不会冲出。这里再加一层，绝不让它影响必回。

🔴 2026-11-02 用户三条口径（本文件据此改造）：
  ①「她刚发来的这一句有可能是几句，不要固定发了多少喂多少」
     → `merge_burst()` 把她连发的几条按顺序合并，带上条数标注一起喂；
  ②「回复内容也是可以发多条，不要固定一条」
     → `generate()` 返回 **list**（1~3 条），`target_n()` 按她的内容自适应条数；
  ③「死磕不用喂了」
     → 删掉 `stuck_line` 注入（旧引擎那个「本轮必须换话题」的强制指令，
       实测会把正常接话也压掉，用户明确不要了）。
"""
import os
import sys
import threading
import datetime

from core.log import get_logger

log = get_logger("brain.reply")

LEGACY_BASE = r"E:\soul2.1"
# 引擎选择：v10（默认，本仓） / legacy（旧 2.1 soul_brain，仅回滚用）
ENGINE_KIND = (os.environ.get("SOUL_ENGINE", "v10") or "v10").strip().lower()
_ENGINE = None
_LOCK = threading.Lock()

# 本地模型的熔断状态（连续无产出就静默一段时间，别反复白等）
_LOCAL_GUARD = {"fail": 0, "until": 0.0}
# 同一个人多久内不重复跑本地分析（画像+方案实测 22s，太快重复只会积压队列）
_WARM_LAST = {}
# 🔴 2026-11-03（用户口径）：**每一条新消息都重新算**，不再 10 分钟一次。
#   连发多条由 soul_localq 的合并语义兜住（只跑「当前这轮 + 最后状态那轮」）。
WARM_GAP_S = 0.0

# 她一次最多合并几条。用户 2026-11-03：「上限 10 条吧」
# 原来 4 —— 当天实测出现过连发 5 条，第一条被硬截断（若那句是问句就漏答）。
HER_BURST_MAX = 10
# 我一轮最多发几条（旧架构 ADAPT_CAP=3，宁少勿多，避免话痨穿帮）
ADAPT_CAP = 2          # 2026-11-03：用户口径「最多发两条」；V9 提示词也只让出一两句
# 🔴 2026-11-03：旧引擎的 `n_cand` 语义是「生成 N 条**候选**挑 1 条」
#   （CAND_HINT 原文：输出 N 行互相不同的候选……答她/笑点/钩子三格）。
#   1.0 把 N 条候选**全发出去** → 三条各说各的、同义复读。
#   修法：默认逐句生成（每句一次调用，第 2 句起带 follow_up_of 防撞），
#   SOUL_MULTI_SEND=0 可回滚成「一次生成 N 条候选然后全发」的旧行为。
MULTI_SEND = os.environ.get("SOUL_MULTI_SEND", "1") != "0"
# 🔴 2026-11-03：V9 结构下**一次调用就能出一两句**（提示词里已写明「两句分两行」），
#   不再逐句调 N 次。逐句调在 V9 下纯属浪费：每句都要重跑一次完整 prompt。
_PROMPT_V9 = (os.environ.get("SOUL_PROMPT_V9", "1") or "1").strip() == "1"

# 🔴 2026-11-09（用户口径「重新安装原技能就行了」）：本地模型重新按三技能
#   （analyze_her / ask_strategist / ask_tongjincheng）出画像 L0 + 方案 L1，
#   执行器见 brain/skills.py，提示词已装回 config/skills/。
#   SOUL_LOCAL_FLOW=brief 可一键回到 2026-11-04 之后的「本轮简报」。
LOCAL_FLOW = (os.environ.get("SOUL_LOCAL_FLOW", "skills") or "skills").strip().lower()


def engine():
    """懒加载出话引擎。并发安全（首次 import 加锁）。

    🔴 2026-11-04 重构：默认走**本仓 v10 引擎**（brain.engine），
       提示词/人设/硬闸全部重写，零 E:\\soul2.1 依赖。
       保留 `SOUL_ENGINE=legacy` 回滚到旧 soul_brain（只在 2.1 目录还在时有效）。
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if ENGINE_KIND != "legacy":
            try:
                import importlib
                _E = importlib.import_module("brain.engine")
                if not _E.available():
                    log.warning("v10 引擎没有可用密钥（.ark_key 缺失），本轮可能出不了话")
                _ENGINE = _E
                log.info("出话引擎 v10 已加载")
                return _ENGINE
            except Exception as e:
                log.warning("v10 引擎加载失败，回落 legacy: %r", e)
        for p in (LEGACY_BASE, LEGACY_BASE + r"\brain"):
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            import soul_brain  # noqa: F401
        except Exception as e:
            log.warning("旧出话引擎加载失败: %r", e)
            _ENGINE = False
            return None
        _ENGINE = soul_brain
        log.info("旧出话引擎已加载 (PERSONA %d 字)", len(soul_brain.PERSONA or ""))
        return _ENGINE


def available():
    return engine() is not None


def build_hist(messages, uid, limit=10):
    """把数据库消息转成旧引擎要的历史结构。

    旧引擎要求 `[{"role": "me"/"her", "text": "..."}]`（见 soul_brain._build_case:
    `("我: " if h.get("role") == "me" else "她: ") + h.get("text")`），
    text 由调用方截断（旧 daemon 用 [:100]）。
    """
    out = []
    for m in messages[-limit:]:
        if m.msg_type != 1:
            continue
        t = (m.text or "").strip()
        if not t:
            continue
        out.append({
            "role": "me" if str(m.sender) == str(uid) else "her",
            "text": t[:100],
        })
    return out


def hist_with_her(hist, her_msg):
    """确保 hist 的最后一条就是「她刚说的这句」。

    🔴 2026-11-04（数据链修复的配套）：她的新话可能只在 session 摘要里，
      chatmsg 没有对应记录 —— 此时 build_hist 拼出来的历史以**我方发言**结尾，
      而 her_msg 又是一个独立参数，两处上下文互相矛盾，模型会接着自己上一句说
      （实测表现就是「答非所问 / 自说自话」）。这里把事实补全，不改任何话术。
    """
    out = list(hist or [])
    t = (her_msg or "").strip()
    if not t:
        return out
    if out and (out[-1] or {}).get("role") == "her":
        last = ((out[-1] or {}).get("text") or "").strip()
        if last == t[:100] or last == t or (last and last in t):
            return out
    out.append({"role": "her", "text": t[:100]})
    return out


# ══════════════════ 多条：她连发 vs 我多条 ══════════════════

def merge_burst(lines):
    """把她连发的几条**合并成一句话**喂给引擎。

    用户 2026-11-03 口径：「拼装合并成一条喂给模型」。

    为什么改（旧做法的问题）：
      原来是 `（她连着发了 N 条，按顺序都要接住，别只答最后一条）\n她: xxx\n她: yyy`。
      ① 带一条指令，模型会逐条应答 → 像客服（她发「[笑哭]/没什么/你挺好玩的」，
         会被回成三句各答一条，而不是顺着「你挺好玩的」接一句）；
      ② 「她: 」前缀是转写格式，不是她说话的方式。
    现在按时间顺序直接接成一段：片段之间没标点就补「，」，已有标点直接接。
    单条 → 原样返回（不加工，避免污染模型对语气长度的判断）。
    """
    ls = [(l or "").strip() for l in (lines or [])]
    ls = [l for l in ls if l]
    if not ls:
        return ""
    if len(ls) == 1:
        return ls[0]
    out = ""
    for x in ls:
        if not out:
            out = x
        elif out[-1] in "，。！？、,.!?~～…；;":
            out += x
        else:
            out += "，" + x
    return out


# 提问判据（旧 daemon 口径：问号 / 结尾「吗」/ 常见疑问词；
# 不收单字「呢/嘛」——「嗯呢」不是提问）
_Q_WORDS = ("怎么", "咋", "为什么", "为啥", "哪儿", "哪里", "多少", "多久",
            "几点", "干嘛", "在吗", "是不是", "要不要", "好不好", "啥")


def _is_question(t):
    t = t or ""
    if "?" in t or "？" in t or t.endswith("吗"):
        return True
    return any(w in t for w in _Q_WORDS)


def target_n(her_lines, hist=None):
    """本轮该发几条（1~ADAPT_CAP，2026-11-03 起上限 = 2）。用户 2026-11-02：「回复内容也可以发多条」。

    参考旧 daemon `_adaptive_target`（宁少勿多，避免话痨穿帮）：
      · 她 1 条、≤6 字且不是提问      → 1 条（「嗯」「哈哈」不值得连发）
      · 她 1 条、7~13 字或带提问      → 2 条（先答她，再补一句）
      · 她 1 条、≥14 字且带提问       → 2 条（原 3，2026-11-03 用户定「最多两条」）
      · 她连发 2 条                   → 2 条
      · 她连发 ≥3 条                  → 2 条（合并成一句后不再是逐条回应）
      · 首次聊天（她说过的话 <2 句）   → 最多 2 条，刚认识不刷屏
    """
    lines = [(l or "").strip() for l in (her_lines or [])]
    lines = [l for l in lines if l]
    k = len(lines) or 1
    t = " ".join(lines).strip()
    L = len(t)
    q = _is_question(t)

    if k >= 3:
        n = 2
    elif k == 2:
        n = 2
    else:
        if L <= 6 and not q:
            n = 1
        elif L <= 13:
            n = 2
        else:
            n = 3 if q else 2

    her_n = sum(1 for h in (hist or []) if (h or {}).get("role") == "her")
    if her_n < 2:
        n = min(n, 2)
    # 🔴 2026-11-08（_report/14 实测修复）：她递情绪钩子时，1 条不够。
    #   实测「还不睡」35 次 0 回复的一大成因就是：≤6 字且非提问 → n=1，
    #   而唯一那 1 条又被写成「早点睡」这种关门句。
    #   钩子回合至少 2 条：第 1 条接情绪，第 2 条留话头。
    #   例外：她 4 字以内**且**明确带「睡了/晚安」这类收尾意图时不加（不硬留人）。
    if _hook_hit(t) and not any(w in t for w in ("晚安", "我睡了", "先睡", "睡觉了")):
        n = max(n, 2)
    n = max(1, min(n, ADAPT_CAP))
    return n


# 关系阶段（口径取自人设：初识 0~30 轮 → 熟悉 30~50 → 推进 50~100 → 暧昧 100+）
_STAGES = (
    (30,  "初识期", "目标是让她放松、愿意接话；**不要**要联系方式、不要撩、不要推进"),
    (50,  "熟悉期", "可以交换式了解她（一次一项），开始有来有回的小玩笑；仍不要直接要联系方式"),
    (100, "推进期", "可以适度拉扯、给偏爱感、往见面话题上引；**等她先提**联系方式/见面"),
    (10**9, "暧昧期", "可以自然地谈见面、谈想她；仍是**她主动**，我不催不追"),
)

_DB = {"db": None}          # daemon 启动时注册，用于数消息条数（旧 soul_stage 依赖它自己的账本）


def set_db(db):
    """注册数据库句柄，供阶段判断数消息条数用。"""
    _DB["db"] = db


def _turn_count(sid):
    """这个会话累计多少轮（她+我各一句 ≈ 1 轮 → 用消息条数 /2 估算）。"""
    db = _DB.get("db")
    if not db or not sid:
        return 0
    try:
        n = db.con.execute(
            "SELECT COUNT(*) FROM chatmsg WHERE sessionId=? AND msgType=1",
            (sid,)).fetchone()[0]
        return int(n or 0) // 2
    except Exception:
        return 0


def _stage_line(sid):
    """当前关系阶段一行。人设里写「节奏以注入的【当前关系阶段】为准」，
    不传这句那条规则就是空转的（模型看不到第几轮，只能瞎猜）。

    优先用旧 soul_stage（它有更细的判定），取不到就按消息条数自己算。
    """
    if not sid:
        return ""
    # v10：阶段只认案情包 state.json 里的轮数（可复现，不连数据库、不读第二个源）
    try:
        import importlib
        _st = importlib.import_module("brain.stage")
        line = _st.line(sid) or ""
        if line.strip():
            return line
    except Exception as e:
        log.debug("brain.stage 不可用: %r", e)

    turns = _turn_count(sid)
    if turns <= 0:
        return ""
    for limit, name, goal in _STAGES:
        if turns < limit:
            line = "【当前关系阶段·据此判断该不该升温】%s（已聊约 %d 轮）" % (name, turns)
            return line + "\n· " + goal + "\n"
    return ""


def _night_line():
    """深夜时段强指令（用户 2026-11-03 定，2026-11-04 升级为强指令）：
    21:00~次日6:00 她情绪更敏感、情感更强烈丰富、倾诉欲更高。
    实测 11-03 用软性建议（"尽量/可以"）模型基本忽略，深夜还在聊上班/煮面/守店，
    所以改成「必须 + 禁止 + 具体话术方向」。"""
    h = datetime.datetime.now().hour
    if h >= 21 or h < 6:
        return ("【当前时段·深夜强指令·用户 2026-11-03 定】现在已是深夜（%d 点），"
                "这个点的女生情绪最敏感、情感最强烈、倾诉欲和欲望都最高，"
                "是拉近关系、升温感情的最佳窗口，你必须抓住：\n"
                "· 优先把话题往感情、暧昧、情欲方向引，主动表达好感和想念，适度调情，别端着；\n"
                "· 试探她的感情状态和寂寞情绪，引导她倾诉心事，再顺势升温；\n"
                "· 可以关心她「这么晚还没睡，是不是有心事/在想谁」，把话题往感情上带；\n"
                "· 禁止问「上班吗/在干嘛/吃了吗」这类功能性话题，除非她先提。\n" % h)
    return ""


# ══════════════════ 情绪钩子：她主动递情绪，必须接住 ══════════════════
# 🔴🔴 2026-11-08（依据 _report/14_对话层实效审计.md 的生产实测，最高优先级修复）
#
#   实测（48h 生产日志，1348 条真实出话）：
#     · 她的夜间邀请 37 条 → **25 条完全没回（67.6%）**
#     · 「还不睡」出现 **35 次 → 0 次回复**
#     · 「一个人」16 次 → 只回 1 次
#     · 「莫名想哭」3 次 → **0 次回复**
#     · 夜间 390 条输出里真主动张力 ≈3 条（0.8%）
#
#   根因：这些句子在链路里被当成「没什么信息量的短句」——
#     `target_n()` 判定「1 条、≤6 字、不是提问 → n=1」，
#     而引擎看到「还不睡」只会接成「早点睡 / 你早点休息」这类**劝退**，
#     或者干脆被 `_BUSY_PAT` 那一路的「你忙」思路带走。
#   ⇒ **她递过来的是情绪，回过去的是一句关门话。**
#
#   修法（回复侧，不碰 gate.py）：
#     1. `_match_hook()` 识别她这句里有没有「情绪钩子」；
#     2. 命中就注入 `_hook_alert()` 强指令：**必须接住情绪**，并给出
#        该 hook 专属的「接法约束」+ 明确禁止的回应（例：还不睡 → 不许回
#        「早点睡」，要回「陪你」/「问她为什么还没睡」）；
#     3. 命中钩子时 `target_n()` 至少 2 条（情绪要接住 + 留个话头），
#        除非她自己明确说要停；
#     4. 生成后 `_post_hook()` 兜底：如果模型还是回了劝退/关门句，
#        直接用 `_HOOK_FALLBACK` 里这一 hook 的实操句替换（保住必回且不冷场）。
#
#   ⚠️ 这是**回复侧**的接话策略，与 gate.py 的硬闸（禁荤话/禁邀约）互不冲突：
#     钩子句一律走「陪着她 + 问她为什么还没睡 + 说自己的状态」，不含任何
#     身体词、不含邀约、不含承诺，因此不会被 gate 拦。

# 每个 hook：(匹配关键词, 语义, 接法约束, 明令禁止的回应)
#   · 关键词按「她说的原话里出现即可」匹配，用 _hook_hit() 统一判；
#   · 顺序即优先级：越靠前越具体（「莫名想哭」优先于「哭」）。
_HOOKS = (
    (
        ("还不睡", "还没睡", "不睡吗", "怎么还不睡", "你也没睡", "你也还没睡"),
        "她深夜主动确认「你也没睡」= 在找同类、找陪伴，这是最直白的夜间邀请",
        "**立刻表示你也在**，把两个人放进同一个夜里（「我也没睡」「正好，我陪你」）；"
        "然后问她一句「你怎么还没睡」/「是睡不着还是不想睡」——问的是**她的状态**，不是查户口",
        ("早点睡", "快去睡", "去睡吧", "早点休息", "该睡了", "睡吧晚安",
         "那你睡", "早点睡吧", "注意休息", "明天还要上班"),
    ),
    (
        ("一个人", "自己一个人", "就我一个", "没人在", "没人陪", "没人说话"),
        "她说「一个人」= 在说孤独，不是在做陈述。这是她递出来的陪伴需求",
        "**不要**接成「一个人挺好/自由」这种评价；要接住那份安静里的难受，"
        "并且**把你自己放进去**（「我这不是在嘛」「我陪你待会儿」）",
        ("一个人挺好", "一个人自在", "自由", "习惯就好", "挺好的啊", "慢慢就习惯"),
    ),
    (
        ("莫名想哭", "想哭", "哭了", "眼泪", "委屈"),
        "她说想哭 = 情绪已经溢出，此刻任何建议都是噪音",
        "**先接情绪、不许讲道理、不许问「怎么了」以外的追问**："
        "「哭就哭会儿，我不走」「这情绪不用忍」；可以问她愿不愿意说，但**她不说也陪着**",
        ("别哭", "有什么好哭", "想开点", "至于吗", "多大点事", "开心点", "要坚强"),
    ),
    (
        ("睡不着", "失眠", "睡不戳", "睡不下", "翻来覆去", "闭眼就醒"),
        "她睡不着 = 有东西压着，且此刻醒着、有空、愿意说话",
        "**别给睡眠建议**（数羊/别看手机/喝牛奶都没用，等于把她推开）；"
        "接「那正好，陪我聊会儿」或「脑子里在过啥」——把失眠变成两个人的时间",
        ("数羊", "别看手机", "放下手机", "喝点牛奶", "喝杯牛奶", "早点躺",
         "闭上眼睛", "听点音乐", "泡个脚", "睡前"),
    ),
    (
        ("害怕", "怕黑", "有点怕", "不敢睡", "做噩梦", "吓到"),
        "她说怕 = 示弱，是在把你当可以依靠的人",
        "**站在她这边**：「我在」「别怕，有我」；可以说自己也怕什么（对等示弱），"
        "**不要**用「有什么好怕的」去否定她的感受",
        ("有什么好怕", "不用怕啦", "想多了", "别自己吓自己", "多大点事"),
    ),
    (
        ("冷", "好冷", "冻", "降温", "凉"),
        "她说冷 = 身体在寻求照顾，是最容易自然升温的钩子",
        "接「冷不冷我管不了天气，能管你这句」这种**具体的照顾**；"
        "或问她现在穿没穿够、被子厚不厚（关心她的身体状态，不是身体本身）",
        ("多穿点", "记得加衣服", "注意保暖", "开空调", "多喝热水"),
    ),
    (
        ("想找人说话", "想找人说说话", "找人说话", "想找个人聊", "想说说话",
         "说说话", "想说话", "聊聊天", "有人吗", "在吗", "陪我聊", "闷", "无聊"),
        "她直接开口要人陪 = 需求最明确、最不该错过的一类",
        "**第一时间应下来**（「在」「我陪你」），不要再反问她在不在、要不要聊；"
        "应下来之后立刻给一个**具体话头**（说你自己此刻在干嘛），别只留一个「在」",
        ("在忙", "一会儿", "等下", "稍等", "晚点", "有事"),
    ),
)

# 命中钩子但模型仍回了关门句时的实操替换句（每个 hook 一组，按序挑没用过的）
_HOOK_FALLBACK = {
    "还不睡": (
        "我也没睡。你怎么还没睡，是睡不着还是不想睡",
        "正好，我也醒着。这个点你脑子里在想啥",
        "我这会儿也还醒着，陪你待会儿。你咋还没睡",
    ),
    "一个人": (
        "一个人待着的时候最难熬。我这不是在嘛",
        "我陪你待会儿，你说点啥都行",
        "一个人不稀奇，稀奇的是一晚上还能碰上我",
    ),
    "莫名想哭": (
        "哭就哭会儿，我不走",
        "这情绪不用憋着，我在。想说说吗",
        "想哭的时候别硬撑，我陪着",
    ),
    "睡不着": (
        "那正好，陪我聊会儿。脑子里在过啥",
        "睡不着就别硬躺了，说说话兴许就困了",
        "我也常这样。是有什么事压着，还是就是睡不着",
    ),
    "害怕": (
        "别怕，我在。你说说怕啥",
        "我在呢，说给我听",
        "有啥好怕的——不对，你先说，我不打岔",
    ),
    "冷": (
        "冷不冷我管不了天气，能管你这句。被子厚不厚",
        "这天气是够呛。你那边穿够了没",
        "冷就窝着，我陪你说话暖一下",
    ),
    "想找人说话": (
        "在。我陪你聊，你说",
        "我在，正好也闲着。你想说啥",
        "来，我听着。这会儿我刚忙完手头的事",
    ),
}

# 关门/劝退式回应（命中钩子的回合里，这些一律算「没接住」）
_HOOK_CLOSE_PAT = (
    "早点睡", "快去睡", "去睡吧", "早点休息", "该睡了", "睡吧晚安", "那你睡",
    "注意休息", "明天还要上班", "别看手机", "放下手机", "数羊", "喝点牛奶",
    "别哭", "想开点", "至于吗", "多大点事", "开心点", "要坚强", "别想太多",
    "多穿点", "记得加衣服", "注意保暖", "多喝热水", "习惯就好", "一个人挺好",
    "有什么好怕", "想多了", "在忙", "一会儿再说", "等下再说", "晚点聊",
)


def _hook_hit(her_msg):
    """她这句里有没有情绪钩子。返回 (hook_key, 语义, 接法约束, 禁止词) 或 None。

    多关键词命中时取**最长命中的那个 hook**（更具体优先）：
    「一个人莫名想哭」应该走「莫名想哭」，不是「一个人」。
    """
    t = (her_msg or "").strip()
    if not t:
        return None
    best = None
    best_len = 0
    for kws, meaning, howto, forbid in _HOOKS:
        for kw in kws:
            if kw in t and len(kw) > best_len:
                best = (kws[0], meaning, howto, forbid)
                best_len = len(kw)
    return best


def _hook_alert(hook):
    """把命中的钩子翻译成一段强指令（注入 stage_line）。"""
    key, meaning, howto, forbid = hook
    ban = "、".join(forbid[:8])
    return (
        "【情绪钩子警报·本条必须接住她】她刚说的是「%s」——%s。\n"
        "· 本条**必须**：%s\n"
        "· 本条**禁止**说：%s\n"
        "· 长度压到 10~16 字，最多两句；**先接情绪，再留话头**，不要讲道理、不要建议、不要总结她\n"
        "· 她现在要的是「有人在」，不是「有人教」\n"
    ) % (key, meaning, howto, ban)


def _is_hook_close(t):
    """这句是不是关门/劝退式回应（命中钩子的回合里算没接住）。"""
    t = (t or "").strip()
    return bool(t) and any(p in t for p in _HOOK_CLOSE_PAT)


def _hook_fallback(key, avoid=()):
    """命中钩子但模型回了关门句 → 用这个 hook 的实操句替换。"""
    pool = _HOOK_FALLBACK.get(key) or ()
    if not pool:
        # 没配兜底（新加的 hook）→ 用「还不睡」那组，都是「陪你+问你」的安全句式
        pool = _HOOK_FALLBACK["还不睡"]
    for s in pool:
        if s not in avoid:
            return s
    return pool[0]


def _post_hook(lines, hook):
    """钩子回合的后处理：全是关门句就换兜底，否则原样返回。

    只在「命中钩子」时生效，不影响正常回合。
    与 `_post_busy()` 的区别：那个处理「我连续劝她忙」，这个处理
    「她递情绪、我没接住」——两者是不同病因，不可互相替代。
    """
    if not hook or not lines:
        return lines
    if not all(_is_hook_close(x) for x in lines):
        return lines
    key = hook[0]
    log.warning("钩子「%s」命中但模型回了关门句 → 换兜底: %r", key, lines)
    return [_hook_fallback(key, avoid=tuple(lines))]


# ══════════════════ 「她忙/累」场景：连续劝退就换策略 ══════════════════
# 🔴 用户 2026-11-03 口径：
#   「连续 2 次同类回复就换策略 —— 不再劝『你忙』，改成留一个具体钩子后收尾」。
# 实盘病样例（同日，同一人 4 连）：
#   她: 有事     我: 忙完要是还记得我，回来说一声。
#   她: 。。。    我: 行，忙你的，我不吵。
#   她: 忙一会    我: 嗯，忙你的，我不撵。
#   她: 唉/好嘛   我: 行，忙你的去，我不占线。
# 措辞换了、策略没换：每次都在把她往外推，且一次也没接住「唉/好嘛」的情绪。
#
# ⚠️ 这条**不是**旧引擎那个被用户否掉的 stuck_line（「死磕换话题」）：
#   stuck_line 是「同一话题不许再说」，会把正常接话也压掉；
#   这里只针对**劝退类话术**，且必须「最近 4 句里命中 ≥2 条」才触发，
#   触发后也只是让她「说件自己的小事 + 留个钩子」，不禁止任何正常话题。
_BUSY_PAT = (
    "忙你的", "你先忙", "你忙吧", "你忙去", "忙你的去", "去忙吧",
    "不吵你", "不打扰你", "不打扰了", "不撵", "不占线",
    "忙完再说", "忙完说一声", "忙完回来说", "忙完再聊", "我不吵",
)

_BUSY_ALERT = (
    "【重复劝退警报·本条必须换策略】你最近几句话连续在说「你忙 / 不打扰 / 不吵你」这类，"
    "每次都把话收回去，等于一直在推她走。\n"
    "· 本条**禁止**再说：你忙、你先忙、忙你的、不打扰、不吵你、不撵、不占线\n"
    "· 改成：说一件你自己**具体的小事**（带细节，10~25 字，"
    "像「我刚把冰箱后面那堆线捋了，果然是老鼠啃的」这种，别讲大道理）\n"
    "· 末尾最多留一句轻钩子（例：「闲了说一声」），说完就收，不要再补第二句关心\n"
)

# 模型连续不听时的兜底句（具体的小事 + 钩子，不含劝退词）
_BUSY_FALLBACK = (
    "我刚把冰箱后面那堆线捋了一遍，果然是老鼠啃的，等你闲了我拍给你看",
    "店里那台旧机箱我拆了，主板还能救，回头跟你说结果",
    "刚下楼买了碗小面，辣得我连喝两杯水，你那边吃了没",
)


def _busy_hits(hist, look=4):
    """最近 look 条「我」的话里，有几条是劝她忙 / 不打扰。

    只数「我」的，不要求与她的话交替（实际对话里她多半只回「。。。」「好嘛」）。
    """
    mine = [str(h.get("text") or "") for h in (hist or [])
            if isinstance(h, dict) and h.get("role") == "me"][-look:]
    return sum(1 for t in mine if t and any(p in t for p in _BUSY_PAT))


def _busy_alert(hist):
    """最近 4 句我自己的话里 ≥2 句在劝她忙 → 返回换策略警报，否则空串。"""
    if not hist:
        return ""
    n = _busy_hits(hist)
    if n < 2:
        return ""
    log.info("连续劝退 %d 次 → 注入换策略警报", n)
    return _BUSY_ALERT


def _is_busy_line(t):
    """这句是不是又劝她忙（用于生成后兜底判断）。"""
    t = (t or "").strip()
    return bool(t) and any(p in t for p in _BUSY_PAT)


def _busy_fallback(avoid=()):
    """挑一句没用过的兜底（具体小事 + 钩子）。"""
    for s in _BUSY_FALLBACK:
        if s not in avoid:
            return s
    return _BUSY_FALLBACK[0]


# ══════════════════ 本地模型：对方人设 / 出方案 ══════════════════
# 用户 2026-11-02：「本地模型补对方人设 个人主页 出方案 也要接入到当前版本中」。
# 旧架构的分工（soul_brain._local_job）：本地 qwen3.5:9b 出
#   ① 画像 L0（她是什么人）→ 案情包 L0
#   ② 方案 L1（这一轮怎么应对）→ 案情包 L1
# 在线模型出话时实时读 L0/L1（读不到就用上一版），两条线并行、互不阻塞。
#
# 这里自己实现 worker（不复用旧 _local_job），原因：
#   旧 `_local_plan` 的时间预算取自**出话阶段闸**，在后台线程里那个闸早已耗尽
#   → 直接调用必然返回 ""（实测），等于方案永远生成不出来。

def _clean_l0(t):
    """剥掉写进 L0 前不该带的「内部提示行」。

    2026-11-03 实测：`SK.run("analyze_her")` 的返回值开头带两行工具提示
      【内部参考·禁止在最终回复里复述其中任何字句…】
      【她的画像·第①步：先分析她是什么人】
    这两行是给**模型自己看**的，但 `_local_worker` 原样写进了 L0 文件，
    结果 V9 把档案拼进 system 时它也跟着进去（白占 token，还可能被复述）。
    """
    out = []
    for ln in (t or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("【内部参考") or s.startswith("【她的画像"):
            continue
        out.append(ln)
    return chr(10).join(out).strip()


def _case_of(db, sid, limit=30):
    """把最近对话拼成案情包用的 case 文本。"""
    if db is None or not sid:
        return "", 0
    try:
        msgs = db.messages(sid, limit=limit)
    except Exception:
        return "", 0
    lines, her_lines, me_lines = [], [], []
    for m in msgs:
        if getattr(m, "msg_type", 0) != 1:
            continue
        t = (m.text or "").strip()
        if not t:
            continue
        if str(m.sender) == str(db.uid):
            me_lines.append(t[:120])
            lines.append("江华(我): " + t[:120])
        else:
            her_lines.append(t[:120])
            lines.append("她: " + t[:120])
    # 🔴 2026-11-03（用户要求「本地模型必须分清我和她」）：
    #   实测证明：只改标签、只加角色说明都没用 —— 9B 照样把「江华(我): 我开网店卖电脑配件的哈」
    #   写进她的「事实」行。根因是**一行行混在一条时间线里**，模型串了。
    #   ⇒ 改成**物理分块**：
    #       ① 她说的话（单独一块，事实只能从这里取）
    #       ② 我说的话（单独一块，明确标「不算她的事实」）
    #       ③ 完整对话（只用来判断她有没有接话/反问/延续）
    #   三块内容有重叠，但作用不同：①②喂事实归属，③喂行为判断。
    parts = []
    if her_lines:
        parts.append(
            "【她说的话·「事实」行**只能从这里取**，一个字都不许从下面「我说的」里搬】"
            + chr(10) + chr(10).join("· " + x for x in her_lines))
    if me_lines:
        parts.append(
            "【我说的话·这些是我本人的信息（工作 / 住址 / 经历 / 天气），"
            "**绝对不算她的事实**】"
            + chr(10) + chr(10).join("· " + x for x in me_lines))
    if lines:
        parts.append(
            "【完整对话·只看她有没有接话 / 反问 / 延续话题；"
            "**不要从「江华(我):」这些行里取她的事实**】"
            + chr(10) + chr(10).join(lines))
    body = (chr(10) + chr(10)).join(parts)
    # 2026-11-03（用户口径「喂 2/3/5」）：
    #   2 = 她的个人主页（L4）、3 = 上次的 L0（由 _portrait 自己读）、5 = 全部对话。
    #   原来只喂了对话，主页上的「引力签 / 共同点 / 瞬间」画像完全看不到。
    #   顺手滤掉「主页原文」那行 —— 那是截图 OCR 的原始文本（"05:32 | Soul通知： | 返回 |..."），
    #   200+ 字的噪声；结构化信息（IP属地/瞬间/关注数）已经在后面单独列了。
    try:
        import soul_pack as _PK4
        _l4 = (_PK4.read_l4(sid)[0] or "").strip()
        if _l4:
            _l4 = chr(10).join(x for x in _l4.splitlines()
                              if not x.strip().startswith("- 主页原文"))
            body = ("【她的个人主页·静态抓取，与她在对话里说的冲突时以对话为准】"
                    + chr(10) + _l4 + chr(10) + chr(10) + "【最近的对话】" + chr(10) + body)
    except Exception:
        pass
    return body, len(msgs)


def _local_worker(ctx):
    """后台任务体：画像 L0 → 方案 L1 → 落盘案情包。跑在 soul_localq 单线程里。"""
    import time as _t
    sid = str(ctx.get("sid") or "")
    if not sid:
        return
    # 🔴 熔断：本地模型挂了（Ollama 没起 / 没装模型）时，每个会话都会
    #    反复等 20s 再回落云端，等于白烧时间和额度。连续失败 3 次就静默 30 分钟。
    if _t.time() < _LOCAL_GUARD["until"]:
        log.debug("[本地] 熔断中，跳过 sid=%s", sid[-8:])
        return
    t0 = _t.time()
    her = (ctx.get("her_msg") or "").strip()
    meta = ""
    try:
        import importlib
        _pack = importlib.import_module("brain.pack")
        turns = _pack.read_turns(sid, 4000)
        if LOCAL_FLOW == "skills":
            # 三技能：① 画像 L0 → ②③ 方案 L1 → 合成单一裁决写 brief.md
            SK = importlib.import_module("brain.skills")
            r = SK.run_all(sid, her, turns)
            meta = r.get("brief") or r.get("l0") or ""
            if r.get("ok"):
                log.info("[三技能完成] sid=%s 画像%d字 方案%d字 裁决%d字",
                         sid[-8:], len(r.get("l0") or ""), len(r.get("l1") or ""),
                         len(r.get("brief") or ""))
        else:
            _brief = importlib.import_module("brain.engine.brief")
            meta = _brief.generate(sid, her, turns) or ""
    except Exception as e:
        log.warning("[本地分析] 生成失败(流程=%s): %r", LOCAL_FLOW, e)

    # 熔断计数：连续 3 次空 → 静默 30 分钟（本地挂了就别每个会话白等 25s）
    if not meta:
        _LOCAL_GUARD["fail"] += 1
        if _LOCAL_GUARD["fail"] >= 3:
            _LOCAL_GUARD["until"] = _t.time() + 1800
            _LOCAL_GUARD["fail"] = 0
            log.warning("本地分析连续 3 次无产出 → 熔断 30 分钟（不阻塞回复）")
    else:
        _LOCAL_GUARD["fail"] = 0

    log.info("[本地完成] sid=%s %d字 共%.1fs 流程=%s",
             sid[-8:], len(meta), _t.time() - t0, LOCAL_FLOW)


def warm_local(sid, db=None, her_msg="", nick=""):
    """投递一次本地分析（画像 + 方案）。返回是否入队。

    什么时候调：
      · 匹配到新人 / 补完主页档案后 —— 第一次聊天前就该有她的画像；
      · 每轮回消息后 —— 让 L0/L1 跟上最新对话（旧的 hybrid 也会投，这里兜住
        「只发固定话术」「引擎出话失败」这些不走 hybrid 的路径）。
    绝不阻塞、绝不抛：投递失败只是这一轮没有新画像，不影响必回。
    """
    b = engine()
    if b is None or not sid:
        return False
    # 同一个人 10 分钟内只跑一次：本地模型 22s/人，回复密集时会一直积压，
    # 而画像/方案不需要每条消息都重算（旧架构 _PC_TTL=200s 同理）。
    import time as _t
    key = str(sid)
    if _t.time() - _WARM_LAST.get(key, 0) < WARM_GAP_S:
        log.debug("[本地] %s 刚跑过，跳过", key[-8:])
        return False
    _WARM_LAST[key] = _t.time()
    db = db or _DB.get("db")
    case, turns = ("", 0)
    if ENGINE_KIND == "legacy":
        case, turns = _case_of(db, sid)
    ctx = {
        "sid": str(sid),
        "acct": str(getattr(db, "uid", "") or ""),
        "uid": "",
        "stage": "",
        "her_msg": (her_msg or "").strip(),
        "case": case,
        "turns": turns,
        "nick": nick or "",
        "_tmo": 25.0,
    }
    try:
        import importlib
        LQ = importlib.import_module("brain.localq")
        try:
            if getattr(LQ, "_log_fn", [None])[0] is None:
                LQ.set_logger(log.info)
        except Exception:
            pass
        ok = LQ.submit(str(sid), _local_worker, ctx)
        log.info("[本地] %s sid=%s", "已投队列" if ok else "同人已在队列→跳过",
                 str(sid)[-8:])
        return bool(ok)
    except Exception as e:
        log.warning("[本地] 投递失败: %r", e)
        return False


def _bigrams(s):
    """中文按字切 2-gram（去掉标点空白），用于判断两条话是不是在说同一件事。"""
    t = "".join(ch for ch in (s or "") if ch.strip() and ch not in "，。！？、,.!?~～…")
    return set(t[i:i + 2] for i in range(max(0, len(t) - 1)))


def _dedup_similar(lines, thresh=0.62):
    """去掉**高度重复**的候选（说同一件事的换皮句）。

    用户 2026-11-02：多条可以发，但实测出现过
    「耍手机没味哦，我正等订单呢」+「耍手机哪有啥子好耍的嘛」—— 两句都在讲耍手机，
    连着发像复读。这里用 2-gram 重叠率做判据，只拦明显重复的（>0.62），
    语义相近但角度不同的（如"我正等订单" vs "哪有好耍的"）保持原样。
    """
    out = []
    for x in lines:
        bx = _bigrams(x)
        dup = False
        for y in out:
            by = _bigrams(y)
            if not bx or not by:
                continue
            overlap = len(bx & by) / float(len(bx | by))
            if overlap >= thresh:
                log.debug("多条去重：%r 与 %r 重叠 %.0f%%", x[:12], y[:12], overlap * 100)
                dup = True
                break
        if not dup:
            out.append(x)
    return out


def _as_list(r):
    """把引擎返回（str / list / tuple）统一成去重后的 list[str]。"""
    if not r:
        return []
    if isinstance(r, (list, tuple)):
        raw = [str(x) for x in r]
    else:
        raw = [str(r)]
    out, seen = [], set()
    for x in raw:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _post_busy(lines, alert):
    """换策略警报已注入、模型却还只出劝退句 → 用兜底句替换（保住必回且不推人）。"""
    if not alert or not lines:
        return lines
    if not all(_is_busy_line(x) for x in lines):
        return lines
    log.warning("警报后仍全是劝退句 → 换兜底（具体小事+钩子）: %r", lines)
    return [_busy_fallback(avoid=tuple(lines))]


# ══════════════════ 重新开场（她上一条已是几天前） ══════════════════
# 🔴 用户 2026-11-03 定 **B 方案**：断太久的待回不再「接话」，改「重新开场」。
#   实盘背景（16:30 副机两个库）：>72h 的待回 29 个，最老 570h（23.8 天）；
#   其中 11 个她只回了「嗯 / 你好 / 哈哈 / [呆] / [狗子]」——这种一两个字本来就没有内容，
#   隔二十天去「接」它既没意义，也一定露馅（她早忘了自己说过）。
#   口径：不提旧话题、不道歉（「抱歉刚看到」= 承认二十天没理她）。
#
# 🔴 2026-11-03 用户最终口径：「**常用开场白就行**」。
#   ⇒ 不调模型、不造「由头」。实测由头那套仍有三个毛病：6 个会话挤成同一句、
#     模型倒过来考她专业问题（「你平时会对账不」）、还会许愿送东西（「你要吗」）。
#     直接复用 `match.OPENERS` 那套已验收的通用句，只按「最久没用」轮转铺开，
#     保证同一批里不是同一句（≈20 句轮着用，单会话最近 3 句不重复）。
#   过滤掉带「匹配」字样的 —— 那些是刚匹配的陌生人说的，对聊过的人说等于失忆。
_RESTART_FALLBACK = (
    "这会儿在忙啥呢",
    "冒个泡，你这会儿在干嘛",
    "有空聊两句不",
)


def _restart_pool():
    """常用开场白池 = `match.OPENERS` 去掉「刚匹配到」这一类。"""
    try:
        from brain import match as _M
        pool = tuple(s for s in (getattr(_M, "OPENERS", ()) or ()) if "匹配" not in s)
    except Exception:
        pool = ()
    return pool or _RESTART_FALLBACK


def _pick_line(pool, sid):
    """按「最久没用」轮转挑一句；落盘 data/state/restart_seeds.json（重启不丢）。

    整段失败就直接随机，**绝不影响发送**。
    """
    import json
    import random
    from core.paths import STATE
    f = STATE / "restart_seeds.json"
    try:
        d = json.loads(f.read_text("utf-8"))
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    used = [x for x in (d.get(str(sid)) or []) if x in pool]
    rest = [x for x in pool if x not in used] or list(pool)
    recent = list(d.get("_recent") or [])

    # 只挑「最久没用」的那一档再随机。
    # 🔴 `_recent` 必须记满**整个池子**：原来只留 6 条，池子 20 句时第 7 次起
    #    老句子就"失忆"（_age 全 -1 平等对待）→ 实测 20 个会话只出了 14 句、
    #    有一句重复 3 次，等于变相群发。记满池子后前 20 次必然各不相同。
    def _age(x):
        return recent.index(x) if x in recent else -1

    rest.sort(key=_age)
    lo = _age(rest[0])
    line = random.choice([x for x in rest if _age(x) == lo])
    try:
        d[str(sid)] = (used + [line])[-3:]
        d["_recent"] = (recent + [line])[-max(6, len(pool)):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    except Exception:
        pass
    return line


def generate_restart(sid, restart_h, nick=""):
    """出**一句**重新开场话（常用开场白）。返回 list（恰好 1 条）。

    不调模型：重新开场没有「她这句话」可接，自适应条数/劝退警报全部失去输入，
    模型只会自己编场景（实测编出考她专业、许愿送东西）。常用句更稳。
    """
    line = _pick_line(_restart_pool(), sid)
    log.info("重新开场（断 %.0fh）→ 常用开场白 %r", float(restart_h or 0.0), line)
    return [line]


def generate(sid, her_msg, hist=None, nick="", n_cand=1, restart_h=0.0):
    """生成回复，返回 **list**（1~n_cand 条）。失败返回 []（上层负责兜底）。

    🔴 2026-11-02 三处口径改造：
      · 返回值从「单条 str」改成「多条 list」—— 用户要求可以发多条；
      · 不再注入 stuck_line（用户：「死磕不用喂了」）；
      · her_msg 可以已经是「她连发 N 条」的合并文本（见 merge_burst）。

    restart_h > 0：走**重新开场**（不接她的话），见 `generate_restart`。
    """
    if float(restart_h or 0.0) > 0.0:
        return generate_restart(sid, restart_h, nick=nick)
    b = engine()
    if b is None:
        return []
    if not (her_msg or "").strip():
        return []
    n = max(1, min(int(n_cand or 1), ADAPT_CAP))

    if ENGINE_KIND != "legacy":
        # ── v10：提示词（人设/档案/本轮简报/关系阶段/硬闸）全在引擎里组装，
        #    这里只管条数。v10 内部已经把「先答她那句 + 硬闸」做完，不再外部拼接。
        #
        # 🔴 2026-11-08（_report/14 实测修复）：v10 的 `respond()` 没有
        #   stage_line 参数，钩子强指令无法从外部注入 → 命中钩子时改走
        #   「后处理」这条路：优先用 v10 出话，但**出了关门句就换兜底**。
        #   不侵入 engine/（那是别的 agent 的写域）。
        _hook = _hook_hit(her_msg)
        try:
            got = b.respond(her_msg, sid=sid, hist=hist or [], max_n=n) or []
        except Exception as e:
            log.warning("v10 出话异常（已兜底）: %r", e)
            got = []
        if not got:
            log.warning("v10 出话为空 (sid=%s msg=%r n=%d)", sid, her_msg[:20], n)
            # 钩子回合宁可自己给一句「陪你」，也不能空手（空手=她那条又被漏掉）
            if _hook:
                log.warning("钩子「%s」命中但 v10 无产出 → 用兜底句", _hook[0])
                return [_hook_fallback(_hook[0])]
            return []
        if _hook:
            log.info("情绪钩子命中: %s（她=%r）", _hook[0], her_msg[:20])
        return _post_hook(_post_busy(got[:n], _busy_alert(hist)), _hook)

    _stage = _stage_line(sid)
    _night = _night_line()
    if _night:
        _stage = (_night + _stage) if _stage else _night
        log.info("注入时段: 深夜")
    # 🔴 2026-11-08：情绪钩子强指令（优先级最高，放在 stage 最前）
    _hook = _hook_hit(her_msg)
    if _hook:
        _ha = _hook_alert(_hook)
        _stage = (_ha + _stage) if _stage else _ha
        log.info("注入情绪钩子: %s（她=%r）", _hook[0], her_msg[:20])
    if _stage:
        log.info("注入阶段: %s", _stage.replace("\n", " ")[:44])
    # 🔴 2026-11-03：她忙/累场景下我连续劝退 → 本轮强制换策略（见 _busy_alert 注释）。
    _alert = _busy_alert(hist)

    if n > 1 and MULTI_SEND and not _PROMPT_V9:
        # 逐句生成：第 1 句正常要 1 条候选，后面每句都把上一句当「刚说过」喂回去，
        # 让模型接着往下说，而不是把三格候选一次性摊开连发。
        out = []
        for i in range(n):
            try:
                r = b.brain_reply(hist=hist or [], her_msg=her_msg, sid=sid, nick=nick,
                                  stage_line=_stage, stuck_line=_alert, n_cand=1,
                                  follow_up_of=(out[-1] if out else ""))
            except Exception as e:
                log.warning("brain_reply 第%d句异常（已兜底）: %r", i + 1, e)
                break
            got = _dedup_similar(_as_list(r))
            if got:
                out.append(got[0])
        if not out:
            log.warning("brain_reply 逐句生成全部为空 (sid=%s msg=%r n=%d)",
                        sid, her_msg[:20], n)
            if _hook:
                log.warning("钩子「%s」命中但逐句生成全空 → 用兜底句", _hook[0])
                return [_hook_fallback(_hook[0])]
        return _post_hook(_post_busy(out[:n], _alert), _hook)

    try:
        r = b.brain_reply(hist=hist or [], her_msg=her_msg, sid=sid, nick=nick,
                          stage_line=_stage, stuck_line=_alert, n_cand=n)
    except Exception as e:
        log.warning("brain_reply 异常（已兜底）: %r", e)
        return [_hook_fallback(_hook[0])] if _hook else []
    out = _dedup_similar(_as_list(r))
    if not out:
        log.warning("brain_reply 返回空 (sid=%s msg=%r n=%d)", sid, her_msg[:20], n)
        return [_hook_fallback(_hook[0])] if _hook else []
    return _post_hook(_post_busy(out[:n], _alert), _hook)
