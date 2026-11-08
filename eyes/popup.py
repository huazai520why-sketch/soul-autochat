# -*- coding: utf-8 -*-
"""弹窗识别。只判断「有没有弹窗、有哪些按钮」，不决定按哪个（决策属于业务层）。

实测触发场景（2026-11-02）：点聊天 tab 时弹出「是否恢复聊天列表 / 取消 / 确认」，
弹窗期间底栏消失，所有依赖底栏文本的定位全部失效 —— 这是必须优先处理的状态。

🔴 2026-11-08 修复（来源：_report/01_识屏通道评估.md，探针 _tmp_screen5/7.py 实测）：
  原来的「底栏存在」判据是 `all(t in texts for t in ("聊天", "广场"))` —— **文本精确相等**。
  但实测底栏在**有未读**时文本会变成合并串：
      `广场 7条帖子未读`（探针 v5 实测底栏节点 text='广场 7条帖子未读'）
  这时精确匹配 `"广场" in texts` 为 False → has_tab=False → 直接进入按钮扫描，
  只要屏上恰好有「是 / 取消 / 关闭 / 知道」之类的字，就会把**正常的会话列表页误判成弹窗**，
  上层（nav.py:115-121）于是去点那个「按钮」，点了等于瞎点。

  现在改成三级判据，从稳到弱：
    ① resource-id：底栏 `main_tab_msg` / `main_tab_square`（实测最稳，不受未读文案影响）
    ② 前缀匹配 + 限定底栏区域（y >= 1500）：`广场 7条帖子未读`.startswith("广场")
    ③ 原精确相等（保留兜底，覆盖极老版本）
  另外「按钮」也加了约束：必须在底栏区域**以外**（y2 <= 1500），
  否则底栏自己的「聊天 / 自己」可能被当成弹窗按钮。
"""
from core.paths import TAB_TEXTS

# 常见的弹窗按钮文案（按语义分组）
BTN_PRIMARY = ["确认", "确定", "允许", "同意", "是", "立即", "恢复", "开始"]
BTN_SECONDARY = ["取消", "以后再说", "暂不", "否", "关闭", "知道了", "我知道了", "跳过"]

_ALL_BTNS = BTN_PRIMARY + BTN_SECONDARY

# 🔴 2026-11-08：底栏区域下界（900x1600 实测底栏 y=1502~1600）。
#   弹窗会**盖住**底栏，所以底栏区里出现的按钮文案一律不算弹窗按钮。
TAB_Y_MIN = 1500

# 底栏 tab 文本 → resource-id（与 eyes/uitree.py 的 TAB_RES 同源，实测 2026-11-02）
_TAB_RID = {"聊天": "main_tab_msg", "广场": "main_tab_square"}


class Popup(object):
    __slots__ = ("texts", "buttons", "primary", "secondary")

    def __init__(self, texts, buttons, primary, secondary):
        self.texts = texts
        self.buttons = buttons      # [(文案, Node)]
        self.primary = primary      # [(文案, Node)]
        self.secondary = secondary

    def __repr__(self):
        return "<Popup buttons=%s texts=%r>" % (
            [b[0] for b in self.buttons], self.texts[:6])


def _tab_present(snap, name):
    """底栏某个 tab 在不在。三级判据，见模块 docstring。

    🔴 2026-11-08：改前只有第 ③ 级（文本精确相等），底栏有未读时必然失效。
    """
    # ① resource-id（最稳）
    rid = _TAB_RID.get(name)
    if rid:
        for n in snap.nodes:
            if n.visible and (rid in (n.res_id or "")):
                return True

    # ② 前缀匹配，且必须落在底栏区域（排除页面顶部同名的「聊天 / 通讯录」切换标签）
    for n in snap.nodes:
        if not n.visible or n.bounds[1] < TAB_Y_MIN:
            continue
        t = (n.text or "").strip()
        if t and t.startswith(name):
            return True

    # ③ 原精确相等（兜底）
    return name in set(snap.texts())


def detect(snap):
    """有弹窗返回 Popup，否则 None。

    判据（两条同时满足）：
    1. 底栏不存在（弹窗会盖住底栏，实测底栏文本全部消失）
    2. 至少找到一个弹窗按钮文案（且按钮不在底栏区域）
    """
    texts = snap.texts()
    has_tab = all(_tab_present(snap, t) for t in ("聊天", "广场"))
    if has_tab:
        return None

    buttons, primary, secondary = [], [], []
    for label in _ALL_BTNS:
        # 🔴 2026-11-08：按钮**文本节点**必须不在底栏区域（y2 <= TAB_Y_MIN），
        #   否则底栏上的文字会被当成弹窗按钮。
        #   判据看文本节点本身、不看它的 clickable 容器 —— 弹窗根容器常常是全屏
        #   (0,0,900,1600)，用容器 bounds 判会把真按钮也一起否掉。
        #   也不能用 snap.hit(text=...)：hit 会重新按文本找一次，可能又命中底栏那个节点。
        cand = None
        for n in snap.find(text=label):
            if n.bounds[3] <= TAB_Y_MIN:
                cand = n
                break
        if cand is None:
            continue
        # 从这个候选向上/向外找真正可点击的容器（弹窗按钮常是外层 ViewGroup）。
        n = snap._clickable_of(cand)
        if n is None:
            continue
        buttons.append((label, n))
        if label in BTN_PRIMARY:
            primary.append((label, n))
        else:
            secondary.append((label, n))

    if not buttons:
        return None
    return Popup(texts, buttons, primary, secondary)


def signature(snap):
    """弹窗指纹：只看文本和按钮，用于判断「同一个弹窗还在不在」。"""
    p = detect(snap)
    if p is None:
        return None
    return "|".join(p.texts[:8]) + "#" + "|".join(b[0] for b in p.buttons)
