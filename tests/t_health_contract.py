# -*- coding: utf-8 -*-
"""Offline health-contract tests shared by daemon telemetry."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _msg_probe():
    spec = importlib.util.spec_from_file_location("soul_msg_probe_test",
                                                  ROOT / "tools" / "msg_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_lock_is_unknown_not_ancient():
    M = _msg_probe()
    assert M._step_age_from_lock({}, now=1000.0) is None
    assert M._step_age_from_lock({"ts": 0}, now=1000.0) is None
    assert M._step_age_from_lock({"step_ts": "abc"}, now=1000.0) is None


def test_heartbeat_age():
    M = _msg_probe()
    assert M._step_age_from_lock({"ts": 990.0}, now=1000.0) == 10.0
    assert M._step_age_from_lock({"ts": 900.0, "step_ts": 950.0}, now=1000.0) == 50.0


if __name__ == "__main__":
    test_missing_lock_is_unknown_not_ancient()
    test_heartbeat_age()
    print("PASS t_health_contract")
