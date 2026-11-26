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
SYS_TEXTS = (
    "[互动消息]", "[互动提醒]", "[系统消息]", "[官方消息]",
    # 2026-11-26 夜修（P1 强制补入死循环）：App 对不支持的消息类型会落一条
    # 系统占位卡「当前版本不支持该消息，请升级到最新版本」，它不是真人话。
    # 实测两个 sid 每轮被设备未读对账强制补入 1526/503 次，再因拿不到昵称放弃。
    "当前版本不支持该消息，请升级到最新版本",
)
HUMAN_PLACEHOLDERS = ("[语音]", "[图片]", "[表情]", "[视频]", "[位置]", "[文件]")
SYSTEM_HARD = (
    "互相关注后即可", "发送一条消息即可", "对方撤回了一条消息",
    "消息已撤回", "语音通话结束", "视频通话结束", "对方拒绝了",
    # 版本/兼容性占位卡的变体（可能带不同后缀），按前缀子串一律判系统。
    "当前版本不支持该消息",
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
    # 🔴 2026-11-15 上午复查（D10，P2）：号段会变，文案特征更稳——与 data/imdb
    #   口径一致（≥2 个营销词命中判 AD）。只命中 1 词不判（误杀真人话=永久漏回）。
    if sum(1 for k in AD_HINTS if k in t) >= 2:
        return AD
    if any(k in t for k in SYSTEM_HARD):
        return SYSTEM
    if len(t) >= 12 and any(t.startswith(p) for p in SYSTEM_PREFIX):
        return SYSTEM
    return HUMAN


def is_human(text: str = "", msg_type: Optional[int] = None,
             uid: Optional[str] = None) -> bool:
    return classify(text, msg_type, uid) == HUMAN
