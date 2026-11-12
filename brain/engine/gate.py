# -*- coding: utf-8 -*-
"""出话后的确定性硬闸（v10）。

为什么必须有这一层（不是靠提示词自觉）：
  历史上每一次「提示词写了但代码没拦」都出过事故 ——
  10-07 本地池漏发「要不咱约个时间去钓鱼」、10-14「我开车过去」漏拦、
  10-28 承诺句式写进提示词反而从 1.8% 升到 4.7%（列举"不许说的话"＝把那句话塞进候选池）。
  ⇒ 结论：**提示词管倾向，代码管红线。** 该拦的一条都不能靠模型自觉。

本模块只做判断与清洗，不改写语义。返回 (ok, reason)。
调用方拿到 ok=False 时按「换一句 / 本轮不发」处理，绝不原样发出去。
"""
import re

# ── 站外导流/时政/违法/擦边：命中即作废（整条剔除，不修补）──────────────
# 🔴 2026-11-08 重构（用户授权 + 实证）：
#   旧版把「微信 / 加微 / vx / 扣扣 / QQ / 支付宝 / 银行卡 / 扫码 / 二维码 /
#   转账 / 红包」和「约炮 / 一夜情 / 裸聊 / 开房 / 上床 / 做爱 / 包养」放在同一张表，
#   命中就整句作废。实测后果（_report/06 实证 482 条样本）：
#     · 「那加个微信耍嘛」被作废 → 而她 16 天里给了 8 次手机号、催了 8 次加微信，
#       会话最后断在我们回的「你发的啥呀我没看清」；
#     · 反过来「想不想做」「我也想要你」**全部放行** —— 闸防住了有用的那句，
#       没防住真危险的词。
#   ⇒ 拆成两张表：
#     HARD_BAN  真正会封号/违法的（时政、毒品、枪支、赌博、诈骗、自杀、招嫖）
#     SOFT_BAN  平台敏感但**可改写**的（导流类）—— 不再整句作废，改由
#               `soft_hit()` 交给调用方决定：能换成安全说法就换，换不了才弃。
HARD_BAN = (
    "习近平", "习主席", "习总", "总书记", "政治局", "武统", "台独", "台湾独立",
    "港独", "疆独", "藏独", "导弹", "核武",
    "毒品", "枪支", "赌博", "诈骗", "走私", "杀人", "自杀", "坐牢",
    # 招嫖/露骨交易（保留：这类在 Soul 会直接封号，且不是「暧昧」）
    "约炮", "一夜情", "裸聊", "包养", "情趣用品", "嫖", "卖淫",
)

# 平台敏感但可改写：不再一票否决，只记 warn + 让调用方改写。
# 判定口径来自实际风控：站外导流会被限流/屏蔽，但**不是封号级**，
# 而「她要联系方式」是最高价值的推进信号，为了躲一个词把它整句删掉是本末倒置。
SOFT_BAN = (
    "微信", "加微", "vx", "VX", "扣扣", "QQ", "支付宝", "银行卡",
    "扫码", "二维码", "转账", "红包",
)

# 露骨词（性张力层）：**不拦**，只作为「这一轮已经够露骨，别再往上加」的信号。
# 2026-11-08：旧版把「上床 / 做爱 / 开房」放进 HARD_BAN，导致她明牌时
# 机器人只能装傻（实测 4 次「我不得来」→ 她回「再见」）。
# 现在的分工：提示词负责「不写露骨词、只往暧昧带」，代码不再一刀切作废整句。
EXPLICIT_WORDS = ("上床", "做爱", "开房", "睡你", "脱", "裸", "胸", "腿", "痒", "湿")

# ── 空头承诺：「等下讲/回头发你/改天带你」——她记住的是"你答应了" ──
_PROMISE_RE = re.compile(
    r"(?:我给你|等下|回头|改天|晚点|下次)[^，。！？\s]{0,10}"
    r"(?:讲|说|发|找|寄|带|看|吃|扯|推)"
    r"|(?:推|发)你")

# 🔴 2026-11-08 补：**结构判据**（dialog-designer 实测 19 条露骨句，纯子串表漏 7 条）。
#   为什么必须有这一层：把「上床/开房」从 HARD_BAN 移走后，`今晚出来开个房`
#   `发张裸照看看` `过来陪我睡` `出来约个炮` 会全部放行 —— 这几句在 Soul
#   是**真会封号**的，不是「暧昧」。暧昧与招嫖的分界线是**有没有动作句**：
#     · 「这个点还醒着，是在等谁」        → 暧昧（张力层，放行）
#     · 「过来陪我睡」「今晚出来开个房」  → 动作句（性邀约，作废）
#   所以用结构判据而不是继续堆词。这条与 EXPLICIT_WORDS 的分工：
#   EXPLICIT_WORDS 只标记（不拦），_SOLICIT_RE 直接作废。
_SOLICIT_RE = re.compile(
    r"(?:来|去|开|陪|上|做|发|给|拍)[^，。！？\s]{0,4}(?:房|床|睡|裸|炮|脱|胸|腿)"
    r"|(?:睡|陪)(?:我|你)(?:一|个)?(?:晚|觉|睡)?"
    r"|(?:裸|脱)(?:照|图|视频|了)"
    r"|(?:上|做)(?:床|爱)"
)

# ── 方向反了：见面必须她动身，我不跑过去 ──
_REV_RE = re.compile(
    r"我(?:开车|骑车|打车|打的|坐车|走路|走过来|跑过去)(?:过去|过来|来)"
    r"|我(?:过去|过来|来)(?:找|看|接|请你)?你"
    r"|我来你"
    r"|我(?:去|来)接你"
    r"|我(?:在|到)你(?:楼下|门口|附近)")

# ── 主动邀约：只认明确形态，绝不误杀「你什么时候方便」（那是把主导权给她）──
# 🔴 2026-11-08 重构（实证 _report/06）：旧版把「想见你」这类**模型自己长出来的
#   升级句**当「主动邀约」拦掉。实测闸丢弃的 23 条里 20 条是「复读」、
#   其余多是被这条 `_INVITE_RE` 误杀（「我想见你本人」「我倒有点想见见你」）。
#   用户的战略是「她动身过来」，但**表达「我想见你」不等于「我跑过去」**——
#   前者是给张力，后者才是方向错。所以：
#     · 删掉 `_INVITE_WANT_RE` 这条拦截（「想见你」放行）
#     · 保留「约个时间/见个面/出来见」这类**实质邀约**的拦截
#     · `_REV_RE`（我过去/我来接你）继续拦 —— 那条才是真正违反方向的
_INVITE_RE = re.compile(
    r"约(?:个时间|个饭|一顿|一下|起|一约)"
    r"|咱(?:俩)?约"
    r"|见(?:个面|一面|面吧)"
    r"|出来见"
    r"|(?:什么时候|啥时候|哪天|有空)(?:见|出来|约)"
)
# 「你哪天过来耍」= 她动身过来（战略方向正确），不能按"主动邀约"拦。
# 2026-11-05 加：stage 推进档要求给这个台阶，闸却把它拦掉 —— 规则与闸对撞。
_HER_COME_RE = re.compile(
    r"(?:你|妳)(?:哪天|有空|什么时候|啥时候)?[^，。！？]{0,8}?(?:过来|来耍|来玩)")
_COME_NEG_RE = re.compile(r"约|见面|见个|我去|我过来|我来")

# ── 表演腔：括号动作/旁白、星号动作 ──
_PAREN_RE = re.compile(r"[（(][^）)]{1,30}[）)]|\*[^*\n]{1,20}\*")
# ── 模型爱带的前缀/标签 ──
_LABEL_RE = re.compile(
    r"^\s*(?:话术\s*\d|回复|答案|候选|第[一二三]句|句子)\s*[:：]\s*")
_QUOTE_STRIP = "\"'“”‘’「」『』"

# ── 长度 ──
# 🔴 2026-11-12（GL-06 说明，不改上限）：MAX_CHARS=40 是**最后防线**（单条超过
#   基本是"小作文"），不是出话长度目标；白天/夜间的实际长度档由 rules.voice()
#   按时段决定（白天 6~18 字）。两者口径不同**不是 bug**：
#   gate 只做"绝不超 40 字"的硬上限，时段档在 rules 侧。改长度档属于话术策略
#   （红线），此处只加注释说明，不硬改。
MAX_CHARS = 40          # 单条硬上限（超过它基本是"小作文"）
IDEAL_MAX = 26          # 超过它记一条 warn，但仍发（宁可发出去也别沉默）


def clean(text):
    """去掉表演腔、标签、引号、多余空白。不改语义。"""
    t = str(text or "")
    t = _PAREN_RE.sub("", t)
    t = re.sub(r"^```.*?$", "", t, flags=re.M)
    t = t.replace("**", "").replace("__", "")
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if not lines:
        return ""
    t = lines[0] if len(lines) == 1 else " / ".join(lines)
    t = _LABEL_RE.sub("", t)
    t = t.strip().strip(_QUOTE_STRIP).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t


def hard_hit(t):
    s = str(t or "")
    for w in HARD_BAN:
        if w in s:
            return w
    return ""


def soft_hit(t):
    """平台敏感词（导流类）。返回命中的词，调用方据此**改写**而不是丢弃。

    2026-11-08 新增：旧的 HARD_BAN 把「微信」和「毒品」放在同一张表里，
    命中就整句作废 —— 于是「那加个微信耍嘛」被删，而她正等着这句
    （_report/06 实证：她 16 天给了 8 次手机号、催 8 次加微信，全被闸吃掉）。
    现在这里只做「提示」，`check()` 不再因为它返回 False。
    """
    s = str(t or "")
    for w in SOFT_BAN:
        if w in s:
            return w
    return ""


def explicit_hit(t):
    """露骨词命中。**不作废**，只作为「别再往上加码」的信号给调用方。"""
    s = str(t or "")
    for w in EXPLICIT_WORDS:
        if w in s:
            return w
    return ""


# ── 白天禁用的「暗示层」词（用户：聊骚只能在晚上，白天禁止）──────────────
# 与 EXPLICIT_WORDS 的区别：这些词**本身不露骨**，只在深夜语境里才有性张力。
# 白天说出来会很怪（「这么晚还不睡」早上说 = 神经病），且容易让对方觉得油腻。
#
# 🔴 2026-11-08 校准（_report/11 §4 + lead 特别提醒「别误伤夜间」）：
#   旧版是一张平表，只在 `if not is_night_now()` 里生效。窗口改成三级之后
#   这就不够了 —— 21~23 的预热层允许「时间层/情绪层」，但不许身体词；
#   如果把整张表都放到 21 点解锁，等于 21 点就允许「勾引/心跳」，
#   与提示词写的「21~23 只走时间和情绪」自相矛盾（提示词与代码对不上，
#   正是 gate.py 头注释里 10-28 那类事故的成因）。
#   ⇒ 拆成两级，各按时段解锁：
#      _TIME_WORDS    时间层（睡不着/失眠/躺着）     21~05 可用（含预热层）
#      _TENSION_WORDS 张力层（想你/心跳/勾引/搂/贴）  **只有 23~05** 可用
#   语料依据：她夜间原话「我在床上躺着呢」「床够宽不」「被窝暖和」
#   属于**场景层**，是 23~05 的主力句式，所以「被窝/躺」必须放在能被夜间放行的一级。
_TIME_WORDS = (
    "睡不着", "失眠", "躺", "被窝", "在床上", "床够宽", "暖好", "这个点",
)
_TENSION_WORDS = (
    "想你了", "想你", "心跳", "上头", "心动", "害羞", "脸红", "想我",
    "抱抱", "亲亲", "亲一口", "搂", "贴", "撩", "勾引",
)


def _tension_hit(t):
    """时间层词（睡不着/躺/被窝）—— 白天拦，夜间（含 21~23 预热层）放行。"""
    s = str(t or "")
    for w in _TIME_WORDS:
        if w in s:
            return w
    return ""


def _sex_tension_hit(t):
    """张力层词（想你/心跳/勾引/搂）—— 白天 + 预热层都拦，**只有 23~05 放行**。"""
    s = str(t or "")
    for w in _TENSION_WORDS:
        if w in s:
            return w
    return ""


def _is_night_now():
    """当前是否夜间（含 21~23 预热层，与 prompt.is_night 同口径）。

    延迟导入避免循环依赖（prompt 会 import gate 里的常量）。
    导入失败时**保守返回 False**（当作白天、禁止荤话）——
    宁可白天少撩，也不要在错误时段说出荤话。
    """
    try:
        from .prompt import is_night
        return bool(is_night())
    except Exception:
        return False


def _is_tension_now():
    """当前是否「张力层」（23~05）。预热层 21~23 返回 False。

    这张力层的边界：**身体词/想你/心跳/勾引只在 23 点后才放行**。
    依据 _report/11 §4：00~05 她带张力 9.9%（凌晨 3~4 点 10.7% 峰值），
    而 22~24 只有 7.2%，且这两小时每 37 条就有 1 条「晚安」——
    她随时要走的时候上身体词，等于自己撞墙。
    """
    try:
        from .prompt import is_tension_time
        return bool(is_tension_time())
    except Exception:
        return False


# ── commit 型问句：要她表态 → 给她拒绝的机会（_report/11 §6.3 实测）──────
# 这是 2026-11-08 最重要的一次方向纠正。数据（她已热的瞬间，n=457）：
#     offer 型问句（要不要我帮你挠 / 床够宽不）  保持热度 **37.5%**
#     probe 型问句（要她提供信息）              25.9%
#     commit 型问句（你会不会…/你是不是特别…）  **11.1%**  ← 给她台阶说「不」
#     非问句陈述句                              **7.3%**  ← 全表最低
# 所以**不是「禁问句」**（我早前那版 rules 里禁提问是过头了），
# 而是：**问句前是「我能给你什么」→ 好；问句前是「你是什么/你会怎么想」→ 差**。
# 语料原话：我说「那我喊疼你会不会心软哦」→ 她「不会」，热度 3→1 直接死。
_COMMIT_RE = re.compile(
    r"会不会|想不想|是不是特别|是不是觉得|你觉得|你怎么想|咋样呀|相处得|"
    r"愿不愿意|肯不肯|喜不喜欢|在不在乎"
)
# offer 白名单：命中就豁免（这些是「我给得起的东西」）
_OFFER_WL = re.compile(
    r"要不要我|我帮你|我给你|我陪你|我请你|我带你去|够不够|够宽|暖好|拉好|"
    r"帮你挠|我给你养|我还敢|要不要给你"
)


def commit_hit(t):
    """commit 型问句（要她表态）→ 命中且不是 offer 型，返回 True。"""
    s = str(t or "")
    if not _COMMIT_RE.search(s):
        return False
    return not _OFFER_WL.search(s)


# ── 冷漠确认式 / 灭火句：她热的时候说这句 = 当场把话头掐了（_report/11 §6.1）──
# 实测频次（我的原话，全部发生在她正热的时候）：
#   17× 在呢，刚看到你说的 | 9× 你也在刷这个 咱俩挺闲啊
#    5× 厂里上班 普工 两班倒 | 4× 那你想聊点啥子撒 | 4× 我这人嘴笨 但不会让你冷场
# 前两类是**零信息应答**，后三类是**把主语换成我自己**。
# 这里只拦「整条就是一句冷漠确认」的形态（短且无实义），
# 不拦「在呢，刚看了你说的那个猫，笑死」这种带内容的 —— 那种是正常接话。
_COLD_ACK = ("在呢", "在的", "刚看到", "刚看见", "我来了", "嗯你说", "你说吧", "怎么了")
_COLD_ACK_MAX = 12          # 超过这个长度视为「后面还有内容」，不拦
# 🔴 2026-11-12（GL-03 → A2：升级为给 Lead 的**明确修复方案**注释，**不改 flow.py**）：
#   问题：flow.py:510 的 FALLBACK_LINES（"嗯嗯，在的"/"刚看到，你说"/"在呢，你继续"/
#         "嗯，我听着"）是必回兜底话术池。日志证实 24h 窗口 4 次真实触发
#         「引擎无产出 → 用兜底话术」，全部命中本 `_COLD_ACK`（在的/刚看到/在呢/在），
#         即**兜底话术本身就是灭火句**（她热的时候这句 = 当场掐话头；_report/11 §6.1
#         实测 17 次，头号灭火句），且池子仅 4 句反复群发。
#   根因：兜底池与 `_COLD_ACK` 判定**用了同一批词** —— 闸后空被兜底成灭火句。
#   修复方案（**需用户拍板后由 flow.py 执行，此处不改 flow.py**）：
#     1) 从 FALLBACK_LINES 去掉命中 `_COLD_ACK` 的词，替换为**不命中** `_COLD_ACK`、
#        短（≤12 字）、且是「offer 型 / 具体画面」的新句（offer 型问句保持热度 37.5%，
#        零信息应答只有 7.3%，见 _report/11 §6.3）；
#     2) 建议新池子（4 条，均不命中 `_COLD_ACK` 全部词：在呢/在的/刚看到/刚看见/
#        我来了/嗯你说/你说吧/怎么了；长度均 ≤12 字；全部 offer 型 / 具体画面）：
#          · 要不要我给你点啥        （offer 型问句：问我能给什么）
#          · 我给你带杯奶茶呀        （offer 型：我给得起的东西）
#          · 我陪你唠到天亮          （offer 型：我给得起时间/陪伴）
#          · 要不要我帮你按按肩      （offer 型：我给得起服务）
#     3) 若暂不换池子，可放宽 `_COLD_ACK` 对「兜底路径」的判定（让 FALLBACK_LINES
#        作为例外放行），但**兜底话术反复群发本身就是最伤账号的行为**（比撞开头严重），
#        建议以换池子为主。
#   边界：**不改 flow.py、不改 _COLD_ACK 本身**；改池子属产品话术（红线），
#        需用户拍板，本注释只给方案。


def cold_ack_hit(t):
    """整条只是一句「我在/刚看到」→ 零信息，命中返回 True。"""
    s = str(t or "").strip()
    if not s or len(s) > _COLD_ACK_MAX:
        return False
    return any(w in s for w in _COLD_ACK)


def solicit_hit(t):
    """性邀约/招嫖的动作句 → 命中即作废（封号级）。

    2026-11-08 新增。这一条是**替代**把「开房/上床」塞进 HARD_BAN 的正确做法：
    旧做法会把「她提了床，我接一句暧昧」也一起毙掉（实测 4 次「我不得来」→「再见」），
    而纯子串表又漏掉 7/19 个变体。结构判据只杀**动作句**，不杀**张力句**：
        放行：「这个点还醒着，是在等谁」「别这么说话，我容易当真」
        作废：「过来陪我睡」「今晚出来开个房」「发张裸照看看」「出来约个炮」
    """
    return bool(_SOLICIT_RE.search(str(t or "")))


def promise_hit(t):
    return bool(_PROMISE_RE.search(str(t or "")))


def reverse_hit(t):
    return bool(_REV_RE.search(str(t or "")))


def invite_hit(t):
    s = str(t or "")
    if _HER_COME_RE.search(s) and not _COME_NEG_RE.search(s):
        return False                     # 「你哪天过来耍」→ 她动身，放行
    # 🔴 2026-11-08：删掉「想见你」拦截。表达「我想见你」是给张力，
    #   不是「我跑过去」（后者才违反方向，由 reverse_hit 管）。
    return bool(_INVITE_RE.search(s))


def _norm(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(s or ""))


def dup_hit(t, recent):
    """与她最近几条我的发言比：完全相同 / 一方包含另一方 / 高度相似 → 判复读。

    🔴 2026-11-08 修（实证 _report/06）：旧版第三条判据是
        `common = 逐字交集占比 >= 0.7`  → 判复读。
    它是**按字面重合**算的，中文短句里几乎必然命中：
        「要得，晚安」vs「要得」→ 交集 {要,得} / 3 = 0.67（勉强过）
        「那加个微信耍嘛」vs「那加个好友」→ 交集 {那,加,个} / 7 = 0.43（过）
    实测后果：闸丢弃的 23 条里有 **20 条被判「复读」**，
    把模型自己长出来的升级句（「我想见你本人」）碾成了「要得，晚安」。
    ⇒ 改为：只有**整句相同**或**一方完整包含另一方**才判复读；
      再补一条「去掉口头禅后的骨架完全相同」才算。
      字数重合度不再单独作为判据 —— 它误杀率太高，而漏放一句重复
      的代价（她看到一句似曾相识的话）远小于碾掉一句升级句的代价。
    """
    a = _norm(t)
    if len(a) < 3:
        return False
    # 去掉方言口头禅后再比：这些词重复出现是「人设口吻」，不是复读
    _FILLER = ("要得", "要撒", "撒", "嘛", "哈", "哦", "咯", "噻", "哦豁")
    a_bare = a
    for f in _FILLER:
        a_bare = a_bare.replace(f, "")
    for r in (recent or []):
        b = _norm(r)
        if not b:
            continue
        if a == b:
            return True
        # 🔴 2026-11-08：短句（<=8 字）不判「包含」—— 新规则鼓励短回复，
        #   而「嗯，那就这样」vs「嗯，那就这样吧」这种一字之差会被误杀。
        #   短句的复读由「完全相同」那条兜住就够了。
        if len(a) <= 8 or len(b) <= 8:
            continue
        # 一方完整包含另一方（且短的那方本身有实义，>=5 字）
        if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
            return True
        # 骨架完全相同（去掉口头禅后一字不差）
        b_bare = b
        for f in _FILLER:
            b_bare = b_bare.replace(f, "")
        if len(a_bare) >= 4 and a_bare == b_bare:
            return True
    return False


def check(text, recent=None, allow_soft=True):
    """返回 (ok, reason)。reason 用于日志归因，不写给用户。

    🔴 2026-11-08 语义变更（用户授权 + 实证）：
      · `soft_hit`（微信/QQ/扫码…）**不再返回 False**。它们是平台敏感但可改写的，
        由 `allow_soft` 保留开关；命中只体现在 reason 里（`ok_soft:微信`），
        调用方想看就自己看。
      · `explicit_hit`（上床/做爱/痒…）**不再返回 False**。旧版把它当红线整句作废，
        直接导致她明牌时机器人只能装傻（4 次「我不得来」→ 她回「再见」）。
        「不写露骨词」是**提示词的活**（rules.ADVANCE 已写明分层表达），
        代码只负责真正会封号的东西。
      · 保留的硬闸：时政/毒品/枪支/赌博/诈骗/自杀/招嫖、空头承诺、
        方向反了（我过去）、实质邀约（约个时间/见个面）、复读。
    """
    t = clean(text)
    if not t:
        return False, "清洗后为空"
    if len(t) > MAX_CHARS:
        return False, "过长(%d字)" % len(t)
    w = hard_hit(t)
    if w:
        return False, "红线词(%s)" % w
    # 🔴 2026-11-08：结构判据优先于 soft/explicit —— 动作句直接毙（封号级）
    if solicit_hit(t):
        return False, "性邀约动作句"
    if promise_hit(t):
        return False, "空头承诺"
    if reverse_hit(t):
        return False, "方向反了(我过去)"
    if invite_hit(t):
        return False, "主动邀约"
    if isinstance(recent, str):
        recent = [recent]
    if recent and dup_hit(t, recent):
        return False, "复读"
    # 🔴 2026-11-08 新增：零信息应答（「在呢」「刚看到」）——
    #   实测 17 次，是她在热的时候的头号灭火句。它不该被当成「安全」而放行。
    if cold_ack_hit(t):
        return False, "零信息应答(在呢/刚看到)"
    # 🔴 2026-11-08 新增：commit 型问句（「你会不会…」「你是不是特别…」）——
    #   实测保持热度 11.1%，而 offer 型 37.5%。给她拒绝的机会 = 帮她结束这段对话。
    #   夜间严格执行（那是张力场景）；白天放宽（「你觉得呢」是自然口语，不该一律毙）。
    if commit_hit(t) and _is_night_now():
        return False, "commit型问句(要她表态)"
    # 🔴🔴 2026-11-08（用户硬要求）：「聊骚一定是在晚上 白天禁止」。
    #   提示词里已经写了昼夜两段（prompt._night_block），但**光靠提示词不够**：
    #   历史教训是「提示词写了但代码没拦」必出事故（见文件头 10-28 那次）。
    #   所以这里加代码闸：**白天**（非 22:00~05:00）出现任何性暗示/露骨词 → 直接作废。
    #   夜间放行（仍然拦动作句，见上面的 solicit_hit）。
    #   判定用 prompt.is_night()，与提示词同一口径，不会出现「提示词说白天、代码说晚上」。
    if not _is_night_now():
        ew0 = explicit_hit(t)
        if ew0:
            return False, "白天禁止荤话(%s)" % ew0
        tw = _tension_hit(t)
        if tw:
            return False, "白天禁止暗示(%s)" % tw
        tw2 = _sex_tension_hit(t)
        if tw2:
            return False, "白天禁止暗示(%s)" % tw2
    elif not _is_tension_now():
        # 21~23 预热层：时间层放行，但身体词/想你/心跳/勾引仍不许（还没到点）
        tw2 = _sex_tension_hit(t)
        if tw2:
            return False, "预热层禁止身体词(%s)" % tw2
    # 以下两条只记录，不否决
    sw = soft_hit(t)
    if sw and not allow_soft:
        return False, "站外导流(%s)" % sw
    if sw:
        return True, "ok_soft(%s)" % sw
    ew = explicit_hit(t)
    if ew:
        return True, "ok_explicit(%s)" % ew
    return True, "ok"


def to_messages(text, max_n=2):
    """模型输出 → [要发出去的 1~2 条]。按行/斜杠切，逐条清洗，不超过 max_n。"""
    raw = str(text or "")
    parts = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if " / " in ln and len(ln) > 24:
            parts.extend(x.strip() for x in ln.split(" / ") if x.strip())
        else:
            parts.append(ln)
    out = []
    for p in parts:
        c = clean(p)
        if not c:
            continue
        if len(c) > MAX_CHARS:          # 过长条目再按标点断一次
            for x in re.split(r"[。！？；]", c):
                x = x.strip()
                if x:
                    out.append(x)
        else:
            out.append(c)
        if len(out) >= max_n:
            break
    return out[:max_n]


__all__ = ["HARD_BAN", "SOFT_BAN", "EXPLICIT_WORDS", "MAX_CHARS", "IDEAL_MAX",
           "clean", "hard_hit", "soft_hit", "explicit_hit", "solicit_hit",
           "promise_hit", "reverse_hit", "invite_hit", "commit_hit", "cold_ack_hit",
           "dup_hit", "check", "to_messages"]
