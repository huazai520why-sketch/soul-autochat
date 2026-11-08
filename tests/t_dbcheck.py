# -*- coding: utf-8 -*-
"""检查本地缓存的库是否损坏，以及 pull 时有没有带 wal/shm。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import DATA  # noqa: E402

for f in sorted(DATA.rglob("*.db")):
    print("\n=== %s (%d KB) ===" % (f, f.stat().st_size // 1024))
    try:
        con = sqlite3.connect(str(f))
        r = con.execute("PRAGMA integrity_check").fetchone()
        print("  integrity_check: %s" % (r[0] if r else "?"))
        try:
            n = con.execute("SELECT COUNT(*) FROM chatmsg").fetchone()[0]
            print("  chatmsg: %d 条" % n)
        except Exception as e:
            print("  查 chatmsg 失败: %r" % e)
        con.close()
    except Exception as e:
        print("  打开失败: %r" % e)
    for suf in ("-wal", "-shm"):
        p = Path(str(f) + suf)
        print("  %s: %s" % (suf, ("%d KB" % (p.stat().st_size // 1024)) if p.exists() else "不存在"))
