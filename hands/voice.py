# -*- coding: utf-8 -*-
"""Soul 新版语音发送界面动作。

2026-11-14 实测，旧版“切语音模式后长按统一录音条”已经不够：

1. 文本模式点 `menu_tab_voice_inner_outside` 切到语音模式；
2. 语音模式同时存在 `tv_press_to_speak`（按住说话）和
   `audio_record_view_optimize`（录音）；
3. 点“录音”进入 `c_ct_new_normal_record_view2` 全屏录音层；
4. 录音中：`imvStatus` 暂停，`btn_delete` 取消；
5. 暂停/结束后：`rlVoiceContainer` 播放预览，`btn_delete` 取消，
   `btnChangeText` 转文字。

用户实测确认：按住“录音”按钮，松开时自动发送。`record_and_release()` 走这条主路径。
暂停后的预览态仍没有独立发送控件，禁止盲点预览或按返回键猜测发送。
"""
import time
import threading

from core.log import get_logger
from core.device import note_action

log = get_logger("hands.voice")

VOICE_TOGGLE = "menu_tab_voice_inner_outside"
VOICE_MODE = "audio_mode_container"
PRESS_TO_SPEAK = "tv_press_to_speak"
RECORD = "audio_record_view_optimize"
RECORD_OVERLAY = "c_ct_new_normal_record_view2"
RECORD_PAUSE = "imvStatus"
RECORD_CANCEL = "btn_delete"
RECORD_PLAY = "rlVoiceContainer"
RECORD_TO_TEXT = "btnChangeText"


class VoiceSendUnconfirmed(RuntimeError):
    pass


def _node(snap, suffix):
    for node in snap.nodes:
        if node.res_id and node.res_id.endswith(suffix) and node.visible:
            return node
    return None


def _wait(actor, suffix, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        snap = actor.snap(force=True)
        node = _node(snap, suffix)
        if node is not None:
            return snap, node
        time.sleep(0.25)
    return actor.snap(force=True), None


def ensure_voice_mode(actor):
    """确保当前聊天页在语音输入模式，返回 (snap, changed)。"""
    snap = actor.snap(force=True)
    if _node(snap, VOICE_MODE) is not None:
        return snap, False
    toggle = _node(snap, VOICE_TOGGLE)
    if toggle is None:
        return snap, False
    actor.hand.tap_node(toggle, settle=0.7)
    snap, _ = _wait(actor, VOICE_MODE, timeout=4.0)
    return snap, True


def start_hands_free(actor):
    """新版“录音”按钮：进入全屏录音层。"""
    snap, _ = ensure_voice_mode(actor)
    rec = _node(snap, RECORD)
    if rec is None:
        raise VoiceSendUnconfirmed("语音模式里没有 audio_record_view_optimize")
    actor.hand.tap_node(rec, settle=0.8)
    snap, overlay = _wait(actor, RECORD_OVERLAY, timeout=4.0)
    if overlay is None:
        raise VoiceSendUnconfirmed("点击录音后没有进入 c_ct_new_normal_record_view2")
    log.info("新版语音录音已开始")
    return snap


def pause(actor):
    """暂停录音，进入可播放/可取消/可转文字的预览态。"""
    snap = actor.snap(force=True)
    btn = _node(snap, RECORD_PAUSE)
    if btn is None:
        raise VoiceSendUnconfirmed("录音态没有 imvStatus")
    actor.hand.tap_node(btn, settle=0.8)
    snap, play = _wait(actor, RECORD_PLAY, timeout=3.0)
    if play is None:
        raise VoiceSendUnconfirmed("暂停后没有进入录音预览态")
    log.info("语音录音已暂停并进入预览")
    return snap


def cancel(actor):
    """取消录音/预览，优先点 btn_delete；不在未知页面按返回键。"""
    snap = actor.snap(force=True)
    if _node(snap, RECORD_OVERLAY) is None:
        return snap
    btn = _node(snap, RECORD_CANCEL)
    if btn is None:
        raise VoiceSendUnconfirmed("录音层没有 btn_delete，拒绝盲按返回键")
    actor.hand.tap_node(btn, settle=0.8)
    return actor.snap(force=True)


def review_controls(snap):
    """返回当前录音预览可确认的控件。"""
    return {
        "overlay": _node(snap, RECORD_OVERLAY) is not None,
        "play": _node(snap, RECORD_PLAY) is not None,
        "cancel": _node(snap, RECORD_CANCEL) is not None,
        "to_text": _node(snap, RECORD_TO_TEXT) is not None,
    }


def record_and_release(actor, speech_seconds, play=None, lead=0.35,
                       control=PRESS_TO_SPEAK):
    """按住“按住说话”按钮，播完音频后松开；新版 UI 松开自动发送。

    `play` 是同步可调用对象，会在线程里启动，避免阻塞长按。
    右下角“录音”会进入持续录音层，不能用于松手发送；默认目标是左侧
    `tv_press_to_speak`。
    """
    snap, _ = ensure_voice_mode(actor)
    rec = _node(snap, control)
    if rec is None:
        raise VoiceSendUnconfirmed("语音模式里没有按住说话控件 %s" % control)
    hold_s = max(1.0, float(speech_seconds or 0) + float(lead) + 0.45)
    result = {"play": None, "error": None}

    def _play_later():
        try:
            time.sleep(float(lead))
            if play is not None:
                result["play"] = play()
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=_play_later, name="voice-audio", daemon=True)
    thread.start()
    note_action()
    # 2026-11-14 夜审修复（D3，P1）：u2 的 HTTP 调用无超时，长按几十秒期间
    #   设备卡死/掉线会把主流程无限期挂死（与已发生两次的「u2 无超时挂死」
    #   同类缺口）。手势放线程里跑 + join 预算兜底；超时按未确认失败处理。
    click_result = {"error": None}

    def _click():
        try:
            actor.dev.u2().long_click(rec.center[0], rec.center[1], duration=hold_s)
        except Exception as exc:
            click_result["error"] = exc

    click_thread = threading.Thread(target=_click, name="voice-hold", daemon=True)
    click_thread.start()
    click_thread.join(timeout=hold_s + 15.0)
    if click_thread.is_alive():
        raise VoiceSendUnconfirmed("长按手势 %.1fs 未返回（设备疑似挂死）" % (hold_s + 15.0))
    if click_result["error"] is not None:
        raise VoiceSendUnconfirmed("按住录音失败: %r" % (click_result["error"],))
    thread.join(timeout=hold_s + 8.0)
    if thread.is_alive():
        raise VoiceSendUnconfirmed("录音期间音频播放线程未结束")
    if result["error"] is not None:
        raise VoiceSendUnconfirmed("录音期间播放失败: %r" % (result["error"],))
    log.info("按住录音 %.1fs 后松开（按新版 UI 应自动发送）", hold_s)
    return result


def send_reviewed(*_args, **_kwargs):
    """发送动作尚未核准：可访问树里没有独立发送控件。"""
    raise VoiceSendUnconfirmed(
        "新版录音预览没有暴露独立发送控件；需确认实际发送手势后才能自动发送")


__all__ = [
    "VoiceSendUnconfirmed", "ensure_voice_mode", "start_hands_free",
    "pause", "cancel", "review_controls", "record_and_release",
]
