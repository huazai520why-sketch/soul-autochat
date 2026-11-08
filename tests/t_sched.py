# -*- coding: utf-8 -*-
"""验证调度闸：间隔/小时上限/持久化。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.scheduler import match_scheduler, wake_scheduler  # noqa: E402


def main():
    s = wake_scheduler()
    print("== 唤醒调度 ==")
    print("  %s" % s.snapshot())

    due, why = s.due()
    print("  现在可以跑吗: %s (%s)" % (due, why))
    if not due:
        print("  → 等 %.0fs 后再试" % max(1, s.wait_left()))

    print("\n  模拟：标记一次后立刻再判")
    s.mark(1)
    due2, why2 = s.due()
    print("  %s -> %s (%s)" % (s.snapshot(), due2, why2))
    print("  剩余等待 %.0fs（应为 ~60）" % s.wait_left())

    print("\n== 匹配调度 ==")
    m = match_scheduler()
    print("  %s" % m.snapshot())
    print("  due=%s" % (m.due(),))

    print("\n== 参数 ==")
    for k in ("SOUL_WAKE_EVERY_S", "SOUL_WAKE_CAP_H", "SOUL_WAKE_BUDGET"):
        import os
        print("  %-20s %s (默认见代码)" % (k, os.environ.get(k, "-")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
