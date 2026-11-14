# -*- coding: utf-8 -*-
"""Pure candidate-ranking policy.

No database, device, filesystem, or logging access. Keeping this policy pure
lets the hot-path ordering and cooldown rules be tested without a live device.
"""
import time


def cooldown_remaining_minutes(record, now=None):
    """Minutes left for a pending_skip record; expired/invalid records return 0."""
    now = time.time() if now is None else float(now)
    try:
        started = float((record or {}).get("ts") or 0)
        hours = float((record or {}).get("hours") or 0)
    except Exception:
        return 0.0
    if not started or hours <= 0:
        return 0.0
    return max(0.0, hours * 60.0 - (now - started) / 60.0)


def candidate_tier(item):
    """0=burst, 1=long, 2=medium, 3=short; stable for equal tiers."""
    _sid, _uid, text, _ts, burst_n = item
    if int(burst_n or 0) >= 2:
        return 0
    n = len((text or "").strip())
    if n >= 6:
        return 1
    if n >= 3:
        return 2
    return 3


def rank_candidates(items, fresh_hours=6.0, hot_minutes=20.0, now_ms=None):
    """Rank by freshness fairness, content tier, then a strict hot-message window.

    Item shape is `(sid, uid, text, her_ts_ms, burst_n)`. Ordering intentionally
    preserves original order inside equal keys (Python stable sort).
    """
    now_ms = (time.time() * 1000.0) if now_ms is None else float(now_ms)
    window_ms = float(fresh_hours) * 3600000.0
    fresh = [x for x in items if now_ms - float(x[3] or 0) < window_ms]
    stale = [x for x in items if now_ms - float(x[3] or 0) >= window_ms]
    fresh.sort(key=lambda x: -float(x[3] or 0))
    stale.sort(key=lambda x: float(x[3] or 0))
    merged = []
    while fresh or stale:
        if fresh:
            merged.append(fresh.pop(0))
        if stale:
            merged.append(stale.pop(0))
    merged = sorted(merged, key=candidate_tier)
    hot_ms = float(hot_minutes) * 60.0 * 1000.0
    hot = [x for x in merged if now_ms - float(x[3] or 0) < hot_ms]
    rest = [x for x in merged if now_ms - float(x[3] or 0) >= hot_ms]
    hot.sort(key=lambda x: -float(x[3] or 0))
    return hot + rest


def prioritize_voice(items, voice_sids, hot_minutes=20.0, now_ms=None):
    """Keep true hot messages first, then move older voice items ahead of text backlog."""
    now_ms = (time.time() * 1000.0) if now_ms is None else float(now_ms)
    hot_ms = float(hot_minutes) * 60.0 * 1000.0
    voices = {str(x) for x in (voice_sids or ())}
    hot, voice_rest, other = [], [], []
    for item in items:
        age_ms = now_ms - float(item[3] or 0)
        if age_ms < hot_ms:
            hot.append(item)
        elif str(item[0]) in voices:
            voice_rest.append(item)
        else:
            other.append(item)
    return hot + voice_rest + other


def compact_reason_counts(counter):
    """Return only non-zero cooldown reason counts from a Counter/dict."""
    return {
        str(k).split(":", 1)[1]: int(v)
        for k, v in (counter or {}).items()
        if str(k).startswith("cooldown:") and v
    }
