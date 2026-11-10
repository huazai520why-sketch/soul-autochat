# -*- coding: utf-8 -*-
"""会话列表：按 RecyclerView 子节点切行，不靠像素聚类。

实测结构（900x1600）：
  RecyclerView (0,136,900,1502)   scrollable=true, 10 个直接子 ViewGroup
  每个 ViewGroup 高 153px：136-289 / 289-442 / 442-595 ...
  行内：头像(desc=头像) + 昵称(res=id/name) + 时间(res=id/time) + 「匹配」标签 + 最后消息预览(res=id/message)

🔴 2026-11-08 修复（来源：_report/01_识屏通道评估.md 的实测证据，探针 _tmp_screen5/6/7.py）：
  1. `_looks_time` 用「含月/日即算时间」反推，把真实昵称当时间戳吃掉 ——
     实测「纸间藏月」「漫赏星河月」「月眠青山里」「十一月的雨」「明日香」全部误判 True，
     导致 9/10 行的 nickname 退化成消息预览（如「既然没啥聊的，那我先歇会儿」）。
     改成**穷举正向正则 + 全文锚定**。
  2. `rows()` 无行高过滤 —— 实测 48px 的 Soul通知横幅行 `(0,136,900,184)`
     （内容只有 `头像 [夜深了]`）和 95px 的底部残行都被当成会话行。
     改成按屏高比例过滤 + 行内内容校验。
  3. `list_view()` 不校验页面 —— 实测在会话页（page=chat）会抓到
     `RecyclerView (0,1405,900,1485)`（底部功能入口条 夜深了/交换答案/桌球/礼物/一起听），
     `rows()` 因此返回 5 个假会话行。后果链见 list_view 的注释。
     改成：优先认 res-id `conversation_list` + 高度必须 > 屏高一半 + 行内必须有 name/time 结构。
"""
import re
import time

from core.log import get_logger
from core.paths import DEV_H

log = get_logger("eyes.chatlist")

LIST_Y_MIN = 130      # 列表可视区上界（顶部栏 0~136）
LIST_Y_MAX = 1502     # 列表可视区下界（底栏 1502~1600）

# 🔴 2026-11-08：行高阈值不再写死 110px，改成屏高比例（900x1600 下 = 110.4px）。
#   实测依据：正常会话行 135~153px（8.4%~9.6% 屏高）；
#             非会话行：Soul通知横幅 48px(3.0%)、底部残行 95px(5.9%)、末梢 7px(0.4%)。
#   阈值取 6.9% 落在 95px 与 135px 之间，既不误杀真行也不放过横幅。
ROW_MIN_H_RATIO = 0.069

# 🔴 2026-11-08：会话列表容器高度必须 > 屏高一半。
#   实测：真正的会话列表 (0,136,900,1502) 高 1366px（85% 屏高）；
#         会话页底部功能入口条 (0,1405,900,1485) 只有 80px（5% 屏高）。
LIST_MIN_H_RATIO = 0.5


def _screen_h(snap):
    """屏幕高度基准：默认 DEV_H，只有快照明显是别的分辨率时才用快照推的值。

    🔴 2026-11-08：不能直接用「快照里最大的 y2」当屏幕高度 ——
      实测有些帧（弹窗/转场/刚好没渲染底栏）最大 y2 只有 1502，
      拿它当基准会把行高阈值从 110px 拉到 104px，判据随帧漂移。
      所以：快照推出来的值跟 DEV_H 差不到 20% 就认为还是同一个分辨率，用 DEV_H；
      差得多（真换了分辨率）才采用快照值。
    """
    h = 0
    for n in snap.nodes:
        b = n.bounds
        if b[3] > h:
            h = b[3]
    if h > 0 and abs(h - DEV_H) > DEV_H * 0.2:
        return h
    return DEV_H


def _is_descendant(node, root):
    cur = node
    while cur is not None:
        if cur is root:
            return True
        cur = cur.parent
    return False


class Row(object):
    """一个会话行。

    行内红点（实测 2026-11-02）：
      FrameLayout (835,215,876,256) > ImageView(底图) > TextView '1'
    位置在行最右侧、与消息预览同一层（y 与预览行相同），不是底栏那种全局角标。
    时间 TextView 的 x 从 762 起，红点数字 x 从 835 起，用 x>=800 区分。
    """
    __slots__ = ("node", "items")

    def __init__(self, node, items):
        self.node = node
        self.items = items                      # 行内所有节点，按阅读顺序

    @staticmethod
    def _is_badge(n):
        t = n.text.strip()
        return t.isdigit() and n.bounds[0] >= 800

    @property
    def labels(self):
        return [n.label for n in self.items if n.label and not self._is_badge(n)]

    @property
    def texts(self):
        return self.labels

    @property
    def badge(self):
        """行内未读数：没有数字返回 0。"""
        for n in self.items:
            t = n.text.strip()
            if t.isdigit() and n.bounds[0] >= 800:
                return int(t)
        return 0

    @property
    def has_dot(self):
        """是否显示红点（数字角标或纯圆点）。

        🔴 2026-11-04：Soul 新版红点是**无文本的 FrameLayout**，res-id 结尾
        `unread_msg_number`（实测 text 恒空、bounds 高仅 ~6px），旧的
        「数字文本 x>=800」和「FrameLayout 高 10~60px」两条判据都失效，
        红点永远识别不出（日志「双击第3次→角标=7 红点=0」）。改为优先认 res-id。
        """
        for n in self.items:
            if "unread_msg_number" in (n.res_id or ""):
                return True
        if self.badge:
            return True
        for n in self.items:
            if n.bounds[0] >= 820 and 10 <= n.width <= 60 and 10 <= n.height <= 60:
                if (n.cls or "").endswith("FrameLayout"):
                    return True
        return False

    @property
    def blob(self):
        return " ".join(self.labels)

    @property
    def center(self):
        return self.node.center

    @property
    def nickname(self):
        """昵称：优先用 res-id，取不到再退回文本启发式。

        🔴 2026-11-08 修复：原实现「排除时间/噪声后第一个 1~20 字文本」有两个问题：
          ① `_looks_time` 误判时会把真实昵称跳过（实测 9/10 行受影响）；
          ② 即使时间判对了，一旦昵称被跳过，就会**退化成消息预览**
             （实测 `纸间藏月` 那行拿到的是「既然没啥聊的，那我先歇会儿」）。
        现在三级：
          ① **res-id `id/name`**（最稳，实测会话行里 name 节点恒存在、depth 31）；
          ② 文本启发式，但**排除 `id/message` 节点**（消息预览永远不能当昵称）；
          ③ ②里优先「含中文且 >=3 字」的候选，再退回第一个短文本
             （覆盖 `464039799`、`XHL` 这种纯数字/英文昵称）。
        """
        # ① res-id 最稳
        for n in self.items:
            rid = n.res_id or ""
            if rid.endswith("/name"):
                t = (n.text or "").strip()
                if t:
                    return t[:20]

        # ② 文本启发式（排除消息预览节点）
        cands = []
        for n in self.items:
            t = (n.text or "").strip()
            if not t or t in ("头像", "匹配") or _looks_time(t):
                continue
            if (n.res_id or "").endswith("/message"):
                continue          # 消息预览绝不能当昵称
            if 1 <= len(t) <= 20:
                cands.append(t)
        # ③ 中文昵称优先，再退回原口径
        for t in cands:
            if len(t) >= 3 and _has_cjk(t):
                return t
        return cands[0] if cands else ""

    def match(self, text, min_len=6):
        """行内是否包含给定文本（用于用数据库的 lastMsgText 定位会话）。

        UI 里的预览会被截断，所以用「前缀包含」：只要行内有文本是 needle 的前缀或包含关系。
        """
        if not text:
            return False
        needle = text.strip()
        for t in self.labels:
            t = t.strip()
            if not t:
                continue
            if t in needle or needle[:len(t)] == t:
                if len(t) >= min_len:
                    return True
        return False

    def __repr__(self):
        return "<Row y=%d %r>" % (self.center[1], self.blob[:40])


# 🔴 2026-11-08：时间判据改成穷举正向匹配 + 全文锚定（^...$）。
#
#   改前（错误做法）：`len(t) <= 7 and (":" in t or "月" in t or "日" in t)`
#     —— 用「含某个字」反推时间，把大量真实昵称吃掉。实测误判：
#        「纸间藏月」(4字) / 「漫赏星河月」(5) / 「月眠青山里」(5)
#        / 「十一月的雨」(5) / 「明日香」(3)  → 全部返回 True
#     后果：`nickname` 跳过它们，9/10 行退化成消息预览；
#           进而 `find_row` 的文本匹配、`clear.dots()` 的黑名单判断全部跑偏。
#
#   改后：只认下面这些 Soul 列表里真实出现的时间形态，且必须整串匹配。
_TIME_RES = [
    re.compile(r"^\d{1,2}:\d{2}$"),                      # 00:38
    re.compile(r"^\d{1,2}:\d{2}:\d{2}$"),                # 00:38:12
    re.compile(r"^(昨天|前天|今天|刚刚)$"),               # 昨天 / 前天 / 今天 / 刚刚
    re.compile(r"^星期[一二三四五六日天]$"),               # 星期三
    re.compile(r"^周[一二三四五六日天]$"),                 # 周三
    re.compile(r"^\d{1,2}月\d{1,2}日$"),                  # 10月28日
    re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$"),           # 2026年10月28日
    re.compile(r"^\d{1,2}/\d{1,2}$"),                     # 10/28
    re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"),               # 2026/10/28
    re.compile(r"^\d{1,2}-\d{1,2}$"),                     # 10-28
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"),               # 2026-10-28
    re.compile(r"^\d{1,3}分钟前$"),                        # 5分钟前
    re.compile(r"^\d{1,3}小时前$"),                        # 3小时前
    re.compile(r"^\d{1,2}天前$"),                          # 2天前
]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_cjk(t):
    """文本里是否含中日韩统一表意文字（用来判「这是中文昵称」）。"""
    return bool(_CJK_RE.search(t or ""))


def _looks_time(t):
    """这段文本是不是列表里的时间戳。

    🔴 2026-11-08 重写。改前是「len<=7 且含 :/月/日」，实测把
      「纸间藏月」「漫赏星河月」「月眠青山里」「十一月的雨」「明日香」
      全部判成时间戳（真实日志里 `纸间藏月` 那一行的 nickname 因此退化成
      消息预览「既然没啥聊的，那我先歇会儿」）。
    现在只做**正向穷举 + 全文锚定**：命中 _TIME_RES 任一才算是时间。
    """
    t = (t or "").strip()
    if not t or len(t) > 16:
        return False
    for pat in _TIME_RES:
        if pat.match(t):
            return True
    return False


def _row_has_content(items):
    """行内是否有「会话行」该有的结构。

    🔴 2026-11-08：专门挡 Soul通知横幅这类假行。
      实测横幅行（`_tmp_screen5.py`）的节点只有：
        · ImageView  res=id/avatar  desc=头像
        · TextView   res=id/message text=[夜深了]
      注意它**也带 `message` res-id** —— 所以「有 message 就算会话行」是错的，
      只靠行高过滤也不够（横幅在部分帧里能到 135px）。
      真会话行的强特征是**同时有 `id/name` 和 `id/time`**（实测每一行都有）。
      所以这里要求：
        ① 有 `/name` 或 `/time` res-id → 认定是会话行；
        ② 没有 res-id 的极老版本兜底：行内文本节点 >= 3 个（横幅只有 1 个）。
    """
    labeled = []
    for n in items:
        rid = n.res_id or ""
        if rid.endswith("/name") or rid.endswith("/time"):
            return True
        t = (n.text or n.desc or "").strip()
        if t and t != "头像":
            labeled.append(t)
    return len(labeled) >= 3


def _kids_of(snap, n):
    return [c for c in snap.nodes if c.parent is n]


def _descend_to_rows(snap, root):
    """把 list_view 下钻到**真正的行容器**，返回它的直接子节点列表。

    🔴🔴 2026-11-08 01:28 生产事故修复（上线 10 分钟打死生产，必须先记这一条）：
      `list_view()` 优先返回 res-id 命中的节点，实测它在 900x1600 上的真实层级是：
          conversation_list FrameLayout (0,136,900,1502)     ← 外壳 1/4
            └ ViewGroup        (0,136,900,1502)              ← 外壳 2/4
              └ RelativeLayout (0,136,900,1502)              ← 外壳 3/4
                └ RecyclerView (0,136,900,1502) scrollable   ← 外壳 4/4
                  └ 9 个 153px 高的行 ← **这才是行容器**
      `rows()` 原来直接对 `list_view` 取 `_kids_of`，于是**只拿到 1 个"行"
      = 整个 ViewGroup**，height=1366 过大不会被行高闸拦下，`_row_has_content`
      也在它内部找到了 `/name` → 判定为 1 个合法会话行（昵称「七秒钟的记忆」）。
      结果：`len(rows(snap)) == 1 < 2` → `page.detect()` 判 **unknown**
      → nav 每轮 back/am start/重启 App 死循环 → 设备被丢在桌面
      → daemon 每轮 blocked，8 分钟零回复。

    修法：**一路下钻到「直接子节点 >= 2」的那一层**。判据只看「是不是单一孩子」，
    不再额外要求 scrollable/same_box —— 因为外壳链上 3 层都是普通 ViewGroup/
    RelativeLayout（不可滚动、但 bounds 完全一致），旧判据在这里 break 掉了，
    导致下钻形同虚设。层数上限 6 层足够覆盖实测的 4 层，且能防环。
    """
    node = root
    for _ in range(6):
        kids = _kids_of(snap, node)
        if len(kids) >= 2:
            return kids
        if len(kids) != 1:
            break                            # 0 个孩子：到底了
        node = kids[0]                       # 只有一个孩子 → 继续下钻
    return _kids_of(snap, node)


def _has_row_structure(snap, rv):
    """容器的直接子节点里，至少有 2 个带 name/time 结构（会话行的强特征）。

    🔴 2026-11-08：用来把「会话页的消息列表 / 底部功能入口条」和
      「真正的会话列表」区分开 —— 消息气泡没有 id/name、id/time 这些 res-id。
    """
    hit = 0
    for c in _descend_to_rows(snap, rv):
        for d in snap.nodes:
            if not _is_descendant(d, c):
                continue
            rid = d.res_id or ""
            if rid.endswith("/name") or rid.endswith("/time"):
                hit += 1
                break
        if hit >= 2:
            return True
    return False


def list_view(snap):
    """找到会话列表的 RecyclerView。返回 Node 或 None。**签名保持不变**。

    🔴 2026-11-08 修复（原实现只有「scrollable + cls 含 RecyclerView + 子节点>=2」）：
      实测在**会话页**（page=chat）会抓到 `RecyclerView (0,1405,900,1485)`，
      也就是输入框上方的功能入口条（夜深了/交换答案/桌球/礼物/一起听），
      `rows()` 于是返回 5 个假会话行。后果链：
        ① `clear.dots()`(clear.py:50-61) 恒为空 → 误判「没有红点」→ 清红点空转；
        ② `page.detect()`(page.py:53-59) 拿 `list_view + rows>=2` 当 chatlist 强判据
           → **chat 页可能被判成 chatlist → 直接点「桌球」「礼物」**
           （这是「瞎操作」体感的一大来源）。

      现在的三条硬约束（每个候选都要过）：
        ① 高度必须 > 屏高的一半（真列表 1366px / 85%，功能入口条只有 80px / 5%）；
        ② 直接子节点 >= 2（原约束，保留）；
        ③ 优先认稳定 res-id `conversation_list`；没有它才走通用 RecyclerView 扫描，
           且通用路径额外要求「子节点里有 >=2 个带 name/time 结构」。

    ⚠️ 调用点（page.py:56、clear.py、pendingq.py、act.py）都按 `list_view(snap)` 单参调用，
       签名绝不能改。
    """
    h_screen = _screen_h(snap)
    min_h = h_screen * LIST_MIN_H_RATIO

    # ---- ① 优先：稳定 res-id conversation_list（实测 900x1600 下 bounds=(0,136,900,1502)）----
    #    res-id 本身就是强证据，这里只要求「高度够 + 至少 1 个子节点」；
    #    通用路径（②）仍要求 >=2 个，那是原逻辑。
    for n in snap.nodes:
        if not n.visible:
            continue
        if "conversation_list" not in (n.res_id or ""):
            continue
        if n.height < min_h:
            continue
        if len(_kids_of(snap, n)) >= 1:
            return n

    # ---- ② 兜底：通用 RecyclerView 扫描（原逻辑 + 高度/结构双校验）----
    best = None
    best_kids = 0
    for n in snap.nodes:
        if not n.scrollable or not n.visible:
            continue
        if "RecyclerView" not in (n.cls or ""):
            continue
        # 原「上界」过滤：y1 < LIST_Y_MIN 的一律跳过（排除 (0,0,900,1600) 那个全屏外壳）
        if n.bounds[1] < LIST_Y_MIN:
            continue
        # 新增：容器必须够高，否则是功能入口条/底栏残条
        if n.height < min_h:
            continue
        kids = _kids_of(snap, n)
        if len(kids) < 2:
            continue
        # 新增：必须长得像会话列表（子节点带 name/time 结构）
        if not _has_row_structure(snap, n):
            continue
        if len(kids) > best_kids:
            best, best_kids = n, len(kids)
    return best


def rows(snap):
    """返回当前可见的会话行（从上到下）。**签名保持不变**。

    🔴 2026-11-08 修复：原实现对 RecyclerView 的每个直接子节点无条件当会话行，
      实测混进来两类垃圾：
        · Soul通知横幅行 `(0,136,900,184)` 高 **48px**，内容只有 `头像 [夜深了]`；
        · 列表底部被底栏裁掉的残行，高 **95px**。
      它们被当成会话行后，`find_row` 会拿横幅文案去匹配（永远匹配不上真会话），
      `first_dot_row` 也可能把横幅当候选点进去。

      现在加两道闸：
        ① 行高 >= 屏高 * ROW_MIN_H_RATIO（1600px 屏 → 110px，真行 135~153px 全过）；
        ② 行内必须有 name/time/message 结构或 >=2 个文本节点（挡只有头像+短文本的横幅）。
    """
    rv = list_view(snap)
    if rv is None:
        return []
    h_screen = _screen_h(snap)
    min_row_h = h_screen * ROW_MIN_H_RATIO

    out = []
    for c in _descend_to_rows(snap, rv):
        if c.height < min_row_h:
            continue
        items = [n for n in snap.nodes if _is_descendant(n, c)]
        if not _row_has_content(items):
            continue
        items.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
        out.append(Row(c, items))
    out.sort(key=lambda r: r.node.bounds[1])
    _log_rows(out)
    return out


# 🔴 2026-11-10（P0 日志缺陷修复）：本模块 430 行、`log` 建了却**一次都没打过**
#   → `logs/eyes.chatlist.log` 长期 0 字节。代价很具体：夜间复盘时
#   「反查不到 sid 368 次」「id_mismatch_giveup 623 次」全都没法定位到屏幕这一层，
#   因为**唯一能证明「列表上到底有没有这个人」的证据从来没被记下来**。
#   这里补一条摘要日志，并做内容去重：同一屏反复解析只打一次，避免刷爆文件。
_LAST_ROWS_SIG = {"sig": None, "ts": 0.0}


def _log_rows(rows_):
    """把本次解析出的会话行打成一行摘要（内容不变则跳过）。

    只在 DEBUG 级别不可用时也应该能看 —— 这里固定用 info，但做签名去重，
    所以每屏内容变化最多一条，稳态下一轮（多屏）也就几条。
    """
    try:
        if not rows_:
            sig = "<empty>"
        else:
            sig = "|".join((r.nickname or "?")[:10] for r in rows_)
        now = time.time()
        if sig == _LAST_ROWS_SIG["sig"] and now - _LAST_ROWS_SIG["ts"] < 20.0:
            return
        _LAST_ROWS_SIG["sig"] = sig
        _LAST_ROWS_SIG["ts"] = now
        if not rows_:
            log.info("列表解析：0 行（没认出任何会话行）")
            return
        _head = " / ".join(
            "%s%s:%s" % (r.nickname or "?", "*" if r.has_dot else "", (r.blob or "")[:12])
            for r in rows_[:6])
        log.info("列表解析：%d 行 顶=%d 底=%d  前几行=[%s]",
                 len(rows_), rows_[0].center[1], rows_[-1].center[1], _head)
    except Exception as e:
        log.warning("列表解析日志异常（不影响主流程）: %r", e)


def find_row(snap, text, min_len=6):
    """按文本（通常是数据库里的 lastMsgText）找行。"""
    for r in rows(snap):
        if r.match(text, min_len=min_len):
            return r
    return None
