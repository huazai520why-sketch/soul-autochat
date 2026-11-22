# -*- coding: utf-8 -*-
"""One-shot rebuild: backfill nick_cache.json from chatmsg.extMap (read-only DB access)."""
import sqlite3
import json
import os
import glob

ROOT = r'D:\soul-autochat'
NICK = os.path.join(ROOT, 'data', 'state', 'nick_cache.json')

data = {}
try:
    with open(NICK, 'r', encoding='utf-8') as f:
        data = json.load(f) or {}
except Exception as e:
    print('load existing failed:', repr(e))

before = len(data)
added_total = 0

for p in sorted(glob.glob(os.path.join(ROOT, 'data', 'cache', '*', '*-DATA.db'))):
    print('=' * 60)
    print('DB:', os.path.basename(p))
    try:
        uri = 'file:' + p.replace('\\', '/') + '?mode=ro'
        con = sqlite3.connect(uri, uri=True, timeout=5)
        cur = con.cursor()
        cur.execute(
            "SELECT sessionId, extMap FROM chatmsg "
            "WHERE extMap LIKE '%name%' ORDER BY localTime DESC")
        got = 0
        for sid, em in cur.fetchall():
            if not em:
                continue
            try:
                d = json.loads(em)
            except Exception:
                continue
            nm = None
            for k in ('name', 'nickName', 'nickname'):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    nm = v.strip()
                    break
            if not nm:
                continue
            key = str(sid)
            if key not in data:
                data[key] = nm
                got += 1
        print('  newly added:', got)
        added_total += got
        con.close()
    except Exception as e:
        print('  ERR:', repr(e))

tmp = NICK + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
os.replace(tmp, NICK)
print('=' * 60)
print('BEFORE=%d AFTER=%d ADDED=%d' % (before, len(data), added_total))
