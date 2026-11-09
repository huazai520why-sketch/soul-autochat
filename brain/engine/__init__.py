# -*- coding: utf-8 -*-
"""出话引擎（v10）：组装 → 调用 → 硬闸 → 返回 1~2 条。

对外只有一个入口 `respond()`。它**绝不抛异常**（必回链路最后一环，
历史上任何未捕获异常都会导致"她来信整轮不发"）。

设计要点：
  · 分层：换模型只改 llm.py，换人设改 persona.py，换规则改 rules.py，
    换组装顺序改 prompt.py，代码硬闸在 gate.py。
  · 硬闸在出话之后、发送之前；命中即丢弃该条，**不修补语义**。
  · 一条都不剩时不沉默：按 SOUL_ENGINE_FALLBACK 返回一句安全兜底，
    由调用方决定发不发（默认返回 None，交给上层 pendingq 的重试）。
"""
import os
import re

from . import gate
from . import llm
from . import persona
from . import rules
from . import prompt
from brain.pack import store

MAX_N = int(os.environ.get("SOUL_MAX_SEND", "2") or 2)


def recent_mine(sid, n=4):
    """她这个会话里我最近发过的 n 条（防复读基线）。"""
    t = store.read_turns(sid, limit_chars=6000)
    out = []
    for ln in t.splitlines():
        if " 我: " in ln:
            out.append(ln.split(" 我: ", 1)[1].strip())
    return out[-n:]


def _call(system, user, her_msg, sid=""):
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    return llm.ark_chat(msgs, her_msg=her_msg, sid=sid)


def respond(her_msg, sid="", hist=None, restart_h=0.0, max_n=None):
    """返回 [要发的句子]（1~max_n 条）；拿不到返回 None。

    参数与旧 `brain_reply` 对齐，方便 reply.py 平替。
    """
    max_n = max_n or MAX_N
    her_msg = (her_msg or "").strip()
    try:
        system, user, meta = prompt.build(her_msg, sid=sid, hist=hist,
                                          restart_h=restart_h)
    except Exception as e:
        llm.log.warning("prompt 组装失败: %r", e)
        return None

    raw = _call(system, user, her_msg, sid)
    if not raw:
        return None

    cands = gate.to_messages(raw, max_n)
    if not cands:
        return None

    recent = []
    if sid:
        try:
            recent = recent_mine(sid)
        except Exception:
            recent = []

    passed, dropped = [], []
    for c in cands:
        ok, why = gate.check(c, recent)
        if ok:
            passed.append(c)
        else:
            dropped.append((c[:30], why))
    if dropped:
        llm.log.info("[闸] 丢弃 %d 条: %s", len(dropped), dropped)

    if passed:
        return passed

    # 全被拦 → 重试一次，明确压低风险（只重试一次，不做无限循环）
    #
    # 🔴 2026-11-08 改（_report/11 §0⑦ 实证）：旧指令是
    #     「换一句。不要问句，不要提邀约，不要承诺，不超过 16 字。」
    #   这三条禁令合起来**正好等于「嗯，好，行」** —— 不能问、不能邀、不能承诺，
    #   又限 16 字，模型唯一的安全解就是一句没有信息的应答。实测这类句子
    #   （「在呢，刚看到你说的」17 次）正是**头号灭火句**。
    #   新指令改成**正向**给一个动作：换画面、压到 12 字、允许半句。
    #   依据：offer 型问句保持热度 37.5%，单独陈述句只有 7.3% ——
    #   所以要求的不是「别问」，而是「问就问你给得起的东西」。
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": raw[:200]},
            {"role": "user",
             "content": "换一个具体画面。不超过 12 字。可以说半句，不用完整。"
                        "如果还是想问，就问「我要不要给你点啥」这种给得起的东西，"
                        "别问她会怎么想。"}]
    raw2 = llm.ark_chat(msgs, her_msg=her_msg, sid=sid, temperature=0.8)
    if raw2:
        for c in gate.to_messages(raw2, 1):
            ok, why = gate.check(c, recent)
            if ok:
                return [c]
    return None


def available():
    """引擎是否可用（有密钥即可；真实可用性由调用结果反映）。"""
    return bool(llm.ark_key())


def describe_image(image_url, timeout=25, question=""):
    """识图（flow 的图片消息路径调它）。"""
    return llm.describe_image(image_url, timeout=timeout, question=question)


def opening_line(sid="", nick="", hist=None, tags=None, common=None,
                 kind="wake", limit=18):
    """主动开场（match/wake 调它）。签名与旧引擎一致。"""
    from . import opener
    return opener.opening_line(sid=sid, nick=nick, hist=hist, tags=tags,
                               common=common, kind=kind, limit=limit)


def head_ban_line(n=8):
    from . import opener
    return opener.head_ban_line(n)


__all__ = ["respond", "available", "recent_mine", "describe_image",
           "opening_line", "head_ban_line",
           "persona", "rules", "prompt", "gate", "llm", "opener"]
