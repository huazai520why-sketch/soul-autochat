# -*- coding: utf-8 -*-
"""core: 设备/路径/日志，最底层，不依赖任何业务。

导入本包即修正 stdout 编码错误处理——副机控制台是 GBK，
日志里出现 emoji（比如消息原文）会直接抛 UnicodeEncodeError 中断整个流程。
"""
import sys

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
