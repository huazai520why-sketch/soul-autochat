# -*- coding: utf-8 -*-
"""页面识别 + 红点读取。纯读屏，不点击。

判据一律用「UI 树里的文本/结构」，不用像素颜色、不用写死坐标。
"""
import re

# 各页面的特征文本（900x1600 实测，2026-11-02；2026-11-08 随 App 改版更新）
SIG = {
    "me": ["编辑昵称", "我的展示标识", "个性商城"],
    "chat": ["发送", "长按说话"],
    "square": ["推荐", "同城", "关注"],
    # 🔴 2026-11-08（P0 空烧根因）：App 改版把匹配入口从「开始匹配」改成
    #   「立即寻找懂你的人」，旧判据只剩「灵魂匹配」1 个命中 → 永远 < 2 →
    #   星球页被判 unknown → nav 每轮 back/am start/重启 App，实测 20:00-21:00
    #   连续 12 轮匹配全失败、整点小时零回复。这里补齐新文案并降到结构判据优先。
    "planet": ["灵魂匹配", "立即寻找懂你的人", "开始匹配", "语音匹配", "群聊派对"],
}

_NUM_RE = re.compile(r"^\d{1,3}$")


def detect(snap):
    """返回页面类型：chatlist / chat / greeting / square / me / planet / unknown。

    chatlist 必须是**强判据**（真的存在会话列表 RecyclerView 且有 >=2 行），
    不能用「底栏在 + 没别的特征」兜底 —— 那样任何带底栏的页面都会被误判，
    等于没判断。
    """
    texts = set(t for t in snap.texts() if t)

    # 新招呼详情页（NewGreetingDetailActivity）：
    # 标题「收到的新招呼」+ 详情页特征文本「发消息后对话框将会被放出哦」/「暂无更多未读消息」。
    # 🔴 2026-11-06 事故（121 轮 blocked，08:47~11:12，33 条未读无人回）：
    #   会话列表里的系统聚合行「收到的新招呼 · 有 N 个新招呼」也带这五个字，
    #   旧判据只要屏上出现这五个字就判 greeting → 整张列表被误判成详情页，
    #   nav 点聊天原地打转（列表本来就是聊天 tab）、全轮 blocked。
    #   修复：必须同时带详情页特征文本才算 greeting；列表行场景落回 chatlist 判据。
    if "收到的新招呼" in texts and (
        "发消息后对话框将会被放出哦" in texts or "暂无更多未读消息" in texts
    ):
        return "greeting"

    # chat 页最强判据：输入框 resource-id 或「发送」
    if snap.find(res="et_sendmessage", limit=1) or snap.find(res="sendmessage", limit=1):
        return "chat"
    if "发送" in texts and not (("聊天" in texts) and ("广场" in texts)):
        return "chat"

    # 🔴 2026-11-08（结构判据优先，文案只做兜底）：
    #   星球页独有的 resource-id 是 `currentOnlineNumTv`（「当前 N 人在线」），
    #   它只在星球页出现，不受文案改版影响；用它可以彻底摆脱「按钮改名 → 整页不识别」。
    if snap.find(res="currentOnlineNumTv", limit=1):
        return "planet"

    for page, keys in SIG.items():
        if page == "chat":
            continue
        hit = sum(1 for k in keys if k in texts)
        if hit >= 2:
            return page

    # 会话列表：必须有列表容器 + 至少两行
    try:
        from .chatlist import list_view, rows
        if list_view(snap) is not None and len(rows(snap)) >= 2:
            return "chatlist"
    except Exception:
        pass

    return "unknown"


def badges(snap, tab_y_min=1500):
    """读底栏红点数字：返回 {tab上方的文本: 数字}。

    实测：广场 tab 的红点是 TextView '6' at (299,1510,333,1544)，
    聊天 tab 是 TextView '12' at (626,1510,660,1544)，都在图标右上角、
    且 y 都在 1500~1560 区间（比 tab 文字 y=1571 更靠上）。
    """
    out = {}
    for n in snap.nodes:
        if not n.visible:
            continue
        t = n.text.strip()
        if not _NUM_RE.match(t):
            continue
        x1, y1, x2, y2 = n.bounds
        if y1 < tab_y_min or y1 > 1570:
            continue
        # 按 x 归到对应的 tab 区间（900 宽四等分）
        if x1 < 201:
            out["星球"] = int(t)
        elif x1 < 402:
            out["广场"] = int(t)
        elif x1 < 699:
            out["聊天"] = int(t)
        else:
            out["自己"] = int(t)
    return out
