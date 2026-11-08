# -*- coding: utf-8 -*-
"""案情包（v3）：事实/主页/对话/状态/简报，分层落盘。

对外统一从这里拿，别直接 import 子模块 —— 以后换存储实现只改本文件。
"""
from . import store                                     # noqa: F401
from .store import (                                    # noqa: F401
    BASE, MEM, VERSION, ACCT_DIR, DIR_ACCT,
    acct_of, pack_dir, exists,
    read_meta, write_meta,
    read_profile, write_profile,
    read_facts, write_facts, add_fact,
    turns_path, read_turns, append_turns, last_her_line, turns_stat,
    sync_turns, note_my_reply, resync_state,
    read_state, write_state,
    read_brief, write_brief, brief_age_h,
    import_v2_dir,
)

__all__ = [n for n in dir() if not n.startswith("_")]
