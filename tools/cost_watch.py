# -*- coding: utf-8 -*-
"""模型调用量（token）统计 + 成本估算 —— 只读日志，不碰任何调用。

新版（soul1.0）复用旧引擎出话，旧引擎在方舟调用处 `_dbg("[ark] 输入 N tok · 缓存命中 M")`
写到 `E:\\soul2.1\\uimap\\daemon\\brain.log`。本脚本解析这些行，按天聚合
prompt_tokens / cached_tokens，并用可配置单价估算费用。

🔴 已知盲区（写本脚本时实测发现，务必先读）：
  旧版 brain.log 的 `[ark]` 行**止于 2026-11-03 06:43，11-04 起没有新记录**，
  而新版 brain.reply.log 显示今天一直在「本地完成/已投队列」正常出话。
  ⇒ 新版的方舟调用 token **没被记录**（记录点断链）。本脚本会：
    · 统计 brain.log 里有的历史用量；
    · 同时扫新版 logs/ 下所有 .log 找 `[ark]` 行（探测新版是否改记到别处）；
    · 若 brain.log 停更，明确打印「记录停更」警告，而不是假装数据正常。

单价（可配置，缺省不给钱数只给 token 数）：
  SOUL_COST_PRICE_INPUT   输入价（元 / 百万 token），默认 0 表示不估算费用
  SOUL_COST_PRICE_CACHE   缓存命中价（元 / 百万 token），默认 = 输入的 1/5

跑法：
    python -X utf8 tools/cost_watch.py           # 近 7 天 token 用量 + 健康度
    python -X utf8 tools/cost_watch.py --days 14 # 近 14 天
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from collections import defaultdict

LEGACY_BRAIN_LOG = r"E:\soul2.1\uimap\daemon\brain.log"
NEW_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

# [11-03 06:25:52] [ark] 输入 2036 tok · 缓存命中 0 (0%)
_ARK_RE = re.compile(r"\[(\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\] \[ark\] 输入 (\d+) tok · 缓存命中 (\d+)")


class _Tee:
    """把 print 同时写到终端和日志文件（计划任务无控制台时靠文件留痕）。"""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def _price_in() -> float:
    try:
        return float(os.environ.get("SOUL_COST_PRICE_INPUT", "0") or 0)
    except ValueError:
        return 0.0


def _price_cache() -> float:
    try:
        return float(os.environ.get("SOUL_COST_PRICE_CACHE", "0") or 0)
    except ValueError:
        return 0.0


def scan_file(path):
    """返回 {day: {"in": N, "cache": N, "calls": N}}。"""
    agg = defaultdict(lambda: {"in": 0, "cache": 0, "calls": 0})
    try:
        with open(path, "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return agg, 0
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0
    for m in _ARK_RE.finditer(data):
        day, pin, cache = m.group(1), int(m.group(2)), int(m.group(3))
        agg[day]["in"] += pin
        agg[day]["cache"] += cache
        agg[day]["calls"] += 1
    return agg, mtime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    # 计划任务跑时无控制台，stdout 会丢 —— tee 到日志文件，事后可查
    _log_path = os.path.join(NEW_LOGS_DIR, "cost_watch.log")
    try:
        _lf = open(_log_path, "a", encoding="utf-8")
    except OSError:
        _lf = None
    if _lf is not None:
        sys.stdout = _Tee(sys.__stdout__, _lf)

    # ① 旧版 brain.log（主数据源）
    agg, mtime = scan_file(LEGACY_BRAIN_LOG)
    print("=== 方舟调用量（来源：%s）===" % LEGACY_BRAIN_LOG)
    print("文件存在: %s，最后修改: %s" % (
        os.path.exists(LEGACY_BRAIN_LOG),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)) if mtime else "无"))

    # ② 新版 logs/ 里也找 [ark]（探测记录点是否迁移）
    new_ark = 0
    for p in glob.glob(os.path.join(NEW_LOGS_DIR, "*.log")):
        a, _ = scan_file(p)
        for day, v in a.items():
            agg[day]["in"] += v["in"]
            agg[day]["cache"] += v["cache"]
            agg[day]["calls"] += v["calls"]
            new_ark += v["calls"]
    if new_ark:
        print("新版 logs/ 里也发现 %d 条 [ark] 记录（记录点已迁移到新版日志）" % new_ark)

    # ③ 健康度：判断「最新 [ark] 记录的日期」是否落后于今天。
    #   不能只看 mtime —— brain.log 还会被非 [ark] 的 _dbg（本地画像/开场白等）写入，
    #   mtime 永远新鲜；只有 [ark] 行停了才说明「云端方舟调用没记账」。
    if mtime:
        today = time.strftime("%m-%d")
        latest_ark_day = max(agg.keys()) if agg else ""
        mtime_fresh = (time.time() - mtime) < 3600
        if latest_ark_day and latest_ark_day < today and mtime_fresh:
            print("🔴 警告：brain.log 仍在写（mtime 新鲜），但最新 [ark] 记录是 %s，"
                  "今天没有任何方舟调用 token 记录 → 新版出话链路 token 记账断链，"
                  "正在烧钱但没人记账（见 V9 出话路径）" % latest_ark_day)
        elif latest_ark_day and latest_ark_day < today:
            print("⚠️ 注意：最新 [ark] 记录是 %s，今天暂无记录（可能尚未出话）" % latest_ark_day)

    # ④ 按天输出
    days = sorted(agg.keys())[-args.days:]
    if not days:
        print("（没有任何 [ark] 记录）")
        return 0
    pin_p, pch_p = _price_in(), _price_cache()
    print("\n%-8s %12s %12s %8s %s" % ("日期", "输入tok", "缓存命中", "调用数", "估算费用" if pin_p else ""))
    for day in days:
        v = agg[day]
        cost = ""
        if pin_p:
            pch = pch_p if pch_p else pin_p / 5.0
            # 🔴 [ark] 的「输入 N tok」是 prompt_tokens（已含缓存命中），
            #    「缓存命中 M」是 N 的子集。费用 = 非缓存部分按输入价 + 缓存部分按缓存价；
            #    若用 N×输入价 + M×缓存价 会把缓存部分算两次（N 里已含 M）。
            cny = ((v["in"] - v["cache"]) * pin_p + v["cache"] * pch) / 1_000_000.0
            cost = "¥%.4f" % cny
        print("%-8s %12d %12d %8d %s" % (day, v["in"], v["cache"], v["calls"], cost))
    tot_in = sum(agg[d]["in"] for d in days)
    tot_calls = sum(agg[d]["calls"] for d in days)
    print("\n近 %d 天合计：输入 %d tok，调用 %d 次（缓存命中占比 %.0f%%）" % (
        args.days, tot_in, tot_calls,
        (100.0 * sum(agg[d]["cache"] for d in days) / tot_in if tot_in else 0)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
