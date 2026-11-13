# -*- coding: utf-8 -*-
"""出话冲突的离线契约测试（不调用模型、不发消息）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain import engine, flow
from brain.engine import brief, gate


def test_brief_contract():
    assert "**必须是问句**" not in brief.SYS
    assert "问句不是义务" in brief.SYS
    assert "她 ≤4 字" in brief.SYS
    assert "不提问、不追加" in brief.SYS


def test_short_reply_hard_contract():
    assert engine._short_her("嗯")
    assert engine._short_her("要得")
    assert engine._short_her("晚安")
    assert not engine._short_her("你在干嘛呀")
    assert engine._short_reply_ok("行，早点睡")
    assert not engine._short_reply_ok("明天见呀？")
    assert not engine._short_reply_ok("这句话我要好好接一下")


def test_fallback_pool_contract():
    for line in flow.FALLBACK_LINES:
        assert not gate.cold_ack_hit(line), line
    for line in flow.SHORT_FALLBACK_LINES:
        assert len(gate.clean(line)) <= 8
        assert "?" not in line and "？" not in line
        assert not gate.cold_ack_hit(line), line


def test_short_response_integration():
    """模拟首轮超长+问句，重试返回短句；最终只能得到一条≤8字回复。"""
    old_call = engine._call
    old_chat = engine.llm.ark_chat
    try:
        engine._call = lambda system, user, her_msg, sid="": (
            "我其实还想追着问一句，你到底怎么想的？\n再补一条"
        )
        engine.llm.ark_chat = lambda *a, **kw: "行，早点睡"
        out = engine.respond("嗯")
        assert out == ["行，早点睡"]
    finally:
        engine._call = old_call
        engine.llm.ark_chat = old_chat


if __name__ == "__main__":
    test_brief_contract()
    test_short_reply_hard_contract()
    test_fallback_pool_contract()
    test_short_response_integration()
    print("PASS t_outtalk_contract")
