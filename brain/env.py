# -*- coding: utf-8 -*-
"""环境（时间/天气/我的状态）—— 由 2.1 soul_env.py 移植，行为不变。

移植只改一处：去掉 `import soul_path`（那是 2.1 的 sys.path 引导，
1.0 的包结构不需要它）。其余逻辑、注释里的历史教训全部保留。
"""
# -*- coding: utf-8 -*-
"""soul_env.py — 回复用的「当前环境」素材（时间 / 季节 / 天气）

用户 2026-10-06 定稿的回复优先级（从高到低）：
    ① 爽      —— 怎么回能让她读起来爽、想接
    ② 我的目的 —— 推进关系（让她多投入/主动/靠近）
    ③ 当下感  —— 结合当前时间/环境/天气（**次要背景**，是佐料不是主菜）

本模块只负责第 ③ 层的**事实素材**：给出一句话的「现在是什么时候、什么天」，
供提示词引用，让回复有「此时此地」的味道，而不是模板车轱辘话。

设计原则
--------
  · 时间 / 星期 / 时段 / 季节：纯本地系统时钟 → **永远可用**，零依赖。
  · 天气：open-meteo 免费接口（无需 key）→ **带缓存 + fail-open**：
      - 成功：缓存 30 分钟；失败：退避 5 分钟再试。
      - 拿不到就只给时间，**绝不因为网络问题让回复链路报错或明显变慢**
        （超时 4s，且绝大多数时候命中缓存，不产生网络调用）。
  · 地理定位固定「重庆綦江」（两个账号一致），不读人设模块、不做账号切换。
  · 只 import 标准库，不 import 任何业务模块，避免循环依赖。
"""
import json
import time
import urllib.request
from datetime import datetime

# ── 地理位置（用户 2026-10-06 定稿：**两个账号都在重庆市綦江区**）────
#   两账号共用同一份人设（江华 / 重庆綦江，2026-11-05 用户口径），
#   真实定位与人设自称一致；1.0 不再有按账号切身份那套 2.1 遗留设定。
LOC_NAME = "重庆綦江"
LOC_LAT, LOC_LON = 29.0284, 106.6514

# ── 天气缓存 ───────────────────────────────────────────────────────
_WX = {"txt": "", "ts": 0.0, "fail": 0.0}
_WX_TTL = 1800.0        # 成功缓存 30 分钟
_WX_FAIL_TTL = 300.0    # 失败后 5 分钟内不再重试（退避）

# WMO weather_code → 中文
_WCODE = {
    0: "晴", 1: "大致晴", 2: "多云", 3: "阴",
    45: "有雾", 48: "冻雾",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨", 99: "雷阵雨",
}


def _city():
    """当前定位（两个账号都在重庆綦江，与实例号无关）。"""
    return LOC_NAME


def _weather(city):
    """一句话天气（如「阴 18℃」）；拿不到返回 ''。带缓存 + 退避。"""
    now = time.time()
    if _WX["txt"] and now - _WX["ts"] < _WX_TTL:
        return _WX["txt"]
    if now - _WX["fail"] < _WX_FAIL_TTL:
        return ""                      # 刚失败过 → 退避，不重试
    lat, lon = LOC_LAT, LOC_LON
    url = ("https://api.open-meteo.com/v1/forecast"
           "?latitude=%.4f&longitude=%.4f"
           "&current=temperature_2m,weather_code&timezone=Asia%%2FShanghai"
           % (lat, lon))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "soul-env/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read().decode("utf-8"))
        c = d.get("current") or {}
        bits = []
        desc = _WCODE.get(int(c.get("weather_code", -1)))
        if desc:
            bits.append(desc)
        t = c.get("temperature_2m")
        if isinstance(t, (int, float)):
            bits.append("%.0f℃" % t)
        txt = " ".join(bits)
        if txt:
            _WX.update(txt=txt, ts=now)
        return txt
    except Exception:
        _WX["fail"] = now
        return ""


def _part(h):
    """时段（口语）。"""
    if h < 5:
        return "凌晨"
    if h < 8:
        return "清早"
    if h < 11:
        return "上午"
    if h < 13:
        return "中午"
    if h < 17:
        return "下午"
    if h < 19:
        return "傍晚"
    if h < 23:
        return "晚上"
    return "深夜"


def _season(m):
    if 3 <= m <= 5:
        return "春"
    if 6 <= m <= 8:
        return "夏"
    if 9 <= m <= 11:
        return "秋"
    return "冬"


# ⭐ 2026-10-22 用户口径：「生成的时候要参考当前我位置家里还是厂里、上班还是下班」。
#   事实来源（本人 2026-10-21 逐条确认）：
#     · 重庆新视通（綦江桥河园区）一线普工，LED 显示屏
#     · **单数月份白班、双数月份夜班，12 小时两班倒**
#     · 住厂里宿舍，很少回家
#   班次时段按 白班 08:00-20:00 / 夜班 20:00-次日 08:00 推算。
#   手动写死（比如今天休息/回家了）：设环境变量 SOUL_STATUS_OVERRIDE=今天休息，在家里
#   整段关闭：SOUL_STATUS=0
# 🔴 2026-11-12（GL-11 标注，不删）：以下三个符号为**死代码**（无任何调用方）。
#   _SHIFT_WHITE/_SHIFT_NIGHT 是旧「两班倒」时段，_day_ctx 是旧节假日/购物节口径；
#   2026-10-29 起工作改为开网店后已无固定班次，_day_ctx 的节假日/调休/购物节
#   逻辑不再被任何路径使用。保留定义不删（避免误删），标记 deprecated 供后续清理。
_SHIFT_WHITE = (8, 20)     # 白班 08:00 - 20:00
_SHIFT_NIGHT = (20, 8)     # 夜班 20:00 - 次日 08:00

# ⭐ 2026-10-22 用户口径：「国家节假日不上班，还有购物节等等」。
#   国庆/春节这类法定节假日 → 不上班（在宿舍，偶尔回三江家里）。
#   购物节 → 只做「今天是什么日子」的背景提醒，方便接她的话题（双11/618/520…）。
#   放假安排按国务院办公厅 2026 年通知；哪天不对直接改这里，或临时用 SOUL_STATUS_OVERRIDE 顶掉。
_HOLIDAYS_2026 = [
    ((1, 1), (1, 3), "元旦"),
    ((2, 15), (2, 21), "春节"),
    ((4, 4), (4, 6), "清明节"),
    ((5, 1), (5, 5), "劳动节"),
    ((6, 19), (6, 21), "端午节"),
    ((9, 25), (9, 27), "中秋节"),
    ((10, 1), (10, 7), "国庆节"),
]
_MAKEUP_2026 = [           # 调休补班日（要上班）
    (1, 4), (2, 14), (2, 28), (5, 9), (9, 28), (10, 10),
]
_SHOP_FEST = [             # 购物节（起始日, 结束日, 名字）
    ((1, 10), (1, 25), "年货节"),
    ((2, 13), (2, 14), "情人节"),
    ((3, 7), (3, 8), "女王节"),
    ((5, 19), (5, 20), "520"),
    ((6, 17), (6, 18), "618"),
    ((8, 18), (8, 19), "七夕"),
    ((9, 8), (9, 9), "99划算节"),
    ((11, 9), (11, 12), "双11"),
    ((12, 11), (12, 12), "双12"),
    ((12, 23), (12, 25), "圣诞/双旦"),
]


def _doy(m, d):
    """(月,日) → 一年中的第几天（用 2001 非闰年，避开 2/29）。"""
    return datetime(2001, m, d).timetuple().tm_yday


def _in_range(md, a, b):
    x, lo, hi = _doy(*md), _doy(*a), _doy(*b)
    return lo <= x <= hi


def _day_ctx(n):
    """返回 (是否法定节假日, 节假日名, 是否调休补班, 购物节名或'')。

    🔴 2026-11-12（GL-11）：死代码，无任何调用方（旧节假日/购物节口径），
    保留定义不删，标记 deprecated 供后续清理。
    """
    y = n.year
    hol = ""
    if y == 2026:
        for a, b, nm in _HOLIDAYS_2026:
            if _in_range((n.month, n.day), a, b):
                hol = nm
                break
    makeup = bool(y == 2026 and (n.month, n.day) in _MAKEUP_2026)
    shop = ""
    for a, b, nm in _SHOP_FEST:
        if _in_range((n.month, n.day), a, b):
            shop = nm
            break
    return bool(hol), hol, makeup, shop


# 🔵 2026-10-29 工作改成「开网店」（闲鱼/抖店）：
#   原来按「单数月份白班、双数月份夜班」推算「在厂里车间 / 在厂里宿舍」——没有固定班次了，整段作废。
#   新口径只给粗事实（在家 / 在忙发货），不给具体物品，避免又变成「我在弄订单」的行程报备。
#   注：`_SHIFT_WHITE/_SHIFT_NIGHT/_day_ctx` 保留定义（无其他调用方），便于以后要恢复班次时改回。
def shift_line():
    """返回「我现在的状态」一行；关闭/异常返回 ''。"""
    try:
        import os
        if os.environ.get("SOUL_STATUS", "1") == "0":
            return ""
        ov = (os.environ.get("SOUL_STATUS_OVERRIDE") or "").strip()
        if ov:
            return ("【我的当前状态·真实，据此回答「在干嘛/在哪/忙不忙」，别答反；"
                    "她没问就别主动提，更不要把打包/发货/快递当每轮的画面】%s" % ov)
        n = datetime.now()
        h = n.hour
        if 2 <= h < 10:
            _where = "在三江家里，还没起或者刚起"
        elif 10 <= h < 18:
            _where = "在三江家里守着网店，等下单、处理售后"
        elif 18 <= h < 22:
            _where = "可能去綦江发快递了，或者在家弄订单"
        else:
            _where = "在三江家里，闲下来了"
        return ("【我的当前状态·真实，据此回答「在干嘛/在哪/忙不忙」，别答反；"
                "她没问就别主动提，更不要把打包/发货/快递/订单 当每轮的画面（24h 只许用一次）】%s"
                % _where)
    except Exception:
        return ""


def now_bg():
    """一句话「当前环境」：`【现在】10月6日 周二 凌晨2点 · 秋季 · 重庆 阴 18℃`
    后面再跟一行「我的当前状态」（在家 / 在忙发货）。

    异常时至少给出时间；再不行返回 ''（调用方照常走，不影响回复）。
    """
    try:
        n = datetime.now()
        wd = "周" + "一二三四五六日"[n.weekday()]
        when = "%d月%d日 %s %s%d点" % (n.month, n.day, wd, _part(n.hour), n.hour)
        city = _city()
        wx = _weather(city)
        # 🔴 2026-10-26 治「说胡话」：数据源是 open-meteo 的网格值（≈城市级预报），
        #   不是她/我头顶的实况。实测 10-26 02:00 此处输出「毛毛雨 21℃」→ 模型照直说成
        #   「刚看见窗外飘毛毛雨」→ 她当场否「没下雨 / 哪有」→「你发错人了吧哥」。
        #   根因不是模型幻觉，是**输入被当成了实况**。这里显式标「预报」+ 写明禁止具体化。
        # 🔴 2026-11-03（用户口径）：第 1 段要明确给出「时间 / 天气 / 地理位置」三样。
        #   原来城市混在【现在】行尾（"… · 秋季 · 重庆綦江"），模型不一定把它当"我在哪"用；
        #   现在拆成独立一行，并写明「她在哪以档案为准，别猜、别提距离」。
        line = "【现在】%s · %s季" % (when, _season(n.month))
        line += ("\n【地理位置】我在 %s（这是我这边的城市；她在哪以档案里她说过的话 / "
                 "主页 IP 为准，没说过就别猜，也别提距离）" % city)
        if wx:
            line += ("\n【天气·只是城市级预报，不是你眼前的实况】%s 预报 %s"
                     "（⚠️ 禁止说成「窗外/外面/我这儿正在下雨（飘雨）」；她没问就别提；"
                     "她问也只能「预报说有点雨」，不写画面）" % (city, wx))
        _s = shift_line()
        return (line + "\n" + _s) if _s else line
    except Exception:
        try:
            return "【现在】%s" % datetime.now().strftime("%m月%d日 %H点")
        except Exception:
            return ""


if __name__ == "__main__":
    try:
        import io
        import sys
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    print("城市    =", _city())
    print("天气    =", repr(_weather(_city())))
    print("now_bg  =", now_bg())
