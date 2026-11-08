# -*- coding: utf-8 -*-
"""核对/修正案情包：把「瑕瑜互见」的资料从「二球」的档案里摘出来，写到正确 sid。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import casepack as CP  # noqa: E402

SID_ERQIU = "9669164614005237"      # 二球（河北）
SID_XIAYU = "96691646172727928"     # 瑕瑜互见（河南）


def show(title, sid):
    print("\n===== %s  sid=%s =====" % (title, sid))
    t = CP.load(sid)
    print(t or "（空）")
    return t


def main():
    show("二球", SID_ERQIU)
    show("瑕瑜互见", SID_XIAYU)
    return 0


if __name__ == "__main__":
    sys.exit(main())
