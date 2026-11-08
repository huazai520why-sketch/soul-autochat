# -*- coding: utf-8 -*-
# 由 E:/soul2.1/db/soul_asr.py 移植（逻辑不变）。
# 为什么是 db/ 而不是 brain/：db/ 那份才带 transcribe_url + download_root，
# 1.0 的 voice.py 调的就是 transcribe_url；brain/ 里那份是旧副本（无此函数）。
# 模型随 __file__ 推导：ROOT = E:/soul1.0 → E:/soul1.0/models/whisper。
"""soul_asr —— 语音消息本地转写（faster-whisper small，CPU int8）。

背景（2026-11-01 实测）：
    Soul 语音消息(msgType=5) 的 msgContent 里 `word` 是 App 自带转写，
    但 **47 条语音里 42 条 word 为空（89%）**。旧逻辑 word 空 → `continue`
    → 她的语音被当成「没人说话」整条丢弃（必回原则被破坏）。

本模块给 `_voice_text()` 做兜底：word 空时用 `url` 下载音频自己转。
    实测 3~6s 语音：small 约 5.8~6.3s/条（准确），base 约 1.6s（会错字）。
    准确优先选 small —— 历史累计语音只有 47 条，频率低，负担可接受。

设计约束：
    · 懒加载模型（首次调用才 import + 加载，不拖慢 daemon 启动）
    · 内存 + 磁盘双缓存（同一 url 只转一次）
    · 全程吞异常、超时兜底，任何失败都返回 ""，绝不影响回复主流程
    · 开关：SOUL_ASR=0 关闭

音频格式（实测两种都有）：
    · 部分 .m4a 实际是 RIFF/WAVE 16k mono —— 直接 wave 读，最快
    · 部分是真 m4a(AAC) —— 用 PyAV 解码到 16k mono float32
"""
import os
import io
import json
import time
import wave
import ssl
import hashlib
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "voice_cache")
MODEL_DIR = os.path.join(ROOT, "models", "whisper")

ENABLED = os.environ.get("SOUL_ASR", "1") != "0"
MODEL_SIZE = os.environ.get("SOUL_ASR_MODEL", "small")
MAX_SECONDS = float(os.environ.get("SOUL_ASR_TIMEOUT", "30"))

# 简体引导（实测：不加这句 small 会输出繁体「選好了已經」）
PROMPT = "以下是普通话的句子，请用简体中文输出。"

_MODEL = None
_MODEL_DEAD = False
_MEM = {}          # url -> text
_SEEN = {"hit": 0, "asr": 0, "fail": 0}


def _log(msg):
    try:
        print("  [asr] %s" % msg, flush=True)
    except Exception:
        pass


def stats():
    return dict(_SEEN)


def _load_model():
    global _MODEL, _MODEL_DEAD
    if _MODEL is not None:
        return _MODEL
    if _MODEL_DEAD:
        return None
    try:
        t0 = time.time()
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(
            MODEL_SIZE, device="cpu", compute_type="int8", download_root=MODEL_DIR
        )
        _log("模型 %s 加载完成 %.1fs" % (MODEL_SIZE, time.time() - t0))
        return _MODEL
    except Exception as e:
        _MODEL_DEAD = True
        _log("模型加载失败（本次进程内不再尝试）: %r" % (e,))
        return None


def _to_array(raw):
    """字节 → float32 16k mono。RIFF 直读，其余走 PyAV。"""
    import numpy as np

    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        with wave.open(io.BytesIO(raw), "rb") as w:
            ch = w.getnchannels()
            rate = w.getframerate()
            width = w.getsampwidth()
            frames = w.readframes(w.getnframes())
        if width != 2:
            raise ValueError("sampwidth=%d 非16bit" % width)
        a = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        if rate != 16000:
            idx = np.linspace(0, len(a) - 1, int(len(a) * 16000 / rate))
            a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
        return a

    import av
    parts = []
    with av.open(io.BytesIO(raw)) as c:
        st = next((s for s in c.streams if s.type == "audio"), None)
        if st is None:
            raise ValueError("无音频流")
        rs = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for fr in c.decode(st):
            for o in rs.resample(fr):
                parts.append(o.to_ndarray().reshape(-1))
    if not parts:
        raise ValueError("解码无输出")
    return np.concatenate(parts).astype(np.float32)


def _cache_path(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode("utf-8")).hexdigest() + ".txt")


def _cache_get(url):
    if url in _MEM:
        return _MEM[url]
    try:
        p = _cache_path(url)
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                t = f.read().strip()
            _MEM[url] = t
            return t
    except Exception:
        pass
    return None


def _cache_put(url, text):
    _MEM[url] = text
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with io.open(_cache_path(url), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    if len(_MEM) > 500:
        _MEM.clear()


def transcribe_url(url, timeout=20):
    """语音 url → 简体文本；任何失败返回 ""（调用方按原逻辑处理）。"""
    if not ENABLED or not url:
        return ""
    if not str(url).startswith("http"):
        return ""

    got = _cache_get(url)
    if got is not None:
        _SEEN["hit"] += 1
        return got

    m = _load_model()
    if m is None:
        return ""

    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            raw = r.read()
    except Exception as e:
        _SEEN["fail"] += 1
        _log("下载失败: %r" % (e,))
        return ""

    try:
        audio = _to_array(raw)
    except Exception as e:
        _SEEN["fail"] += 1
        _log("解码失败(%dB): %r" % (len(raw), e))
        return ""

    if len(audio) < 1600:          # <0.1s 当成空音频
        _SEEN["fail"] += 1
        return ""

    try:
        segs, _info = m.transcribe(
            audio, language="zh", beam_size=1, vad_filter=False,
            without_timestamps=True, initial_prompt=PROMPT,
        )
        text = "".join(s.text for s in segs).strip()
    except Exception as e:
        _SEEN["fail"] += 1
        _log("转写异常: %r" % (e,))
        return ""

    el = time.time() - t0
    if not text:
        _SEEN["fail"] += 1
        _log("转写为空（%.1fs / %.1fs 音频）" % (el, len(audio) / 16000.0))
        return ""

    _SEEN["asr"] += 1
    _log("%.1fs 音频 → %r（%.1fs）" % (len(audio) / 16000.0, text, el))
    _cache_put(url, text)
    return text
