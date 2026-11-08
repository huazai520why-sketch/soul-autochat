# -*- coding: utf-8 -*-
"""诊断本地模型链路：LQ 队列、PACK 案情包、SK 技能库是否可用。

用户要求（2026-11-02）：本地模型补「对方人设 / 个人主页 / 出方案」，接入 1.0。
先搞清楚旧引擎里这三样现在什么状态，别盲目重写。
"""
import os
import sys
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
    row = db.con.execute(
        "SELECT sessionId, toUserId FROM session WHERE toUserId>0 "
        "ORDER BY timestamp DESC LIMIT 1").fetchone()
    sid = row[0]
    print("测试会话 sid=%s nick=%s" % (sid, row[1]))

    # ① 三个模块能不能 import
    print("\n=== 模块可用性 ===")
    for mod in ("soul_pack", "soul_skills", "soul_localq", "soul_stage", "soul_rules"):
        try:
            m = __import__(mod)
            print("  %-14s OK  %s" % (mod, getattr(m, "__file__", "")))
        except Exception as e:
            print("  %-14s FAIL %r" % (mod, e))

    # ② PACK 目录与各层内容
    print("\n=== 案情包（PACK）===")
    try:
        import soul_pack as PACK
        d = PACK.pack_dir(sid)
        print("  pack_dir = %s" % d)
        print("  存在 = %s" % os.path.isdir(d))
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                print("    %-24s %6d B" % (f, os.path.getsize(p)))
        for name, fn in (("L0 她的人设", PACK.read_l0),
                         ("L1 本轮方案", PACK.read_l1),
                         ("L4 她的资料", lambda s: (PACK.read_l4(s), 0))):
            try:
                t, ts = fn(sid)
                print("\n  --- %s（%d 字）---" % (name, len(t or "")))
                if t:
                    print("    " + (t or "")[:400].replace("\n", "\n    "))
                else:
                    print("    (空)")
            except Exception as e:
                print("  %s 读取失败: %r" % (name, e))
    except Exception as e:
        print("  PACK 不可用: %r" % e)

    # ③ 本地模型直连
    print("\n=== 本地模型 ===")
    try:
        import soul_skills as SK
        print("  SK 已加载，技能: %s" % (SK.names() if hasattr(SK, "names") else "?"))
        import soul_brain as SB
        print("  LOCAL_CHAT_URL   = %s" % SB.LOCAL_CHAT_URL)
        print("  LOCAL_CHAT_MODEL = %s" % SB.LOCAL_CHAT_MODEL)
        import time
        t0 = time.time()
        out = SK._llm_local("只回答一个词。", "你是本地模型吗？回答：是")
        print("  实测调用 %.1fs -> %r" % (time.time() - t0, (out or "")[:60]))
    except Exception as e:
        print("  本地模型不可用: %r" % e)

    # ④ LQ 队列状态
    print("\n=== 本地任务队列 ===")
    try:
        import soul_localq as LQ
        for attr in ("_Q", "_QUEUE", "_WORKER", "_TH", "_THREAD"):
            if hasattr(LQ, attr):
                print("  %s = %r" % (attr, getattr(LQ, attr)))
        print("  submit 存在 = %s" % hasattr(LQ, "submit"))
    except Exception as e:
        print("  LQ 不可用: %r" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
