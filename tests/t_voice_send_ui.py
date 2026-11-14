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
    print("PASS t_voice_send_ui")


if __name__ == "__main__":
    main()
