# -*- coding: utf-8 -*-
"""关系阶段 + 本轮方向（v12：投入度驱动）。

════════════════════════════════════════════════════════════════════
2026-11-08 重写：**方向不再由轮数决定，由她的实测投入决定**
────────────────────────────────────────────────────────────────────
改前（v11）的分档是纯轮数：0-20 破冰 / 20-30 熟悉 / 30-45 私人 /
45-60 暧昧 / 60+ 推进，90 轮下最后通牒。失效证据（账号1 全量，945 会话）：

  · 320 轮那批人被判定「推进档」，但她 45 轮之后平均 **5.75 字**，
    ≤4 字占 **49.8%** —— 轮数涨了，她一个字都没多。轮数和投入没有关系。
  · 能爬到 45 轮的会话只有 **112 / 945 = 11.9%**；能到 90 轮的 **5.4%**。
    「45 轮开始暧昧」这条规则，**88% 的会话一辈子走不到**。
    用户说的「聊了很久感觉没什么进展」，制度原因在这里。
  · 反过来：她释放过信号的会话 **124 个（13.1%）**，其中 **78.2% 在 45 轮之前
    就出现了**（首次出现位置中位 = 第 16.5 条）。信号来得比阶梯早得多。

⇒ 现在用投入度分档。**分数不在这里重算** —— 全项目唯一口径是
   `brain.engine.prompt.her_stats(turns_body)`（lead 落地，两个账号共 504 个
   真实会话校准过，分布几乎一致）。本模块只负责把它**翻译成方向**，
   并把「她这一条」的即时状态叠加进去。

  为什么不各算各的：同一件事有两个公式，必然出现「规则说该升温、
  判定说在冷档」的自相矛盾 —— 这正是 v10 记录过的「方向只认一处」那条教训
  （旧版 L0 说稳一稳、L1 说撩，模型没有裁决规则只能折中 → 四平八稳）。

⚠️ 与 prompt._her_block 的分工（不要合并，合并会打架）：
   · prompt._her_block  → 给模型的「她现在的状态」（冷/温/热/燃 + 行为建议）
   · stage.line()       → 给模型的「当前关系」档位 + 本轮硬要求 + 确定性警告
   两段都进 system，prompt.py 里已明写裁决规则：**冲突时以「她的状态」为准**，
   因为轮数只说明聊了多久，不代表她投入了多少。
   所以本模块的输出必须与 her_stats 同源，否则那条裁决规则会失效。
"""
import os

from brain.pack import store
from brain.engine import prompt as _prompt

try:
    from core.log import get_logger
    log = get_logger("brain.stage")
except Exception:                                    # 单线程脚本/离线分析可直接用
    import logging
    log = logging.getLogger("brain.stage")


# ─────────────────────────────────────────────────────────────
# 一、轮数阶梯（保留：只作降级兜底，不再决定方向）
# ─────────────────────────────────────────────────────────────
# 保留 LADDER 这个名字和结构：`stage.LADDER` 有外部读取点，且降级分支要用。
#
# 🔴 2026-11-08：**第 4 列（这一档该做什么）全部重写了**。
#   改前第 0 档写的是「接住她这句 + 一个只有她能答的具体问题」，
#   第 1 档写的是「交换信息」—— 这等于把刚在 rules.OUTPUT_SPEC 里删掉的
#   「每轮必须提问」从后门放回来：新会话（她的消息 < 6 条）走的正是降级路径，
#   于是「越早越好聊」的阶段反而最强制提问，而这段正好是她最冷淡的时候。
#   实测：带问号她回 5.5 字 / 不带问号 4.9 字，差 0.6 字 —— 提问买不到字数。
#   现在每一档都写「先接住 + 说自己的 + 收住」，问句只是可选项。
LADDER = [
    (0, 0, "破冰", "让她觉得你好聊：接住她这句 + 说一句你自己的（不提问也能成立）。"
                   "问句最多一个，她回得短就不问。"),
    (20, 1, "熟悉", "接住情绪，说一件你自己的小事，让她觉得你是真人；"
                    "问句最多一个，她答得短就收住，别追。"),
    (30, 2, "私人", "把话题往生活里带（吃啥、几点睡、住哪一片、一个人还是有人陪）——"
                    "由她说的话引出来，不硬问。"),
    (45, 3, "暧昧", "带一点男女之间的张力：夸她这个人（不是她做的事）、试探她对你的态度。"
                    "只在**她给了信号**的那一轮走一格。"),
    (60, 4, "推进", "该拿联系方式或见面了：她动身过来，别再原地陪聊。"
                    "给台阶不给压力，她不接就退回正常聊。"),
]

PUSH_LV = 2
HARD_TURNS = int(os.environ.get("SOUL_HARD_TURNS", "90") or 90)
GOAL_LV = 3


# ─────────────────────────────────────────────────────────────
# 二、投入度分档（新：方向由这里决定）
# ─────────────────────────────────────────────────────────────
# (下界, 档位号, 名称)。阈值 = lead 在账号1(323 会话)/账号2(181 会话) 上实测的
# 分位：p10=0.21 p25=0.27 p50=0.42 p75=0.66 p90=0.75 max=0.92，
# 按 <0.30 / 0.30-0.50 / 0.50-0.70 / >=0.70 切，实际分布：
#   **冷 30.0% / 温 28.2% / 热 22.3% / 燃 19.5%**
# 这个分布很关键：**不是「大部分人都是冷的」**。库里有 40% 的会话她其实在投入
# （热+燃），旧引擎按轮数一刀切把这 40% 全浪费了 —— 45 轮才会带男女张力，
# 而她给信号的中位位置是第 16.5 条。所以档位一定要按投入切，不能按轮数切。
SCORE_BANDS = [
    (0.00, 0, "冷"),
    (0.30, 1, "温"),
    (0.50, 2, "热"),
    (0.70, 3, "燃"),
]

BAND_GOAL = {
    0: ("她这条很敷衍。**只接住，不推进**：一条、≤8 字、不提问、不新开话题、不说你自己的事。"
        "不许提任何私人问题，不许要联系方式。她说几个字你回几个字，说完就停。"
        "停住不是失败，硬聊才是。"),
    1: ("正常聊。可以接情绪、可以说一件你自己的小事；问句最多一个，且要具体。"
        "**不加码**：她回得短你就跟着短。不提联系方式、不提见面。"),
    2: ("热档，她在给东西了。可以带一点男女之间的张力 —— 按「时间层→距离层→张力层」"
        "接住她那句的劲儿，**只走一格**，走完停住看她接不接。永远不写露骨词。"),
    3: ("燃档，她信号很明确。可以在接住她这句之后，收尾时贴话题给一格具体台阶"
        "（「你哪天过来耍」这类，**她动身，你不跑**），给台阶不给压力。"
        "只给一格，她不接就退回正常聊。"),
}

# 她这条本身「冷」时，当场降一档（与 prompt._her_block 的 -0.15 同一口径）
COLD_PENALTY = 0.15
# 样本下限：her_stats 里 n_her 少于这个数，分数不可信 → 降级
MIN_HER = int(os.environ.get("SOUL_HIS_MIN_HER", "6") or 6)

# 她的信号词（与 rules.ADVANCE 第二、三条**必须保持同一份**）
# 为什么放进代码：rules 是给模型看的散文，这里要给 stage 做确定性判定，
# 两边写同一份词表才不会出现「规则说该升、判定说在冷档」。
SIGNAL_T1 = ("无聊", "一个人", "没人陪", "没人聊", "周末", "没事做", "睡不着", "在家")
SIGNAL_T2 = ("好看", "帅", "可爱", "心疼", "害羞", "脸红", "想你", "想我", "追")
SIGNAL_T3 = ("老公", "媳妇", "抱", "亲", "床", "睡觉", "见面", "喜欢你")

# 她这条是收尾语 → 本轮不推进（和 rules.voice 的「收尾就短回」对齐）
HER_CLOSE = ("睡了", "晚安", "困了", "不聊了", "拜拜", "去忙", "先睡", "睡觉", "睡啦", "告辞")

# 问句判据：与 prompt.her_stats 的 `_HER_RICH_RE` 同口径（问号）
# —— 不另立一套「吗/呢」中文疑问词表，否则两处 ask_rate 会不一样。
_Q_MARK = ("?", "？")


# ─────────────────────────────────────────────────────────────
# 三、文本工具
# ─────────────────────────────────────────────────────────────
def nchars(s):
    """有效字数（去空白）。"""
    return len("".join(str(s or "").split()))


def _norm(s):
    """剥标点空白，判「纯应答」用。"""
    return "".join(ch for ch in str(s or "")
                   if ch.strip() and ch not in "，。！？、,.!?~～…；;:：\"'“”‘’()（）[]【】")


def is_lazy(s):
    """这条是不是纯应答（嗯/哦/好/哈哈/切）。**词表直接用 prompt 那一份。**

    为什么复用：`prompt._HER_COLD` 是 cold_rate 的计算依据，如果这里另写一份，
    两边的「敷衍」定义会漂移，分档和提示词就会打架。
    """
    t = (str(s or "")).strip()
    return bool(t) and t in set(_prompt._HER_COLD)


def is_question(s):
    """她这条是不是在问我（用于本轮的即时判定，**不参与打分**）。

    ⚠️ 打分用的 ask_rate 在 `prompt.her_stats` 里，口径是「看问号」；
    这里放宽到「问号 或 吗/呢 结尾」，因为本轮要做的是「她问了就得先答」，
    「在吗」「睡了吗」这种没有问号的也算问句。
    两边不一致是**故意的**，且不会打架：本函数的结果不回流到分数里。
    """
    t = str(s or "").strip()
    if not t:
        return False
    if any(m in t for m in _Q_MARK):
        return True
    return t.endswith("吗") or t.endswith("呢") or t.endswith("嘛")


def is_close(her_msg):
    """她这条是不是收尾语。"""
    s = str(her_msg or "").strip()
    return bool(s) and len(s) <= 14 and any(k in s for k in HER_CLOSE)


# 老名字保留（历史调用点/自检脚本可能 import 过 `_is_close`）
_is_close = is_close


def signals_of(her_msg):
    """她这句话里有哪几级信号。返回 (最高级, 命中的词)。

    一级=走半步，二级=带男女意思，三级=给台阶。没信号返回 (0, ())。
    """
    s = str(her_msg or "")
    hit3 = tuple(w for w in SIGNAL_T3 if w in s)
    if hit3:
        return 3, hit3
    hit2 = tuple(w for w in SIGNAL_T2 if w in s)
    if hit2:
        return 2, hit2
    hit1 = tuple(w for w in SIGNAL_T1 if w in s)
    if hit1:
        return 1, hit1
    return 0, ()


# ─────────────────────────────────────────────────────────────
# 四、读盘（只读；store.read_turns 走 _dir()，不会建目录）
# ─────────────────────────────────────────────────────────────
def _turns_body(sid, limit_chars=8000):
    """turns.md 原文。her_stats 吃的就是这个格式（`- MM-DD HH:MM 她: ...`）。"""
    try:
        return store.read_turns(sid, limit_chars=limit_chars) or ""
    except Exception as e:
        log.debug("stage 读 turns 失败 sid=%s: %r", str(sid)[-8:], e)
        return ""


def her_opened_ever(sid):
    """她有没有主动开过场（turns.md 第一条是她发的）。

    实测只有 12/945 = 1.3% 的会话有这件事，所以**不做成加权因子**，
    只在 her_block 里作为一句「她主动找过你」的提示用（见 line()）。
    """
    try:
        raw = store.read_turns(sid) or ""
    except Exception:
        return False
    for ln in raw.splitlines():
        if " 她: " in ln or " 她：" in ln:
            return True
        if " 我: " in ln or " 我：" in ln:
            return False
    return False


# ─────────────────────────────────────────────────────────────
# 五、分数（**唯一口径：prompt.her_stats**）
# ─────────────────────────────────────────────────────────────
def score_parts(sid, her_msg=""):
    """返回 (0~1 分, her_stats 原始 dict)。样本不够返回 (None, stats)。

    分数 = `prompt.her_stats(turns_body)["score"]`，再加上「她这条当场是冷的」
    的即时修正（-COLD_PENALTY）—— 与 prompt._her_block 里的修正是同一套，
    这样两段提示词不会对同一轮给出不同的档位。
    """
    body = _turns_body(sid)
    s = _prompt.her_stats(body)
    sc = float(s.get("score") or 0.0)
    if int(s.get("n_her") or 0) < MIN_HER:
        return None, s
    cur = (her_msg or "").strip()
    if cur and (cur in set(_prompt._HER_COLD) or len(cur) <= 3):
        sc = max(0.0, sc - COLD_PENALTY)
    return round(sc, 4), s


def score(sid, her_msg=""):
    """她对这个会话的投入度（0~1）。样本不够返回 None。"""
    sc, _ = score_parts(sid, her_msg)
    return sc


def band(sc):
    """分数 → (档位号, 名称, 这一档该干什么)。sc=None 视为冷档。

    ⚠️ SCORE_BANDS 每行是 `(下界, 档位号, 名称)` 三元组 ——
    取档位号必须是 `row[1]`，不是 `row[0]`（row[0] 是分数阈值）。
    """
    if sc is None:
        return 0, "冷", BAND_GOAL[0]
    cur = SCORE_BANDS[0]
    for row in SCORE_BANDS:
        if sc >= row[0]:
            cur = row
        else:
            break
    lv, name = int(cur[1]), cur[2]
    return lv, name, BAND_GOAL.get(lv, BAND_GOAL[1])


# ─────────────────────────────────────────────────────────────
# 六、轮数阶梯（降级用；签名不变）
# ─────────────────────────────────────────────────────────────
def level(turns):
    """轮数 → (档位号, 名称, 这一档该做什么)。

    ⚠️ v12 起**方向不再用它**，只作 `line()` 的降级兜底。
    保留它是因为外部有读取点，且缺数据时要有一个可复现的答案。
    """
    try:
        t = max(0, int(turns or 0))
    except Exception:
        t = 0
    cur = LADDER[0]
    for row in LADDER:
        if t >= row[0]:
            cur = row
        else:
            break
    return cur[1], cur[2], cur[3]


# ─────────────────────────────────────────────────────────────
# 七、给提示词用的「当前关系」
# ─────────────────────────────────────────────────────────────
def line(sid, her_msg=""):
    """给提示词用的关系摘要 + 本轮方向。没数据返回 ""。

    行为：
      ① 样本够 → 用 her_stats 的 score 定档，并把**具体数字**写进提示词
        （她均字数 / 反问率 / 敷衍率 / 有内容率），让模型知道「她现在有多冷」，
        而不是只拿一句形容词。
      ② 样本不够 → 降级到轮数阶梯，并且**显式打日志**（用户口径：降级必须留痕，
        否则又变成静默失效 —— v11 那套「90 轮最后通牒」就是因为没人看日志，
        在 88% 走不到 45 轮的会话上白挂了一年）。
      ③ 她这条是收尾 → 只回短的，本轮不推进（保留 v11 行为，实测有效）。
      ④ 她这条 ≤4 字 → 在提示词里明写「禁止提问」。
        这是确定性判定，不能指望模型自己数她那条有几个字。
    """
    if not sid:
        return ""
    try:
        st = store.read_state(sid)
    except Exception as e:
        log.debug("stage.line 读 state 失败（按无数据处理）: %r", e)
        st = {}
    turns = int(st.get("turns") or 0)

    sc, s = score_parts(sid, her_msg)

    # ── 降级：样本不够 → 轮数阶梯 + 留痕 ──
    if sc is None:
        lv, name, goal = level(turns)
        log.info("[stage] sid=%s 投入度样本不足（她的消息 %d 条 < %d，turns=%d）"
                 "→ 降级用轮数阶梯「%s」", str(sid)[-8:], int(s.get("n_her") or 0),
                 MIN_HER, turns, name)
        out = ["【当前关系】%s（累计 %d 轮；她的投入度样本还太少，本档按轮数兜底）"
               % (name, turns)]
        if is_close(her_msg):
            out.append("她这条是收尾 → 本轮不推进、不提问，只回一句短的（8 字内）。")
            return "\n".join(out)
        out.append("**这一轮必须做到的**：%s" % goal)
        # 🔴 降级不等于放弃本轮判据：她这条的字数/问句是**当场可判**的，
        #   与历史样本多少无关。不写这一条，新会话就会退回「每轮必问」的老路。
        cur0 = str(her_msg or "").strip()
        if cur0 and nchars(cur0) <= 4 and not is_question(cur0):
            out.append("⚠️ 她这条只有 %d 字（%r）→ **禁止提问**，一条 ≤8 字，说完就停。"
                       % (nchars(cur0), cur0[:12]))
        out.append("⚠️ 每轮最多推进一格；她不接就退回一级，不硬顶、不重复试探。")
        return "\n".join(out)

    # ── 正常：投入度驱动 ──
    lv, name, goal = band(sc)
    out = ["【当前关系】%s档（她的投入度 %.2f，累计 %d 轮）" % (name, sc, turns)]
    out.append("· 她的实测行为：平均 %.1f 字；反问 %.0f%%；有内容的回复 %.0f%%；"
               "整条只是「嗯/哦/好」的占 %.0f%%"
               % (s.get("avg_len", 0), s.get("ask_rate", 0) * 100,
                  s.get("rich_rate", 0) * 100, s.get("cold_rate", 0) * 100))
    if her_opened_ever(sid):
        out.append("· 她主动找过你（这个会话第一条是她发的）—— 全库只有 1.3% 的会话有，"
                   "很稀罕，别用敷衍把它消耗掉。")

    # 她这条是收尾 → 本轮唯一该做的就是好好收尾
    if is_close(her_msg):
        out.append("她这条是收尾 → 本轮不推进、不提问，只回一句短的（8 字内）。")
        return "\n".join(out)

    out.append("**这一轮必须做到的**：%s" % goal)

    # 她这条本身的状态，直接影响本轮动作（确定性判定，不靠模型猜）
    cur = str(her_msg or "").strip()
    hl = nchars(cur)
    s_lv, s_words = signals_of(cur)
    if cur and hl <= 4 and not is_question(cur):
        out.append("⚠️ 她这条只有 %d 字（%r）→ **禁止提问**，一条 ≤8 字，说完就停。"
                   % (hl, cur[:12]))
    elif s_lv >= 2:
        out.append("✅ 她这条带了 %d 级信号（%s）→ 可以接住它走一格，"
                   "方向按规则里「时间层→距离层→张力层」的顺序，只走一格。"
                   % (s_lv, "、".join(s_words[:3])))

    if st.get("goal_hit"):
        out.append("✅ 联系方式 / 见面已经拿到 → 别再推了，把力气花在聊得舒服上。")
        return "\n".join(out)

    if st.get("giveup"):
        out.append("⚠️ 这个号以前判过推不动：这一轮只挪一格，她接了再继续，别加码。")

    out.append("⚠️ 每轮最多推进一格；她不接就退回一级，不硬顶、不重复试探。")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
# 八、轮数累计（签名与行为不变）
# ─────────────────────────────────────────────────────────────
def bump(sid, n=1):
    """轮数 +n（对话落盘时调）。返回新轮数。

    保留原样：投入度由 her_stats 从 turns.md 现算，不依赖这个计数；
    但 state.json 里 lv/name/goal 有别的读取点，所以仍按轮数写一份。
    """
    st = store.read_state(sid)
    turns = int(st.get("turns") or 0) + int(n)
    lv, name, goal = level(turns)
    store.write_state(sid, turns=turns, lv=lv, name=name, goal=goal)
    return turns


__all__ = ["LADDER", "PUSH_LV", "HARD_TURNS", "GOAL_LV", "level", "line", "bump",
           "SCORE_BANDS", "BAND_GOAL", "COLD_PENALTY", "MIN_HER",
           "score", "score_parts", "band", "her_opened_ever",
           "signals_of", "is_lazy", "is_question", "is_close", "nchars",
           "SIGNAL_T1", "SIGNAL_T2", "SIGNAL_T3"]
