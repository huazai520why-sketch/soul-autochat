# -*- coding: utf-8 -*-
"""测「她要照片」的判据：该认的认，不该认的别认。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import picreq as PR  # noqa: E402

HIT = [
    "发张你的照片看看",
    "看看你长啥样",
    "能发个自拍吗",
    "你本人照片有吗",
    "我想看看你",
    "露个脸呗",
    "你长什么样呀",
]
MISS = [
    "我发你照片了",
    "你的照片真好看",       # 她夸我的？反向，不发
    "我看看你朋友圈",
    "今天天气不错",
    "你朋友的照片呢",
    "照片",                 # 只提照片，没指向
    "我喜欢拍照",
]


def main():
    bad = 0
    print("== 应该认（要照片）==")
    for t in HIT:
        r = PR.wants_pic(t)
        print("  %-18r -> %s" % (t, r))
        if not r:
            bad += 1
    print("\n== 不应该认 ==")
    for t in MISS:
        r = PR.wants_pic(t)
        print("  %-18r -> %s" % (t, r))
        if r:
            bad += 1
    print("\n误判 %d 条" % bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
