# -*- coding: utf-8 -*-
"""自检：语音消息链路是否真的通了（生产巡检用）。

用户 2026-11-08 明确要求：「一定要正常识别对方语音内容 然后在回复」。
这个脚本回答一个具体问题：**最近的语音消息，有没有被转写、有没有被回复。**

只读，不点设备，不进会话。退出码：
  0 = 正常（最近语音都处理了，或最近根本没有语音）
  2 = 有语音没被处理（需要人看）
  3 = 自身异常
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_AGE_H = 72.0      # 只看最近 72 小时的语音


def main():
    try:
        from core.device import Device
        from data import imdb
    except Exception as e:
        print("导入失败: %r" % (e,))
        return 3

    try:
        dev = Device.get()
        db = imdb.open_account(dev)
    except Exception as e:
        print("打开账号失败: %r" % (e,))
        return 3

    con = db.con
    now_ms = time.time() * 1000.0
    since = now_ms - MAX_AGE_H * 3600000.0

    rows = list(con.execute(
        "SELECT sessionId,senderId,msgContent,localTime FROM chatmsg "
        "WHERE msgType=5 AND localTime>=? ORDER BY localTime DESC",
        (int(since),)))
    if not rows:
        print("最近 %.0fh 无语音消息（正常）" % MAX_AGE_H)
        return 0

    uid = str(db.uid)
    hers = [r for r in rows if str(r[1]) != uid]
    print("最近 %.0fh 语音 %d 条（她的 %d 条）" % (MAX_AGE_H, len(rows), len(hers)))

    # 她的语音 vs 我在同会话里之后有没有发过消息
    bad = []
    for sid, sender, mc, lt in hers[:20]:
        d = {}
        try:
            d = json.loads(mc or "{}")
        except Exception:
            pass
        word = (d.get("word") or "").strip()
        dur = d.get("duration") or 0
        # 她这条语音之后，我有没有回过
        after = con.execute(
            "SELECT COUNT(*) FROM chatmsg WHERE sessionId=? AND senderId=? AND localTime>?",
            (sid, uid, int(lt))).fetchone()[0]
        age_h = (now_ms - float(lt)) / 3600000.0
        tag = "已回" if after else "未回"
        print("  %-14s %2ds word=%-6s 之后我发了%d条  %s  龄%.1fh" % (
            str(sid)[-14:], dur, "有" if word else "无", after, tag, age_h))
        if not after and age_h > 2.0:      # 超 2 小时还没回 = 真漏了
            bad.append((sid, lt, age_h))

    if bad:
        print("")
        print("⚠ %d 条语音超过 2 小时仍未回：" % len(bad))
        for sid, lt, age_h in bad[:10]:
            print("   sid=%s  龄%.1fh" % (sid, age_h))
        return 2
    print("")
    print("✓ 语音链路正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
