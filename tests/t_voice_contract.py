# -*- coding: utf-8 -*-
"""Offline test for session-summary -> real voice chatmsg resolution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import voice as V  # noqa: E402


class _Row(object):
    def __init__(self, values):
        self.values = values

    def __getitem__(self, index):
        return self.values[index]


class _Con(object):
    def execute(self, sql, params):
        assert "msgType=5" in sql
        return self

    def fetchone(self):
        return _Row(['{"word":"已经识别","duration":4,"url":""}', 123456, "u1", "m1"])


class _DB(object):
    con = _Con()


class _SummaryVoice(object):
    msg_type = 5
    content = ""
    text = "[语音]"
    ts = 123456
    sender = "u1"


def main():
    msg = V.resolve_msg(_SummaryVoice(), db=_DB(), sid="s1")
    assert msg.msg_type == 5
    assert V.duration(msg) == 4
    text, how = V.voice_text(msg, allow_asr=False, db=_DB(), sid="s1")
    assert text == "已经识别"
    assert how == "word"
    print("PASS t_voice_contract")


if __name__ == "__main__":
    main()
