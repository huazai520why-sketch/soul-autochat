# -*- coding: utf-8 -*-
"""Persistent reply/cooldown ledgers for pending conversations.

This module is the shared source for `pending_skip.json` and `replied.json`.
It has no UI/device/brain dependencies, so both data-layer statistics and brain
orchestration can use exactly the same semantics without creating a reverse
import from data to brain.
"""
import json
import os
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("data.pending_ledger")

SKIP_FILE = STATE / "pending_skip.json"
REPLIED_FILE = STATE / "replied.json"
REPLIED_GAP = 300
DEFAULT_SKIP_HOURS = 3


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(path))
        return True
    except Exception as e:
        log.warning("台账保存失败 %s: %r", path.name, e)
        return False


def load_skip():
    return _load_json(SKIP_FILE)


def save_skip(data):
    return _save_json(SKIP_FILE, data)


def should_skip(sid, text, default_hours=DEFAULT_SKIP_HOURS, last_out=None):
    rec = load_skip().get(str(sid)) or {}
    if not rec:
        return False
    if (rec.get("text") or "").strip() != (text or "")[:120].strip():
        return False
    age = time.time() - float(rec.get("ts") or 0)
    hours = float(rec.get("hours") or default_hours)
    if age < hours * 3600:
        if last_out is not None:
            last_out[str(sid)] = rec
        return True
    return False


def mark_skip(sid, text, reason="notfound", hours=None):
    data = load_skip()
    now = time.time()
    data[str(sid)] = {
        "ts": now,
        "text": (text or "")[:120],
        "reason": reason,
        "hours": DEFAULT_SKIP_HOURS if hours is None else float(hours),
    }
    cutoff = now - 7 * 86400
    data = {k: v for k, v in data.items()
            if float((v or {}).get("ts") or 0) > cutoff}
    save_skip(data)
    return data[str(sid)]


_REPLIED = {}


def load_replied():
    raw = _load_json(REPLIED_FILE)
    now = time.time()
    out = {}
    for k, v in (raw or {}).items():
        try:
            if isinstance(v, dict):
                ts = float(v.get("ts") or 0)
                if ts and now - ts < 7 * 86400:
                    out[str(k)] = {"text": str(v.get("text") or ""), "ts": ts}
            else:
                ts = float(v)
                if now - ts < REPLIED_GAP * 4:
                    out[str(k)] = {"text": "", "ts": ts}
        except Exception:
            continue
    return out


def _expire_replied(data, now=None):
    """对 `_REPLIED` 做一次过期收缩（复用 load_replied 同款 7 天 / REPLIED_GAP*4 规则）。

    只删过期条目，不动未过期条目；返回收缩后的 dict，并同步更新传入的 dict 本身，
    保证同进程内 recently_replied() 读到的仍是同一份（一致性不被破坏）。
    """
    now = time.time() if now is None else float(now)
    out = {}
    for k, v in (data or {}).items():
        try:
            if isinstance(v, dict):
                ts = float(v.get("ts") or 0)
                if ts and now - ts < 7 * 86400:
                    out[str(k)] = v
            else:
                ts = float(v)
                if now - ts < REPLIED_GAP * 4:
                    out[str(k)] = {"text": "", "ts": ts}
        except Exception:
            continue
    if out is not data:
        data.clear()
        data.update(out)
    return data


def mark_replied(uid, sid=None, text=None):
    key = str(sid) if sid else str(uid)
    _REPLIED[key] = {"text": (text or "")[:120], "ts": time.time()}
    _expire_replied(_REPLIED)          # 🔴 P1-A5：落盘前收缩过期条目，台账不无限增长
    save_replied(_REPLIED)


def save_replied(data):
    return _save_json(REPLIED_FILE, data)


def recently_replied(uid, sid=None, text=None, her_ts_ms=0, now=None):
    now = time.time() if now is None else float(now)
    rec = _REPLIED.get(str(sid)) if sid else None
    if rec is None:
        rec = _REPLIED.get(str(uid))
    # 🔴 2026-11-19 修复 DATA-13（P2 内存查不到时 fallback 读一次盘）：
    #   _REPLIED 只在本进程启动时 load_replied() 一次，之后靠 mark_replied 更新。
    #   若台账被**别的进程**（另一个 daemon/工具）写过，本进程内存里没有这条，
    #   直接 return False → 误判「没回过」→ 对同一人重复回（重复回比漏回更伤）。
    #   修法：内存（sid/uid 两个键）都查不到时，读一次盘兜底（load_replied 同款
    #   口径，已含 7 天 / REPLIED_GAP*4 过期收缩），与 load_skip 每次读盘一致。
    #   只读不回填内存：避免跨键污染（按 uid 命中的盘上记录若回填进 sid 键，
    #   会干扰后续判定），读盘开销小（几十条）可接受。
    if not isinstance(rec, dict):
        try:
            _disk = load_replied()
        except Exception as _e:
            log.debug("recently_replied 读盘兜底失败（按未回处理）: %r", _e)
            _disk = {}
        _k_sid = str(sid) if sid else None
        rec = (_disk.get(_k_sid) if _k_sid else None) or _disk.get(str(uid))
    if not isinstance(rec, dict):
        return False
    try:
        ts = float(rec.get("ts") or 0)
    except Exception:
        return False
    if not ts:
        return False
    try:
        if her_ts_ms and float(her_ts_ms) / 1000.0 > ts + 1.0:
            return False
    except Exception:
        pass
    old = (rec.get("text") or "").strip()
    cur = (text or "").strip()
    if not old or not cur:
        return (now - ts) < max(REPLIED_GAP, 1800)
    return old == cur


_REPLIED.update(load_replied())
