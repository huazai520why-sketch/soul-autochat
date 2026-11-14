# -*- coding: utf-8 -*-
"""语音消息：把「她发来的语音」变成可以回复的文字。

🔴 为什么必须有这一层（用户 2026-11-02：「语音消息 这个一定要处理好」）：
   实测本号 48 条语音，`msgContent.word`（Soul 自带转写）**全部为空**。
   旧逻辑 `text` 空就 continue —— 她的语音会被当成「没人说话」整条丢掉，
   直接破坏「必回」这条最高优先级硬规则。

三层取值：
   ① `msgContent.word` —— App 自带转写，有就直接用（0 成本）
   ② `soul_asr.transcribe_url(url)` —— 下载音频本地转写（faster-whisper small）
      实测 3~6s 语音约 5.8~6.3s/条，带内存 + 磁盘缓存，同一 url 只转一次
   ③ 都失败 → 返回占位串，**让上层照样回一句**，绝不允许静默跳过

语音消息结构（实测 2026-11-02，type=5）：
    msgContent = {"duration":5,"url":"https://china-chat-img.soulapp.cn/audio/....m4a",
                  "localUrl":"","word":"","mark":-1}
"""
import json
import sys
import time

from core.log import get_logger

log = get_logger("brain.voice")

VOICE_MT = 5
IMAGE_MT = 2      # 图片（msgContent 有 imageUrl/imageW/imageH，尺寸大）
EMOJI_MT = 8      # 表情包（同结构但尺寸小，URL 常含 expression）
TIP_MT = 35       # 小提示卡片（messageType=little_tip）→ 系统性质，**不该回**
PLACEHOLDER = "（她发来一条语音）"
IMAGE_PLACEHOLDER = "（她发来一张图片）"
EMOJI_PLACEHOLDER = "（她发来一个表情）"
OTHER_PLACEHOLDER = "（她发来一条消息）"

_ASR = None


class _VoicePayload(object):
    __slots__ = ("msg_type", "content", "text", "ts", "sender", "msg_id")

    def __init__(self, content="", ts=0, sender="", msg_id=""):
        self.msg_type = VOICE_MT
        self.content = content or ""
        self.text = ""
        self.ts = int(ts or 0)
        self.sender = sender
        self.msg_id = msg_id


def asr():
    """懒加载 ASR（模型在 E:/soul1.0/models/whisper，随 brain/asr.py 的 __file__ 推导）。"""
    global _ASR
    if _ASR is not None:
        return _ASR or None
    try:
        from brain import asr as soul_asr
    except Exception as e:
        log.warning("ASR 模块加载失败（语音只能靠 App 转写）: %r", e)
        _ASR = False
        return None
    _ASR = soul_asr
    log.info("ASR 已加载（模型目录 %s）", getattr(soul_asr, "MODEL_DIR", "?"))
    return _ASR


def content(msg):
    """解析 msgContent JSON；坏数据返回 {}。"""
    raw = getattr(msg, "content", "") or ""
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def is_voice(msg):
    return int(getattr(msg, "msg_type", 0) or 0) == VOICE_MT


def resolve_msg(msg, db=None, sid=None):
    """Return a voice message that still carries msgContent.

    `db.latest()` may return the session summary (`text='[语音]'`) instead of
    the chatmsg row. That summary has no URL/duration, so direct ASR cannot run.
    Fall back to the newest real type=5 chatmsg row for the same sid.
    """
    if not is_voice(msg):
        return msg
    d = content(msg)
    if (d.get("url") or d.get("word") or d.get("localUrl")):
        return msg
    if db is None or not sid:
        return msg
    try:
        row = db.con.execute(
            "SELECT msgContent,localTime,senderId,msgId FROM chatmsg "
            "WHERE sessionId=? AND msgType=5 AND msgContent IS NOT NULL "
            "AND msgContent != '' ORDER BY localTime DESC LIMIT 1",
            (str(sid),)).fetchone()
        if row:
            return _VoicePayload(row[0], row[1], row[2], row[3])
    except Exception as e:
        log.debug("语音消息内容回查失败 sid=%s: %r", sid, e)
    return msg


def duration(msg):
    try:
        return float(content(msg).get("duration") or 0)
    except Exception:
        return 0.0


def voice_text(msg, allow_asr=True, timeout=30, db=None, sid=""):
    """语音 → 文本。返回 (text, how)。

    how: "word" App 转写 / "asr" 本地转写 / "none" 都没拿到
    text 为 "" 时上层应使用 PLACEHOLDER 并照样回复。
    """
    msg = resolve_msg(msg, db=db, sid=sid)
    d = content(msg)
    w = (d.get("word") or "").strip()
    if w:
        return w, "word"

    url = (d.get("url") or "").strip()
    if not url or not allow_asr:
        return "", "none"

    a = asr()
    if a is None:
        return "", "none"
    t0 = time.time()
    try:
        t = (a.transcribe_url(url, timeout=timeout) or "").strip()
    except Exception as e:
        log.warning("语音转写异常: %r", e)
        t = ""
    dt = time.time() - t0
    if t:
        log.info("语音转写 %.1fs（%ds）: %r", dt, int(duration(msg)), t[:30])
        return t, "asr"
    log.warning("语音转写失败（%.1fs，%ds）", dt, int(duration(msg)))
    return "", "none"


def kind_of(msg):
    """消息大类：text / voice / image / emoji / tip / other。"""
    t = int(getattr(msg, "msg_type", 0) or 0)
    if t == 1:
        return "text"
    if t == VOICE_MT:
        return "voice"
    if t == IMAGE_MT:
        return "image"
    if t == EMOJI_MT:
        return "emoji"
    if t == TIP_MT:
        return "tip"
    return "other"


def image_url(msg):
    """图片消息取公网图片 URL；取不到返回 ""。

    实测图片消息 msgContent = {"imageH":1220,"imageUrl":"https://china-chat-img.soulapp.cn/image/...","imageW":2712,"mark":-1}
    imageUrl 是公网可访问 URL，可直接传给方舟视觉模型（无需下载转 base64）。
    """
    d = content(msg)
    for k in ("imageUrl", "url", "image_url", "imgUrl"):
        v = (d.get(k) or "").strip()
        if v.startswith("http"):
            return v
    return ""


def her_msg_of(msg, allow_asr=True, db=None, sid=""):
    """给 flow / pendingq 用：把「她这一条」变成可回复的文本。

    返回 (text, how)。how 同时是消息大类，上层据此选话术：
      text  → 引擎按上下文出话
      voice → 引擎按转写内容出话
      image / emoji / other → **用固定话术**（占位符喂引擎容易编造）
      tip   → 系统提示卡片，上层应跳过（不该回）
    """
    k = kind_of(msg)
    if k == "text":
        return (getattr(msg, "text", "") or "").strip(), "text"
    if k == "voice":
        t, how = voice_text(msg, allow_asr=allow_asr, db=db, sid=sid)
        return (t, how) if t else (PLACEHOLDER, "none")
    if k == "image":
        return IMAGE_PLACEHOLDER, "image"
    if k == "emoji":
        return EMOJI_PLACEHOLDER, "emoji"
    if k == "tip":
        return "", "tip"
    return OTHER_PLACEHOLDER, "other"
