# -*- coding: utf-8 -*-
"""跟进阶梯的会话水位线台账（obs §104 §6.5）。

为什么需要独立台账：
  * 现有 ``replied.json`` / ``pending_skip.json`` 都记「我回过哪一句」，
    拿不到「她末条人话之后我一共发过几条」——而 C1 的 2/6 条额度必须按**条数**算。
  * 实时库 pull 有 5 分钟延迟（REFRESH_S=300），等库同步再计数会重复发。
    所以**发送成功当场追加**（note_sent），不等库。
  * 系统消息不能推进 her_ts 水位线（C5），也不能触发冷却（C8），
    归档状态单独存一个字段，供 candidates() / wake.candidates() 双处排除（C4）。

文件：``data/state/reply_state.json``
    {sid: {"her_ts_ms": float, "sends": [ts, ...], "archived": bool,
           "sys_only": bool, "updated": float}}

所有 IO 都吞异常并打 WARNING：台账坏了只能降级成「放行」，绝不能把生产链路打断。
"""
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from core.log import get_logger
from core.paths import STATE

log = get_logger("data.reply_state")

FILE = STATE / "reply_state.json"
_LOCK = threading.RLock()
# 🔴 性能护栏：candidates() 每轮扫 300 个会话，若每次 get() 都读一遍 JSON，
#    单轮就要 300 次磁盘读（§100 已实测 candidates 最坏 29.75s）。
#    同进程内按 mtime_ns 缓存，文件被别的进程改过才重读。
_CACHE = {"mtime_ns": 0, "d": None}
KEEP_DAYS = 7
MAX_SESSIONS = 2000
MAX_SENDS = 24          # 单会话最多留 24 条发送时间戳（够覆盖 6 条 × 多回合）


def _blank() -> Dict[str, Any]:
    """一条空水位线记录。"""
    return {"her_ts_ms": 0.0, "sends": [], "archived": False,
            "sys_only": False, "updated": 0.0}


def _mtime_ns() -> int:
    """取台账文件的纳秒 mtime；不存在返回 0。"""
    try:
        return FILE.stat().st_mtime_ns
    except Exception:
        return 0


def load() -> Dict[str, Any]:
    """读全量台账（带同进程 mtime 缓存）；文件不存在/损坏返回 {}。

    Returns:
        {sid: rec} 的浅拷贝，调用方改动不会污染缓存。
    """
    mt = _mtime_ns()
    with _LOCK:
        if _CACHE["d"] is not None and _CACHE["mtime_ns"] == mt:
            return dict(_CACHE["d"])
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except Exception as e:
            log.warning("读 reply_state 失败（按空台账继续）: %r", e)
            d = {}
        _CACHE["d"] = d
        _CACHE["mtime_ns"] = mt
        return dict(d)


def _save(d: Dict[str, Any]) -> None:
    """原子写：临时文件 + os.replace，避免半截 JSON 把台账写坏。"""
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_name(FILE.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(FILE))
        with _LOCK:
            _CACHE["d"] = d
            _CACHE["mtime_ns"] = _mtime_ns()
    except Exception as e:
        log.warning("写 reply_state 失败（本轮计数可能丢失）: %r", e)


def _purge(d: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """清掉过期会话，防止台账无限膨胀。"""
    now = float(now if now is not None else time.time())
    cutoff = now - KEEP_DAYS * 86400.0
    out = {}
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        if float(v.get("updated") or 0) > cutoff:
            sends = v.get("sends") or []
            v["sends"] = [float(t) for t in sends[-MAX_SENDS:] if t]
            out[str(k)] = v
    if len(out) > MAX_SESSIONS:
        out = dict(sorted(out.items(), key=lambda kv: float(kv[1].get("updated") or 0),
                          reverse=True)[:MAX_SESSIONS])
    return out


def get(sid: str) -> Dict[str, Any]:
    """取单个会话的水位线（返回副本，改它不影响台账）。

    Args:
        sid: 会话 id。

    Returns:
        记录字典；不存在返回空记录。
    """
    if not sid:
        return _blank()
    with _LOCK:
        rec = load().get(str(sid)) or {}
    out = _blank()
    out.update(rec if isinstance(rec, dict) else {})
    out["sends"] = [float(t) for t in (out.get("sends") or []) if t]
    return out


def her_ts_of(sid: str) -> float:
    """她最后一条真人消息时间（毫秒）；无记录返回 0。"""
    return float(get(sid).get("her_ts_ms") or 0)


def sends_of(sid: str) -> List[float]:
    """本会话已记录的发送时刻（秒，升序）。"""
    return sorted(get(sid).get("sends") or [])


def on_her(sid: str, her_ts_ms: float, human: bool = True) -> None:
    """她来消息时更新水位线。

    Args:
        sid: 会话 id。
        her_ts_ms: 消息时间（毫秒）。
        human: 是否真人消息。False = 系统卡/广告：C5 要求**不更新 her_ts**、
            C8 要求**不冷却**，因此只标 sys_only，绝不清 sends、不改归档。

    Returns:
        None
    """
    if not sid:
        return
    with _LOCK:
        d = load()
        rec = dict(d.get(str(sid)) or _blank())
        if not human:
            # C8：系统消息只跳过、不冷却。连 archived 也不因系统卡解除。
            # 已标记过就不重复落盘（candidates 每轮都会扫到同一条系统卡）。
            if rec.get("sys_only"):
                return
            rec["sys_only"] = True
            rec["updated"] = time.time()
            d[str(sid)] = rec
            _save(_purge(d))
            return
        ts = float(her_ts_ms or 0)
        old = float(rec.get("her_ts_ms") or 0)
        # C2：她再发真人消息 → 回合重置（计数清零、回第 1 档、解除归档）。
        # 只有「更新的」消息才重置，库 pull 补进来的旧消息不能把计数洗掉。
        # 无变化直接返回：避免每轮 300 次无谓写盘。
        # sys_only 只在「更新的真人消息」到来时清除（上一分支已处理系统卡）。
        if ts <= old:
            return
        rec["her_ts_ms"] = ts
        rec["sends"] = []
        rec["archived"] = False
        rec["sys_only"] = False
        rec["updated"] = time.time()
        d[str(sid)] = rec
        _save(_purge(d))


def note_sent(sid: str, n: int = 1, ts: Optional[float] = None) -> None:
    """发送成功后追加 n 条发送时间戳（不等库 pull）。

    Args:
        sid: 会话 id；空表示无主会话（奇遇铃/匹配开场白），不记账。
        n: 本次实际发出的条数（按真实条数扣，不按轮次，§6.6-2）。
        ts: 发送时刻（秒），缺省 time.time()。

    Returns:
        None
    """
    if not sid or n <= 0:
        return
    with _LOCK:
        d = load()
        rec = dict(d.get(str(sid)) or _blank())
        now = float(ts if ts is not None else time.time())
        sends = [float(t) for t in (rec.get("sends") or []) if t]
        # 多条连发间隔 1.6s（flow._send_lines），给同一批 n 条各留一个可分辨的时刻，
        # 避免「同一秒 n 条」在滚动 24h 统计里被误当成一次。
        for i in range(int(n)):
            sends.append(now - 1.6 * max(0, int(n) - 1 - i))
        rec["sends"] = sends[-MAX_SENDS:]
        rec["sys_only"] = False
        rec["updated"] = now
        d[str(sid)] = rec
        _save(_purge(d))


def set_archived(sid: str, archived: bool = True) -> None:
    """标记/解除归档。归档≠拉黑：on_her(human=True) 会自动解除。"""
    if not sid:
        return
    with _LOCK:
        d = load()
        rec = dict(d.get(str(sid)) or _blank())
        rec["archived"] = bool(archived)
        rec["updated"] = time.time()
        d[str(sid)] = rec
        _save(_purge(d))


def is_archived(sid: str) -> bool:
    """该会话是否已归档（candidates / wake 双处排除）。"""
    return bool(get(sid).get("archived"))


def archived_sids() -> List[str]:
    """全量归档 sid 列表，供候选链一次性排除。"""
    with _LOCK:
        return [k for k, v in load().items()
                if isinstance(v, dict) and v.get("archived")]


def reset(sid: str) -> None:
    """清空单个会话的水位线（手工运维用）。"""
    if not sid:
        return
    with _LOCK:
        d = load()
        d.pop(str(sid), None)
        _save(_purge(d))


__all__ = ["FILE", "load", "get", "her_ts_of", "sends_of", "on_her",
           "note_sent", "set_archived", "is_archived", "archived_sids", "reset"]
