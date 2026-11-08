# -*- coding: utf-8 -*-
# 由 2.1 brain/soul_localq.py 原样移植（逻辑一字未改）。
# 为什么保留原样：设计是被显存约束逼出来的 —— qwen3.5:9b 实占约 6.9GB，
# RTX 3060 只 12GB，NUM_PARALLEL=1；并发不会并行算只会排队，
# 而不同 num_ctx 会另起 runner 并把旧的挂 30 分钟 → 显存假满。必须单线程串行。
"""本地模型任务队列 —— 单 worker 串行 + 同 sid 只留最新。

════════════════════════════════════════════════════════════════════
为什么必须排队
════════════════════════════════════════════════════════════════════
本地 `qwen3.5:9b`（num_ctx=16384, KV q8_0）实占显存约 6.9 GB，
RTX 3060 只有 12 GB，且 `NUM_PARALLEL=1` / `MAX_LOADED_MODELS=1`。
官方与实测结论一致：**并发请求不会并行计算，只会在 GPU 上排队，
但不同 num_ctx 会另起 runner 并把旧的挂 30 分钟不释放 → 显存假满**。
⇒ 必须由本模块做成**单线程串行**，绝不让两个本地调用同时在飞。

════════════════════════════════════════════════════════════════════
与在线模型的关系（用户 2026-10-25 定稿）
════════════════════════════════════════════════════════════════════
    收到新消息
        ├─ 本地 worker（排队）→ 画像 L0 → 方案 L1 → 落盘应用包
        └─ 在线模型（立刻）  → 实时读应用包 L0+L1（上一轮的也行）→ 出话

关键点：**两边同时开始，互不等待**。
    本地慢（6~14s）不影响这一轮出话 —— 在线只用「已经躺在磁盘上的」L0/L1。
    本地这几轮没跑完，就一直用更早那版；跑完了下一轮立刻用上新的。
    这正是用户原话：「有可能本地模型还没出人设和方案，但是不影响全局，
    在线模型那里的历史人设和方案都可以，但是每次都要实时去拿」。

════════════════════════════════════════════════════════════════════
去重策略
════════════════════════════════════════════════════════════════════
同一 sid 在队列里**最多只保留一条待处理任务**（后来的替换先来的）。
理由：人设/方案是「当前状态的快照」，不是「每条消息各要一份」。
她连发 5 条 → 只需要按最新上下文算一次，算 5 次纯属烧显存。
"""
import threading
import time
import traceback

try:
    import queue as _queue
except ImportError:                                     # pragma: no cover
    import Queue as _queue                              # type: ignore

_q = _queue.Queue(maxsize=200)
_inflight = set()                                    # 正在执行 / 排队中的 sid
_pending = {}                                        # 每个会话只留最新一份任务参数（合并用）
_lock = threading.Lock()
_started = [False]
_stats = {"done": 0, "fail": 0, "skip_dup": 0, "drop_full": 0,
          "last_ms": 0, "last_sid": "", "last_err": ""}

_log_fn = [None]


def set_logger(fn):
    """注入日志函数（soul_brain._dbg 或 soul_skills._dbg），避免循环 import。"""
    _log_fn[0] = fn


def _log(msg):
    fn = _log_fn[0]
    if fn:
        try:
            fn(msg)
            return
        except Exception:
            pass
    try:
        print("[localq] " + msg)
    except Exception:
        pass


def _worker():
    while True:
        try:
            task = _q.get()
        except Exception:
            continue
        if task is None:
            _q.task_done()
            continue
        sid = task[0] if isinstance(task, (tuple, list)) else task
        with _lock:
            item = _pending.pop(str(sid), None)
        if item is None:                 # 已被取消/取走
            try:
                _q.task_done()
            except Exception:
                pass
            continue
        fn, args, kw = item
        t0 = time.time()
        try:
            fn(*args, **(kw or {}))
            _stats["done"] += 1
        except Exception as e:
            _stats["fail"] += 1
            _stats["last_err"] = "%r" % (e,)
            _log("!! 本地任务异常 sid=%s: %r" % (str(sid)[-8:], e))
            try:
                _log("!! 栈: %s" % traceback.format_exc()[-500:])
            except Exception:
                pass
        finally:
            _stats["last_ms"] = int((time.time() - t0) * 1000)
            _stats["last_sid"] = str(sid)[-8:]
            # 🔴 2026-11-03：跑的过程中又来了新消息（_pending 里有新参数）→ 再跑一轮，
            #   保证「最后一条消息带来的对话」也能进画像，不会因为"正在跑"被丢掉。
            again = False
            with _lock:
                _inflight.discard(str(sid))
                if str(sid) in _pending:
                    _inflight.add(str(sid))
                    again = True
            if again:
                try:
                    _q.put_nowait((str(sid),))
                    _stats["rerun"] = _stats.get("rerun", 0) + 1
                    _log("[本地] 跑的过程中又有新消息 → 再跑一轮 sid=%s" % str(sid)[-8:])
                except Exception:
                    with _lock:
                        _inflight.discard(str(sid))
            try:
                _q.task_done()
            except Exception:
                pass


def _ensure_worker():
    if _started[0]:
        return
    with _lock:
        if _started[0]:
            return
        th = threading.Thread(target=_worker, name="soul-localq", daemon=True)
        th.start()
        _started[0] = True


def submit(sid, fn, *args, **kw):
    """投递一个本地任务（画像 L0 + 方案 L1）。

    🔴 2026-11-03（用户口径「每一条新消息都重新算，重复就覆盖」）：
       以前同 sid 已在跑就**直接丢弃**（`skip_dup`）—— 结果是「她在 10 分钟内又发了
       几条，画像一个字都不更新」。现在改成**合并**：
         · 不在跑 → 入队；
         · 正在跑 → 只把参数换成最新的（`_pending` 覆盖），跑完发现还有新参数就再跑一次。
       这样「每条新消息都会触发重算」，但连发多条不会排出 5 个 28s 的任务 ——
       最多跑「当前这轮 + 最后状态那一轮」。

    返回 True=已入队或已合并；False=队列满（丢弃）。
    绝不阻塞调用方，绝不抛。
    """
    try:
        _ensure_worker()
        key = str(sid or "")
        again = False
        with _lock:
            _pending[key] = (fn, args, kw)      # 永远只留最新一份
            if key in _inflight:
                _stats["merge_dup"] = _stats.get("merge_dup", 0) + 1
                return True                     # 正在跑，跑完会自动再跑一轮
            _inflight.add(key)
        try:
            _q.put_nowait((key,))
        except Exception:
            with _lock:
                _inflight.discard(key)
                _pending.pop(key, None)
            _stats["drop_full"] += 1
            _log("!! 本地队列已满，丢弃 sid=%s" % key[-8:])
            return False
        return True
    except Exception as e:
        _log("!! submit 异常: %r" % (e,))
        return False


def drain(timeout=30.0):
    """等队列跑空（**仅测试/诊断用**，生产路径绝不调用）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if _q.unfinished_tasks == 0:
                return True
        except Exception:
            return True
        time.sleep(0.05)
    return False


def status():
    try:
        pending = _q.qsize()
    except Exception:
        pending = -1
    with _lock:
        busy = sorted(x[-8:] for x in _inflight)
    d = dict(_stats)
    d.update({"pending": pending, "inflight": busy,
              "worker": _started[0]})
    return d
