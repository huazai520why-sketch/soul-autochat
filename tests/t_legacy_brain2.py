# -*- coding: utf-8 -*-
"""验证 2：不 chdir 能否复用旧 brain；不同 sid 是否都能出话。"""
import sys
import time

BASE = r"E:\soul2.1"
sys.path.insert(0, BASE)
sys.path.insert(0, BASE + r"\brain")

import soul_brain  # noqa: E402

print("cwd = %s" % __import__("os").getcwd())
print("PERSONA = %d 字" % len(soul_brain.PERSONA or ""))

CASES = [
    ("p_a1", "", "你好呀"),
    ("p_a2", "", "你在干嘛"),
    ("p_a3", "我: 今天好累\n她: 怎么了", "没事 就是上班上的"),
    ("p_a1", "", "又来了"),          # 复用同一个 sid，看是否冷却
]

for sid, hist, msg in CASES:
    t0 = time.time()
    try:
        r = soul_brain.brain_reply(hist=hist, her_msg=msg, sid=sid)
    except Exception as e:
        r = "EXC:%r" % (e,)
    print("  sid=%-6s msg=%-14r -> %.1fs %r" % (sid, msg, time.time() - t0, r))
