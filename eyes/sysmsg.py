# -*- coding: utf-8 -*-
"""系统消息 / 广告识别（obs §104 C5、C8）。

背景（2026-11-10 夜班复盘）：系统卡「互相关注后即可…」被当成她说的真人话回了出去，
而且它还会把 ``her_ts`` 水位线往前推，让真正的人话看起来「已经回过」。

规则：
  * ``msg_type`` 命中 ``data.imdb.SYS_TYPES``（27 / 35）→ system。
  * 文本命中系统卡 / 官方推送特征 → system 或 ad。
  * ``[语音]`` / ``[图片]`` / ``[表情]`` 是**真人消息占位**，必须判 human，
    否则语音会话会被整批漏回（这是最容易踩的反例）。
  * 系统消息只跳过、不冷却、不更新 her_ts（C5/C8），由调用方据此决定。
"""
from typing import Optional
from core import message_kind as _MK

HUMAN = _MK.HUMAN
SYSTEM = _MK.SYSTEM
AD = _MK.AD
SYS_TEXTS = _MK.SYS_TEXTS
HUMAN_PLACEHOLDERS = _MK.HUMAN_PLACEHOLDERS

# 🔴 §106 交叉审查实证（P1-2）：旧版对 SYSTEM_HINTS 做**子串**匹配，
#    把「通话时长挺长的」「此消息很重要」「你已成功啦」「互相关注吧」
#    这些真人话判成系统卡 → pendingq 直接 continue，永久漏回。
#    改成两层：无歧义固定整句（硬判据）+ 平台提示前缀且文本够长（软判据）。
SYSTEM_HARD = _MK.SYSTEM_HARD
SYSTEM_PREFIX = _MK.SYSTEM_PREFIX

# 营销 / 广告（_OFFICIAL_HINTS 同源）
AD_HINTS = _MK.AD_HINTS


def classify(
    text: str = "",
    msg_type: Optional[int] = None,
    pos: str = "",
    uid: Optional[str] = None,
) -> str:
    """把一条消息判成 human / system / ad。

    Args:
        text: 消息文本（可能是 ``[语音]`` 之类占位串）。
        msg_type: imdb 的 msgType；27 / 35 为系统卡。
        pos: 气泡方向（left=她 / right=我），只作参考，不改变类型判定。
        uid: 对方 uid；官方营销号段 2042683 直接判 ad。

    Returns:
        ``"human"`` / ``"system"`` / ``"ad"``。空文本按 system 处理
        （不能拿空串当她说了话，去推进 her_ts 水位线）。
    """
    sys_types = _MK.SYSTEM_TYPES
    try:
        if msg_type is not None and int(msg_type) in sys_types:
            return SYSTEM
    except (TypeError, ValueError):
        pass

    return _MK.classify(text, msg_type, uid)


def is_human(
    text: str = "",
    msg_type: Optional[int] = None,
    pos: str = "",
    uid: Optional[str] = None,
) -> bool:
    """是否真人消息（供 ``has_human`` / her_ts 水位线使用）。

    Args:
        text: 消息文本。
        msg_type: imdb msgType。
        pos: 气泡方向。
        uid: 对方 uid。

    Returns:
        True 表示可以推进 her_ts 并计入待回；系统/广告返回 False。
    """
    return classify(text, msg_type, pos, uid) == HUMAN


def is_system(text: str = "", msg_type: Optional[int] = None,
              pos: str = "", uid: Optional[str] = None) -> bool:
    """是否系统/广告（供 C8「只跳过不冷却」使用）。"""
    return not is_human(text, msg_type, pos, uid)


__all__ = ["HUMAN", "SYSTEM", "AD", "SYS_TEXTS", "HUMAN_PLACEHOLDERS",
           "SYSTEM_HARD", "SYSTEM_PREFIX", "AD_HINTS", "classify",
           "is_human", "is_system"]
