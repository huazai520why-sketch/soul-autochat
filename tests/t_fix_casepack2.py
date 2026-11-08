# -*- coding: utf-8 -*-
"""修复串号：重建二球档案 + 把瑕瑜互见的资料写到正确 sid。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import casepack as CP  # noqa: E402

SID_ERQIU = "9669164614005237"      # 二球（河北，天蝎，引力签=动漫，96%）
SID_XIAYU = "96691646172727928"     # 瑕瑜互见（河南，品质小资 2043 天，94%）

ERQIU = {"个人主页": {
    "昵称": "二球",
    "IP属地": "河北",
    "匹配度": "96%",
    "引力签": "动漫",
    "星座": "天蝎座",
}}

XIAYU = {"个人主页": {
    "昵称": "瑕瑜互见",
    "IP属地": "河南",
    "匹配度": "94%",
    "共同点": "火象星座",
    "灵魂画像": "品质小资 2043天",
    "标签": "拙笔难诉心事、自制牛肉煎包",
    "瞬间": "成年人的苦  七荤八素  各有各的的坟头要哭",
}}


def main():
    p = CP.engine()
    if p is None:
        print("案情包模块没加载")
        return 1

    print("重建二球 -> %s" % p._dump_l4(SID_ERQIU, ERQIU))
    print("写入瑕瑜互见 -> %s" % p._dump_l4(SID_XIAYU, XIAYU))

    for name, sid in (("二球", SID_ERQIU), ("瑕瑜互见", SID_XIAYU)):
        print("\n===== %s  %s =====" % (name, sid))
        print(CP.load(sid) or "（空）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
