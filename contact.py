# -*- coding: utf-8 -*-
"""联系方式轮 —— 薄转发层。

2026-11-22 修复 D15（P2）：根 `contact.py` 与 `brain/contact.py` 是逐字节副本，
  任何人只改一处就会漂移。改为从此薄转发到权威源 `brain.contact`，
  保留旧 `import contact` 调用点的兼容性（无 `if __main__` 逻辑需要保留）。
"""
# 2026-11-22 修复 D15：整文件转发到权威源 brain.contact
from brain.contact import *  # noqa: F401,F403
from brain.contact import (  # noqa: F401  # 显式列出，方便 IDE 跳转
    is_ask, is_open_door, is_contact_lines, has_promise,
    done, mark_done, stats,
)
