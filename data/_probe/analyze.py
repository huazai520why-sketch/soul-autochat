# -*- coding: utf-8 -*-
"""临时分析：IM-SDK 数据库 schema。不属于正式模块。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent / "IM-SDK-SmNjOUhiUUhZa1RWVlgvZUh1NEExdz09-DATA.db"

con = sqlite3.connect(str(DB))
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("tables: %d" % len(tables))

rows = []
for t in tables:
    try:
        n = cur.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    except Exception as e:
        n = -1
    rows.append((n, t))
rows.sort(reverse=True)

print("\n%-8s %s" % ("ROWS", "TABLE"))
for n, t in rows:
    cols = [c[1] for c in cur.execute('PRAGMA table_info("%s")' % t).fetchall()]
    print("%-8d %-28s %s" % (n, t, ",".join(cols)[:110]))

con.close()
