# -*- coding: utf-8 -*-
"""UI 树：读取 / 解析 / 查询 / 指纹。

只做「读到什么」，不做任何动作。
实测：u2 常驻通道 dump 一次 104KB / 0.21s，所以缓存 TTL 可以很短（默认 0），
不再需要旧架构那种 6s TTL 来省时间。
"""
import hashlib
import os
import re
import threading
import time

from core.log import get_logger

log = get_logger("eyes.uitree")

# dump_hierarchy 的超时（秒）。正常 0.8~6s（随树大小）；超过就是设备无响应。
DUMP_TIMEOUT = float(os.environ.get("SOUL_DUMP_TIMEOUT", "20") or 20)

# 🔴 2026-11-08（提速·实测修正）：dump 参数收紧**只保留 root_in_active**。
#   实测（副机 21:10 同一页面）：
#     max_depth=None → 185~210 节点，page=planet ✅（p50 0.13s / max 2.55s）
#     max_depth=50   → 155 节点，page=planet ✅
#     max_depth=30   → **8 节点**，page=unknown ❌（Soul 的内容层级比 30 深得多）
#   差点又一次「只 py_compile 不实测」把生产打死：深度截断会让页面识别直接失明。
#   所以默认**不限制深度**（=0），只开 root_in_active（限定当前活动窗口，去掉多窗口噪声）。
#   要试更激进的深度，用 SOUL_DUMP_DEPTH 显式开启并先跑 _depth.py 验证节点数。
_DUMP_DEPTH = int(os.environ.get("SOUL_DUMP_DEPTH", "0") or 0) or None


def _dump_timeout(d, timeout=None):
    """带超时的 dump_hierarchy。

    🔴 2026-11-05：u2 的 HTTP 请求**没有超时**。设备一次无响应（MuMu 卡住 /
    server 掉线），daemon 就会永久挂起在 socket read 上 —— 实测两次：
    07:48 走 search、07:50 走 find_row，每次都要等看门狗 15 分钟阶段闸。
    这里用 daemon 线程 + join 兜住：超时就抛，让上层 reset/跳过，
    绝不把整条链路拖死（必回链路最后一环不能被一个 dump 卡住）。
    """
    timeout = DUMP_TIMEOUT if timeout is None else timeout
    box = {}

    def _run():
        try:
            box["xml"] = d.dump_hierarchy(compressed=False, max_depth=_DUMP_DEPTH,
                                          root_in_active=True)
        except Exception as e:            # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError("dump_hierarchy 超过 %.0fs（设备无响应）" % timeout)
    if "err" in box:
        raise box["err"]
    return box.get("xml") or ""

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# 底栏 tab 的 resource-id（实测 2026-11-02；2026-11-08 随 App 改版补齐）
# 为什么不能只靠文本：底栏有未读时文本会变成「聊天 5条消息未读」，
# 日志里 17 次「tap_tab '聊天' 未命中」全是这个原因；只有 res 是稳定的。
# 🔴 2026-11-08 实测设备当前 res：tab_planet / tvSquare / main_tab_msg_text / meTextView，
#    旧表里的 main_tab_planet / main_tab_square / main_tab_msg / main_tab_me 已经全部失效，
#    一直靠「文本兜底」在跑（文案一变就点不中）。这里两套都留着，按顺序命中。
TAB_RES = {
    "星球": ("tab_planet", "main_tab_planet"),
    "广场": ("tvSquare", "main_tab_square"),
    "聊天": ("main_tab_msg_text", "main_tab_msg"),
    "自己": ("meTextView", "main_tab_me"),
}


class Node(object):
    """一个 UI 节点。属性名对齐 uiautomator 的 XML。"""
    __slots__ = ("text", "desc", "res_id", "cls", "pkg", "bounds",
                 "clickable", "enabled", "selected", "scrollable", "depth", "parent")

    def __init__(self, text="", desc="", res_id="", cls="", pkg="", bounds=(0, 0, 0, 0),
                 clickable=False, enabled=True, selected=False, scrollable=False,
                 depth=0, parent=None):
        self.text = text
        self.desc = desc
        self.res_id = res_id
        self.cls = cls
        self.pkg = pkg
        self.bounds = bounds
        self.clickable = clickable
        self.enabled = enabled
        self.selected = selected
        self.scrollable = scrollable
        self.depth = depth
        self.parent = parent

    # ---- 几何 ----
    @property
    def center(self):
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def width(self):
        return max(0, self.bounds[2] - self.bounds[0])

    @property
    def height(self):
        return max(0, self.bounds[3] - self.bounds[1])

    @property
    def visible(self):
        return self.width > 0 and self.height > 0

    def contains(self, x, y):
        x1, y1, x2, y2 = self.bounds
        return x1 <= x <= x2 and y1 <= y <= y2

    # ---- 展示 ----
    @property
    def label(self):
        return (self.text or self.desc or "").strip()

    def __repr__(self):
        return "<Node %r cls=%s b=%s click=%s>" % (
            self.label[:20], (self.cls or "").split(".")[-1], self.bounds, self.clickable)


class Snapshot(object):
    """一次 dump 的完整结果。"""

    def __init__(self, xml, nodes, ts=None):
        self.xml = xml
        self.nodes = nodes
        self.ts = ts or time.time()

    # ---- 查询 ----
    def find(self, text=None, text_contains=None, desc=None, res=None, cls=None,
             clickable=None, visible_only=True, limit=0):
        """按属性过滤，返回 Node 列表（文档顺序）。"""
        out = []
        for n in self.nodes:
            if visible_only and not n.visible:
                continue
            if text is not None and n.text.strip() != text:
                continue
            if text_contains and text_contains not in n.text:
                continue
            if desc is not None and n.desc.strip() != desc:
                continue
            if res and res not in n.res_id:
                continue
            if cls and cls not in n.cls:
                continue
            if clickable is not None and n.clickable != clickable:
                continue
            out.append(n)
            if limit and len(out) >= limit:
                break
        return out

    def find_one(self, **kw):
        r = self.find(limit=1, **kw)
        return r[0] if r else None

    def hit(self, **kw):
        """返回真正可点击的目标。三级策略，按可靠性排序：

        1. 节点自己 clickable -> 用它
        2. 向上找 clickable 祖先 -> 用它
        3. **找包含该点的最小 clickable 节点** -> 用它

        第 3 条是 Soul 底栏的必需品：底栏的 TextView("聊天") 和可点击的
        View(498,1502,699,1600) 是**兄弟节点**，父链全是 clickable=false，
        只靠上溯永远找不到，必须按几何包含关系反查。
        """
        n = self.find_one(**kw)
        if n is None:
            return None
        if n.clickable and n.visible:
            return n
        cur = n.parent
        while cur is not None:
            if cur.clickable and cur.visible:
                return cur
            cur = cur.parent
        cands = [x for x in self.nodes
                 if x.clickable and x.visible and x.contains(*n.center)]
        if cands:
            cands.sort(key=lambda x: x.width * x.height)
            return cands[0]
        return n if n.visible else None

    def tab(self, name, y_min=1500):
        """只认底栏的 tab（y >= y_min），返回可点击容器。

        🔴 2026-11-02 日志实测：底栏有未读时，**文本会变成「聊天 5条消息未读」**
          （res 仍是 main_tab_msg），原来要求 `text == '聊天'` 直接匹配不到 ——
          日志里 17 次「tap_tab '聊天' 未命中」全是这个原因。
        现在的判据顺序：
          ① resource-id 精确匹配（最稳，不受未读文案影响）
          ② 文本完全等于
          ③ 文本以它开头（「聊天 5条消息未读」）
        不能用 hit(text="聊天")：会话列表页顶部还有「聊天 / 通讯录」切换标签。
        """
        # ① resource-id
        rids = TAB_RES.get(name) or ()
        if isinstance(rids, str):
            rids = (rids,)
        for rid in rids:
            for n in self.nodes:
                if n.visible and n.bounds[1] >= y_min and rid in (n.res_id or ""):
                    n2 = self._clickable_of(n)
                    if n2 is not None:
                        return n2

        # ② 完全匹配 / ③ 前缀匹配（都限定在底栏区域）
        cands = [n for n in self.nodes
                 if n.visible and n.bounds[1] >= y_min
                 and (n.text.strip() == name or n.text.strip().startswith(name))]
        if not cands:
            return None
        cands.sort(key=lambda n: (0 if n.text.strip() == name else 1, n.bounds[0]))
        return self._clickable_of(cands[0])

    def _clickable_of(self, n):
        """从节点向上/向外找可点击容器。"""
        if n.clickable and n.visible:
            return n
        cur = n.parent
        while cur is not None:
            if cur.clickable and cur.visible:
                return cur
            cur = cur.parent
        over = [x for x in self.nodes
                if x.clickable and x.visible and x.contains(*n.center)]
        if over:
            over.sort(key=lambda x: x.width * x.height)
            return over[0]
        return n

    def tabs(self, y_min=1500):
        """底栏所有 tab：{文本: Node}。"""
        out = {}
        for n in self.nodes:
            if not n.visible or n.bounds[1] < y_min:
                continue
            t = n.text.strip()
            if t and t not in out:
                out[t] = self.tab(t, y_min=y_min)
        return out

    def texts(self):
        """所有可见非空文本，按 y 再 x 排序（阅读顺序）。"""
        items = [n for n in self.nodes if n.visible and n.label]
        items.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
        return [n.label for n in items]

    def labeled(self):
        """所有可见带文本/描述的节点（保留几何信息）。"""
        items = [n for n in self.nodes if n.visible and (n.label or n.clickable)]
        items.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
        return items

    # ---- 指纹 ----
    def signature(self):
        """页面指纹：忽略纯文本内容变化的位置，取 结构+文本 的哈希。

        用途：点击/滑动后判断页面是否真的变了。
        注意不要用整段 xml —— 动画中间帧会抖动，导致每次都判「变了」。
        """
        parts = []
        for n in self.labeled():
            parts.append("%d|%d|%s|%s" % (n.bounds[0] // 10, n.bounds[1] // 10,
                                          (n.cls or "").split(".")[-1], n.label[:30]))
        return hashlib.md5("\n".join(parts).encode("utf-8", "ignore")).hexdigest()[:12]


def _parse_bounds(s):
    m = _BOUNDS_RE.match(s or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(x) for x in m.groups())


def parse(xml):
    """把 uiautomator XML 解析成 Snapshot。

    🔴 2026-11-08：这里原来写「用 iterparse 保守处理大文件」，**是假的** ——
      实现就是 `ET.fromstring(xml)` 一次性把整棵树建出来 + 递归 walk。
      改注释而不改实现：实测 900x1600 满屏树约 200~400 个 node、XML 200~500KB，
      fromstring 解析耗时 <80ms，相对一次 dump（2~4s）可以忽略；
      真换成 iterparse 反而要自己拼父子关系和 clickable 继承，风险远大于收益。
      别再照着旧注释以为有流式解析。
    """
    import xml.etree.ElementTree as ET
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8", "ignore")
    root = ET.fromstring(xml)
    nodes = []

    def walk(el, depth, parent):
        for child in el:
            if child.tag != "node":
                continue
            a = child.attrib
            n = Node(
                text=a.get("text", ""),
                desc=a.get("content-desc", ""),
                res_id=a.get("resource-id", ""),
                cls=a.get("class", ""),
                pkg=a.get("package", ""),
                bounds=_parse_bounds(a.get("bounds", "")),
                clickable=a.get("clickable") == "true",
                enabled=a.get("enabled", "true") == "true",
                selected=a.get("selected") == "true",
                scrollable=a.get("scrollable") == "true",
                depth=depth,
                parent=parent,
            )
            nodes.append(n)
            walk(child, depth + 1, n)

    walk(root, 0, None)
    return Snapshot(xml, nodes)


class Screen(object):
    """带缓存的取树入口。一个 Screen 实例对应一次业务流程。

    🔴 2026-11-08（A2 帧复用，用户授权自主实施）：
      `ttl=0.0` 意味着**任何两次取树都要各付一次全树 dump**。实测单次
      dump p50=3.65s / p90=4.58s，而每个动作的固定开销是
        `snap()`（动作前定位）+ 动作 + `_after()` 的 `snap(force=True)`（动作后确认）
      = **2 次 dump ≈ 7.3s/动作**。日志里 `tap_tab(聊天): chatlist->chatlist`
      出现 1238 次（点了页面根本没变），每次白付一次 3.65s ≈ **75 分钟/天**。

      修法**只做「动作前读」的复用**：动作后确认（`Actor._after`）保持
      `force=True` 铁律不动 —— 用户 2026-11-02 定的「每个动作之后必须重新取树
      并确认当前页面」一个字都没改。被复用的那一帧，本来就是上一个动作
      `_after()` 刚 dump 出来的、距今 < TTL 的新鲜帧。

      🛡️ 两道守卫（缺一不可）：
        ① **动作代数**（`core.device.note_action`）：任何点击/滑动/返回/灌字都会
           让代数 +1。复用时代数变了 = 中间发生过动作 = 这一帧一定过期。
           它不依赖 Activity，能兜住「同一 Activity 内翻页/滚动/弹窗」——
           这类变化 Activity 根本看不出来（主框架切 tab 时 Activity 恒为
           MainActivity，实测 10/10）。
        ② **Activity**：dump 时记下 `mCurrentFocus`，复用时花 0.07s 复核，
           变了就作废（兜住「App 被切走 / 进出会话」）。
           ⚠️ 只用它做「作废」这一侧，**绝不**用它推断「页面没变」。

      ⚠️ 例外（必须显式 force=True）：**等异步加载**的轮询。屏幕会自己变
        （转圈 → 出结果、消息陆续到），中间没有任何动作，代数守卫抓不到。
        `brain/search.py` 的搜索结果轮询、`match.py` 的匹配等待、
        `hands/input.py` 的发送后校验都属于这类，已各自标了 force=True。
    """

    def __init__(self, device, ttl=0.0):
        self.dev = device
        self.ttl = ttl
        self._snap = None
        self._act = None          # 产出这一帧时的前台 Activity（ttl>0 才记录）
        self._gen = None          # 产出这一帧时的动作代数（ttl>0 才记录）

    def _activity(self):
        """当前前台 Activity 短名（拿不到返回空串，调用方按「未知」处理）。"""
        try:
            _pkg, act = self.dev.current_app()
            return act or ""
        except Exception:
            return ""

    def get(self, force=False):
        now = time.time()
        if not force and self._snap and (now - self._snap.ts) <= self.ttl:
            if self.ttl <= 0:
                return self._snap
            # 🛡️ 守卫 1（最硬）：动作代数变了 = 中间发生过点击/滑动/灌字，
            #    这一帧一定过期。它不依赖 Activity，能兜住「同一 Activity 内
            #    翻页/滚动/弹窗」这类 Activity 看不出来的变化。
            from core.device import action_gen
            if self._gen is not None and action_gen() != self._gen:
                log.debug("帧复用作废：动作代数 %s -> %s", self._gen, action_gen())
            else:
                # 🛡️ 守卫 2：Activity 变了就作废（只做「作废」，不做「没变」的推断）
                cur = self._activity()
                if not cur or not self._act or cur == self._act:
                    return self._snap
                log.info("帧复用作废：Activity %s -> %s（重取树）", self._act, cur)
        t0 = time.time()
        d = self.dev.u2()
        try:
            xml = _dump_timeout(d)
        except Exception as e:
            # u2 device 端 server 掉线（RemoteDisconnected 等）→ 重连后重试一次。
            # 不兜这一层的话，一次掉线会让整轮业务全崩。
            log.warning("dump 失败（%r）→ 重置 u2 重试", e)
            self.dev.reset_u2()
            d = self.dev.u2()
            xml = _dump_timeout(d)
        self._snap = parse(xml)
        self._snap.dump_ms = int((time.time() - t0) * 1000)
        # 记下这一帧对应的 Activity 与动作代数，供下次复用时做守卫
        if self.ttl > 0:
            self._act = self._activity()
            from core.device import action_gen
            self._gen = action_gen()
        else:
            self._act = None
            self._gen = None
        from core import device as _dev
        _dev.note_dump(self._snap.dump_ms)
        return self._snap

    def invalidate(self):
        self._snap = None
        self._act = None
        self._gen = None
