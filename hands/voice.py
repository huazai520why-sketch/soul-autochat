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

当前版本的可访问树没有暴露独立的“发送语音”控件。禁止盲点预览或按返回键猜测发送，
否则可能把空录音发给真人。等确认实际发送手势后再补最后一步。
"""
import time

from core.log import get_logger

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


def send_reviewed(*_args, **_kwargs):
    """发送动作尚未核准：可访问树里没有独立发送控件。"""
    raise VoiceSendUnconfirmed(
        "新版录音预览没有暴露独立发送控件；需确认实际发送手势后才能自动发送")


__all__ = [
    "VoiceSendUnconfirmed", "ensure_voice_mode", "start_hands_free",
    "pause", "cancel", "review_controls",
]
