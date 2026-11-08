# -*- coding: utf-8 -*-
"""截图到 logs/_pic.png 并取回本地。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402


def main():
    d = Device.get()
    p, n, dt = d.screencap_to(LOGS / "_pic.png")
    print("shot %s %d bytes %.2fs" % (p.name, n, dt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
