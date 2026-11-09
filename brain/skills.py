# -*- coding: utf-8 -*-
"""本地模型「三技能」执行器 —— 2026-11-09 按用户口径「重新安装原技能」装回。

原执行器是旧架构 `E:\\soul2.1\\brain\\soul_skills.py`，该目录已不存在，
git 历史与本机镜像里也没有副本；三份技能提示词原件仍在
`E:\\soul1.0\\memory\\_reference\\技能_*.md`（被 .gitignore 排除）。
本模块**按原三技能原文重建**，并把提示词正式装进仓库 `config/skills/`
（原件含真实地名，入库版只替换了那一处示例地名）。

三技能（2026-10-24 定的 FunctionCall 三技能）：
  ① analyze_her       —— 她的性格建模 / 投入度 → 画像 L0
  ② ask_strategist    —— 推进策略（情绪→信号→状态→动作档→收束）
  ③ ask_tongjincheng  —— 人性判断（五个模型 + 九条启发式）
  原架构里 ②③ 合并成「方案 L1」，这里保持一致（一次调用，省一半时间）。

设计约束（不重演 2026-11-04 判死简报时那三个问题）：
  · L0 / L1 只**落档**（l0.md / l1.md）供追溯，不各自塞进 system；
  · 出话侧只收一份「合成裁决」写进 brief.md —— **方向只有一处**，
    避免 L0「稳一稳」与 L1「撩」同时进提示词导致模型折中；
  · 合成段明确禁写「禁令清单」与整段话术模板（实测会把话削平 / 被照抄）。

开关：SOUL_LOCAL_FLOW=skills（默认，本模块生效）| brief（回到纯简报）。
      SOUL_SKILLS_MERGE=0 可关掉第③次合成调用（只落 L0/L1，不写 brief）。
绝不阻塞、绝不抛：任何一步失败返回空串，调用方按「没有三技能」降级。
"""
import io
import os
import re
from pathlib import Path

try:
    from core.log import get_logger
    log = get_logger("brain.skills")
except Exception:                                     # 单测/离线可直接 import
    import logging
    log = logging.getLogger("brain.skills")

BASE = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE / "config" / "skills"
LEGACY_DIR = BASE / "memory" / "_reference"

# 技能名 → 装回仓库后的文件名
FILES = {
    "analyze_her": "技能_analyze_her.md",
    "ask_strategist": "技能_strategist.md",
    "ask_tongjincheng": "技能_tongjincheng.md",
}

_CCache = {}

DISCIPLINE = (
    "\n\n【输出纪律】\n"
    "只输出判断本身，不复述上面任何提示文字、不加「【内部参考」之类标记、不解释思路。\n"
    "所有结论必须能追到对话里她真实说过的话；样本不足就写「样本不足」。\n"
    "不超过 500 字。\n"
)

MERGE_SYS = (
    "你是聊天参谋。下面给你两份内部判断（画像 + 策略/人性判断），请合成一份"
    "**这一轮**用的简短素材，纯文本，五个小节，不要解释思路：\n\n"
    "## 她的状态\n一句话：她什么情绪 + 想干什么。\n\n"
    "## 可接的点\n1~2 条，每条用她这句里真实出现过的词。\n\n"
    "## 方向\n**只选一个**：稳一稳 / 撩一下 / 往前推一格。不许给两个方向。\n\n"
    "## 一个开口\n一句她一句话能答的具体问句，标明「可改」（不许写成整段话术）。\n\n"
    "## 别踩\n最多 1 条，只写真会翻车的。\n\n"
    "🔴 禁止写「禁止再提…/禁止解释…」这类禁令清单（实测会把出话压平）；"
    "禁止给整段话术模板（会被照抄成口头禅）。全文不超过 240 字。\n"
)

FACT_SYS = (
    "你是事实抽取器。从对话里挑出**关于她的、能长期成立的新事实**，"
    "每条一行，格式「事实 | 她原话片段」，只写这一轮新出现、档案里还没有的。\n\n"
    "硬规矩：\n"
    "1. 只写「她本人说过的客观信息」（身份/职业/住址/喜好/作息/关系状态等），"
    "不写推测、不写评价、不写「我」说过的事。\n"
    "2. 竖线右边必须是**从她原话里逐字复制**的一句话，一个字都不能改。\n"
    "3. 没有新事实就输出「无」。\n"
    "4. 最多 6 条。\n"
)


def _load(name):
    """读技能原文，优先仓库版 config/skills/，回落 memory/_reference/ 原件。"""
    if name in _CCache:
        return _CCache[name]
    fn = FILES.get(name)
    if not fn:
        return ""
    for d, prefix in ((SKILLS_DIR, ""), (LEGACY_DIR, "技能_")):
        p = d / (fn if not prefix else prefix + fn.split("_", 1)[-1])
        # 原件的名字是 技能_analyze_her.md 等，与仓库版同名，直接试两种
        for cand in (d / fn, p):
            try:
                if cand.is_file():
                    t = io.open(str(cand), encoding="utf-8").read().strip()
                    if t:
                        _CCache[name] = t
                        return t
            except Exception:
                continue
    log.warning("技能提示词缺失: %s（找过 %s 与 %s）", name, SKILLS_DIR, LEGACY_DIR)
    return ""


def available():
    return all(_load(n) for n in FILES)


def _account_context(sid, max_turns=8000, max_facts=40):
    """拉账号档案：静态主页 profile + 沉淀事实 facts + 全部对话 turns。

    这是「三技能输入 = 对方账号档案信息」的落地：画像技能①据此见到的
    不只是一句话，而是这个人的主页标签、已确认的事实、以及完整聊天历史。
    任何一处读失败都静默降级（绝不因档案读取失败而阻塞三技能）。
    """
    parts = []
    try:
        from brain.pack import store
        p = store.read_profile(sid) or {}
        if p:
            nice = []
            for k in ("nick", "signature", "tags", "common", "match", "ip"):
                v = p.get(k)
                if v not in (None, "", [], {}):
                    nice.append("%s=%s" % (k, v))
            if nice:
                parts.append("【账号档案·主页】\n" + "\n".join(nice))
        f = store.read_facts(sid) or {}
        hers = f.get("hers") or []
        mine = f.get("mine") or []
        if hers or mine:
            lines = []
            for it in hers[:max_facts]:
                t = (it.get("t") or "") if isinstance(it, dict) else str(it)
                if t:
                    lines.append("- 她: " + t)
            for it in mine[:max_facts]:
                t = (it.get("t") or "") if isinstance(it, dict) else str(it)
                if t:
                    lines.append("- 我: " + t)
            if lines:
                parts.append("【账号档案·已确认事实】\n" + "\n".join(lines))
        turns = store.read_turns(sid, max_turns) or ""
        if turns.strip():
            parts.append("【账号档案·对话历史】\n" + turns[-max_turns:])
    except Exception as e:
        log.warning("[三技能] 读账号档案失败 sid=%s: %r", str(sid)[-8:], e)
    return "\n\n".join(parts).strip()


def _parse_fact_lines(block, evidence_pool):
    """从模型输出的「事实」块抽 (内容, 原话片段)。

    复用 brief._parse_facts 的「竖线分隔 + 逐字校验」思路，但证据源从
    「单条 her_msg」扩大到「当前消息 + 档案全文」——证据必须逐字出现在
    evidence_pool 里才收，模型改写过的直接丢弃（防编造）。
    """
    out = []
    for ln in (block or "").splitlines():
        s = ln.strip()
        if not s or s == "无" or s.startswith("（") or s.startswith("#"):
            continue
        s = re.sub(r"^[-*·\d.)、\s]*", "", s)
        if "|" not in s:
            continue
        content, _, ev = s.partition("|")
        content, ev = content.strip(), ev.strip()
        if not content or not ev:
            continue
        if ev not in (evidence_pool or ""):
            continue
        out.append((content[:40], ev[:60]))
    return out


def _extract_facts(sid, her_msg, account=""):
    """独立调一次本地模型，抽取「关于她的新事实」并走 add_fact 落库。

    返回 (新增条数, 错误)。绝不抛：任何失败返回 (0, err)，不影响三技能主链。
    """
    try:
        from brain.engine import llm
        from brain.pack import store
        # 证据池 = 当前消息 + 档案全文（这样跨轮出现的事实也能落地）
        pool = (her_msg or "") + "\n" + (account or "")
        raw = llm.analyze(
            [{"role": "system", "content": FACT_SYS},
             {"role": "user", "content":
              "【她刚说的】\n%s\n\n【已有档案（避免重复抽取）】\n%s"
              % ((her_msg or "（无）"), (account or "（无）")[:5000])}],
            timeout=40, temperature=0.3, max_tokens=500)
        added = 0
        for content, ev in _parse_fact_lines(raw, pool):
            if store.add_fact(sid, content, side="hers", ev=ev, conf=0.9):
                added += 1
                log.info("[事实] + %s（出处 %r）", content[:20], ev[:16])
        return added, ""
    except Exception as e:
        return 0, str(e)


def _messages(name, ctx, extra_sys=""):
    sys_txt = _load(name) + DISCIPLINE + extra_sys
    her = (ctx.get("her_msg") or "").strip() or "（无）"
    acct = (ctx.get("account") or "").strip()
    case = (ctx.get("case") or ctx.get("turns") or "").strip() or "（无历史）"
    if acct:
        # 账号档案已在 ctx.account 里给全，对话历史直接用档案里的，避免重复截断
        user = ("【她刚发来的消息】\n%s\n\n【对方账号档案信息】\n%s\n"
                % (her, acct[-9000:]))
    else:
        user = ("【她刚发来的消息】\n%s\n\n【最近的对话（时间顺序）】\n%s\n"
                % (her, case[-3000:]))
    return [{"role": "system", "content": sys_txt},
            {"role": "user", "content": user}]


def _clean(t):
    """剥掉模型自己带出来的工具提示行/标签（旧架构踩过：会被原样写进 L0）。"""
    out = []
    for ln in (t or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("【内部参考") or s.startswith("【她的画像") or s.startswith("【技能"):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _call(name, ctx, extra_sys="", max_tokens=700, timeout=None):
    try:
        from brain.engine import llm
        r = llm.analyze(_messages(name, ctx, extra_sys),
                        timeout=timeout or 40, temperature=0.4,
                        max_tokens=max_tokens)
        return _clean(r)
    except Exception as e:
        log.warning("[三技能] %s 调用失败: %r", name, e)
        return ""


def run(name, ctx=None, **_kw):
    """兼容旧 `SK.run("analyze_her", {}, ctx)` 语义的单技能入口。"""
    if ctx is None:
        ctx = _kw.get("ctx") or {}
    return _call(name, ctx)


def run_all(sid, her_msg, turns_text="", write=True):
    """跑完三技能并落档。返回 {'l0','l1','brief', 'ok'}。

    ① analyze_her → L0 画像
    ②③ 合并      → L1 方案
    ③ 合成         → 单一方向裁决，写 brief.md（带 her 指纹，出话链路原样可读）
    """
    ctx = {"sid": str(sid or ""), "her_msg": her_msg or "", "turns": turns_text or ""}
    res = {"l0": "", "l1": "", "brief": "", "ok": False}
    if not available():
        log.warning("[三技能] 提示词不全，跳过（改用简报）")
        return res

    # 画像技能①吃「账号档案全量」：主页 + 事实 + 完整历史，不只最近一句。
    account = _account_context(sid)
    ctx["account"] = account

    res["l0"] = _call("analyze_her", ctx, max_tokens=700)

    s2, s3 = _load("ask_strategist"), _load("ask_tongjincheng")
    merged_sys = ("\n\n──────── 技能② 推进策略 ────────\n%s\n\n"
                  "──────── 技能③ 人性判断 ────────\n%s" % (s2, s3))
    # ②③ 也吃全量档案（复用 account），画像①的结果作为内部参考一并给
    ctx2 = dict(ctx)
    ctx2["account"] = (account + "\n\n【①画像（内部参考）】\n" + res["l0"])[-9000:]
    ctx2["case"] = ""          # account 分支里已含完整历史，不再重复塞 case
    res["l1"] = _call("ask_strategist", ctx2, extra_sys=merged_sys, max_tokens=900)

    if os.environ.get("SOUL_SKILLS_MERGE", "1") != "0":
        try:
            from brain.engine import llm
            raw = llm.analyze(
                [{"role": "system", "content": MERGE_SYS},
                 {"role": "user", "content":
                  "【画像 L0】\n%s\n\n【方案 L1】\n%s\n\n【她这句】\n%s"
                  % (res["l0"][:900], res["l1"][:900], her_msg or "（无）")}],
                timeout=40, temperature=0.4, max_tokens=500)
            res["brief"] = _clean(raw)[:600]
        except Exception as e:
            log.warning("[三技能] 合成裁决失败: %r", e)

    # 事实提取：独立一步，从对话里抽「带原话出处的新事实」增量写 facts.json。
    # 复用 brief 那套「竖线分隔 + 逐字校验」防编造闸门，证据池扩到档案全文。
    res["facts"] = 0
    if os.environ.get("SOUL_FACTS_ON", "1") != "0":
        try:
            added, err = _extract_facts(sid, her_msg, account)
            res["facts"] = added
            if err:
                log.warning("[三技能] 事实提取失败: %r", err)
        except Exception as e:
            log.warning("[三技能] 事实提取异常: %r", e)

    res["ok"] = bool(res["l0"] or res["l1"])
    if write:
        save(sid, her_msg, res)
    return res


def save(sid, her_msg, res):
    """L0/L1 落档 + 合成裁决写 brief（带指纹，供 prompt._brief_block 读取）。"""
    try:
        from brain.pack import store
        d = store.pack_dir(sid)
        if res.get("l0"):
            store._atomic_write(d / "l0.md", res["l0"] + "\n")
        if res.get("l1"):
            store._atomic_write(d / "l1.md", res["l1"] + "\n")
        if res.get("brief"):
            from brain.engine.brief import her_stamp
            store.write_brief(sid, "<!-- her:%s -->\n%s"
                              % (her_stamp(her_msg), res["brief"]))
    except Exception as e:
        log.warning("[三技能] 落档失败 sid=%s: %r", str(sid)[-8:], e)


__all__ = ["run", "run_all", "save", "available", "FILES"]
