# -*- coding: utf-8 -*-
"""找铃的数据源：列出所有库的表名，找 bell/love/encounter/popup 相关。"""
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402

DB_DIR = "/data/data/cn.soulapp.android/databases"
TMP = Path("data/_bellprobe")
KEYS = ("bell", "love", "encount", "meet", "popup", "dialog", "float")


def main():
    dev = Device.get()
    dev.ensure_root()
    out = dev.text("ls %s" % DB_DIR)
    names = [n.strip() for n in out.replace("\r", "").split("\n")
             if n.strip() and not n.strip().endswith(("-wal", "-shm", "-journal"))]
    print("设备上共 %d 个文件，开始扫表名\n" % len(names))
    TMP.mkdir(parents=True, exist_ok=True)

    for name in names:
        if not (name.endswith(".db") or "/" not in name):
            continue
        local = TMP / name
        rc, _, err = dev.run(["pull", "%s/%s" % (DB_DIR, name), str(local)], timeout=90)
        if rc != 0 or not local.exists():
            continue
        try:
            con = sqlite3.connect(str(local))
            tabs = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            con.close()
        except Exception:
            continue
        hits = [t for t in tabs
                if any(k in t.lower() for k in KEYS)]
        print("%-46s %2d 张表  %s" % (name[:46], len(tabs), ("命中: " + str(hits)) if hits else ""))
        for t in tabs:
            print("      - %s" % t)
        local.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
