# -*- coding: utf-8 -*-
"""Compatibility wrapper for the production planet-match runner.

用法:
    python tests/t_match_loop.py            # 跑 3 轮
    python tests/t_match_loop.py 5          # 跑 5 轮
    python tests/t_match_loop.py 3 dry      # 只读卡片不发

铁律：**开场白没发成功，绝不点「匹配下一个」**（会白费一次匹配次数）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import match_runner as R  # noqa: E402


def main():
    rounds = 3
    dry = False
    for arg in sys.argv[1:]:
        if arg.lower() == "dry":
            dry = True
        elif arg.isdigit():
            rounds = int(arg)
    return R.main(rounds=rounds, dry=dry)


if __name__ == "__main__":
    sys.exit(main())
