# -*- coding: utf-8 -*-
"""Windows 定向播放 WAV（用于送入 VB-Cable 的 CABLE Input）。"""
import ctypes
import sys
import time
import wave
from pathlib import Path
from ctypes import POINTER, Structure, byref, c_char, c_void_p, c_uint, c_ulong, c_ushort

from core.log import get_logger

log = get_logger("hands.audioout")

WHDR_DONE = 0x00000001
MAXPNAMELEN = 32


class _WaveFormat(Structure):
    _fields_ = [
        ("wFormatTag", c_ushort),
        ("nChannels", c_ushort),
        ("nSamplesPerSec", c_ulong),
        ("nAvgBytesPerSec", c_ulong),
        ("nBlockAlign", c_ushort),
        ("wBitsPerSample", c_ushort),
        ("cbSize", c_ushort),
    ]


class _WaveOutCaps(Structure):
    _fields_ = [
        ("wMid", c_ushort),
        ("wPid", c_ushort),
        ("vDriverVersion", c_uint),
        ("szPname", ctypes.c_wchar * MAXPNAMELEN),
        ("wFormats", c_ushort),
        ("wChannels", c_ushort),
        ("wReserved1", c_ushort),
        ("dwSupport", c_ulong),
    ]


class _WaveHdr(Structure):
    _fields_ = [
        ("lpData", c_void_p),
        ("dwBufferLength", c_ulong),
        ("dwBytesRecorded", c_ulong),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", c_ulong),
        ("dwLoops", c_ulong),
        ("lpNext", c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


def _winmm():
    if sys.platform != "win32":
        raise RuntimeError("定向播放仅支持 Windows")
    mm = ctypes.WinDLL("winmm", use_last_error=True)
    mm.waveOutGetNumDevs.restype = c_uint
    mm.waveOutGetDevCapsW.argtypes = [
        ctypes.c_size_t, POINTER(_WaveOutCaps), c_uint]
    mm.waveOutGetDevCapsW.restype = c_uint
    mm.waveOutOpen.argtypes = [
        POINTER(c_void_p), c_uint, POINTER(_WaveFormat),
        ctypes.c_size_t, ctypes.c_size_t, c_uint]
    mm.waveOutOpen.restype = c_uint
    mm.waveOutPrepareHeader.argtypes = [c_void_p, POINTER(_WaveHdr), c_uint]
    mm.waveOutPrepareHeader.restype = c_uint
    mm.waveOutWrite.argtypes = [c_void_p, POINTER(_WaveHdr), c_uint]
    mm.waveOutWrite.restype = c_uint
    mm.waveOutUnprepareHeader.argtypes = [c_void_p, POINTER(_WaveHdr), c_uint]
    mm.waveOutUnprepareHeader.restype = c_uint
    mm.waveOutClose.argtypes = [c_void_p]
    mm.waveOutClose.restype = c_uint
    return mm


def output_devices():
    mm = _winmm()
    out = []
    for i in range(int(mm.waveOutGetNumDevs())):
        caps = _WaveOutCaps()
        rc = mm.waveOutGetDevCapsW(i, byref(caps), ctypes.sizeof(caps))
        if rc == 0:
            out.append((i, caps.szPname))
    return out


def _find_device(hint):
    hint = (hint or "VB-Audio").lower()
    for idx, name in output_devices():
        if hint in name.lower():
            return idx, name
    raise RuntimeError("找不到音频输出设备 %r；可用=%r" % (hint, output_devices()))


def play_wav(path, device_hint="VB-Audio", gain=1.0):
    """同步播放 WAV 到指定 MME 输出设备，返回实际设备信息。"""
    if gain != 1.0:
        raise ValueError("gain 暂只支持 1.0")
    mm = _winmm()
    dev, name = _find_device(device_hint)
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError("定向播放只支持 16-bit PCM WAV")

    fmt = _WaveFormat(
        1, channels, rate, rate * channels * width,
        channels * width, 16, 0)
    handle = c_void_p()
    rc = mm.waveOutOpen(byref(handle), dev, byref(fmt), 0, 0, 0)
    if rc:
        raise RuntimeError("waveOutOpen rc=%s device=%r" % (rc, name))

    buf = (c_char * len(frames)).from_buffer_copy(frames)
    hdr = _WaveHdr(
        ctypes.cast(buf, c_void_p), len(frames), 0, 0, 0, 0, None, 0)
    try:
        rc = mm.waveOutPrepareHeader(handle, byref(hdr), ctypes.sizeof(hdr))
        if rc:
            raise RuntimeError("waveOutPrepareHeader rc=%s" % rc)
        rc = mm.waveOutWrite(handle, byref(hdr), ctypes.sizeof(hdr))
        if rc:
            raise RuntimeError("waveOutWrite rc=%s" % rc)
        timeout = max(5.0, len(frames) / float(rate * channels * width) + 5.0)
        t0 = time.time()
        while not (hdr.dwFlags & WHDR_DONE):
            if time.time() - t0 > timeout:
                raise RuntimeError("waveOut playback timeout")
            time.sleep(0.02)
    finally:
        # 2026-11-14 夜审修复（D9，P2）：超时/异常路径直接 Close 会因缓冲区
        #   仍在播放返回 WAVERR_STILLPLAYING 静默失败 → 句柄泄漏 + 旧音频继续
        #   送 VB-Cable 与下一通语音叠音。MME 协议要求 Close 前先 Reset+Unprepare。
        try:
            mm.waveOutReset(handle)
        except Exception:
            pass
        try:
            mm.waveOutUnprepareHeader(handle, byref(hdr), ctypes.sizeof(hdr))
        except Exception:
            pass
        mm.waveOutClose(handle)
    log.info("定向播放完成 device=%r bytes=%d", name, len(frames))
    return {"device_id": dev, "device": name, "bytes": len(frames)}


def pcm_to_wav(pcm_path, output_path=None, channels=1, sample_width=2,
               sample_rate=24000):
    """把火山 TTS 返回的裸 PCM 包成标准 WAV。"""
    src = Path(pcm_path)
    dst = Path(output_path) if output_path else src.with_suffix(".wav")
    data = src.read_bytes()
    if not data:
        raise RuntimeError("PCM 文件为空: %s" % src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as wf:
        wf.setnchannels(int(channels))
        wf.setsampwidth(int(sample_width))
        wf.setframerate(int(sample_rate))
        wf.writeframes(data)
    return dst


def wav_duration(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(max(1, wf.getframerate()))


__all__ = ["output_devices", "play_wav", "pcm_to_wav", "wav_duration"]
