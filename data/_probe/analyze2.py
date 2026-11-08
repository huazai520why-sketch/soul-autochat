# -*- coding: utf-8 -*-
"""临时分析 2：真实数据抽样，确认时间戳单位 / msgType / 未读判定。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "IM-SDK-SmNjOUhiUUhZa1RWVlgvZUh1NEExdz09-DATA.db"
con = sqlite3.connect(str(DB))
con.row_factory = sqlite3.Row
cur = con.cursor()


def ts(v):
    try:
        v = int(v)
    except Exception:
        return str(v)
    if v > 10 ** 12:      # 毫秒
        return "%s (ms)" % __import__("datetime").datetime.fromtimestamp(v / 1000).strftime("%m-%d %H:%M")
    if v > 10 ** 9:       # 秒
        return "%s (s)" % __import__("datetime").datetime.fromtimestamp(v).strftime("%m-%d %H:%M")
    return str(v)


print("== 未读会话 top10 ==")
for r in cur.execute(
    "SELECT sessionId,unReadCount,lastMsgText,timestamp,toUserId FROM session "
    "WHERE unReadCount>0 ORDER BY timestamp DESC LIMIT 10"
):
    print("  unread=%-3s %-14s %-16s %s | %r"
          % (r["unReadCount"], r["sessionId"][:14], ts(r["timestamp"]),
             r["toUserId"], (r["lastMsgText"] or "")[:34]))

print("\n== 最近消息 top8 ==")
for r in cur.execute("SELECT * FROM chatmsg ORDER BY localTime DESC LIMIT 8"):
    print("  sid=%s sender=%s recv=%s type=%s status=%s t=%s"
          % (r["sessionId"][:12], r["senderId"], r["receiverId"], r["msgType"],
             r["msgStatus"], ts(r["localTime"])))
    print("     text=%r" % (r["text"] or "")[:70])
    print("     content=%r" % (r["msgContent"] or "")[:70])

print("\n== msgType 分布 ==")
for r in cur.execute("SELECT msgType, COUNT(*) c FROM chatmsg GROUP BY msgType ORDER BY c DESC"):
    print("  type=%-4s count=%s" % (r["msgType"], r["c"]))

print("\n== session 总览 ==")
print("  total=%s unread_sessions=%s"
      % (cur.execute("SELECT COUNT(*) FROM session").fetchone()[0],
         cur.execute("SELECT COUNT(*) FROM session WHERE unReadCount>0").fetchone()[0]))

con.close()
