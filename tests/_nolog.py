# -*- coding: utf-8 -*-
"""测试专用：禁止把模拟动作写进生产 logs/*.log。

🔴 2026-11-09 事故（数据可信度）：在副机跑 `tests/t_nav_ladder.py` 时，
   nav 里「连续 4 次回不到 / 重启 App / 放弃本次导航」等 WARNING 全部
   写进了生产 `logs/brain.nav.log`，且挤在同一秒（00:09:00）。
   随后 `tools/action_audit.py --since 23:59` 误报「修复后仍有 6 次重启、
   8 次回不去」，差点让人以为 nav 修复失效。
   根因：core.log.get_logger 默认挂 RotatingFileHandler 到生产日志目录，
   而行为测试用假对象重放故障阶梯时，日志是真打的。

用法：**必须在任何 `from brain import ...` 之前**导入本模块，例如：

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _nolog  # noqa: F401
    from brain import clear

原理：brain.* 顶层是 `from core.log import get_logger`，只要在此之前替换
core.log.get_logger，模块拿到的就是 NullHandler 版本，零文件写入。
生产代码完全不受影响（只有测试进程会 import 本模块）。
"""
import logging

from core import log as _corelog


def _null_logger(name="soul", filename=None, level=logging.INFO):
    lg = logging.getLogger(name)
    if lg.handlers:
        # 兜底：万一别的模块先建过，把 FileHandler 摘掉
        for h in list(lg.handlers):
            if isinstance(h, logging.FileHandler):
                lg.removeHandler(h)
        return lg
    lg.setLevel(level)
    lg.propagate = False
    lg.addHandler(logging.NullHandler())
    return lg


_corelog.get_logger = _null_logger
