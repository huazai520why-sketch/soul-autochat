# -*- coding: utf-8 -*-
"""验证：用真实 sid + 真实历史，让旧引擎出话。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import reply  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev)
    print("lib uid = %s" % db.uid)

    # 找一个「最后一条是对方发的」会话
    targets = []
    for s in db.sessions(unread_only=True, include_official=False):
        last = db.last_message(s.session_id)
        if last is not None and str(last.sender) != str(db.uid):
            targets.append((s, last))
    print("待回会话 %d 个" % len(targets))
    if not targets:
        print("没有可测的会话")
        return 1

    for s, last in targets[:3]:
        msgs = db.messages(s.session_id, limit=12)
        hist = reply.build_hist(msgs, db.uid)
        print("\n== sid=%s uid=%s ==" % (s.session_id, s.to_uid))
        print("   她最后说: %r" % (last.text or "")[:40])
        print("   历史 %d 条:" % len(msgs))
        for m in msgs[-4:]:
            who = "我" if str(m.sender) == str(db.uid) else "她"
            print("      %s %s: %s" % (m.time_str, who, (m.text or "<%s>" % m.msg_type)[:30]))

        r = reply.generate(s.session_id, last.text, hist=hist)
        print("   >> 出话: %r" % (r,))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
