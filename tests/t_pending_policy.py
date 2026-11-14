# -*- coding: utf-8 -*-
"""Offline tests for pure pending-candidate policy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import pending_policy as P  # noqa: E402


def test_cooldown():
    now = 1_000_000.0
    assert round(P.cooldown_remaining_minutes(
        {"ts": now - 600, "hours": 0.5}, now=now), 1) == 20.0
    assert P.cooldown_remaining_minutes({"ts": now - 3600, "hours": 0.5}, now=now) == 0.0
    assert P.cooldown_remaining_minutes({"ts": 0, "hours": 6}, now=now) == 0.0
    assert P.cooldown_remaining_minutes(None, now=now) == 0.0


def test_rank_hot_first_then_tier():
    now = 10_000_000.0
    items = [
        ("a", "1", "old but long enough", now - 10 * 3600000, 1),
        ("b", "2", "短", now - 2 * 60000, 1),
        ("c", "3", "普通长句", now - 5 * 60000, 1),
        ("d", "4", "连发", now - 3 * 3600000, 3),
    ]
    ranked = P.rank_candidates(items, fresh_hours=6, hot_minutes=20, now_ms=now)
    assert ranked[0][0] == "b"   # hottest, even if text is short
    assert ranked[1][0] == "c"
    assert ranked[2][0] == "d"   # tier 0 before old tier 1
    assert ranked[3][0] == "a"


def test_reason_counts():
    got = P.compact_reason_counts({
        "cooldown": 5,
        "cooldown:nocue_hard": 3,
        "cooldown:timeout": 2,
        "archived": 9,
        "cooldown:unused": 0,
    })
    assert got == {"nocue_hard": 3, "timeout": 2}


def test_voice_backlog_priority():
    now = 10_000_000.0
    items = [
        ("text_old", "1", "old text", now - 30 * 3600000, 1),
        ("voice_old", "2", "voice transcript", now - 30 * 3600000, 1),
        ("hot", "3", "hot text", now - 60000, 1),
    ]
    ranked = P.prioritize_voice(items, {"voice_old"}, now_ms=now)
    assert [x[0] for x in ranked] == ["hot", "voice_old", "text_old"]


if __name__ == "__main__":
    test_cooldown()
    test_rank_hot_first_then_tier()
    test_reason_counts()
    test_voice_backlog_priority()
    print("PASS t_pending_policy")
