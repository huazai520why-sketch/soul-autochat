# -*- coding: utf-8 -*-
"""操作层行为审计：把日志里的「动作」量化，找出白点 / 无效操作。

用途（2026-11-08 新增）：用户反馈「乱点瞎操作很严重」，但卡顿感不等于数据。
这个脚本把每个动作归类计数，并特别统计两类东西：

  ① **原地打转**：`page -> page`（点了页面没变）——说明这一下是白点的；
  ② **恢复动作链**：back / am start / restart 的次数——它们不代表业务推进，
     只代表"上一步没成功"。这三项占比越高，操作层越浪费。

典型基线（修复前，每文件最后 4000 行）：nav_back 725 / am_start 465 /
restart 279 / 放弃 137 —— 其中 restart 每次 20~40s，等于 2~3 小时纯停机。

跑法：python tools/action_audit.py [每个文件看最后多少行]
"""

import io
import os
import re
import sys
from collections import Counter, defaultdict

LOGS = r"E:\soul1.0\logs"
TAIL = 4000          # 每个文件看最后多少行

# 我们要统计的关键动作（正则 → 归类）
CATS = [
    ("tap_tab_未命中", re.compile(r"tap_tab .* 未命中")),
    ("tap_tab_正常", re.compile(r"tap_tab .*: (\S+) -> (\S+)")),
    ("double_tap", re.compile(r"double_tap_tab\((.+?)\): (\S+) -> (\S+)")),
    ("nav_back", re.compile(r"\[nav\].*→\s*back")),
    ("nav_am_start", re.compile(r"强制回首页|am start")),
    ("nav_restart", re.compile(r"强制重启 Soul|重启 App")),
    ("nav_H5逃逸", re.compile(r"卡在 H5 网页页")),
    ("nav_放弃", re.compile(r"放弃本次导航")),
    ("nav_unknown", re.compile(r"unknown 第 (\d+) 次")),
    ("nav_回不去", re.compile(r"连续 (\d+) 次回不到")),
    ("wait_page超时", re.compile(r"wait_page.*超时|等不到")),
    ("进会话失败", re.compile(r"进会话失败|进入后不是 chat 页")),
    ("重定位失败", re.compile(r"重新定位不到")),
    ("soul不在前台", re.compile(r"Soul 不在前台")),
    ("点发送", re.compile(r"点发送 \(")),
    ("发送确认读不到框", re.compile(r"发送确认读不到输入框")),
    ("发送残留", re.compile(r"输入框.*残留|框有残留")),
    ("双击无进展", re.compile(r"双击.*无进展")),
    ("sweep结束", re.compile(r"清红点结束")),
    ("假红点", re.compile(r"假红点")),
    ("弹窗关闭", re.compile(r"\[popup\].*关闭")),
    ("搜索notfound", re.compile(r"搜索.*未找到相关结果|reason=notfound")),
    ("搜索打不开", re.compile(r"打不开搜索页|找不到搜索入口")),
]

# "X -> X" 表示点了页面没变
NOOP_RX = re.compile(r":\s*(\w+)\s*->\s*(\w+)")
TS_RX = re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\s+(\w+)\s+(.*)$")


def read_tail(path, n):
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return lines[-n:]


def main():
    if not os.path.isdir(LOGS):
        print("找不到日志目录：%s" % LOGS)
        print("这个脚本要在**跑 daemon 的那台机器**上执行（日志在项目目录的 logs/ 下）。")
        print("如果你在别的机器上，先 scp 一份 logs/ 过来，或改 LOGS 常量指向实际路径。")
        return 2
    files = [fn for fn in sorted(os.listdir(LOGS)) if fn.endswith(".log")]
    total_cat = Counter()
    per_file = {}
    noop = Counter()          # (from, to) 里 from == to 的
    tap_move = Counter()      # 真变化的
    minute_actions = Counter()   # 每分钟动作数
    day_span = None

    for fn in files:
        lines = read_tail(os.path.join(LOGS, fn), TAIL)
        if not lines:
            continue
        c = Counter()
        for ln in lines:
            for name, rx in CATS:
                if rx.search(ln):
                    c[name] += 1
                    total_cat[name] += 1
            m = NOOP_RX.search(ln)
            if m:
                a, b = m.group(1), m.group(2)
                if a == b:
                    noop[(fn, a)] += 1
                else:
                    tap_move[fn] += 1
            t = TS_RX.match(ln)
            if t and ("点发送" in ln or "tap_tab" in ln or "→ back" in ln or "am start" in ln):
                minute_actions[t.group(3) + ":" + t.group(4)] += 1
        per_file[fn] = c

    print("=" * 72)
    print("动作分类统计（每文件最后 %d 行）" % TAIL)
    print("=" * 72)
    names = [n for n, _ in CATS if total_cat[n]]
    print("%-18s %s" % ("类别", "  ".join("%-12s" % f.replace(".log", "") for f in [])))
    for n in sorted(names, key=lambda x: -total_cat[x]):
        row = [f for f in per_file if per_file[f][n]]
        print("%-18s 合计 %-6d | %s" % (
            n, total_cat[n],
            "  ".join("%s:%d" % (f.replace(".log", ""), per_file[f][n]) for f in row[:6])))

    print()
    print("=" * 72)
    print("无效操作（点了页面没变 X -> X）")
    print("=" * 72)
    if noop:
        for (f, state), n in noop.most_common(10):
            print("  %-22s %-12s 原地打转 %d 次" % (f, state, n))
    else:
        print("  （无）")
    print()
    print("有效页面切换：")
    for f, n in tap_move.most_common():
        print("  %-22s %d 次" % (f, n))

    print()
    print("=" * 72)
    print("动作最密集的分钟（点发送 / tap_tab / back / am start）")
    print("=" * 72)
    for mm, n in minute_actions.most_common(12):
        print("  %s  %d 次动作  %s" % (mm, n, "█" * min(40, n)))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
