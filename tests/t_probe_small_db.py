# -*- coding: utf-8 -*-
"""探针：看那两个非 -DATA 的小库是什么（可能含 uid->昵称 映射）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import DB_DIR_ANDROID  # noqa: E402

NAMES = [
    "SmNjOUhiUUhZa1RWVlgvZUh1NEExdz09",
    "WGpBRi94dVhpNUdiM0YxdnRVc25uQT09",
]


def main():
    dev = Device.get()
    dest = Path(__file__).resolve().parent.parent / "data" / "_probe"
    dest.mkdir(parents=True, exist_ok=True)

    for n in NAMES:
        local = dest / (n + ".db")
        for suf in ("", "-wal", "-shm"):
            dev.run(["pull", "%s/%s%s" % (DB_DIR_ANDROID, n, suf), str(local) + suf],
                    timeout=60)
        print("\n== %s (%d bytes) ==" % (n[:16], local.stat().st_size if local.exists() else -1))
        try:
            import sqlite3
            con = sqlite3.connect(str(local))
            cur = con.cursor()
            tabs = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            print("   tables: %s" % tabs)
            for t in tabs:
                cols = [c[1] for c in cur.execute('PRAGMA table_info("%s")' % t)]
                cnt = cur.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                print("   - %-24s rows=%-5d cols=%s" % (t, cnt, ",".join(cols)[:90]))
            con.close()
        except Exception as e:
            print("   打开失败: %r" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
