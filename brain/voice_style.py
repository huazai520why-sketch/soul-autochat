# -*- coding: utf-8 -*-
"""根据聊天上下文生成 TTS 语音指令。

只决定“怎么说”，不改回复内容。输出给豆包 TTS 2.0 的
`req_params.additions.context_texts`，支持情绪、语气、语速和方言。
"""
_DIALECTS = (
    ("四川话", ("巴适", "安逸", "啥子", "咋个", "莫得", "要得", "晓得",
              "摆龙门阵", "龙门阵", "瓜娃子", "铲铲", "哦豁", "得行")),
    ("东北话", ("咋整", "唠嗑", "老铁", "整挺好", "干哈", "啥玩意儿",
              "埋汰", "磕碜", "得瑟")),
    ("北京话", ("倍儿", "甭", "得嘞", "胡同", "您猜怎么着", "麻利儿")),
    ("上海话", ("阿拉", "侬", "晓得伐", "白相")),
    ("粤语", ("唔该", "冇", "点解", "系唔系", "嘅", "咩")),
)

_SAD = ("想哭", "哭了", "难过", "委屈", "失眠", "睡不着", "心情不好", "烦",
        "崩溃", "压力", "累死", "好累")
_FLIRTY = ("想你", "抱抱", "亲亲", "喜欢你", "暧昧", "陪我", "宝贝", "老公",
           "老婆", "想见你", "心动", "撩")
_PLAYFUL = ("哈哈", "笑死", "好玩", "逗你", "哼", "调皮", "嘿嘿", "乐死",
            "傻瓜", "笨蛋")
_SERIOUS = ("生气", "吵架", "凭什么", "烦你", "别理我", "过分", "失望",
            "讨厌", "滚")
_TIRED = ("晚安", "睡了", "困了", "好累", "下班", "熬夜", "不想睡")


def _recent(texts, k):
    return [str(x or "").strip() for x in (texts or []) if str(x or "").strip()][-k:]


def _detect_dialect(history):
    """只有持续出现方言词才切换，单次口头禅不触发。"""
    counts = []
    for name, words in _DIALECTS:
        n = 0
        for text in history:
            n += sum(1 for word in words if word in text)
        if n:
            counts.append((n, name))
    if not counts:
        return "", ""
    counts.sort(reverse=True)
    if counts[0][0] < 2:
        return "", ""
    return counts[0][1], "检测到持续方言词：%s" % counts[0][1]


def _voice_rate(voice_duration, voice_chars):
    """用她最近语音的“字数/秒”轻微跟随节奏，不机械照搬。"""
    try:
        duration = float(voice_duration or 0)
        chars = int(voice_chars or 0)
    except Exception:
        return 0, ""
    if duration <= 0 or chars <= 0:
        return 0, ""
    cps = chars / duration
    if cps >= 5.0:
        return 5, "她语音节奏偏快"
    if cps <= 2.2:
        return -5, "她语音节奏偏慢"
    return 0, "她语音节奏自然"


def infer(her_texts, voice_duration=None, voice_chars=None):
    """返回 {instruction, speech_rate, mood, dialect, reason}。"""
    history = _recent(her_texts, 10)
    recent = " ".join(history[-5:])
    last = history[-1] if history else ""
    mood = "neutral"
    rate = 0
    reason = "普通聊天"
    style = "像真人发微信语音，自然、口语，不要播音腔"

    if any(x in recent for x in _SAD):
        mood, rate = "soothing", -8
        reason = "她最近有难过/失眠/委屈信号"
        style = "语气温柔、心疼，放慢一点，轻声陪伴，不要热情过头"
    elif any(x in recent for x in _SERIOUS):
        mood, rate = "serious", -3
        reason = "她最近有明显生气/冲突信号"
        style = "语气认真、克制、真诚，不要嬉皮笑脸，也不要像客服道歉"
    elif any(x in recent for x in _FLIRTY):
        mood, rate = "flirty", -4
        reason = "她最近有暧昧/想念/亲密信号"
        style = "带一点暧昧和笑意，声音放低，像靠近了说话，但不要油腻"
    elif any(x in recent for x in _PLAYFUL):
        mood, rate = "playful", 2
        reason = "她最近有玩笑/逗趣信号"
        style = "轻松、带笑、略带调侃，节奏自然，不要夸张表演"
    elif any(x in recent for x in _TIRED) or len(last) <= 4:
        mood, rate = "tender_short", -4
        reason = "她最近偏累/偏短回复"
        style = "温和轻声，短句自然收住，不拖腔，不强行热络"

    pace, pace_reason = _voice_rate(voice_duration, voice_chars)
    if pace:
        rate = max(-12, min(12, rate + pace))
        reason = reason + "；" + pace_reason

    dialect, dialect_reason = _detect_dialect(history)
    if dialect:
        style += "；用自然的%s口音，只带一点地方味，不要刻意夸张" % dialect
        reason = reason + "；" + dialect_reason

    return {
        "instruction": style,
        "speech_rate": rate,
        "mood": mood,
        "dialect": dialect,
        "reason": reason,
    }


def infer_from_db(db, sid, limit=16):
    """从真实会话提取她的文本；语音走同一 ASR 缓存。"""
    from brain import voice as V

    rows = db.messages(sid, limit=limit)
    her, last_voice_text, last_voice_duration = [], "", 0
    for msg in rows:
        if str(msg.sender) == str(db.uid):
            continue
        text, how = V.her_msg_of(msg, db=db, sid=sid)
        if text and how != "tip":
            her.append(text)
        if V.is_voice(msg):
            last_voice_text = text or ""
            last_voice_duration = V.duration(msg)
    return infer(her, voice_duration=last_voice_duration,
                 voice_chars=len(last_voice_text))


__all__ = ["infer", "infer_from_db"]
