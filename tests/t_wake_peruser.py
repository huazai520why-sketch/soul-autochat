# -*- coding: utf-8 -*-
"""验证按人计：补记刚发过的那位，候选应自动排除他。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import wake  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402

SENT_UID = "498390470"      # 06:17 刚发过


def main():
    db = open_account(Device.get())
    print("uid=%s" % db.uid)

    print("\n台账（补记刚才那条）")
    wake.mark_woke(SENT_UID)
    print("  已唤醒 24h 内: %s -> %s" % (SENT_UID, wake.already_woke(SENT_UID)))

    cs = wake.candidates(db, limit=10)
    print("\n候选 %d 人：" % len(cs))
    for c in cs:
        mark = " <<< 已排除" if str(c.uid) == SENT_UID else ""
        print("   uid=%-10s 消息=%-3d 冷=%.1fh%s" % (c.uid, c.msgs, c.cold_h, mark))
    print("\n  验证：%s 在候选里吗 -> %s"
          % (SENT_UID, any(str(c.uid) == SENT_UID for c in cs)))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
