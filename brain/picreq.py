# -*- coding: utf-8 -*-
"""她要是主动要照片，就发一张。

用户 2026-11-02：「对方要我的照片的话，我副机电脑桌面上有 123 那三张照片」。

判据设计原则：**宁可漏发，不可误发**。
  发错了是「她只想聊天，我甩了张自拍」——尴尬且不可撤回；
  漏发了只是少一次撩，下次她再提还会触发。
所以：
  ① 必须出现「明确指向我」的要图词（看看你 / 你的照片 / 发张自拍 / 你长啥样）
  ② 排除反向（我发你 / 你的照片真好看 / 我看看你的朋友圈…）
  ③ 同一个人 PIC_COOL_H 小时内只发一次（防她连问两次就发两张）
  ④ 发送失败不抛异常，降级为文字回复
"""
import json
import re
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("brain.picreq")

PIC_COOL_H = 12          # 同一个人多久内不重复发
BOOK = STATE / "pic_book.json"

# ① 强短语：自身就足够，不需要再判「你」
STRONG = ("发张你的照片", "发个你的照片", "发张照片", "发个照片",
          "发张自拍", "发个自拍", "来张照片", "来张自拍",
          "看看你长", "你长啥样", "你长什么样", "你长得啥样",
          "露个脸", "看看你本人", "你本人照片", "你的照片呢",
          "照片发我", "发我看看", "看看你照片", "发来看看")

# ② 弱判据：必须**同时**命中「指向你」和「图/脸」
YOU = ("你", "咱俩", "你自己")
WANT = ("照片", "自拍", "长啥样", "啥样子", "本人照", "真容", "长什么样", "样子", "看看你")

# ③ 反向：只有「我方动作」才拦（原来把「你的照片」也拦了，
#    结果「发张你的照片看看」被误伤 → 漏发）
# 反向/无关：我方动作、夸图、提第三方 —— 都不是「要我的照片」
BLOCK = ("我发你", "我发张", "我发个", "我发照片", "我给你发", "我发张给你",
         "朋友", "真好看", "挺好看", "好帅", "好漂亮")


def wants_pic(text):
    """她这句话是不是在要我的照片。"""
    t = (text or "").strip()
    if len(t) < 2 or len(t) > 60:
        return False
    if any(b in t for b in BLOCK):
        return False
    if any(k in t for k in STRONG):
        return True
    return any(k in t for k in YOU) and any(k in t for k in WANT)


def _load():
    try:
        return json.loads(BOOK.read_text("utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        BOOK.parent.mkdir(parents=True, exist_ok=True)
        BOOK.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("保存发图台账失败: %r", e)


def can_send(sid):
    """这个人最近没发过图。"""
    rec = _load().get(str(sid)) or {}
    ts = float(rec.get("ts") or 0)
    if ts and (time.time() - ts) < PIC_COOL_H * 3600:
        return False, "%.1f 小时前发给过这个人" % ((time.time() - ts) / 3600)
    return True, ""


def note_sent(sid, idx):
    d = _load()
    d[str(sid)] = {"ts": time.time(), "idx": idx}
    # 顺手清 30 天前的
    cutoff = time.time() - 30 * 86400
    d = {k: v for k, v in d.items() if float((v or {}).get("ts") or 0) > cutoff}
    _save(d)


def pick_index(sid, total=3):
    """轮换发第几张（1 起）。"""
    rec = _load().get(str(sid)) or {}
    last = int(rec.get("idx") or 0)
    return (last % max(1, total)) + 1


def try_send(actor, dev, sid, text):
    """如果她要照片且能发，就发一张。返回 (sent, 说明)。

    调用点：flow 在出话之后、发文字之前。
    发图成功会**自己回到会话页**（pic.send 内部处理），调用方可以直接继续发文字。
    """
    if not wants_pic(text):
        return False, "不是在要照片"
    ok, why = can_send(sid)
    if not ok:
        return False, why
    from hands import pic as P
    idx = pick_index(sid)
    sent, msg = P.send_from_chat(actor, dev, index=idx)
    if sent:
        note_sent(sid, idx)
        log.info("📷 她要照片 → 已发第 %d 张", idx)
        return True, "已发第 %d 张" % idx
    log.warning("发图失败（%s）→ 降级为文字", msg)
    # 失败可能停在相册页，必须退回会话页，否则下面灌字会灌到相册里
    try:
        actor.hand.back(settle=1.0)
    except Exception:
        pass
    return False, msg
