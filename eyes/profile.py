# -*- coding: utf-8 -*-
"""眼睛：读对方个人主页（UserHomeActivity）。

实测 2026-11-02 予安的主页 UI 树（900x1600）：
    予安 / IP属地:重庆 / 96% 匹配度 / 3 关注 12 被关注 9 礼物
    务实家（灵魂画像）/ 53天
    职场打工人 / 已婚 / 音乐爱好者 / 拓展人际关系
    Ta的展品馆 / 瞬间 3 / 2026-10-30 20:18:41 / 瞬间正文

只读，不点任何东西。返回 dict 交给 brain 决定存哪。
"""
import re

from core.log import get_logger

log = get_logger("eyes.profile")

UI_NOISE = {
    "返回", "更多", "头像", "关注", "被关注", "礼物", "私聊", "瞬间", "收藏",
    "全部", "图片", "音乐", "视频", "文字", "Ta的展品馆", "灵魂画像", "匹配度",
    "手机信号满格。", "WLAN 信号满格。",
}
IP_RE = re.compile(r"IP\s*属地[:：]\s*(\S+)")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[\sT]")
PCT_RE = re.compile(r"^\d{1,3}%$")


def read(snap):
    """从主页 UI 树抽资料。返回 dict（缺的字段为空）。"""
    ts = [n.label.strip() for n in snap.nodes if n.label and n.label.strip()]
    out = {
        "nick": "", "ip": "", "soul": "", "days": "", "match_pct": "",
        "follow": "", "fans": "", "gifts": "",
        "tags": [], "moments": [], "raw": "",
    }

    # IP 属地
    for t in ts:
        m = IP_RE.search(t)
        if m:
            out["ip"] = m.group(1)
            break

    # 匹配度
    for t in ts:
        if PCT_RE.match(t):
            out["match_pct"] = t
            break

    # 昵称：顶部标题（状态栏在 y<70，必须排除，否则会把「正在充电，已完成百分之 71。」当昵称）
    STATUS_RE = re.compile(r"信号满格|正在充电|已完成百分之|^\d{1,2}:\d{2}$")
    top = [n.label.strip() for n in snap.nodes
           if n.label and 70 <= n.center[1] < 260
           and not STATUS_RE.search(n.label)
           and n.label.strip() not in UI_NOISE]
    top = [t for t in top if not IP_RE.search(t) and not t[:2].isdigit()
           and not t.endswith("%") and len(t) <= 20]
    if top:
        # 主页昵称是标题，通常是这一带最长的那条
        out["nick"] = max(top, key=len)[:20]

    # 关注/被关注/礼物：连续三个纯数字
    nums = [t for t in ts if t.isdigit() and len(t) <= 4]
    if len(nums) >= 3:
        out["follow"], out["fans"], out["gifts"] = nums[0], nums[1], nums[2]

    # 灵魂画像：布局是 [画像名 务实家] [53天] / [灵魂画像 标签]，
    # 且树上「灵魂画像」可能排在画像名之前 —— 必须按坐标找，不能按文本顺序。
    lab = [n for n in snap.nodes if n.label == "灵魂画像"]
    if lab:
        ly, lx = lab[0].center[1], lab[0].center[0]
        cands = [n for n in snap.nodes
                 if n.label and 0 < ly - n.center[1] < 130
                 and n.label.strip() not in UI_NOISE
                 and not re.fullmatch(r"\d+\s*天", n.label.strip())
                 and not n.label.strip().isdigit()
                 and 1 <= len(n.label.strip()) <= 6]
        if cands:
            out["soul"] = min(cands, key=lambda n: abs(n.center[0] - lx)).label.strip()
    for t in ts:
        if re.fullmatch(r"\d+\s*天", t):
            out["days"] = t
            break

    # 标签：灵魂画像之后、展品馆之前的那批短词
    try:
        a = ts.index("Ta的展品馆")
    except ValueError:
        a = len(ts)
    try:
        b = ts.index("灵魂画像")
    except ValueError:
        b = -1
    if b >= 0:
        for t in ts[b + 1:a]:
            if (t in UI_NOISE or t.isdigit() or PCT_RE.match(t)
                    or re.fullmatch(r"\d+\s*天", t) or not (2 <= len(t) <= 12)):
                continue
            if t not in out["tags"]:
                out["tags"].append(t)

    # 瞬间：时间戳 + 正文
    for i, t in enumerate(ts):
        if TS_RE.match(t):
            for j in range(i + 1, min(i + 4, len(ts))):
                body = ts[j]
                if body in UI_NOISE or TS_RE.match(body) or body.isdigit():
                    continue
                if 4 <= len(body) <= 120:
                    out["moments"].append(body)
                break

    out["raw"] = " | ".join(t for t in ts if t not in ("手机信号满格。", "WLAN 信号满格。")
                            and not t.startswith("正在充电"))[:300]
    return out


def summary(p):
    """一行摘要，用于日志。"""
    bits = []
    if p.get("nick"):
        bits.append("昵称=%s" % p["nick"])
    if p.get("ip"):
        bits.append("IP=%s" % p["ip"])
    if p.get("soul"):
        bits.append("画像=%s%s" % (p["soul"], p.get("days") or ""))
    if p.get("tags"):
        bits.append("标签=%s" % "/".join(p["tags"][:5]))
    if p.get("moments"):
        bits.append("瞬间=%d条" % len(p["moments"]))
    return " ".join(bits) or "（没抓到资料）"
