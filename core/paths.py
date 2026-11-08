# -*- coding: utf-8 -*-
"""路径与常量：全部基于本文件位置推导，本地/副机都能跑，不写死 E:\\soul1.0。"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
LOGS = BASE / "logs"
CONFIG = BASE / "config"
STATE = DATA / "state"

for _d in (DATA, LOGS, CONFIG, STATE):
    _d.mkdir(parents=True, exist_ok=True)

# ---- 设备 ----
# MuMu 官方 adb 可能装在两个位置，按存在顺序取第一个
ADB_CANDIDATES = [
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\MuMuPlayer\nx_main\adb.exe",
]

# MuMu 管理器：设备深层挂死（screencap rc=124 / adbd 无 root）时重建实例用。
# 2026-11-03 夜间 00:46-03:32 挂了 2h46m 无人救，加自愈后需要它。
MUMU_MANAGER_CANDIDATES = [
    r"D:\MuMuPlayer\nx_main\MuMuManager.exe",
    r"D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe",
]

# 目标 App
SOUL_PKG = "cn.soulapp.android"

# 屏幕（由 wm size 实测，这里只是兜底默认值；不要在业务里写死）
DEV_W, DEV_H = 900, 1600

# 关键 UI 文本（Soul 900x1600 实测，用于语义定位而不是坐标）
# 注意：第 4 个 tab 的文本是「自己」，不是「我的」（2026-11-02 实测）
TAB_TEXTS = ["星球", "广场", "聊天", "自己"]

__all__ = [
    "BASE", "DATA", "LOGS", "CONFIG", "STATE",
    "ADB_CANDIDATES", "MUMU_MANAGER_CANDIDATES", "SOUL_PKG", "DEV_W", "DEV_H", "TAB_TEXTS",
]
