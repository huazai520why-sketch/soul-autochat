# -*- coding: utf-8 -*-
"""今日对话质量评估（每日复盘）—— 直读副机 IM-SDK 库，不依赖本地导出副本。

从 `_diag/qa_today.py` 固化而来，数据源改成遍历 `data/cache/IM-SDK-*/...-DATA.db`
（自动识别账号 uid），口径不变（2026-10-25 用户定）：

  口径（双层，强制）：
    A. 触达层（reach）= 全部会话。零回会话、白发条数只属这一层，不计入对话质量。
    B. 对话层（dialog）= 她至少回过 1 条的会话。所有质量指标只在这一层算。
       会话尾部「她最后没再回」不算缺陷；「她说了我还没回」（待回）仍算缺陷。
  仅 chatmsg.msgType=1（纯文本）；我 = senderId == 账号 uid；
  窗口 = 今天 00:00 → 现在，昨日取同一日历时刻做同窗口对比。

跑法：
    python -X utf8 tools/daily_review.py            # 打印今日 vs 昨日
    python -X utf8 tools/daily_review.py --days 1   # 只看今日（默认）
    python -X utf8 tools/daily_review.py --json out.json  # 落 JSON
"""
import argparse
import glob
import io
import json
import os
import re
import sqlite3
import sys
import datetime as dt
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")

# 账号昵称映射（uid -> 名称）。发现新账号时用 uid 兜底。
ME = {"96691646": "抬头仰望星空", "402857053": "离殇描绘未来时光"}

now = dt.datetime.now()
TODAY0 = dt.datetime(now.year, now.month, now.day)
YEST0 = TODAY0 - dt.timedelta(days=1)


def pct(arr, q):
    if not arr:
        return 0
    a = sorted(arr)
    k = min(len(a) - 1, int(round((len(a) - 1) * q)))
    return a[k]


def norm(s):
    s = re.sub(r"\[[^\]]{1,8}\]", "", s or "")
    s = re.sub(r"[\s，。！？、~～…\.\!\?,\-—：:；;\"'“”‘’()（）【】]+", "", s)
    return s


def jac(a, b):
    A, B = set(norm(a)), set(norm(b))
    return len(A & B) / len(A | B) if A | B else 0.0


def list_local_dbs():
    """返回 [(uid, db_path, nick_map)]，遍历 cache 下的 IM-SDK 库并猜 uid。"""
    out = []
    for d in glob.glob(os.path.join(CACHE, "IM-SDK-*")):
        if not os.path.isdir(d):
            continue
        dbs = glob.glob(os.path.join(d, "*DATA.db"))
        if not dbs:
            continue
        path = dbs[0]
        uid = guess_uid(path)
        out.append((uid, path))
    return out


def guess_uid(path):
    """复用 imdb 的 _guess_uid 逻辑：sessionId = 自己uid + toUserId，取前缀众数。"""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=5)
        rows = con.execute(
            "SELECT sessionId, toUserId FROM session WHERE sessionId IS NOT NULL "
            "AND toUserId IS NOT NULL LIMIT 300").fetchall()
        votes = {}
        for sid, touid in rows:
            sid, touid = str(sid), str(touid)
            if touid and sid.endswith(touid) and len(sid) > len(touid):
                pre = sid[:-len(touid)]
                votes[pre] = votes.get(pre, 0) + 1
        con.close()
        if votes:
            return max(votes.items(), key=lambda kv: kv[1])[0]
    except Exception:
        pass
    return None


def load_nicks(uid):
    """从旧版 soul_memory.db 读昵称表 nick(uid,name)。失败返回空 dict。"""
    for base in (r"E:\soul2.1\data\accounts", r"E:\soul1.0\data\accounts"):
        p = os.path.join(base, str(uid), "soul_memory.db")
        if not os.path.exists(p):
            continue
        try:
            con = sqlite3.connect(p)
            nicks = dict(con.execute("SELECT uid,name FROM nick"))
            con.close()
            return nicks
        except Exception:
            continue
    return {}


def collect(ts_from, ts_to):
    """返回该窗口内的会话结构与统计。"""
    sessions = []
    my, her, gaps = [], [], []
    for uid, path in list_local_dbs():
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=5)
        except Exception:
            continue
        uid_s = str(uid)
        nicks = load_nicks(uid)
        sess = {}
        try:
            for sid, to_uid in con.execute(
                    "SELECT sessionId,toUserId FROM session"):
                sess[sid] = to_uid
        except Exception:
            con.close()
            continue
        try:
            rows = list(con.execute(
                "SELECT sessionId,senderId,localTime,text FROM chatmsg "
                "WHERE msgType=1 AND localTime>=? AND localTime<? ORDER BY localTime",
                (ts_from, ts_to)))
        except Exception:
            con.close()
            continue
        con.close()
        by = defaultdict(list)
        for sid, snd, t, txt in rows:
            txt = (txt or "").replace("\n", " ").strip()
            if not txt:
                continue
            by[sid].append((str(snd), t, txt))
        for sid, msgs in by.items():
            to_uid = sess.get(sid, "?")
            name = nicks.get(str(to_uid)) or nicks.get(to_uid) or ("UID:%s" % to_uid)
            mine = [m for m in msgs if m[0] == uid_s]
            hers = [m for m in msgs if m[0] != uid_s]
            my.extend([m[2] for m in mine])
            her.extend([m[2] for m in hers])
            g = []
            i = 0
            while i < len(msgs):
                if msgs[i][0] != uid_s:
                    j = i
                    while j + 1 < len(msgs) and msgs[j + 1][0] != uid_s:
                        j += 1
                    k = j + 1
                    if k < len(msgs):
                        d = (msgs[k][1] - msgs[j][1]) / 1000.0
                        if 0 <= d <= 3600:
                            g.append(d)
                            gaps.append(d)
                    i = j + 1
                else:
                    i += 1
            sessions.append({
                "acct": uid_s, "acct_name": ME.get(uid_s, "UID:" + uid_s),
                "sid": sid, "name": name,
                "n_my": len(mine), "n_her": len(hers),
                "first": msgs[0][1], "last": msgs[-1][1],
                "last_sender": ("我" if msgs[-1][0] == uid_s else "她"),
                "last_her": (hers[-1][2] if hers else ""),
                "gaps": g,
                "msgs": [("我" if s == uid_s else "她", t, x) for s, t, x in msgs],
            })
    return sessions, my, her, gaps


def filter_replied(sessions):
    out = [s for s in sessions if s["n_her"] > 0]
    my, her, gaps = [], [], []
    for s in out:
        my += [x for who, t, x in s["msgs"] if who == "我"]
        her += [x for who, t, x in s["msgs"] if who == "她"]
        gaps += s["gaps"]
    return out, my, her, gaps


def reach(sessions):
    none_rep = [s for s in sessions if s["n_her"] == 0]
    my_all = sum(s["n_my"] for s in sessions)
    my_waste = sum(s["n_my"] for s in none_rep)
    return {
        "sessions_all": len(sessions),
        "sessions_noreply": len(none_rep),
        "noreply_rate": (len(none_rep) / len(sessions) * 100 if sessions else 0),
        "my_all": my_all,
        "my_waste": my_waste,
        "waste_rate": (my_waste / my_all * 100 if my_all else 0),
    }


def metrics(sessions, my, her, gaps):
    n_my, n_her = len(my), len(her)
    cm = Counter(norm(x) for x in my); cm.pop("", None)
    ch = Counter(norm(x) for x in her); ch.pop("", None)
    uniq_my = len(cm) / n_my * 100 if n_my else 0
    rep3_my = sum(v for v in cm.values() if v >= 3) / n_my * 100 if n_my else 0
    openers = []
    for s in sessions:
        for who, t, x in s["msgs"]:
            if who == "我":
                openers.append(x); break
    oc = Counter(norm(x) for x in openers)
    uniq_op = len(oc) / len(openers) * 100 if openers else 0
    q_my = sum(1 for x in my if ("？" in x or "?" in x)) / n_my * 100 if n_my else 0
    len_my = sum(len(x) for x in my) / n_my if n_my else 0
    len_her = sum(len(x) for x in her) / n_her if n_her else 0
    deep = sum(1 for s in sessions if s["n_her"] >= 10)
    deep20 = sum(1 for s in sessions if s["n_her"] >= 20)
    mono = 0
    for s in sessions:
        run = 0
        for who, t, x in s["msgs"]:
            if who == "我":
                run += 1
            else:
                if run >= 3:
                    mono += 1
                run = 0
        if run >= 3:
            mono += 1
    cold = sum(1 for x in her if len(re.sub(r"\[[^\]]{1,8}\]", "", x).strip()) <= 2)
    cold_ratio = cold / n_her * 100 if n_her else 0
    engaged = sum(1 for s in sessions if s["n_her"] >= 3)
    INV = re.compile(r"(过来|来耍|有空来|等你|你来|来嘛|来玩|来找我)")
    inv = sum(1 for x in my if INV.search(x))
    catch = catch_tot = 0
    dup_pairs = []
    for s in sessions:
        msgs = s["msgs"]
        for i, (who, t, x) in enumerate(msgs):
            if who == "我":
                prev = [m for m in msgs[:i] if m[0] == "她"]
                if prev:
                    catch_tot += 1
                    if jac(prev[-1][2], x) > 0.08:
                        catch += 1
        for i in range(len(msgs) - 1):
            if msgs[i][0] == "我" and msgs[i + 1][0] == "我" and (msgs[i + 1][1] - msgs[i][1]) < 90000:
                dup_pairs.append(jac(msgs[i][2], msgs[i + 1][2]))
    dup_hi = sum(1 for v in dup_pairs if v > 0.35)
    return {
        "sessions": len(sessions), "n_my": n_my, "n_her": n_her,
        "ratio": (n_my / n_her if n_her else 0),
        "her_avg": (n_her / len(sessions) if sessions else 0),
        "my_avg": (n_my / len(sessions) if sessions else 0),
        "p50": pct(gaps, .5), "p90": pct(gaps, .9),
        "pending": sum(1 for s in sessions if s["last_sender"] == "她"),
        "uniq_my": uniq_my, "rep3_my": rep3_my,
        "uniq_her": (len(ch) / n_her * 100 if n_her else 0),
        "openers": len(openers), "uniq_op": uniq_op,
        "q_my": q_my, "len_my": len_my, "len_her": len_her,
        "deep": deep, "deep20": deep20, "mono": mono,
        "cold_ratio": cold_ratio, "engaged": engaged,
        "inv_rate": (inv / n_my * 100 if n_my else 0),
        "catch_rate": (catch / catch_tot * 100 if catch_tot else 0),
        "catch_n": catch_tot,
        "dup2_rate": (dup_hi / len(dup_pairs) * 100 if dup_pairs else 0),
        "dup2_n": len(dup_pairs),
        "top_my": cm.most_common(12),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--dialogues", default="")
    args = ap.parse_args()

    s_today, my_all, her_all, gaps_all = collect(
        TODAY0.timestamp() * 1000, now.timestamp() * 1000)
    last_ts = max((s["last"] for s in s_today), default=now.timestamp() * 1000)
    cut = dt.datetime.fromtimestamp(last_ts / 1000)
    yest_cut = YEST0 + (cut - TODAY0)
    s_yest, my_y_all, her_y_all, gaps_y_all = collect(
        YEST0.timestamp() * 1000, yest_cut.timestamp() * 1000)

    R_t, R_y = reach(s_today), reach(s_yest)
    d_t, my_t, her_t, gaps_t = filter_replied(s_today)
    d_y, my_y, her_y, gaps_y = filter_replied(s_yest)
    M = metrics(d_t, my_t, her_t, gaps_t)
    Y = metrics(d_y, my_y, her_y, gaps_y)

    result = {
        "today": M, "yesterday": Y,
        "reach_today": R_t, "reach_yesterday": R_y,
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "cut": cut.strftime("%H:%M"), "yest_cut": yest_cut.strftime("%H:%M"),
        "scope": "dialog=她有回过1条以上；reach=全部会话",
    }
    if args.json:
        with io.open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

    if args.dialogues:
        d_t.sort(key=lambda s: s["n_her"], reverse=True)
        D = []
        for s in d_t[:14]:
            D.append("\n## %s/%s 她%d 我%d\n" % (s["acct"], s["name"], s["n_her"], s["n_my"]))
            for who, t, x in s["msgs"]:
                D.append("- %s %s：%s" % (dt.datetime.fromtimestamp(t / 1000).strftime("%H:%M"), who, x))
        with io.open(args.dialogues, "w", encoding="utf-8") as f:
            f.write("\n".join(D))

    print("=== 触达层（不计入质量）===")
    for k in ("sessions_all", "sessions_noreply", "noreply_rate", "my_all", "my_waste", "waste_rate"):
        print("  %-16s today=%-8s yest=%s" % (
            k, round(R_t[k], 2) if isinstance(R_t[k], float) else R_t[k],
            round(R_y[k], 2) if isinstance(R_y[k], float) else R_y[k]))
    print("=== 对话层（质量只用这一层）同窗口 %s -> 昨日 %s ===" % (cut.strftime("%H:%M"), yest_cut.strftime("%H:%M")))
    for k in ("sessions", "n_my", "n_her", "ratio", "her_avg", "p50", "p90", "pending",
              "uniq_my", "rep3_my", "uniq_op", "q_my", "len_my", "len_her", "deep",
              "deep20", "mono", "cold_ratio", "engaged", "inv_rate", "catch_rate", "dup2_rate"):
        print("  %-12s today=%-8s yest=%s" % (
            k, round(M[k], 2) if isinstance(M[k], float) else M[k],
            round(Y[k], 2) if isinstance(Y[k], float) else Y[k]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
