# -*- coding: utf-8 -*-
"""Offline contract for history-derived TTS voice instructions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import voice_style as S  # noqa: E402


def main():
    sad = S.infer(["今天真的有点难过", "睡不着", "想哭"], voice_duration=5.0,
                  voice_chars=8)
    assert sad["mood"] == "soothing"
    assert sad["speech_rate"] < 0
    assert "心疼" in sad["instruction"]

    flirty = S.infer(["你是不是想我了", "抱抱", "陪我一会儿"], voice_duration=3.0,
                     voice_chars=12)
    assert flirty["mood"] == "flirty"
    assert flirty["speech_rate"] > -8
    assert "暧昧" in flirty["instruction"]

    sichuan = S.infer(["今天巴适得很", "你晓得啥子嘛", "要不要得"], voice_duration=4.0,
                      voice_chars=14)
    assert sichuan["dialect"] == "四川话"
    assert "四川话" in sichuan["instruction"]

    single = S.infer(["晓得了，知道啦"], voice_duration=3.0, voice_chars=6)
    assert single["dialect"] == ""

    print("PASS t_voice_style")


if __name__ == "__main__":
    main()
