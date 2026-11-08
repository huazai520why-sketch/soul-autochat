# -*- coding: utf-8 -*-
"""查：session.extInfo / 其他表里有没有昵称，能否做 uid->昵称映射。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    db = open_account(Device.get())
    uid = "445709465"

    print("== session.extInfo 样本 ==")
    for r in db.con.execute(
            "SELECT sessionId, toUserId, extInfo FROM session LIMIT 5").fetchall():
        print("   uid=%s ext=%r" % (r[1], (r[2] or "")[:160]))

    print("\n== 目标 uid=%s ==" % uid)
    r = db.con.execute(
        "SELECT sessionId, toUserId, extInfo FROM session WHERE toUserId = ?",
        (uid,)).fetchone()
    print("   %r" % (r,))

    print("\n== 全库表名 ==")
    for t in db.con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        print("   %s" % t[0])

    print("\n== chatmsg 里是否带昵称字段 ==")
    print("   ", [c[1] for c in db.con.execute("PRAGMA table_info(chatmsg)")])
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
