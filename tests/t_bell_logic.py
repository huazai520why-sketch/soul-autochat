# -*- coding: utf-8 -*-
"""奇遇铃清列表逻辑的离线测试。"""
import importlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bell():
    return importlib.import_module("brain.bell")


def test_helpers():
    B = _bell()
    assert B._row_key("妮妮", "同城奇遇", "00:13") == "妮妮|同城奇遇|00:13"
    assert B.profile_block_reason({"tags": ["不约", "音乐"]}) == "不约"
    assert B.profile_block_reason({"tags": ["已婚", "音乐"]}) == ""
    assert B.BELL_BATCH_MAX >= 1
    assert B.BELL_DAILY_MAX >= B.BELL_BATCH_MAX

    uid = "test_bell_logic"
    path = B._ledger_file(uid)
    try:
        data = {"version": 2, "opened": {}, "nicks": {}}
        key = "A|同城奇遇|10:00"
        data["opened"][key] = {
            "at": time.time(),
            "status": "sent",
            "nick": "A",
            "tag": "同城奇遇",
            "row_ts": "10:00",
            "retry_after": 0,
        }
        data["nicks"]["A"] = {"at": time.time(), "status": "sent"}
        B._ledger_save(uid, data)
        assert B._ledger_seen(uid, key)
        assert B._ledger_seen(uid, "changed-key", nick="A")
        assert B.bell_daily_count(uid) >= 1

        data = B._ledger_load(uid)
        old = "B||"
        data["opened"][old] = {"at": time.time() - B.BELL_LIST_LEDGER_TTL_S - 10,
                               "status": "sent"}
        B._ledger_save(uid, data)
        data = B._ledger_load(uid)
        assert old not in data["opened"]
        assert key in data["opened"]
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


if __name__ == "__main__":
    test_helpers()
    print("PASS t_bell_logic")
