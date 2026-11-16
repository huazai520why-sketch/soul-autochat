# -*- coding: utf-8 -*-
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain import auto_voice as AV  # noqa: E402
from brain.flow import Outcome  # noqa: E402
from eyes.uitree import Node  # noqa: E402


class _Snap:
    def __init__(self, nodes):
        self.nodes = nodes


class _Actor:
    def __init__(self):
        self.snaps = [
            _Snap([]),
            _Snap([Node(res_id="cn.soulapp.android:id/voice_bubble", bounds=(700, 900, 880, 960))]),
        ]
        self.dev = object()

    def snap(self, force=False):
        return self.snaps[-1]


class _DB:
    uid = "1001"


def test_gate_and_text():
    with mock.patch.dict(os.environ, {"SOUL_AUTO_VOICE_REPLY": "1"}, clear=False):
        assert AV.enabled()
        assert AV.should_reply("voice", "123")
        assert not AV.should_reply("text", "123")
        assert AV.voice_text(["第一句", "第二句"]) == "第一句，第二句"
        out = Outcome()
        out.kind = "asr"
        out.voice_input = True
        assert AV.should_reply("voice" if out.voice_input else out.kind, "123")

    with mock.patch.dict(os.environ, {"SOUL_AUTO_VOICE_REPLY": "0"}, clear=False):
        assert not AV.enabled()


def test_device_confirmation_parser():
    def fake_sql(dev, dbname, sql, timeout=15, ok=None):
        if ok is not None:
            ok["v"] = True
        return "1001|5|9999999999999"

    with mock.patch("data.imdb._db_name_for_uid", return_value="x-DATA.db"), \
            mock.patch("data.imdb._dev_sql", side_effect=fake_sql) as sql:
        ok, reason = AV._device_voice_confirmed(object(), "1001", "2002", 1)
        assert ok
        assert reason == "msgType5-confirmed"
        assert "sessionId='2002'" in sql.call_args.args[2]


def test_send_voice_reply_confirmed_by_device_db():
    with tempfile.TemporaryDirectory() as td:
        pcm = Path(td) / "x.pcm"
        wav = Path(td) / "x.wav"
        pcm.write_bytes(b"pcm")
        wav.write_bytes(b"wav")

        def fake_sql(dev, dbname, sql, timeout=15, ok=None):
            if ok is not None:
                ok["v"] = True
            return "1001|5|9999999999999"
        env = {"SOUL_AUTO_VOICE_REPLY": "1"}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("eyes.page.detect", return_value="chat"), \
                mock.patch("brain.ratelimit.can_send", return_value=True), \
                mock.patch("brain.ratelimit.note_sent") as note, \
                mock.patch("brain.sendgate.allow") as allow, \
                mock.patch("brain.sendgate.note_sent") as gate_note, \
                mock.patch("brain.voice_style.infer_from_db", return_value={}), \
                mock.patch("data.watch.mark_self_write"), \
                mock.patch("hands.tts.synthesize",
                           return_value={"path": str(pcm), "sample_rate": 24000}), \
                mock.patch("hands.audioout.pcm_to_wav", return_value=wav), \
                mock.patch("hands.audioout.wav_duration", return_value=1.25), \
                mock.patch("hands.audioout.play_wav") as play, \
                mock.patch("hands.voice.record_and_release",
                           side_effect=lambda actor, seconds, play=None: play()) as record, \
                mock.patch("data.imdb._db_name_for_uid", return_value="x-DATA.db"), \
                mock.patch("data.imdb._dev_sql", side_effect=fake_sql):
            allow.return_value.ok = True
            allow.return_value.reason = ""
            out = AV.send_voice_reply(_Actor(), _DB(), "2002", ["你好", "听得到吗"], kind="voice")
            assert out["sent"]
            assert out["text"] == "你好，听得到吗"
            assert out["voice_db"] == "msgType5-confirmed"
            record.assert_called_once()
            play.assert_called_once()
            note.assert_called_once()
            gate_note.assert_called_once_with("2002", 1)


def main():
    test_gate_and_text()
    test_device_confirmation_parser()
    test_send_voice_reply_confirmed_by_device_db()
    print("PASS t_auto_voice")


if __name__ == "__main__":
    main()
