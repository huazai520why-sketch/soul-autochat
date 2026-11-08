# -*- coding: utf-8 -*-
"""把实际喂给模型的 prompt 原样打印出来，看对话层到底给了什么。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import reply as R  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev, force=True)

    # 找一个最近活跃、末条是她发的会话
    row = db.con.execute(
        "SELECT s.sessionId, s.lastMsgText FROM session s "
        "WHERE s.toUserId > 0 AND s.lastMsgText IS NOT NULL AND s.lastMsgText != '' "
        "ORDER BY s.timestamp DESC LIMIT 1").fetchone()
    sid = row[0]
    her = row[1]
    print("会话 sid=%s  她最后一句=%r" % (sid, her[:40]))

    msgs = db.messages(sid, limit=20)
    print("库里有 %d 条消息（本次传入 %d 条做 hist）" % (len(msgs), 10))
    for m in msgs[-6:]:
        who = "我" if str(m.sender) == str(db.uid) else "她"
        print("   %s: %r" % (who, (m.text or "")[:40]))
    hist = R.build_hist(msgs, db.uid, limit=10)

    B = R.engine()
    if B is None:
        print("!! 引擎没加载")
        return 1

    # system 层
    try:
        system = B._system_for(getattr(B, "BASE_SYS", "") or "", persona=B.PERSONA)
    except Exception as e:
        system = "<_system_for 失败 %r>" % e
    print("\n" + "=" * 60)
    print("=== SYSTEM（%d 字）===" % len(system))
    print("=" * 60)
    print(system[:1500])
    if len(system) > 1500:
        print("\n...(后面还有 %d 字，省略)" % (len(system) - 1500))

    # case 层
    try:
        case = B._build_case(B.PERSONA, hist, her, stage_line="", stuck_line="")
    except Exception as e:
        case = "<_build_case 失败 %r>" % e
    print("\n" + "=" * 60)
    print("=== CASE / 用户消息（%d 字）===" % len(case))
    print("=" * 60)
    print(case)
    return 0


if __name__ == "__main__":
    sys.exit(main())
