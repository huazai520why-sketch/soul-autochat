# -*- coding: utf-8 -*-
"""案情包存储层（v3 schema）。

为什么重写而不是沿用 v2（用户 2026-11-04「整体重构，档案/案情包重新构建」）：
  v2 把五层平铺成 5 个 md（L0_人设/L1_方案/L2_对话/L3_本轮/L4_资料），有两个硬伤：
  ① **没有归属**：L0 的「事实：」行把「我:」说过的话写成她的事实
     （实测样本：`事实：真的尽力了；你真的服了；什么意思` —— 那是她的话/语气词，
     不是关于她的事实；另有把「我开网店卖电脑配件」记成她的事实）。
  ② **没有来源**：任意一条事实都不知道是哪一句对话里来的，无法校验、无法清洗，
     模型说错也查不出是哪一步错的。

v3 的分工（每个文件一个职责，互不覆盖）：
  meta.json     元信息：版本/sid/uid/账号/昵称/时间戳
  profile.json  她的静态主页（匹配时抓的）：昵称/引力签/共同点/标签/瞬间/IP/匹配度
  facts.json    事实，**每条带归属与出处**：
                  hers = [{t, ev(她原话证据), at, conf}]
                  mine = [{t, ev, at}]      ← 我说过的事，绝不进 hers
  turns.md      对话原文，append-only，格式 `- MM-DD HH:MM 她: ...`
  state.json    关系状态：轮数/档位/目标/status/最后互动
  brief.md      本轮简报（模型产出，短，≤300 字，下一轮作废）

🔴 铁律：事实进 hers 之前必须有 `ev`（她原话里的一段）。没有出处的不写 ——
   宁可少一条，也不让「我」的事变成「她」的人设。
"""
import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

try:
    from core.log import get_logger
    log = get_logger("brain.pack.store")
except Exception:                                    # 单测/离线脚本可直接用
    import logging
    log = logging.getLogger("pack.store")

BASE = Path(__file__).resolve().parent.parent.parent   # E:\soul1.0
MEM = BASE / "memory"

# 账号 uid ↔ 目录名（沿用用户口径：账号1 / 账号2）
ACCT_DIR = {"96691646": "账号1", "402857053": "账号2"}
DIR_ACCT = {v: k for k, v in ACCT_DIR.items()}

VERSION = 3

_FILES = ("meta.json", "profile.json", "facts.json", "state.json",
          "turns.md", "brief.md")


# ────────────────────────────── 基础 IO ──────────────────────────────
def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".swp")
    try:
        with io.open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _read_json(path, default=None):
    try:
        with io.open(str(path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def _write_json(path, obj):
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=1,
                                  sort_keys=True) + "\n")


def _read_text(path, limit=None):
    try:
        with io.open(str(path), encoding="utf-8", errors="replace") as f:
            t = f.read()
    except Exception:
        return ""
    if limit and len(t) > limit:
        return t[-limit:]
    return t


# ────────────────────────────── 目录定位 ──────────────────────────────
def acct_of(sid):
    """sid = <uid><对方uid 尾部>，前 8~9 位是账号 uid。识别不出返回空串。"""
    s = str(sid or "")
    for uid in ACCT_DIR:
        if s.startswith(uid):
            return uid
    return ""


def _dir(sid, acct=""):
    """只算路径，**不建目录**。所有纯读路径必须走它。

    血泪（2026-11-04）：pack_dir 原来无条件 mkdir，而读函数全经过它，
    于是「只是查一下有没有档案」也会在 memory 下留一个空目录 ——
    账号1 因此多出 3 个空会话目录，按目录数统计会话就虚高。
    """
    a = acct or acct_of(sid)
    name = ACCT_DIR.get(a) or (a if a in DIR_ACCT else "_未知账号")
    return MEM / name / str(sid)


def pack_dir(sid, acct=""):
    """返回 memory/<账号目录>/<sid>/ 并确保存在（**写路径专用**）。"""
    d = _dir(sid, acct)
    d.mkdir(parents=True, exist_ok=True)
    return d


def exists(sid):
    try:
        return (_dir(sid) / "meta.json").is_file()
    except Exception:
        return False


# ────────────────────────────── meta ──────────────────────────────
def read_meta(sid):
    return _read_json(_dir(sid) / "meta.json", {})


def write_meta(sid, **kw):
    d = pack_dir(sid)
    m = _read_json(d / "meta.json", {})
    m.setdefault("sid", str(sid))
    m.setdefault("version", VERSION)
    m.setdefault("created", time.strftime("%Y-%m-%d %H:%M:%S"))
    m.update(kw)
    m["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    m["version"] = VERSION
    _write_json(d / "meta.json", m)
    return m


# ────────────────────────────── profile（她的静态主页）──────────────────
def read_profile(sid):
    return _read_json(_dir(sid) / "profile.json", {})


def write_profile(sid, **kw):
    d = pack_dir(sid)
    p = _read_json(d / "profile.json", {})
    p.update({k: v for k, v in kw.items() if v not in (None, "", [], {})})
    _write_json(d / "profile.json", p)
    write_meta(sid)
    return p


# ────────────────────────────── facts（带归属的事实）──────────────────
def read_facts(sid):
    f = _read_json(_dir(sid) / "facts.json", {})
    return {"hers": list(f.get("hers") or []), "mine": list(f.get("mine") or [])}


def write_facts(sid, facts):
    d = pack_dir(sid)
    out = {"hers": [], "mine": []}
    seen = set()
    for side in ("hers", "mine"):
        for it in (facts.get(side) or []):
            t = (it.get("t") if isinstance(it, dict) else str(it) or "").strip()
            if not t:
                continue
            key = (side, t)
            if key in seen:
                continue
            seen.add(key)
            rec = {"t": t}
            if isinstance(it, dict):
                for k in ("ev", "at", "conf", "src"):
                    if it.get(k) not in (None, ""):
                        rec[k] = it[k]
            out[side].append(rec)
    out["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(d / "facts.json", out)
    write_meta(sid)
    return out


def add_fact(sid, text, side="hers", ev="", conf=1.0, at=""):
    """追加一条事实。**hers 必须有 ev**，否则拒绝（防串台的第一道闸）。"""
    text = (text or "").strip()
    if not text:
        return False
    if side == "hers" and not (ev or "").strip():
        log.warning("拒绝写入无出处的事实: %r", text[:40])
        return False
    f = read_facts(sid)
    if any(x.get("t") == text for x in f[side]):
        return False
    f[side].append({"t": text, "ev": (ev or "").strip()[:80],
                    "at": at or time.strftime("%m-%d"), "conf": conf})
    write_facts(sid, f)
    return True


# ────────────────────────────── turns（对话原文）──────────────────
def turns_path(sid):
    return pack_dir(sid) / "turns.md"


def read_turns(sid, limit_chars=None):
    # 读不建目录：直用 _dir，不走 turns_path（那是写路径入口）
    return _read_text(_dir(sid) / "turns.md", limit_chars).strip()


def append_turns(sid, rows):
    """rows = [(when_str, role, text)]，role ∈ {"她","我"}。append-only。"""
    if not rows:
        return 0
    d = pack_dir(sid)
    p = d / "turns.md"
    buf = []
    for when, role, text in rows:
        t = (text or "").replace("\r", " ").replace("\n", " / ").strip()
        if not t:
            continue
        buf.append("- %s %s: %s\n" % (when, role, t))
    if not buf:
        return 0
    with io.open(str(p), "a", encoding="utf-8", newline="\n") as f:
        f.write("".join(buf))
    write_meta(sid)
    resync_state(sid)
    # 🔴 2026-11-10（日志缺陷修复）：本模块只在「拒绝写无出处事实」时打 warning，
    #   正常写入一条不留 → `logs/brain.pack.store.log` 长期 0 字节。
    #   L2(turns.md) 是「她说了新话有没有被记住」的唯一凭据，
    #   而 pendingq 的 `_l2_last_is_me` 判定完全依赖它 —— 写没写进去必须留痕。
    try:
        log.info("L2 追加 sid=%s %d 行（末行=%s）", sid, len(buf), buf[-1].strip()[:60])
    except Exception:
        pass
    return len(buf)


def sync_turns(sid, msgs, my_uid, max_add=60):
    """把数据库里的新消息补进 turns.md（幂等：按 meta.last_ts_ms 游标 + 末行去重）。

    msgs 是 imdb.Msg 列表（需有 .msg_type/.sender/.ts/.text）。
    只收文本消息；系统/提示卡片不进对话史。
    返回新增条数。
    """
    m = _read_json(pack_dir(sid) / "meta.json", {})
    last_ts = int(m.get("last_ts_ms") or 0)
    # 去重基线：已经落盘的行（防止「先手工补一句、再被 DB 同步进来」出现两份）
    seen = set()
    for ln in read_turns(sid, limit_chars=8000).splitlines()[-60:]:
        for role in ("她", "我"):
            if " %s: " % role in ln:
                seen.add((role, ln.split(" %s: " % role, 1)[1].strip()))
                break
    rows, newest = [], last_ts
    for x in msgs or []:
        try:
            if int(getattr(x, "msg_type", 0) or 0) != 1:
                continue
            ts = int(getattr(x, "ts", 0) or 0)
            txt = (getattr(x, "text", "") or "").strip()
        except Exception:
            continue
        if not txt or ts <= last_ts:
            continue
        role = "我" if str(x.sender) == str(my_uid) else "她"
        if (role, txt) in seen:
            continue
        when = time.strftime("%m-%d %H:%M", time.localtime(ts / 1000.0))
        rows.append((when, role, txt))
        newest = max(newest, ts)
    if len(rows) > max_add:
        rows = rows[-max_add:]
    n = append_turns(sid, rows)
    if n:
        m = _read_json(pack_dir(sid) / "meta.json", {})
        m["last_ts_ms"] = newest
        _write_json(pack_dir(sid) / "meta.json", m)
    return n


def note_my_reply(sid, text, ts_ms=None):
    """我刚发出去的一句 —— 立刻落盘。

    为什么必须立刻写（不能等下一轮从 DB 补）：
      pendingq 判「已读未回」看的是 turns 末行是不是「我:」。
      如果等 DB 回写，这中间的窗口里末行还是「她」→ 判未回 → **重复回复**。
    """
    ts = int(ts_ms or (time.time() * 1000))
    when = time.strftime("%m-%d %H:%M", time.localtime(ts / 1000.0))
    n = append_turns(sid, [(when, "我", text)])
    if n:
        m = _read_json(pack_dir(sid) / "meta.json", {})
        m["last_ts_ms"] = max(int(m.get("last_ts_ms") or 0), ts)
        _write_json(pack_dir(sid) / "meta.json", m)
    return n


def resync_state(sid):
    """按 turns.md 重算轮数与档位（唯一事实源，可复现）。"""
    st = turns_stat(sid)
    cur = dict(STATE_DEFAULT)
    cur.update(_read_json(pack_dir(sid) / "state.json", {}))
    cur["turns"] = st["turns"]
    if st["last_role"] == "她":
        cur["last_her_at"] = st["last_at"]
    elif st["last_role"] == "我":
        cur["last_me_at"] = st["last_at"]
    _write_json(pack_dir(sid) / "state.json", cur)
    return cur


def last_her_line(sid):
    """最近一条「她:」的原文（判断接话用）。"""
    t = read_turns(sid, limit_chars=4000)
    last = ""
    for ln in t.splitlines():
        if " 她: " in ln:
            last = ln.split(" 她: ", 1)[1]
    return last.strip()


def turns_stat(sid):
    t = read_turns(sid)
    n_her = t.count(" 她: ")
    n_me = t.count(" 我: ")
    last_at, last_role = "", ""
    for ln in t.splitlines():
        if ln.startswith("- ") and len(ln) > 18:
            last_at = ln[2:18].strip()
            if " 她: " in ln:
                last_role = "她"
            elif " 我: " in ln:
                last_role = "我"
    return {"turns": n_her + n_me, "her": n_her, "me": n_me,
            "last_at": last_at, "last_role": last_role}


# ────────────────────────────── state（关系状态）──────────────────
STATE_DEFAULT = {
    "turns": 0, "lv": 0, "name": "初识", "goal": "",
    "goal_hit": False, "giveup": False, "status": "active",
    "last_her_at": "", "last_me_at": "",
}


def read_state(sid):
    s = dict(STATE_DEFAULT)
    s.update(_read_json(_dir(sid) / "state.json", {}))
    return s


def write_state(sid, **kw):
    d = pack_dir(sid)
    s = dict(STATE_DEFAULT)
    s.update(_read_json(d / "state.json", {}))
    s.update(kw)
    _write_json(d / "state.json", s)
    write_meta(sid)
    return s


# ────────────────────────────── brief（本轮简报）──────────────────
def read_brief(sid):
    return _read_text(_dir(sid) / "brief.md").strip()


def write_brief(sid, text):
    _atomic_write(pack_dir(sid) / "brief.md", (text or "").strip() + "\n")
    write_meta(sid)


def brief_age_h(sid):
    p = _dir(sid) / "brief.md"
    try:
        return (time.time() - p.stat().st_mtime) / 3600.0
    except Exception:
        return 1e9


# ────────────────────────────── 迁移辅助 ──────────────────────────────
def import_v2_dir(v2_dir, sid):
    """把 v2 目录里的原始文件**只读**拷进 v3 的 _legacy/ 供 rebuild 参考，不解析。"""
    src = Path(v2_dir)
    if not src.is_dir():
        return []
    dst = pack_dir(sid) / "_legacy"
    dst.mkdir(parents=True, exist_ok=True)
    kept = []
    for fn in ("L0_人设.md", "L1_方案.md", "L2_对话.md", "L3_本轮.md",
               "L4_资料.md", "pack.json"):
        p = src / fn
        if p.is_file():
            shutil.copy2(str(p), str(dst / fn))
            kept.append(fn)
    return kept


__all__ = [
    "BASE", "MEM", "VERSION", "ACCT_DIR", "DIR_ACCT",
    "acct_of", "pack_dir", "exists",
    "read_meta", "write_meta",
    "read_profile", "write_profile",
    "read_facts", "write_facts", "add_fact",
    "turns_path", "read_turns", "append_turns", "last_her_line", "turns_stat",
    "sync_turns", "note_my_reply", "resync_state",
    "read_state", "write_state",
    "read_brief", "write_brief", "brief_age_h",
    "import_v2_dir",
]
