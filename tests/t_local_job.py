# -*- coding: utf-8 -*-
"""主动跑一次本地 job（画像 L0 + 方案 L1），验证能不能落到案情包。

为什么单独测：brain_reply 内部是「投递到后台队列」，看不到中间过程。
这里直接同步调用，把每一步耗时和输出都打出来。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"E:\soul2.1")
sys.path.insert(0, r"E:\soul2.1\brain")
sys.path.insert(0, r"E:\soul2.1\db")

from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    dev = Device.get()
    db = open_account(dev, force=True)

    # 找最近有来回对话的会话（她至少说过 2 句，画像才有料）
    rows = db.con.execute(
        "SELECT s.sessionId, s.toUserId, s.lastMsgText, s.timestamp FROM session s "
        "WHERE s.toUserId > 0 AND s.lastMsgText IS NOT NULL AND s.lastMsgText != '' "
        "ORDER BY s.timestamp DESC LIMIT 12").fetchall()
    sid = None
    for r in rows:
        n = db.con.execute(
            "SELECT COUNT(*) FROM chatmsg WHERE sessionId=? AND msgType=1 "
            "AND senderId=?", (r[0], r[1])).fetchone()[0]
        if n >= 3:
            sid, uid, last = r[0], r[1], r[2]
            print("选中 sid=%s (她说过 %d 句) 末条=%r" % (sid, n, (last or "")[:30]))
            break
    if not sid:
        print("没有合适的测试会话")
        return 1

    # 构造 case（跟 brain_reply 里一样：历史对话 + 她这句）
    msgs = db.messages(sid, limit=30)
    lines = []
    for m in msgs:
        if m.msg_type != 1:
            continue
        t = (m.text or "").strip()
        if not t:
            continue
        lines.append(("我: " if str(m.sender) == str(db.uid) else "她: ") + t[:120])
    case = "\n".join(lines)

    ctx = {
        "acct": str(db.uid),
        "uid": str(uid),
        "sid": str(sid),
        "stage": "",
        "her_msg": (last or "").strip(),
        "case": case,
        "turns": len(msgs),
        "nick": "",
        "_tmo": 60.0,
    }

    import soul_pack as PACK
    import soul_skills as SK

    print("\n=== ① 画像 L0（本地模型）===")
    t0 = time.time()
    try:
        p1 = SK.run("analyze_her", {}, ctx) or ""
        print("耗时 %.1fs，输出 %d 字" % (time.time() - t0, len(p1)))
        print(p1[:900])
    except Exception as e:
        p1 = ""
        print("画像失败: %r" % e)

    if p1:
        try:
            PACK.write_l0(sid, p1, mode="worker")
            print(">> L0 已写入")
        except Exception as e:
            print("!! L0 写入失败: %r" % e)

    print("\n=== ② 方案 L1（本地模型）===")
    import soul_brain as SB
    t0 = time.time()
    try:
        plan = SB._local_plan(case, p1, timeout=60.0) or ""
        print("耗时 %.1fs，输出 %d 字" % (time.time() - t0, len(plan)))
        print(plan[:700])
    except Exception as e:
        plan = ""
        print("方案失败: %r" % e)

    if plan:
        try:
            PACK.write_l1(sid, plan)
            print(">> L1 已写入")
        except Exception as e:
            print("!! L1 写入失败: %r" % e)

    print("\n=== ③ 复查案情包 ===")
    print("pack_dir = %s" % PACK.pack_dir(sid))
    t0, _ = PACK.read_l0(sid)
    t1, _ = PACK.read_l1(sid)
    print("L0 = %d 字   L1 = %d 字" % (len(t0), len(t1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
