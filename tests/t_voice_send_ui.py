# -*- coding: utf-8 -*-
"""Offline contract for the current Soul voice-recording review controls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eyes.uitree import Node  # noqa: E402
from hands import voice as V  # noqa: E402


class _Snap(object):
    def __init__(self, nodes):
        self.nodes = nodes


class _U2(object):
    def __init__(self):
        self.calls = []

    def long_click(self, x, y, duration=0.5):
        self.calls.append((x, y, duration))


class _Dev(object):
    def __init__(self):
        self._u2 = _U2()

    def u2(self):
        return self._u2


class _Actor(object):
    def __init__(self, snap):
        self._snap = snap
        self.dev = _Dev()


def _n(res, bounds=(0, 0, 10, 10)):
    return Node(res_id=res, bounds=bounds)


def main():
    preview = _Snap([
        _n("cn.soulapp.android:id/c_ct_new_normal_record_view2"),
        _n("cn.soulapp.android:id/rlVoiceContainer"),
        _n("cn.soulapp.android:id/btn_delete"),
        _n("cn.soulapp.android:id/btnChangeText"),
    ])
    controls = V.review_controls(preview)
    assert controls == {
        "overlay": True,
        "play": True,
        "cancel": True,
        "to_text": True,
    }
    try:
        V.send_reviewed(preview)
    except V.VoiceSendUnconfirmed as exc:
        assert "没有暴露独立发送控件" in str(exc)
    else:
        raise AssertionError("未确认发送手势时不应发送")

    mode = _Snap([
        _n("cn.soulapp.android:id/audio_mode_container"),
        _n("cn.soulapp.android:id/audio_record_view_optimize", (200, 300, 300, 400)),
    ])
    actor = _Actor(mode)
    actor.snap = lambda force=False: mode
    played = []
    out = V.record_and_release(
        actor, 1.0, play=lambda: played.append("ok"))
    assert len(actor.dev.u2().calls) == 1
    x, y, hold = actor.dev.u2().calls[0]
    assert (x, y) == (250, 350)
    assert hold >= 1.45
    assert played == ["ok"]
    assert out["error"] is None

    from hands import audioout as A
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        pcm = Path(td) / "x.pcm"
        pcm.write_bytes(b"\x00\x00" * 2400)
        wav = A.pcm_to_wav(pcm, sample_rate=24000)
        assert wav.is_file()
        assert abs(A.wav_duration(wav) - 0.1) < 0.001
    print("PASS t_voice_send_ui")


if __name__ == "__main__":
    main()
