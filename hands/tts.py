# -*- coding: utf-8 -*-
"""火山语音按量付费 TTS 客户端。

默认走新版控制台按量付费 HTTP Chunked 接口：
`doubao-seed-tts-2.0` -> X-Api-Resource-Id: `seed-tts-2.0`。
`ICL_` 开头的音色属于声音复刻 2.0，自动切换 `seed-icl-2.0`。

这里只负责把文本合成为本地音频，不发聊天消息，也不改模拟器音频路由。
"""
import base64
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.log import get_logger
from core.paths import BASE, STATE

log = get_logger("hands.tts")

DEFAULT_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_RESOURCE_ID = "seed-tts-2.0"
DEFAULT_SPEAKER = "zh_male_liufei_uranus_bigtts"
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 24000
MAX_TEXT = 2000


class TTSError(RuntimeError):
    pass


class TTSConfigError(TTSError):
    pass


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def api_key():
    """读取 Speech API Key；正文永不写日志。"""
    for name in ("SOUL_TTS_KEY", "SOUL_SPEECH_KEY", "SOUL_ARK_PLAN_KEY"):
        value = _env(name)
        if value:
            return value
    for rel in (".tts_key", "config/tts.key"):
        path = BASE / rel
        try:
            value = path.read_text(encoding="utf-8").strip()
        except Exception:
            value = ""
        if value:
            return value.splitlines()[0].strip()
    return ""


def available():
    return bool(api_key())


def resource_id_for_speaker(speaker):
    """按音色自动选择按量资源；显式配置非 auto 时以配置为准。"""
    explicit = _env("SOUL_TTS_RESOURCE_ID")
    if explicit and explicit.lower() != "auto":
        return explicit
    if (speaker or "").startswith("ICL_"):
        return "seed-icl-2.0"
    return DEFAULT_RESOURCE_ID


def _save_audio(data, output_dir=None, output_format=None):
    fmt = (output_format or _env("SOUL_TTS_FORMAT", DEFAULT_FORMAT)).lower()
    if fmt not in ("mp3", "pcm", "ogg_opus"):
        raise TTSConfigError("不支持的音频格式: %s" % fmt)
    suffix = ".ogg" if fmt == "ogg_opus" else "." + fmt
    out_dir = Path(output_dir) if output_dir else (STATE / "voice_out")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "tts-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:8])
    target = out_dir / (stem + suffix)
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(bytes(data))
        os.replace(str(part), str(target))
    finally:
        try:
            if part.exists():
                part.unlink()
        except Exception:
            pass
    return target


def synthesize(text, output_dir=None, speaker=None, output_format=None,
               sample_rate=None, timeout=None, style=None):
    """合成一段文本并返回结果字典。

    结果至少包含 `path`、`audio_bytes`、`log_id`、`usage`。
    服务端错误码、空音频和网络错误都会抛出 TTSError，绝不返回半成品。
    本函数会真实调用已计费的 TTS。
    """
    value = (text or "").strip()
    if not value:
        raise TTSConfigError("合成文本为空")
    if len(value) > MAX_TEXT:
        raise TTSConfigError("合成文本过长：%d > %d" % (len(value), MAX_TEXT))

    key = api_key()
    if not key:
        raise TTSConfigError(
            "缺少 Speech API Key：设置 SOUL_TTS_KEY，"
            "或写入项目根目录 .tts_key（一行）")

    url = _env("SOUL_TTS_URL", DEFAULT_URL)
    speaker = speaker or _env("SOUL_TTS_SPEAKER", DEFAULT_SPEAKER)
    resource_id = resource_id_for_speaker(speaker)
    output_format = output_format or _env("SOUL_TTS_FORMAT", DEFAULT_FORMAT)
    sample_rate = int(sample_rate or _env("SOUL_TTS_SAMPLE_RATE", str(DEFAULT_SAMPLE_RATE)))
    timeout = float(timeout or _env("SOUL_TTS_TIMEOUT", "30"))
    if timeout <= 0:
        raise TTSConfigError("TTS timeout 必须大于 0")

    payload = {
        "req_params": {
            "text": value,
            "speaker": speaker,
            "audio_params": {
                "format": output_format,
                "sample_rate": sample_rate,
            },
        },
    }
    style = dict(style or {})
    instruction = (style.get("instruction") or "").strip()
    if instruction:
        payload["req_params"]["additions"] = json.dumps(
            {"context_texts": [instruction]}, ensure_ascii=False)
    speech_rate = style.get("speech_rate")
    if speech_rate not in (None, "", 0):
        payload["req_params"]["audio_params"]["speech_rate"] = int(speech_rate)
    headers = {
        "X-Api-Key": key,
        "X-Api-Resource-Id": resource_id,
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "X-Control-Require-Usage-Tokens-Return": "*",
    }
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    audio = bytearray()
    usage = {}
    log_id = ""
    finished = False
    t0 = time.time()
    try:
        with urlopen(req, timeout=timeout) as resp:
            log_id = resp.headers.get("X-Tt-Logid") or resp.headers.get("x-tt-logid") or ""
            for raw in resp:
                line = (raw or b"").decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    item = json.loads(line)
                except Exception as exc:
                    raise TTSError("TTS 返回了非 JSON 响应片段: %r (%r)" % (line[:120], exc))
                code = item.get("code", 0)
                if code == 20000000:
                    finished = True
                    usage = item.get("usage") or usage
                    break
                if code and int(code) > 0:
                    raise TTSError(
                        "TTS 服务端失败 code=%s message=%s logid=%s"
                        % (code, item.get("message") or "", log_id))
                if item.get("data"):
                    audio.extend(base64.b64decode(item["data"]))
                if item.get("usage"):
                    usage = item["usage"]
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise TTSError(
            "TTS HTTP %s，logid=%s，body=%r"
            % (exc.code, exc.headers.get("X-Tt-Logid") or log_id, body))
    except URLError as exc:
        raise TTSError("TTS 网络错误: %r" % (exc,))

    if not finished:
        raise TTSError("TTS 流未收到成功终止码 20000000，logid=%s" % (log_id or "-"))
    if not audio:
        raise TTSError("TTS 未返回音频，logid=%s" % (log_id or "-"))
    path = _save_audio(audio, output_dir=output_dir, output_format=output_format)
    result = {
        "path": str(path),
        "audio_bytes": len(audio),
        "text_bytes": len(value.encode("utf-8")),
        "text_chars": len(value),
        "speaker": speaker,
        "sample_rate": sample_rate,
        "format": output_format,
        "log_id": log_id,
        "usage": usage,
        "elapsed_s": round(time.time() - t0, 2),
        "style": {
            "mood": style.get("mood") or "",
            "dialect": style.get("dialect") or "",
            "speech_rate": int(style.get("speech_rate") or 0),
            "instruction": instruction,
        },
    }
    log.info(
        "TTS 完成 speaker=%s chars=%d bytes=%d %.1fs logid=%s",
        speaker, len(value), len(audio), result["elapsed_s"], log_id or "-")
    return result


__all__ = [
    "TTSError", "TTSConfigError", "api_key", "available",
    "resource_id_for_speaker", "synthesize",
]
