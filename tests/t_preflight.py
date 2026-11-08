# -*- coding: utf-8 -*-
"""验证切号前体检：看它能不能正确列出未完成项。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import acct as AC  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    st = {"last_wake": 0, "last_msg_ts": time.time()}

    print("账号 uid=%s" % db.uid)
    t0 = time.time()
    ok, blockers = AC.preflight(a, db, st)
    print("\n体检结果: ok=%s（%.1fs）" % (ok, time.time() - t0))
    if ok:
        print("  没有未完成事项 → 允许切号")
    else:
        print("  未完成 %d 项：" % len(blockers))
        for b in blockers:
            print("    ✗ %s" % b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
