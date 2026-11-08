# -*- coding: utf-8 -*-
"""档案重建：旧 v2 案情包（L0~L4 md）→ 新 v3 schema（facts/turns/profile/state）。

「重建」不是「拷贝」，三件事必须做：
  ① **归属**：旧 L0 的「事实：」行是她和我的混在一起（实测把「我开网店卖电脑配件」
     记成她的事实）。这里拿 L2 原文逐条比对，只在「我:」里出现过 → 归 mine，
     只在「她:」里出现过 → 归 hers，两边都没有 → **丢弃**（无出处不写）。
  ② **清洗**：语气词/回声（「真的尽力了」「什么意思」）不是事实，丢掉。
  ③ **补齐**：从 L2 原文里按高置信模式重新抽事实（住哪/年纪/工作/孩子/婚况/宠物…），
     同样带 evidence。旧档案里没有的，这里能补出来。

旧文件不删：拷进 `<sid>/_legacy/` 留档，方便事后核对「这条事实从哪来」。

用法（在副机上跑）：
    python rebuild.py            # 干跑，只出报告
    python rebuild.py --apply    # 真正写入 memory/
"""
import io
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))        # E:\soul1.0

from brain.pack import store                        # noqa: E402

V2_MEM = Path(os.environ.get("SOUL_V2_MEM", r"E:\soul2.1\memory"))

_WHEN = re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2})")


def sort_turns(rows):
    """按时间排序 [(when, role, text)]。

    为什么必须排：旧 L2 是按「批次」拼接的，同一会话内会出现
    「11:32 → 11:32 → 11:28」这种段内逆序（实测 16/355 会话）。
    prompt 里写的是「时间顺序，最近的在最后」，乱序会让模型误判因果。

    键用 (月,日,时,分) 而不是字符串 —— 跨年时 "12-31" 排不到 "01-01" 前面。
    月份跨度 > 6 判为跨年，把 <=6 的月份 +12 再排。
    """
    if not rows:
        return rows

    def parse(when):
        m = _WHEN.match(str(when or ""))
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

    parsed = [parse(x[0]) for x in rows]
    valid = [p for p in parsed if p]
    wrap = bool(valid) and (max(v[0] for v in valid) - min(v[0] for v in valid) > 6)

    def key(i):
        p = parsed[i]
        if not p:
            return (9999, 0, 0, 0)          # 解析不出的排最后（稳定）
        mo = p[0] + 12 if (wrap and p[0] <= 6) else p[0]
        return (mo, p[1], p[2], p[3])

    return [rows[i] for i in sorted(range(len(rows)), key=key)]


# ── 语气词/回声：不是事实 ────────────────────────────────────────
_ECHO = re.compile(
    r"^(?:真的|确实|实在|好吧|好|行|要得|懂了|知道了|明白|哈哈|呵呵|嗯+|哦+|额+|啊+|"
    r"什么意思|啥意思|你说啥|怎么|为什么|啥|什么|在吗|在不在|没事|算了|随便|不知道|不晓得)")
_FACT_CUE = re.compile(
    r"(?:在|住|是|有|做|干|上|读|学|岁|老家|家|工作|上班|开店|卖|喜欢|爱|养|"
    r"孩子|女儿|儿子|娃|老公|老婆|对象|男朋友|女朋友|结婚|离婚|单身|一个人|"
    r"重庆|四川|贵州|湖南|广东|浙江|江苏|山东|河南|河北|陕西|云南|广西|福建|"
    r"安徽|湖北|江西|山西|甘肃|新疆|内蒙|辽宁|吉林|黑龙江|北京|上海|天津)")

# ── 从原文抽事实（只收高置信、且必须带原话）──────────────────────
_HARVEST = [
    ("住哪", re.compile(r"我(?:在|住在|住|老家在|是)([\u4e00-\u9fff]{2,8})(?:这边|那边|这|那)?(?:人|的)?")),
    ("年纪", re.compile(r"我(?:今年|今年都|都)?\s*(\d{2})\s*(?:岁|了)")),
    ("工作", re.compile(r"我(?:在|是|干|做)([\u4e00-\u9fff]{2,10})(?:工作|上班|的|这行)")),
    ("婚况", re.compile(r"我(?:已经)?(离婚|结婚了|单身|没结婚|离异)")),
    ("孩子", re.compile(r"我(?:有|带|养)(?:一个|个|两个)?(孩子|女儿|儿子|娃)")),
    ("宠物", re.compile(r"我(?:养|有)(?:了|只|条|个)?(猫|狗|仓鼠|兔子|乌龟)")),
    ("作息", re.compile(r"我(?:每天|一般|经常)([\u4e00-\u9fff]{2,10})(?:上班|下班|睡|起)")),
]

_UID_TAIL = re.compile(r"^- (\d{2})-(\d{2}) (\d{2}):(\d{2}) (她|我): (.*)$")


# ══════════════════════════ 解析旧文件 ══════════════════════════
def parse_turns(text):
    """L2 原文 → [(when, role, text)]"""
    out = []
    for ln in (text or "").splitlines():
        m = _UID_TAIL.match(ln.strip())
        if m:
            when = "%s-%s %s:%s" % (m.group(1), m.group(2), m.group(3), m.group(4))
            out.append((when, m.group(5), m.group(6)))
    return out


def parse_l4(text):
    """L4 资料 → profile dict。键名沿用页面口径。"""
    p = {}
    section = ""
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith("## "):
            section = s[3:].strip()
            continue
        if not s.startswith("- "):
            continue
        body = s[2:]
        if "：" not in body and ":" not in body:
            continue
        k, _, v = (body.partition("：") if "：" in body else body.partition(":"))
        k, v = k.strip(), v.strip()
        if not v:
            continue
        if section == "个人主页" or k in ("昵称", "引力签", "共同点", "匹配度",
                                        "IP属地", "灵魂画像", "标签", "瞬间"):
            p[k] = v
    return p


def parse_l0_facts(text):
    """L0「事实：」行 → [str]。其余行（类型/投入度/吃哪套/下一步/这一轮该）不进 facts。"""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not (s.startswith("事实：") or s.startswith("事实:")):
            continue
        body = s.partition("：")[2] if "：" in s else s.partition(":")[2]
        for x in re.split(r"[；;]", body):
            x = x.strip(" 　·、,，")
            if x:
                out.append(x)
    return out


def parse_pack_json(text):
    try:
        d = json.loads(text)
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


# ══════════════════════════ 归属判定 ══════════════════════════
def _norm(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s or "")


def attribute(item, turns):
    """返回 (side, ev, conf)。side ∈ {"hers","mine",""}，空 = 无出处，丢弃。"""
    key = _norm(item)
    if len(key) < 3:
        return "", "", 0.0
    hits_her, hits_me = [], []
    for when, role, txt in turns:
        if key in _norm(txt):
            (hits_her if role == "她" else hits_me).append((when, txt))
    if hits_her and not hits_me:
        return "hers", hits_her[0][1][:80], 0.9
    if hits_me and not hits_her:
        return "mine", hits_me[0][1][:80], 0.9
    if hits_her and hits_me:
        # 两边都说过：优先算她的（她说过的关于自己的话更可信），但降置信
        return "hers", hits_her[0][1][:80], 0.5
    return "", "", 0.0


def is_junk(item):
    """语气词、回声、过长过短 → 不是事实。"""
    t = (item or "").strip()
    if len(t) < 3 or len(t) > 40:
        return True
    if _ECHO.match(t) and len(t) < 14:
        return True
    if not _FACT_CUE.search(t):
        return True
    return False


def harvest(turns):
    """从原文抽事实，只收「她」说的；同一句里出现多个模式也只留最长。"""
    facts = []
    seen = set()
    for when, role, txt in turns:
        if role != "她":
            continue
        for label, pat in _HARVEST:
            for m in pat.finditer(txt):
                val = (m.group(1) or "").strip()
                if not val or len(val) < 2:
                    continue
                if val in ("不知道", "不晓得", "什么", "这个", "那个"):
                    continue
                t = "%s：%s" % ({"住哪": "住在", "年纪": "年龄", "工作": "在做",
                                 "婚况": "婚况", "孩子": "有孩子", "宠物": "养",
                                 "作息": "作息"}[label], val)
                if t in seen:
                    continue
                seen.add(t)
                facts.append({"t": t, "ev": txt[:80], "at": when[:5],
                              "conf": 0.7, "src": "原文抽取"})
    return facts


# ══════════════════════════ 单会话重建 ══════════════════════════
def rebuild_one(v2_dir, sid, apply=False):
    v2 = Path(v2_dir)
    L2 = (v2 / "L2_对话.md")
    L0 = (v2 / "L0_人设.md")
    L4 = (v2 / "L4_资料.md")
    PJ = (v2 / "pack.json")

    turns = parse_turns(L2.read_text(encoding="utf-8", errors="replace")
                        if L2.is_file() else "")
    l0 = L0.read_text(encoding="utf-8", errors="replace") if L0.is_file() else ""
    l4 = L4.read_text(encoding="utf-8", errors="replace") if L4.is_file() else ""
    pj = parse_pack_json(PJ.read_text(encoding="utf-8", errors="replace")
                         if PJ.is_file() else "")

    profile = parse_l4(l4)
    old_facts = parse_l0_facts(l0)

    hers, mine, dropped = [], [], []
    for it in old_facts:
        if is_junk(it):
            dropped.append((it, "语气词/无事实线索"))
            continue
        side, ev, conf = attribute(it, turns)
        if not side:
            dropped.append((it, "原文无出处"))
            continue
        rec = {"t": it, "ev": ev, "at": (turns[0][0][:5] if turns else ""),
               "conf": conf, "src": "old_L0"}
        (hers if side == "hers" else mine).append(rec)

    # 原文抽取补齐
    for f in harvest(turns):
        if any(f["t"] == h["t"] for h in hers):
            continue
        hers.append(f)

    rel = (pj.get("rel") or {})
    stat = {
        "turns": int(rel.get("turns") or len(turns)),
        "lv": int(rel.get("lv") or 0),
        "name": rel.get("name") or "",
        "goal": rel.get("goal") or "",
        "goal_hit": bool(rel.get("goal_hit")),
        "giveup": bool(rel.get("giveup")),
        "status": pj.get("status") or "active",
    }

    row = {"sid": sid, "turns": len(turns), "hers": len(hers), "mine": len(mine),
           "dropped": len(dropped), "profile": len(profile), "rel_turns": stat["turns"]}

    if apply:
        d = store.pack_dir(sid, pj.get("acct") or "")
        store.write_meta(sid, uid=pj.get("uid") or "", acct=pj.get("acct") or "",
                         nick=pj.get("nick") or profile.get("昵称") or "",
                         l0_rounds=pj.get("l0_rounds") or 0,
                         legacy="v2")
        store.write_profile(sid, **profile)
        store.write_facts(sid, {"hers": hers, "mine": mine})
        store.write_state(sid, **stat)
        tp = store.turns_path(sid)
        if turns and not tp.is_file():
            with io.open(str(tp), "w", encoding="utf-8", newline="\n") as f:
                for when, role, txt in sort_turns(turns):
                    f.write("- %s %s: %s\n" % (when, role,
                                               txt.replace("\n", " / ").strip()))
        # 轮数只认 turns.md（唯一可复现来源），覆盖旧 pack.json 的估算值
        store.resync_state(sid)
        store.import_v2_dir(v2, sid)
        row["dir"] = str(d)
        row["rel_turns"] = store.read_state(sid).get("turns")
    row["dropped_items"] = dropped[:6]
    return row


# ══════════════════════════ 批处理 ══════════════════════════
def iter_v2_sessions():
    if not V2_MEM.is_dir():
        return
    for acct in sorted(os.listdir(V2_MEM)):
        ad = V2_MEM / acct
        if not ad.is_dir() or not acct.startswith("账号"):
            continue
        for sid in sorted(os.listdir(ad)):
            sd = ad / sid
            if sd.is_dir() and (sd / "L2_对话.md").is_file():
                yield acct, sid, sd


def main():
    apply = "--apply" in sys.argv
    rows = []
    t0 = time.time()
    for acct, sid, sd in iter_v2_sessions():
        try:
            rows.append(rebuild_one(sd, sid, apply=apply))
        except Exception as e:
            rows.append({"sid": sid, "err": repr(e)})

    ok = [r for r in rows if "err" not in r]
    tot_turns = sum(r["turns"] for r in ok)
    tot_h = sum(r["hers"] for r in ok)
    tot_m = sum(r["mine"] for r in ok)
    tot_d = sum(r["dropped"] for r in ok)
    empty = [r for r in ok if r["turns"] == 0]

    lines = []
    lines.append("=" * 70)
    lines.append("档案重建 %s" % ("【已写入】" if apply else "【干跑】"))
    lines.append("=" * 70)
    lines.append("会话数        : %d  (失败 %d)" % (len(ok), len(rows) - len(ok)))
    lines.append("对话总轮次    : %d" % tot_turns)
    lines.append("事实 hers     : %d" % tot_h)
    lines.append("事实 mine     : %d  （从她档案里剔出去的串台条目）" % tot_m)
    lines.append("丢弃条目      : %d" % tot_d)
    lines.append("无对话的会话  : %d" % len(empty))
    lines.append("耗时          : %.1fs" % (time.time() - t0))
    lines.append("")
    lines.append("── 有对话的会话（按轮次降序，前 25）──")
    for r in sorted([x for x in ok if x["turns"] > 0],
                    key=lambda x: -x["turns"])[:25]:
        lines.append("%-20s 轮%-4d hers%-3d mine%-3d 丢%-3d 主页%-2d"
                     % (r["sid"], r["turns"], r["hers"], r["mine"],
                        r["dropped"], r["profile"]))
    lines.append("")
    lines.append("── 抽样：被判为「串台」或「无出处」的条目 ──")
    for r in ok:
        for it, why in r.get("dropped_items") or []:
            lines.append("%s  [%s] %s" % (r["sid"][-8:], why, it[:50]))
    if any("err" in r for r in rows):
        lines.append("")
        lines.append("── 失败 ──")
        for r in rows:
            if "err" in r:
                lines.append("%s %s" % (r["sid"], r["err"]))

    txt = "\n".join(lines)
    io.open(str(store.BASE / "_rebuild_report.txt"), "w",
            encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
