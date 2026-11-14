# -*- coding: utf-8 -*-
"""Offline tests for cooperative preemption helpers."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import search as S  # noqa: E402


def test_signal_breaks_wait_without_device():
    assert S._wait_preempt(5.0, lambda: True) is True


def test_no_signal_uses_bounded_sleeps():
    sleeps = []
    clock = [0.0]

    def fake_time():
        return clock[0]

    def fake_sleep(n):
        sleeps.append(n)
        clock[0] += n

    with mock.patch.object(S.time, "sleep", side_effect=fake_sleep):
        with mock.patch.object(S.time, "time", side_effect=fake_time):
            assert S._wait_preempt(1.0, lambda: False) is False
    assert sleeps
    assert all(0 < n <= 0.25 for n in sleeps)


if __name__ == "__main__":
    test_signal_breaks_wait_without_device()
    test_no_signal_uses_bounded_sleeps()
    print("PASS t_flow_preempt")
