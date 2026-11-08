# -*- coding: utf-8 -*-
"""跑一轮唤醒：按调度闸判断 -> 选 2 人 -> 逐个发送 -> 记台账。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav, wake  # noqa: E402
from brain.act import Actor  # noqa: E402
from brain.scheduler import wake_scheduler  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)
    db = open_account(dev)
    sched = wake_scheduler()

    due, why = sched.due()
    print("调度闸: %s (%s)" % (due, why))
    print("状态: %s" % sched.snapshot())
    if not due:
        return 0

    plan = wake.plan(db, n=N)
    print("\n本轮计划 %d 人" % len(plan))
    if not plan:
        print("没有可唤醒的人")
        return 0

    t0 = time.time()
    ok_n = 0
    for i, (cand, text) in enumerate(plan, 1):
        print("\n[%d/%d] uid=%s 消息=%d 冷=%.1fh"
              % (i, len(plan), cand.uid, cand.msgs, cand.cold_h))
        print("   他/她最后: %r" % (cand.last_text or "")[:36])
        print("   开场白: %r" % text)
        try:
            ok, msg = wake.send_wake(a, dev, cand, text)
        except Exception as e:
            ok, msg = False, "异常 %r" % e
        print("   -> %s %s" % ("OK" if ok else "FAIL", msg))
        if ok:
            ok_n += 1
            sched.mark(1)
        if time.time() - t0 > sched.budget_s:
            print("\n  已到单批预算 %.0fs，停手" % sched.budget_s)
            break

    print("\n== 本轮结束 ==")
    print("  成功 %d / %d  耗时 %.0fs" % (ok_n, len(plan), time.time() - t0))
    print("  调度状态: %s" % sched.snapshot())
    db.close()
    return 0 if ok_n else 1


if __name__ == "__main__":
    sys.exit(main())
