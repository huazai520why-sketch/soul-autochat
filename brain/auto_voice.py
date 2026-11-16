# -*- coding: utf-8 -*-
"""自动语音回复：仅在对方上一条是语音时，把本轮文字回复合成为一条语音。

默认关闭，设置 SOUL_AUTO_VOICE_REPLY=1 后启用。成功条件不是“点完了”，而是
设备实时库里出现 sender=本人、msgType=5 的新消息；确认不到时不补发文字，
避免同一句话同时以语音和文字重复打扰。
"""
import os
import time

from core.log import get_logger

log = get_logger("brain.auto_voice")

MAX_VOICE_CHARS = 500
CONFIRM_TIMEOUT_S = 14.0


def _truthy(name, default=False):
    value = (os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on", "y")


def enabled():
    return _truthy("SOUL_AUTO_VOICE_REPLY", False)


def should_reply(kind, sid):
    """当前只自动回语音消息；普通文字仍走文本链路。"""
    if not enabled() or not sid:
        return False
    if _truthy("SOUL_AUTO_VOICE_ALL", False):
        return True
    return str(kind or "") == "voice"


def voice_text(lines):
    """把本轮多条文字合成一条适合朗读的语音。"""
    clean = [str(x or "").strip() for x in (lines or []) if str(x or "").strip()]
    text = "，".join(clean)
    if len(text) > MAX_VOICE_CHARS and clean:
        text = clean[0]
    return text[:MAX_VOICE_CHARS]


def _right_voice_bubbles(snap):
    return len([
        n for n in getattr(snap, "nodes", [])
        if n.res_id and n.res_id.endswith("voice_bubble") and n.bounds[0] > 400
    ])


def _device_voice_confirmed(dev, uid, sid, since_ms):
    """只读设备实时库，确认本人新语音已落库。"""
    from data import imdb as IM

    if not str(sid).isdigit():
        return False, "sid 非数字，拒绝拼 SQL"
    dbname = IM._db_name_for_uid(dev, str(uid), timeout=8)
    if not dbname:
        return False, "找不到当前账号设备库"
    sql = (
        "select senderId,msgType,localTime from chatmsg "
        "where sessionId='%s' order by localTime desc limit 1" % str(sid)
    )
    ok = {}
    raw = IM._dev_sql(dev, dbname, sql, timeout=8, ok=ok) or ""
    if not ok.get("v"):
        return False, "设备库查询失败"
    for line in raw.replace("\r", "").splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        sender, msg_type, local_time = (line.split("|", 2) + ["", "", ""])[:3]
        try:
            if (sender.strip() == str(uid) and int(msg_type or 0) == 5
                    and int(float(local_time or 0)) >= int(since_ms)):
                return True, "msgType5-confirmed"
        except (TypeError, ValueError):
            continue
    return False, "设备库未见本人 msgType=5：%s" % raw[:120]


def send_voice_reply(actor, db, sid, lines, kind="voice", nick=""):
    """发送一条自动语音并等待数据库落地确认。"""
    result = {
        "ok": False, "sent": False, "text": "", "err": "",
        "voice_db": "", "audio_seconds": 0.0, "wav": "",
    }
    if not should_reply(kind, sid):
        result["err"] = "自动语音未启用或不是语音会话"
        return result
    text = voice_text(lines)
    result["text"] = text
    if not text:
        result["err"] = "语音文本为空"
        return result

    from brain import ratelimit as RL
    from brain import sendgate as SG
    from brain import voice_style as VS
    from data import watch as W
    from eyes.page import detect
    from hands import audioout as AO
    from hands.input import Input
    from hands import tts as T
    from hands import voice as HV

    snap = actor.snap(force=True)
    if detect(snap) != "chat" and Input.box(snap) is None:
        result["err"] = "当前不在 chat 页"
        return result
    try:
        if not RL.can_send():
            result["err"] = "小时发送限流"
            return result
        gate = SG.allow(str(sid), 1, has_human=True)
        if not gate.ok:
            result["err"] = "跟进阶梯拦截：%s" % gate.reason
            return result
    except Exception as exc:
        log.debug("语音发送前置闸门异常（降级放行）: %r", exc)

    style = None
    try:
        style = VS.infer_from_db(db, str(sid))
    except Exception as exc:
        log.debug("语音风格推断失败，使用默认风格: %r", exc)

    try:
        W.mark_self_write(20.0)
        before_snap = actor.snap(force=True)
        before_bubbles = _right_voice_bubbles(before_snap)
        since_ms = int(time.time() * 1000) - 3000
        tts = T.synthesize(text, output_format="pcm", style=style)
        wav = AO.pcm_to_wav(tts["path"], sample_rate=tts["sample_rate"])
        seconds = AO.wav_duration(wav)
        result["audio_seconds"] = round(seconds, 2)
        result["wav"] = str(wav)
        HV.record_and_release(
            actor, seconds,
            play=lambda: AO.play_wav(wav, device_hint="VB-Audio"))
        log.info("[%s] 自动语音已执行录音手势，等待落库确认", nick or str(sid)[-6:])

        deadline = time.time() + CONFIRM_TIMEOUT_S
        ui_confirmed = False
        db_confirmed = False
        reason = ""
        while time.time() < deadline:
            snap = actor.snap(force=True)
            if _right_voice_bubbles(snap) > before_bubbles:
                ui_confirmed = True
            db_confirmed, reason = _device_voice_confirmed(
                actor.dev, db.uid, sid, since_ms)
            if db_confirmed:
                break
            time.sleep(1.0)

        result["voice_db"] = reason
        if not db_confirmed:
            result["err"] = "语音未得到 msgType=5 落库确认（UI=%s）：%s" % (
                ui_confirmed, reason)
            log.warning("[%s] %s", nick or str(sid)[-6:], result["err"])
            return result

        result["ok"] = True
        result["sent"] = True
        RL.note_sent()
        SG.note_sent(str(sid), 1)
        W.mark_self_write(15.0)
        log.info("[%s] 自动语音回复已确认：%.1fs，%r",
                 nick or str(sid)[-6:], seconds, text[:40])
        return result
    except (T.TTSError, HV.VoiceSendUnconfirmed, RuntimeError, OSError) as exc:
        result["err"] = "自动语音异常: %r" % (exc,)
        log.warning("[%s] %s", nick or str(sid)[-6:], result["err"])
        return result


__all__ = ["enabled", "should_reply", "voice_text", "send_voice_reply"]
