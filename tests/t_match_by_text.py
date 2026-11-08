# -*- coding: utf-8 -*-
"""验证：用 OCR 读到的会话消息内容，反查数据库 sessionId，再核对最后一条是谁发的。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import chat  # noqa: E402


def main():
    p = LOGS / "_ocr_chat.png"
    png = p.read_bytes()

    bs = chat.bubbles(png)
    texts = [t for t, side, it in bs]
    print("== OCR 可见消息 %d 条 ==" % len(texts))
    for t, side, it in bs:
        print("   y=%-5d %-4s %r" % (it.cy, side, t[:36]))

    db = open_account(Device.get())
    print("\n== 反查 sessionId ==")
    cands = db.sessions_for_texts(texts)[:5]
    if not cands:
        print("   没有命中任何会话")
        return 1
    for sid, n in cands:
        s = db.session(sid)
        last = db.last_message(sid)
        who = "?" if last is None else ("我" if str(last.sender) == str(db.uid) else "对方")
        print("   sid=%s 命中=%d  uid=%-10s unread=%-2s %s"
              % (sid, n, s.to_uid if s else "?", s.unread if s else "?",
                 s.time_str if s else "?"))
        print("      最后一条[%s] type=%s: %r"
              % (who, last.msg_type if last else "?", (last.text if last else "")[:40]))

    print("\n== 交叉核对 ==")
    last_ocr = chat.last_bubble(png)
    sid, n = cands[0]
    last_db = db.last_message(sid)
    ocr_side = last_ocr[1] if last_ocr else "?"
    db_side = ("?" if last_db is None else
               ("me" if str(last_db.sender) == str(db.uid) else "her"))
    print("   OCR 最后一条 : %r  side=%s" % (last_ocr[0][:32] if last_ocr else None, ocr_side))
    print("   DB  最后一条 : %r  side=%s"
          % ((last_db.text if last_db else "")[:32], db_side))
    print("   一致性: %s" % ("OK" if ocr_side == db_side else "!! 不一致"))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
