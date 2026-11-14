# -*- coding: utf-8 -*-
"""Pure message classification shared by data and perception layers.

This module only classifies text/type/uid. It has no device, database, or UI
side effects, which lets both `data.pending` and `eyes.sysmsg` use the same
rules without creating a data -> eyes dependency.
"""
from typing import Optional

HUMAN = "human"
SYSTEM = "system"
AD = "ad"

SYSTEM_TYPES = (27, 35)
SYS_TEXTS = ("[互动消息]", "[互动提醒]", "[系统消息]", "[官方消息]")
HUMAN_PLACEHOLDERS = ("[语音]", "[图片]", "[表情]", "[视频]", "[位置]", "[文件]")
SYSTEM_HARD = (
    "互相关注后即可", "发送一条消息即可", "对方撤回了一条消息",
    "消息已撤回", "语音通话结束", "视频通话结束", "对方拒绝了",
)
SYSTEM_PREFIX = (
    "对方设置了", "系统提示", "温馨提示", "请遵守", "社区规范",
    "实名认证", "青少年模式", "安全提醒", "该消息已", "通话时长",
    "你已成功", "已成为好友",
)
AD_HINTS = (
    "积分", "礼物", "周报", "兑换", "优惠", "上新", "限时", "福利",
    "领取", "会员", "直播", "任务", "打卡", "高定", "邀你", "快来看看",
    "即将登场", "广告", "下载APP", "点击链接", "关注公众号", "扫码",
)


def classify(text: str = "", msg_type: Optional[int] = None, uid: Optional[str] = None) -> str:
    try:
        if msg_type is not None and int(msg_type) in SYSTEM_TYPES:
            return SYSTEM
    except (TypeError, ValueError):
        pass
    t = (text or "").strip()
    if not t:
        return SYSTEM
    if any(t.startswith(p) or t == p for p in HUMAN_PLACEHOLDERS):
        return HUMAN
    if t in SYS_TEXTS or any(k in t for k in SYS_TEXTS):
        return SYSTEM
    u = str(uid or "")
    if u.startswith("2042683") or (u.startswith("-") and u[1:].isdigit()):
        return AD
    if any(k in t for k in SYSTEM_HARD):
        return SYSTEM
    if len(t) >= 12 and any(t.startswith(p) for p in SYSTEM_PREFIX):
        return SYSTEM
    return HUMAN


def is_human(text: str = "", msg_type: Optional[int] = None,
             uid: Optional[str] = None) -> bool:
    return classify(text, msg_type, uid) == HUMAN
