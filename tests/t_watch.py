# -*- coding: utf-8 -*-
"""验证库监控：stat 能不能读到指纹，变化能不能被发现。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data import watch as W  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    path = "/data/data/cn.soulapp.android/databases/" + db.path.name
    print("库: %s" % path)

    w = W.Watcher(dev, path)
    t0 = time.time()
    sig = w._sig()
    print("指纹(1): %r  (%.0fms)" % (sig, (time.time() - t0) * 1000))
    if not sig:
        print("!! stat 读不到，监控不可用")
        return 1

    time.sleep(2)
    sig2 = w._sig()
    print("指纹(2): %r" % (sig2,))
    print("两次相同 = %s（相同说明这 2s 没有写入，正常）" % (sig == sig2))

    # 挂线程跑 6 秒，看有没有自然变化
    W.attach(dev, path)
    print("\n挂监控跑 6 秒…")
    for _ in range(6):
        time.sleep(1)
        if W.urgent():
            print("  第 %ds：⚡ 检测到变化" % (_ + 1))
            W.consume()
    print("结束（监控线程随进程退出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
