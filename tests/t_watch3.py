# -*- coding: utf-8 -*-
"""验证监控能抓到变化：touch wal 模拟一次写入。"""
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
    W.attach(dev, path)
    time.sleep(2.5)
    print("初始 dirty=%s" % W.urgent())

    print(">> touch 一下 wal（模拟写入）")
    dev.text("touch " + path + "-wal", timeout=15)

    for i in range(6):
        time.sleep(1.0)
        if W.urgent():
            print("  第 %.0fs：⚡ 检测到变化（dirty=True）" % (i + 1))
            return 0
    print("  !! 6 秒没检测到变化")
    return 1


if __name__ == "__main__":
    sys.exit(main())
