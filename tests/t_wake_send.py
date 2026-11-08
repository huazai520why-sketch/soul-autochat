# -*- coding: utf-8 -*-
"""唤醒真发：选 1 人 -> 出开场白 -> 搜索定位 -> 进会话 -> 发送。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav, wake  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)
    db = open_account(dev)
    print("账号 uid=%s" % db.uid)

    plan = wake.plan(db, n=1)
    if not plan:
        print("没有可唤醒的人")
        return 0
    cand, text = plan[0]
    print("\n目标 uid=%s 消息=%d 冷=%.1fh" % (cand.uid, cand.msgs, cand.cold_h))
    print("  她/他最后说: %r" % (cand.last_text or "")[:40])
    print("  开场白: %r" % text)

    print("\n>> 搜索定位并发送")
    ok, msg = wake.send_wake(a, dev, cand, text)
    print("  结果: %s  %s" % ("OK" if ok else "FAIL", msg))
    db.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
