# -*- coding: utf-8 -*-
"""会话页读消息（OCR 兜底）。

Soul 的聊天气泡是自绘的，a11y 树里消息节点数为 0（实测 6 个会话全为 0），
所以只能截图 OCR。实测 900x1600：
  对方气泡：文本左边界 x1 ≈ 157~200
  我的气泡：文本右边界 x2 ≈ 742~743
  时间戳：居中 (380~523)，形如「10月28日04:10」
  底部快捷栏：y ≥ 1420（早上好/交换答案/礼物/一起听）
  输入框：y ≈ 1500+
"""
import re

from . import ocr

TS_RE = re.compile(r"(\d+月\d+日|\d{1,2}:\d{2}|昨天|前天|刚刚)")
SYS_TEXTS = {
    "关注", "关注后可邀请通话", "查看主页", "发送", "文明聊天，友善交友~",
    "早上好", "交换答案", "桌球", "礼物", "一起听", "语音", "表情", "更多",
    # 系统通知卡片上的按钮文案（实测被 OCR 当成"对方消息"，导致误判需回复）
    "去看看", "去回复", "查看详情", "立即查看", "点击查看", "查看",
}

# 系统文案/匹配卡片（实测会混进 OCR 结果，被误当成对方说的话）
SYS_PHRASES = (
    "你们的共同点", "Ta的引力签", "Ta的星座", "Ta思想家星球", "匹配度",
    "与ta的聊天记录", "消息云漫游", "正在使用个性化提示装扮", "Soul周年",
    "关注后可邀请", "交换答案", "查看主页", "不合拍", "举报",
)

MSG_TOP = 140        # 状态栏/标题栏以下
MSG_BOTTOM = 1400    # 快捷栏以上
RIGHT_EDGE = 700     # 旧判据（先判右导致她长句误判 me），由 side_of 就近边判定取代
LEFT_EDGE = 210      # 旧判据（存档）
SCREEN_W = 900       # 实测分辨率（900x1600）
NEAR_EDGE = 300      # 左右距离都超过此值 -> 居中（"?"）


def _is_noise(it):
    t = it.text.strip()
    if not t:
        return True
    if t in SYS_TEXTS:
        return True
    if any(p in t for p in SYS_PHRASES):
        return True
    if TS_RE.fullmatch(t) or (TS_RE.search(t) and len(t) <= 12):
        return True
    if len(t) == 1 and not t.isalnum():
        return True
    return False


def side_of(it):
    """me / her / ?——**就近边判定**。

    🔴 2026-11-10（演示实弹解剖实锤）：原实现**先判右再判左**——她的长句
      （左起 x1≈157，长句文本框右边界可延伸过 700）会先命中 me 分支被误判
      → 不回 → 「红点消了消息没回」。实弹样本：霜鸢Icy 13:30
      「胆子大才能保护人嘛~…」box=(158,1316,723,1352) 被判 me（库明明 her），
      截图存证 logs/_anatomy_134326.png；短句永不踩线，只咬她的长句。
    修复：左边距 box[0] vs 右边距 SCREEN_W-box[2]，**小者胜**；两侧距离都
      超过 NEAR_EDGE（居中：时间戳/资料条）→ "?"（保持原行为）。
    实测：她长句 158<177 → her ✓；我方 (428,742) 158<428 → me ✓；
      居中资料条 (293,490) 均>300 → "?" 与原行为一致。
    """
    x1, _, x2, _ = it.box
    dl, dr = x1, SCREEN_W - x2
    if min(dl, dr) > NEAR_EDGE:
        return "?"
    return "me" if dr < dl else "her"


TITLE_RES = "id/tv_title"


def title_of(snap):
    """对话页顶栏昵称（UI 树）。读不到返回 ""。

    实测（2026-11-04）：节点 res-id 结尾是 `id/tv_title`，text 即昵称；
    旁边 `id/tv_online_label` 是「10小时前」这种状态，不要混进来。
    """
    try:
        for n in snap.nodes:
            rid = (n.res_id or "")
            if rid.endswith(TITLE_RES) and (n.text or "").strip():
                return n.text.strip()
    except Exception:
        pass
    return ""


def bubbles(png_bytes):
    """会话页所有可见消息，按 y 升序：(text, side, item)。"""
    out = []
    for it in ocr.read(png_bytes):
        if it.cy < MSG_TOP or it.cy > MSG_BOTTOM:
            continue
        if _is_noise(it):
            continue
        out.append((it.text.strip(), side_of(it), it))
    out.sort(key=lambda x: x[2].cy)
    return out


def last_bubble(png_bytes):
    """最后一条可见消息。返回 (text, side, item) 或 None。

    side == "her"  => 必须回复（业务硬规则）
    side == "me"   => 无需回复
    side == "?"    => 判不准，保守按 her 处理（宁可多回，不可不回）
    """
    bs = bubbles(png_bytes)
    if not bs:
        return None
    return bs[-1]
