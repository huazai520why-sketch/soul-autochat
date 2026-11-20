# -*- coding: utf-8 -*-
"""统一日志：控制台 + 滚动文件。不用 emoji（副机 GBK 控制台会炸）。"""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from .paths import LOGS


def setup_stdout():
    """副机控制台是 GBK，日志里出现 emoji 会直接抛 UnicodeEncodeError。

    统一在入口调用一次：保留 GBK（否则中文乱码），只把不可编码字符替换掉。
    """
    try:
        # 🔴 2026-11-03：原来只改 errors、保留 locale 编码（GBK）→ daemon.out 全是
        #    UTF-16/GBK 混杂，排障只能硬解（交接报告 §79 的 P1 项）。
        #    统一成 UTF-8：文件/管道可读；控制台若真是 GBK，用 errors=replace 兜住。
        # 🔴 2026-11-08 22:5x（「日志停住」的假象）：加 line_buffering=True。
        #    现象：watchdog_live.py 拉起 daemon 时没带 -u，stdout 被重定向到文件后
        #    变成**块缓冲**（约 8KB），于是 daemon.out 好几分钟不涨一行，
        #    而进程其实在正常干活（锁里的 step 一直在推进），排障时极易误判成卡死。
        #    真正的权威日志是 logs/<模块>.log（RotatingFileHandler 每条 flush），
        #    这里只是让 stdout 副本也实时，两条通道都可信。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass


def get_logger(name="soul", filename=None, level=logging.INFO):
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(level)
    lg.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    lg.addHandler(sh)

    fh = RotatingFileHandler(
        str(LOGS / (filename or (name + ".log"))),
        maxBytes=8 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    lg.addHandler(fh)
    return lg


# ---- WARN 限频（2026-11-11：nightly_collect 巡检 core.device.log WARN 一天 579 次）----
# 设备层有多条「进入某恢复/降级路径」的 WARN：adb 超时、adb connect 失败、u2 重连、
# adb root 失败等。单次都有意义，但设备抖动/自愈循环时会**每轮都打**，一天几百上千行，
# 把真异常（设备真挂死）全淹了，巡检阈值(500)也随之爆表。
# 修法：**按 key 限频**。同一 key 在窗口内只 WARN 一次，其余降 DEBUG；窗口过后
# （key 过期）再次进入会重新 WARN —— 状态恢复/再现不被永久静音。
_WARN_LIMIT = {}          # key -> last WARN ts
_WARN_EVERY = 3600.0      # 同一 key 两次 WARN 的最短间隔（秒）


def warn_limited(logger, key, msg, *args, every=_WARN_EVERY):
    """限频版 log.warning：同一 key 每 `every` 秒最多 WARN 一次，其余降 DEBUG。

    用于「进入某恢复/降级/持久状态」的日志：首次进入要 WARN（有人看得到），
    之后在状态持续期间只 DEBUG，避免刷屏；状态恢复后 key 过期，下次再进重新 WARN。
    用法：warn_limited(log, "adb-timeout", "adb 超时 %.1fs: %s", dt, cmd)
    """
    now = time.time()
    last = _WARN_LIMIT.get(key, 0.0)
    if now - last >= every:
        _WARN_LIMIT[key] = now
        logger.warning(msg, *args)
    else:
        logger.debug(msg, *args)
