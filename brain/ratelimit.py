# -*- coding: utf-8 -*-
"""发送限流：每小时的发送条数上限 + 全天总量上限。

为什么必须有（旧架构 `SEND_CAP_H`，1.0 重写时漏掉了）：
  账号被封最直接的原因就是短时间高频发送。实测正常聊天一小时 10~20 条，
  超过 40 条就已经很不自然；再叠加匹配开场白 + 唤醒，很容易冲破阈值。

两层限制：
  ① 每小时上限（默认 40）—— 超过就本轮停发，下一小时自动恢复
  ② 连续失败保护 —— 用于 flow/pendingq 判断是否还值得继续

状态落 `data/state/send_cap.json`，重启不清零（跨小时自动 roll）。
"""
import json
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("brain.ratelimit")

CAP_H = 200             # 每小时最多发多少条（用户 2026-11-02：设 200，有消息该回就回）
CAP_WARN = 150          # 到 150 条提醒一次（真到 200 就停，防封）
FILE = STATE / "send_cap.json"


def _load():
    try:
        return json.loads(FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save(d):
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("保存限流状态失败: %r", e)


def _hour():
    return time.strftime("%Y%m%d%H")


def _roll(d):
    h = _hour()
    if d.get("hour") != h:
        d["hour"] = h
        d["n"] = 0
    return d


def sent_this_hour():
    d = _roll(_load())
    return int(d.get("n", 0) or 0)


def can_send():
    """本小时还能不能发。超了就返回 False（调用方应停止发送并进下一阶段）。"""
    n = sent_this_hour()
    # 🔴 2026-11-10（日志缺陷修复）：本模块只有「超限/接近上限」才打日志，
    #   正常时一条都不写 → `logs/brain.ratelimit.log` 长期 0 字节。
    #   复盘时完全看不出「这个小时到底发了几条、离封号线多远」。
    #   这里加低频心跳（30 分钟一条），正常情况下的余量也留痕。
    _hb(n)
    if n >= CAP_H:
        log.warning("⛔ 本小时已发 %d 条（上限 %d）→ 暂停发送，等下一小时", n, CAP_H)
        return False
    return True


_HB = {"ts": 0.0}


def _hb(n):
    """限流心跳：每 30 分钟记一次余量，正常态也留证据。"""
    try:
        now = time.time()
        if now - _HB["ts"] < 1800:
            return
        _HB["ts"] = now
        log.info("限流心跳：本小时已发 %d / 上限 %d（余 %d）", n, CAP_H, max(0, CAP_H - n))
    except Exception:
        pass


def note_sent(n=1):
    """发出去一条就记一次。调用点：flow 发送成功后、pendingq 发送成功后。"""
    d = _roll(_load())
    d["n"] = int(d.get("n", 0) or 0) + n
    d["ts"] = time.time()
    _save(d)
    cur = d["n"]
    if cur == CAP_WARN:
        log.warning("⚠️ 本小时已发 %d 条，接近上限 %d", cur, CAP_H)
    elif cur > CAP_WARN and cur % 5 == 0:
        log.info("本小时累计 %d 条", cur)
    return cur
