# -*- coding: utf-8 -*-
"""鏁版嵁灞傦細鐩磋 Soul 鐨?IM-SDK 鏁版嵁搴擄紙root锛屾槑鏂?SQLite锛夈€?

涓轰粈涔堜笉鐢?UI 鎶撹亰澶╄褰曪細
- UI 闇€瑕併€屾壂鍒楄〃 -> 鍒ょ孩鐐?-> 杩涗細璇?-> OCR銆嶏紝涓€杞嚑鍗佺杩樺彲鑳界偣閿欎汉锛?
- 搴撻噷 session.unReadCount / lastMsgText / timestamp 鍏ㄩ兘鏈夛紝姣绾т笖鏃犳涔夈€?

琛ㄧ粨鏋勶紙2026-11-02 瀹炴祴锛?3k 娑堟伅 / 1248 浼氳瘽锛夛細
  chatmsg(id,msgId,sessionId,senderId,receiverId,localTime,serverTime,msgType,
          msgStatus,msgReceiveStatus,msgContent,text)
  session(id,sessionId,chatType,userType,toUserId,unReadCount,timestamp,
          lastMsgText,msgStatus,status,dbStatus,extInfo)

msgType: 1=鏂囨湰(11184) 27=绯荤粺寮曞(1196) 35=? (426) 2/5/8/9=鍥剧墖/璇煶/绀肩墿
localTime / timestamp 鍧囦负 **姣**銆?
"""
import os
import re
import sqlite3
import time
from pathlib import Path

from core.log import get_logger
from core.paths import DATA

log = get_logger("data.imdb")

DB_DIR_ANDROID = "/data/data/cn.soulapp.android/databases"
SP_INFO = "/data/data/cn.soulapp.android/shared_prefs/sp_info_gather.xml"
MSG_TEXT = 1          # 绾枃鏈秷鎭?
MSG_SYSTEM = 27       # 绯荤粺寮曞鍗＄墖锛坱agAuthGuide锛夛紝涓嶆槸鐪熶汉娑堟伅
MSG_SYS2 = 35         # 绯荤粺鎺ㄩ€侊紙"Ta姝ｅ湪浣跨敤涓€у寲鎻愮ず瑁呮壆"锛夛紝text 涓虹┖锛宑ontent 鏄?JSON
SYS_TYPES = (MSG_SYSTEM, MSG_SYS2)
CACHE = DATA / "cache"

_OFFICIAL_UID = -1    # 璐熸暟 toUserId = 瀹樻柟/绯荤粺浼氳瘽

# 钀ラ攢/绯荤粺鎺ㄩ€佺殑鏂囨鐗瑰緛锛?026-11-02 瀹炴祴锛?042683xx 鍙锋鍏ㄦ槸杩欑被锛?
_OFFICIAL_HINTS = (
    "娲诲姩", "绉垎", "绀肩墿", "鍛ㄦ姤", "鍏戞崲", "浼樻儬", "涓婃柊", "绯诲垪", "闄愭椂",
    "绂忓埄", "棰嗗彇", "浼氬憳", "鐩存挱", "浠诲姟", "鎵撳崱", "楂樺畾", "鍔熻兘甯搁┗",
    "閭€浣?, "蹇潵鐪嬬湅", "鍗冲皢鐧诲満",
)


def _ms(v):
    """姣鏃堕棿鎴?-> 鏈湴鏃堕棿瀛楃涓层€?""
    try:
        v = int(v)
    except Exception:
        return "?"
    if v > 10 ** 12:
        v = v / 1000.0
    return time.strftime("%m-%d %H:%M", time.localtime(v))


class Session(object):
    __slots__ = ("session_id", "to_uid", "unread", "ts", "last_text",
                 "chat_type", "user_type", "ext")

    def __init__(self, row):
        self.session_id = row["sessionId"]
        self.to_uid = row["toUserId"]
        self.unread = row["unReadCount"] or 0
        self.ts = row["timestamp"] or 0
        self.last_text = row["lastMsgText"] or ""
        self.chat_type = row["chatType"]
        self.user_type = row["userType"]
        self.ext = row["extInfo"]

    @property
    def is_group(self):
        return "-" in str(self.session_id)

    @property
    def is_official(self):
        """瀹樻柟/钀ラ攢浼氳瘽銆?

        涓ょ骇鍒ゆ嵁锛氳礋鏁?toUserId 鑲畾鏄紱鏂囨鍛戒腑 **鈮? 涓?*钀ラ攢璇嶄篃绠椼€?
        涓嶇敤鍙锋纭紪鐮?鈥斺€?鍙锋浼氬彉锛屾枃妗堢壒寰佹洿绋炽€?

        馃敶 2026-11-04锛堝繀鍥為棴鐜慨澶嶏級锛氬師鏉ユ槸銆屽懡涓?鈮? 涓瘝銆嶅氨绠楀畼鏂瑰彿銆?
          鑰岃瘝琛ㄩ噷銆岀ぜ鐗?/ 娲诲姩 / 鐩存挱 / 浼氬憳 / 浠诲姟 / 绯诲垪銆嶉兘鏄?*鐪熶汉鏃ュ父楂橀璇?*
          鈥斺€?濂硅涓€鍙ャ€屼綘閫佹垜鐨勭ぜ鐗╁憿銆嶅氨浼氳鍒ゆ垚瀹樻柟鍙凤紝浜庢槸鍦?clear 娓呯孩鐐广€?
          wake 鍞ら啋鍊欓€夈€乤cct 寰呭洖缁熻閲岃**鐩存帴璺宠繃 = 姘镐笉鍥炲**锛堣繚鑳屽繀鍥烇級銆?
          鏀逛负銆屸墺2 涓瘝銆嶏細瀹炴祴搴撳唴 1356 涓湡浜轰細璇濓紙toUid>0锛夊彧鏈?4 涓鍒ゅ畼鏂广€?
          涓旇繖 4 涓叏鏄湡钀ラ攢鍙凤紙鍛戒腑 2~4 涓瘝锛夛紝鏀剁揣鍚庝粛 100% 璇嗗埆銆?
        """
        try:
            if int(self.to_uid) < 0:
                return True
        except Exception:
            return True
        t = self.last_text or ""
        hit = sum(1 for h in _OFFICIAL_HINTS if h in t)
        return hit >= 2

    @property
    def time_str(self):
        return _ms(self.ts)

    def __repr__(self):
        return "<Session %s uid=%s unread=%s %s %r>" % (
            self.session_id[-8:], self.to_uid, self.unread, self.time_str,
            self.last_text[:14])


class Msg(object):
    __slots__ = ("msg_id", "session_id", "sender", "receiver", "ts",
                 "msg_type", "status", "text", "content")

    def __init__(self, row):
        self.msg_id = row["msgId"]
        self.session_id = row["sessionId"]
        self.sender = row["senderId"]
        self.receiver = row["receiverId"]
        self.ts = row["localTime"] or 0
        self.msg_type = row["msgType"]
        self.status = row["msgStatus"]
        self.text = row["text"] or ""
        self.content = row["msgContent"] or ""

    @property
    def time_str(self):
        return _ms(self.ts)

    def __repr__(self):
        return "<Msg %s %s %r>" % (self.time_str, self.sender, self.text[:18])




# session 鎽樿鏂囨湰 鈫?msgType锛氬彧璁ゆ槑纭殑濯掍綋/绯荤粺鏍囪锛屽叾浣欎竴寰嬪綋鏂囨湰銆?
# 涓轰粈涔堜笉鎶婃墍鏈?[xx] 閮藉綋琛ㄦ儏锛氬ス鐨勮创绾稿湪 chatmsg 閲屾湰鏉ュ氨鏄€孾鐙楀瓙]銆嶈繖绉嶆枃鏈紝
# 鍒ゆ垚 emoji 浼氳蛋鍥哄畾璇濇湳銆佹妸涓婁笅鏂囦涪鎺夛紙瀹炴祴搴撳唴 15486 鏉￠噷杩欑被寰堝锛夈€?
_DIGEST_MEDIA = (
    ("[璇煶]", 5), ("[鍥剧墖]", 2), ("[鐓х墖]", 2), ("[瑙嗛]", 2),
    ("[鏂囦欢]", 2), ("[閾炬帴]", 2),
)
_DIGEST_TIP = ("[褰撳墠鐗堟湰杩囦綆", "[浜掑姩娑堟伅]", "[绯荤粺", "[鎴充竴涓媇")


def _digest_mt(text):
    """session.lastMsgText -> msgType銆?""
    t = (text or "").strip()
    for k, mt in _DIGEST_MEDIA:
        if t.startswith(k):
            return mt
    for k in _DIGEST_TIP:
        if t.startswith(k):
            return MSG_SYS2
    return MSG_TEXT

class IMDB(object):
    """涓€涓处鍙风殑 IM 搴撱€俻ath 鎸囧悜鏈湴缂撳瓨鍓湰锛堢敱 sync 缁存姢锛夈€?""

    def __init__(self, path, uid=None):
        self.path = Path(path)
        self._con = None
        self.uid = uid or self._guess_uid()
        # 馃敶 2026-11-08 21:2x锛氭妸 device 寮曠敤鎸傚埌搴撳璞′笂銆?
        #   `data/pending.py` 鐨勩€岃澶囧瓨娲绘牎楠屻€嶇敤 getattr(db, "dev", None)锛?
        #   鑰岃繖涓睘鎬т粠鏉ユ病鏈夎璧嬭繃鍊?鈫?閭ｅ眰杩囨护**浠庢潵娌＄敓鏁?*锛?
        #   浜庢槸鏃ュ織涓€鐩存樉绀恒€屽緟鍥?71 浜猴紙鏈 6 / 宸茶鏈洖 65锛夈€嶏紝鐪熷疄鍊欓€夊彧鏈?9 涓€?
        #   鏁板瓧铏氶珮浼氳瀵煎垽鏂紙涔熶細褰卞搷绾㈢偣闂哥殑鍒ゆ嵁锛夛紝杩欓噷琛ヤ笂銆?
        self.dev = None

    # ---------- 杩炴帴 ----------
    def _usable_path(self):
        """杩斿洖涓€涓€岃兘璇诲埌 wal 灏鹃儴銆嶇殑搴撹矾寰勶紙蹇呰鏃剁敤骞插噣蹇収锛夈€?

        馃敶 2026-11-04 蹇呭洖鐩插尯锛堝疄娴嬪鐓э紝鍚屼竴浠?db+wal锛夛細
          路 甯﹁澶囨媺涓嬫潵鐨勬棫 -shm 鈫?鍙璇绘垚 unread=0銆佹湯鏉?07:02锛堝ス 08:12 鐨勮瘽涓嶅瓨鍦級
          路 鍙?db+wal锛堟棤 shm锛?   鈫?璇诲埌 unread=2銆?8:12:52銆屾病蹇欎粈涔堛€?
          shm 鏄?App 杩涚▼鐨?mmap 绱㈠紩锛屾瘮 wal 鏃ф椂 SQLite 浼氭寜瀹冪殑 mxFrame 鎴柇 wal锛?
          浜庢槸 latest() 鍒ゃ€屾渶鍚庝竴鏉℃槸鎴戝彂鐨勩€嶁啋 candidates 闈欓粯鍚炴帀蹇呭洖銆?
        澶勭悊锛氳兘鍒犲氨鍒狅紙SQLite 鑷繁閲嶅缓锛夛紱鍒犱笉鎺夛紙鍙ユ焺琚湰杩涚▼/鍒殑杩涚▼鍗犵潃锛?
        灏辨妸 db+wal 澶嶅埗鎴?`<db>-snap.db`锛堝叏鏂?inode 鈫?shm 蹇呯劧閲嶅缓锛夊啀鎵撳紑銆?
        """
        wal = Path(str(self.path) + "-wal")
        shm = Path(str(self.path) + "-shm")
        if not wal.exists() or wal.stat().st_size == 0:
            return self.path
        if not shm.exists() or shm.stat().st_mtime >= wal.stat().st_mtime:
            return self.path
        try:
            shm.unlink()
            log.info("鍒犻櫎闄堟棫 shm锛?s锛夆啋 SQLite 閲嶅缓鍚庡嵆鍙鍒?wal 灏鹃儴", self.path.name)
            return self.path
        except OSError:
            pass
        snap = Path(str(self.path) + "-snap.db")
        try:
            import shutil
            for suf in ("-shm", "-wal", ""):
                q = Path(str(snap) + suf)
                if q.exists():
                    try:
                        q.unlink()
                    except OSError:
                        pass
            shutil.copy2(str(self.path), str(snap))
            shutil.copy2(str(wal), str(snap) + "-wal")
            # FIX 2026-11-12 P0-1: snapshot integrity check
            #   copy2 of actively-written WAL db can produce corrupt snapshot
            #   ("file is not a database"), causing _guess_uid() to return
            #   None and open_account() to fail with "uid mismatch".
            #   Verify snapshot; on failure fall back to main db (valid uid).
            try:
                import sqlite3 as _sq
                _v = _sq.connect(str(snap))
                try:
                    _r = _v.execute("PRAGMA integrity_check").fetchone()
                    if not _r or str(_r[0]).lower() != "ok":
                        raise RuntimeError("integrity_check: %r" % (_r,))
                    _v.execute("SELECT COUNT(*) FROM session LIMIT 1").fetchone()
                finally:
                    _v.close()
            except Exception as _ie:
                log.warning(
                    "蹇収 integrity 鏍￠獙澶辫触锛?d KB wal锛夆啋 鍥為€€涓诲簱锛?r",
                    int(wal.stat().st_size / 1024), _ie)
                return self.path
            log.info("闄堟棫 shm 鍒犱笉鎺?鈫?鐢ㄥ揩鐓?%s 鎵撳紑锛?d KB wal锛?,
                     snap.name, int(wal.stat().st_size / 1024))
            return snap
        except Exception as e:      # noqa: BLE001
            log.warning("蹇収澶辫触锛岄€€鍥炲師搴擄紙鍙兘璇讳笉鍒?wal 灏鹃儴锛? %r", e)
            return self.path

    @property
    def con(self):
        if self._con is None:
            if not self.path.exists():
                raise RuntimeError("搴撲笉瀛樺湪: %s" % self.path)
            p = self._usable_path()
            self._con = sqlite3.connect("file:%s?mode=ro" % p.as_posix(),
                                        uri=True, timeout=5)
            self._con.row_factory = sqlite3.Row
        return self._con

    def close(self):
        if self._con is not None:
            self._con.close()
            self._con = None

    def _guess_uid(self):
        """鑷繁 uid銆?

        瀹炴祴瑙勫緥锛歴essionId = 鑷繁uid + str(toUserId) 鐩存帴鎷兼帴锛岄暱搴︿笉瀹氥€?
        渚嬪 96691646 + 204268346 -> '96691646204268346'銆?
        鎵€浠ョ敤 sid 鍘绘帀 toUid 鍚庣紑鍙嶆帹锛屽彇浼楁暟锛涘け璐ュ啀閫€鍥?chatmsg 閲屽彂鏂囨湰鏈€澶氱殑浜恒€?
        """
        try:
            rows = self.con.execute(
                "SELECT sessionId, toUserId FROM session WHERE sessionId IS NOT NULL "
                "AND toUserId IS NOT NULL LIMIT 300"
            ).fetchall()
        except Exception:
            return None
        votes = {}
        for sid, touid in rows:
            sid, touid = str(sid), str(touid)
            if touid and sid.endswith(touid) and len(sid) > len(touid):
                pre = sid[: -len(touid)]
                votes[pre] = votes.get(pre, 0) + 1
        if votes:
            return max(votes.items(), key=lambda kv: kv[1])[0]
        try:
            row = self.con.execute(
                "SELECT senderId, COUNT(*) c FROM chatmsg WHERE msgType = ? "
                "GROUP BY senderId ORDER BY c DESC LIMIT 1", (MSG_TEXT,)).fetchone()
            return str(row[0]) if row else None
        except Exception:
            return None

    # ---------- 鏌ヨ ----------
    def sessions(self, unread_only=False, include_official=True, limit=0):
        sql = "SELECT * FROM session"
        args = []
        if unread_only:
            sql += " WHERE unReadCount > 0"
        sql += " ORDER BY timestamp DESC"
        if limit:
            sql += " LIMIT %d" % int(limit)
        out = []
        for row in self.con.execute(sql, args):
            s = Session(row)
            if not include_official and s.is_official:
                continue
            out.append(s)
        return out

    def session(self, session_id):
        row = self.con.execute(
            "SELECT * FROM session WHERE sessionId = ?", (session_id,)).fetchone()
        return Session(row) if row else None

    def messages(self, session_id, limit=20, skip_system=True):
        """鎸夋椂闂存搴忚繑鍥炴渶杩?limit 鏉°€?

        skip_system=True 鏃舵帓闄?msgType=27锛堢郴缁熷紩瀵煎崱鐗囷級锛?
        鍚﹀垯銆屾渶鍚庝竴鏉°€嶄細琚郴缁熷崱鐗囨薄鏌?鈥斺€?瀹炴祴 204268346 绛変細璇濆氨鏄繖绉嶃€?
        """
        sql = "SELECT * FROM chatmsg WHERE sessionId = ?"
        if skip_system:
            sql += " AND msgType NOT IN (%d,%d)" % SYS_TYPES
        sql += " ORDER BY localTime DESC LIMIT %d" % int(limit)
        rows = [Msg(r) for r in self.con.execute(sql, (session_id,))]
        rows.reverse()
        return rows

    def last_message(self, session_id, skip_system=True):
        ms = self.messages(session_id, limit=1, skip_system=skip_system)
        return ms[0] if ms else None

    # ---------- session 鎽樿锛氬叆鍚戜笉钀?chatmsg 鏃剁殑鍞竴鍙俊鏉ユ簮 ----------
    def session_digest(self, session_id):
        """session 琛ㄩ噷鐨勩€屾渶鏂颁竴鏉°€嶆憳瑕侊紝dict 鎴?None銆?

        馃敶 2026-11-04锛堝繀鍥為棴鐜锋暟鎹摼锛屽疄娴?402857053锛夛細
          璇ュ彿 App **鍙洿鏂?session锛坲nReadCount/lastMsgText锛夛紝涓嶅啓 chatmsg 鍏ュ悜**
          鈥斺€?24h chatmsg 鍏ュ悜 1 鏉★紝鑰?session 閲屾湁濂?07:17 鐨勬柊璇濄€屽彲鑳芥墜婊戜簡鍚с€嶃€?
          浜庢槸鎵€鏈夈€屽彧璇?chatmsg銆嶇殑鍒ゅ畾鍏ㄧ洸锛堝垏鍙峰悗 4.5h 瀹炴祴锛夛細
            鏈潯鍒ゅ畾 鈫?璇垽銆屾渶鍚庝竴鏉℃槸鎴戝彂鐨?鈫?鏃犻渶鍥炲銆?9 娆?
            鏂囨湰鍙嶆煡 sid 鈫?銆屽弽鏌ヤ笉鍒?sessionId銆?8 娆?
            韬唤鏍￠獙 鈫?fail-closed 姘歌繙涓嶅彂 63 娆?
          session.lastMsgText 涓庡垪琛ㄧ孩鐐规槸鍚屼竴浠芥暟鎹紝蹇呴』绾冲叆銆?
        """
        try:
            r = self.con.execute(
                "SELECT toUserId, unReadCount, lastMsgText, timestamp, chatType "
                "FROM session WHERE sessionId = ?", (session_id,)).fetchone()
        except Exception as e:
            log.debug("璇?session 鎽樿寮傚父: %r", e)
            return None
        if r is None:
            return None
        return {
            "to_uid": str(r["toUserId"] or ""),
            "unread": int(r["unReadCount"] or 0),
            "text": (r["lastMsgText"] or "").strip(),
            "ts": int(r["timestamp"] or 0),
            "chat_type": r["chatType"],
        }

    def my_recent_texts(self, session_id, limit=40):
        """鎴戞渶杩戝彂杩囩殑鏂囨湰闆嗗悎锛堝垽鎽樿鏈€鍚庝竴鍙ュ埌搴曟槸璋佽鐨勶級銆?""
        out = set()
        try:
            for m in self.messages(session_id, limit=limit):
                if str(m.sender) == str(self.uid) and (m.text or "").strip():
                    out.add((m.text or "").strip())
        except Exception:
            pass
        return out

    def my_text_ts(self, session_id, text, limit=60):
        """鎴戝彂杩囪繖鍙ョ殑鏈€杩戞椂闂达紙姣锛夛紝娌℃湁鍒?0銆?

        馃敶 涓轰粈涔堥渶瑕侊紙2026-11-04锛夛細濂硅鐨勫彲鑳藉拰鎴戞浘璇磋繃鐨勪竴妯′竴鏍?
          锛堛€屽搱鍝堛€嶃€屽湪鐨勩€嶃€屽棷銆嶏級銆傚彧鎸夋枃鏈垽鏂瑰悜浼氭妸濂圭殑璇濆綋鎴愭垜璇寸殑 鈫?
          姘镐笉鍥炲锛堟紡鍥?= 鏈€宸け璐ユā寮忥級銆傛墍浠ュ啀鐢?*鏃堕棿閭昏繎**鍋氫竴娆′氦鍙夐獙璇侊細
          鎽樿鏃堕棿蹇呴』璐磋繎鎴戝彂閭ｅ彞鐨勬椂闂达紝鎵嶇畻鍚屼竴鍙ャ€?
        """
        text = (text or "").strip()
        if not text:
            return 0
        best = 0
        try:
            for m in self.messages(session_id, limit=limit):
                if str(m.sender) != str(self.uid):
                    continue
                if (m.text or "").strip() == text:
                    best = max(best, int(m.ts or 0))
        except Exception:
            pass
        return best

    def latest(self, session_id):
        """浼氳瘽鏈€鏂颁竴鏉★細(Msg|None, source)锛宻ource 鈭?{"db", "session", ""}銆?

        鍙?chatmsg 鏈潯涓?session 鎽樿閲?*鏃堕棿鏇存柊**鐨勯偅涓€?
        鎽樿鑻ユ槸鎴戣嚜宸辨渶鍚庤鐨勶紙鏂囨湰鍛戒腑 my_recent_texts锛夆啋 鍚堟垚 sender=uid锛?
        涓婂眰鐓ф棫鍒ゃ€屾垜鍙戠殑 鈫?鏃犻渶鍥炲銆嶏紝涓嶄細鍥犱负濂规病鍥炲氨閲嶅鍙戙€?

        馃敶 瀹炴祴锛?02857053锛?026-11-04锛夛細chatmsg 鏈潯鍋滃湪 87h 鍓嶏紝session 鍗存槸
          3 鍒嗛挓鍓?鈥斺€?鍙湅 chatmsg 浼氭妸濂瑰垰璇寸殑璇濆綋绌烘皵锛屽洖鍑烘潵鍏ㄦ槸 3 澶╁墠鐨勪笂涓嬫枃
          锛堣繖灏辨槸銆岀瓟闈炴墍闂€嶇殑鏍瑰洜锛屼笉鏄ā鍨嬬锛夈€?
        """
        msg = self.last_message(session_id)
        dig = self.session_digest(session_id)
        if not dig or not dig["text"]:
            return msg, ("db" if msg is not None else "")
        d_ts, d_txt = int(dig["ts"] or 0), dig["text"]
        m_ts = int(getattr(msg, "ts", 0) or 0)
        if msg is not None and d_ts <= m_ts:
            return msg, "db"
        mine = d_txt in self.my_recent_texts(session_id)
        if mine:
            # 鏃堕棿绐椾氦鍙夐獙璇侊細闅斾簡 3 鍒嗛挓浠ヤ笂 鈫?涓嶆槸鍚屼竴鍙ワ紝鏄ス璇翠簡鍚屾牱鐨勮瘽
            ts_mine = self.my_text_ts(session_id, d_txt)
            if not ts_mine or abs(d_ts - ts_mine) > 180000:
                mine = False
        sender = str(self.uid) if mine else str(dig["to_uid"] or "")
        return Msg({
            "msgId": "", "sessionId": session_id,
            "senderId": sender, "receiverId": str(dig["to_uid"] or ""),
            "localTime": d_ts, "msgType": _digest_mt(d_txt),
            "msgStatus": 0, "text": d_txt, "msgContent": "",
        }), "session"

    def digest_matches(self, session_id, texts, min_len=2):
        """褰撳墠浼氳瘽鐨勬憳瑕佹枃鏈槸鍚﹀嚭鐜板湪 texts 閲岋紙韬唤鏍￠獙鐨勫己璇佹嵁锛夈€?

        馃敶 鐢ㄩ€旓細pendingq 杩涗細璇濆悗瑕佺‘璁ゃ€岃繖鏄笉鏄€欓€夐偅涓汉銆嶃€傚師鏉ュ彧鑳芥嬁
          姘旀场鏂囨湰鍘?chatmsg 鍙嶆煡 鈥斺€?鍏ュ悜涓嶈惤搴撶殑璐﹀彿涓婂繀鐒跺け璐?鈫?fail-closed
          姘歌繙涓嶅彂锛堝疄娴嬨€孾鐙楀瓙]銆嶃€岄偅涓嶇煡閬撱€嶅悇澶辫触 10 娆★級銆?
          鎽樿灏辨槸鍒楄〃棰勮锛屽拰灞忓箷涓婄殑鏈€鍚庝竴鍙ヨ瘽蹇呯劧涓€鑷达紝鏄渶绋崇殑涓€鏉¤瘉鎹€?
        """
        dig = self.session_digest(session_id)
        if not dig or not dig["text"]:
            return False
        want = (dig["text"] or "").strip()
        if len(want) < min_len:
            return False
        for t in texts:
            t = (t or "").strip()
            if not t or len(t) < min_len:
                continue
            if t == want or (len(t) >= 4 and (want.startswith(t) or t.startswith(want))):
                return True
        return False

    def pending(self, min_gap_s=0):
        """寰呭洖浼氳瘽锛氭湁鏈 / 闈炲畼鏂?/ 鏈€鍚庝竴鏉℃槸瀵规柟鍙戠殑銆?

        杩斿洖鎸夋渶鍚庢秷鎭椂闂存搴忥紙鍏堝洖鏈€涔呮病鍥炵殑锛夈€?
        """
        out = []
        for s in self.sessions(unread_only=True, include_official=False):
            last = self.last_message(s.session_id)
            if last is None:
                continue
            if self.uid and str(last.sender) == str(self.uid):
                continue          # 鏈€鍚庝竴鏉℃槸鎴戝彂鐨?-> 涓嶇畻寰呭洖
            if min_gap_s and (time.time() * 1000 - int(s.ts)) < min_gap_s * 1000:
                continue
            out.append((s, last))
        out.sort(key=lambda x: x[0].ts)
        return out

    def stats(self):
        return {
            "sessions": self.con.execute("SELECT COUNT(*) FROM session").fetchone()[0],
            "unread": self.con.execute(
                "SELECT COUNT(*) FROM session WHERE unReadCount>0").fetchone()[0],
            "unread_total": self.unread_total(),
            "messages": self.con.execute("SELECT COUNT(*) FROM chatmsg").fetchone()[0],
            "uid": self.uid,
        }

    def sessions_for_texts(self, texts, min_len=2, unread_only=False):
        """鐢ㄣ€屼細璇濋噷鍙鐨勬秷鎭枃鏈€嶅弽鏌?sessionId锛坈hatmsg + session 鎽樿锛夈€?

        UI 鍒楄〃琛岄噷娌℃湁 uid銆佹樀绉颁篃涓嶅湪搴撻噷锛屽彧鑳介潬鍘熸枃鍙嶆煡銆傚姞鏉冭鍒?
        锛堟暟鍊艰秺澶ц秺鍙俊锛夛細
          session.lastMsgText 绮剧‘  3  鈫?鍒楄〃棰勮灏辨槸瀹冿紝鑰屼笖鏄?*鏈€鏂?*閭ｅ彞
          chatmsg.text 绮剧‘         2
          session.lastMsgText 鍓嶇紑  2  鈫?棰勮琚埅鏂紙銆?..銆嶏級鏃跺彧鑳藉墠缂€姣?
          chatmsg.text 鍓嶇紑         1
          鐩爣浼氳瘽鏈夋湭璇荤孩鐐?       +1  鈫?绾㈢偣=濂瑰垰鍙戯紝涓庛€岃鍥炶皝銆嶈涔変竴鑷?

        馃敶 2026-11-04锛堝繀鍥為棴鐜級锛?02857053 鍙峰叆鍚戜笉钀?chatmsg 鏃讹紝
          鍘熸潵鍙煡 chatmsg 鈫?濂瑰垰鍙戠殑璇?*蹇呯劧**鍙嶆煡涓嶅埌锛?8 娆?4.5h锛夛紝
          娴佺▼閫€鍖栨垚銆屼粎鍑?OCR銆嶆垨 fail-closed銆俿ession 鎽樿蹇呴』涓€璧锋煡銆?

        unread_only=True 鏃跺彧缁熻鏈夌孩鐐圭殑浼氳瘽锛堢煭鏂囨湰 2~3 瀛椾笓鐢紝闃叉挒杞︼級銆?
        """
        hits = {}
        unread = {}
        try:
            for r in self.con.execute(
                    "SELECT sessionId, unReadCount FROM session"):
                unread[str(r["sessionId"])] = int(r["unReadCount"] or 0)
        except Exception:
            pass

        def _add(sid, w):
            sid = str(sid)
            if unread_only and unread.get(sid, 0) <= 0:
                return
            hits[sid] = hits.get(sid, 0) + w

        def _q(sql, arg, w):
            try:
                for (sid,) in self.con.execute(sql, arg).fetchall():
                    _add(sid, w)
            except Exception:
                pass

        for t in texts:
            t = (t or "").strip()
            if len(t) < min_len:
                continue
            _q("SELECT DISTINCT sessionId FROM session WHERE lastMsgText = ? LIMIT 30",
               (t,), 3)
            _q("SELECT DISTINCT sessionId FROM chatmsg WHERE text = ? LIMIT 30",
               (t,), 2)
            if len(t) >= 4:
                _q("SELECT DISTINCT sessionId FROM session "
                   "WHERE lastMsgText LIKE ? LIMIT 30", (t + "%",), 2)
                _q("SELECT DISTINCT chatmsg.sessionId FROM chatmsg "
                   "WHERE text LIKE ? LIMIT 30", (t + "%",), 1)
        for sid in list(hits):
            if unread.get(sid, 0) > 0:
                hits[sid] += 1
        return sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))

    def unread_total(self):
        """鍏ㄩ儴浼氳瘽鏈鏁颁箣鍜屻€?

        涓氬姟纭害鏉燂紙鐢ㄦ埛 2026-11-02 瀹氾級锛?*绾㈢偣蹇呴』娓呴浂鎵嶅厑璁歌繘鏄熺悆鍖归厤**銆?
        璋冨害灞傜敤鏈柟娉曞仛闂革紝涓嶈鐢ㄥ儚绱犲垽绾㈢偣銆?
        """
        r = self.con.execute(
            "SELECT SUM(unReadCount) FROM session WHERE unReadCount > 0").fetchone()
        return int(r[0] or 0)


# ---------------- 鍚屾锛氫粠璁惧鎷夊簱鍒版湰鍦扮紦瀛?----------------
def list_device_dbs(device):
    """鍒楀嚭璁惧涓婃墍鏈?IM-SDK 搴擄紙鏂囦欢鍚嶉噷鍚?-DATA.db锛夈€?

    馃敶 2026-11-08 10:42锛堢敓浜у疄娴嬩慨澶嶏級锛?
      `/data/data/cn.soulapp.android/databases` 鏄?**u0_a52 绉佹湁鐩綍**锛?
      闈?root 鐨?adb shell 璇诲畠蹇呯劧 `Permission denied`锛堝疄娴?10:35锛夈€?
      鏀瑰墠鐩存帴 `ls` 涓旀妸 stderr 娣疯繘 stdout 涓€璧疯В鏋?鈫?鎷垮埌绌哄垪琛?
      鈫?`open_account()` 鎶涖€岃澶囦笂娌℃湁 IM-SDK 搴撱€嶁啋 **鏁翠釜 daemon 鐦棯**銆?
      鏀规硶锛氫紭鍏?`su -c ls`锛屽け璐ュ啀閫€鍥炴櫘閫?`ls`锛堝吋瀹瑰凡 root/adb root 鐨勭幆澧冿級銆?
    """
    names = []
    for cmd in ("su -c 'ls %s'" % DB_DIR_ANDROID, "ls %s" % DB_DIR_ANDROID):
        try:
            out = device.text(cmd)
        except Exception:
            continue
        for line in (out or "").replace("\r", "").split("\n"):
            n = line.strip()
            if n.startswith("IM-SDK-") and n.endswith("-DATA.db"):
                names.append(n)
        if names:
            break
    # 鍘婚噸锛坰u 涓庢櫘閫?ls 鍙兘鍚勬嬁鍒颁竴娆★級
    seen, uniq = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _merge_device_into_mirror(device, name, local, dest_dir):
    """璁惧搴撶缉姘存椂锛氭妸璁惧渚?*鏂板琛屽悎骞惰繘鏈湴闀滃儚**锛堝巻鍙蹭繚鐣欙級锛岃€屼笉鏄烦杩囧悓姝ャ€?

    馃敶 2026-11-08 21:0x锛圥0銆屾秷鎭嚑灏忔椂鎵嶅洖銆嶇殑鐪熸牴鍥狅紝瀹炴祴锛夛細
      鏃у疄鐜版槸銆岃澶囧簱 < 鏈湴 50% 鈫?`return local`銆嶏紝绛変簬**涓€娆￠兘涓嶅悓姝?*銆?
      鑰?Soul 浠婂ぉ 10:25 鎶婅处鍙峰簱娓呯┖锛?.0MB 鈫?167KB锛夛紝鏈湴闀滃儚浠?**09:29 璧峰交搴曞喕缁?*锛?
      濂?19:56銆屼负鍟ュ憖銆嶃€?0:21銆屽ソ鍚с€嶅彧瀛樺湪浜庤澶囧簱锛岄暅鍍忛噷鏈潯浠嶆槸鎴戞棭涓婂彂鐨勯偅鍙?
      鈫?`candidates()` 鍒ゃ€屾渶鍚庝竴鏉℃槸鎴戝彂鐨勩€嶁啋 闈欓粯璺宠繃锛屽嚑鏉℃秷鎭瓑浜嗗嚑灏忔椂娌′汉鍥炪€?
      褰撳ぉ 107 鏉″洖澶嶉噷 16-20 鐐瑰彧鏈?12 鏉★紝鍏朵綑鍏ㄩ潬绾㈢偣 OCR 鎾炶繍姘斻€?

      姝ｇ‘濮垮娍锛氳澶囧簱浠嶆槸**鏂版秷鎭殑鍞竴鏉ユ簮**锛屾妸瀹冨苟杩涢暅鍍忥細
        路 chatmsg锛氭寜 msgId 鍞竴绱㈠紩 INSERT OR IGNORE锛堜笉閲嶅銆佷笉涓㈠巻鍙诧級
        路 session 锛氭寜 sessionId UPSERT 鏈/鏃堕棿/鎽樿锛堣繖鍑犲垪浠ヨ澶囦负鍑嗭級
    杩斿洖 (鏂板娑堟伅鏁? 鍙樻洿浼氳瘽鏁?锛涗换浣曚竴姝ュけ璐ヨ繑鍥?None锛岃皟鐢ㄦ柟鎸夋棫琛屼负鐢ㄩ暅鍍忕户缁窇銆?
    """
    import sqlite3

    tmp_dir = dest_dir / "_merge"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    tmp_db = tmp_dir / name
    for suffix in ("", "-wal", "-shm"):
        p = tmp_dir / (name + suffix)
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
    for suffix in ("", "-wal"):
        src = "%s/%s%s" % (DB_DIR_ANDROID, name, suffix)
        rc, _out, err = device.run(["pull", src, str(tmp_dir / (name + suffix))], timeout=120)
        if rc != 0 and suffix == "":
            log.warning("鍚堝苟璁惧搴擄細pull 澶辫触 %r", err[:120])
            return None
    if not tmp_db.exists():
        return None

    con = sqlite3.connect(str(local))
    try:
        con.execute("ATTACH DATABASE ? AS dev", (str(tmp_db),))

        def cols(table, schema="main"):
            try:
                return [r[1] for r in con.execute("PRAGMA %s.table_info(%s)" % (schema, table))]
            except Exception:
                return []

        main_cols = cols("chatmsg")
        dev_cols = set(cols("chatmsg", "dev"))
        use = [c for c in main_cols if c != "id" and c in dev_cols]
        if not use or "msgId" not in use:
            log.warning("鍚堝苟璁惧搴擄細chatmsg 鍒椾笉鍖归厤锛坢ain=%d dev=%d锛?, len(main_cols), len(dev_cols))
            return None
        before = con.total_changes
        con.execute("INSERT OR IGNORE INTO main.chatmsg (%s) SELECT %s FROM dev.chatmsg"
                    % (", ".join(use), ", ".join(use)))
        new_msgs = con.total_changes - before

        s_cols = cols("session")
        s_dev = set(cols("session", "dev"))
        s_use = [c for c in s_cols if c != "id" and c in s_dev]
        touched = 0
        if s_use and "sessionId" in s_use:
            upd = [c for c in s_use if c != "sessionId"]
            before2 = con.total_changes
            con.execute(
                "INSERT INTO main.session (%s) SELECT %s FROM dev.session WHERE 1 "
                "ON CONFLICT(sessionId) DO UPDATE SET %s"
                % (", ".join(s_use), ", ".join(s_use),
                   ", ".join("%s=excluded.%s" % (c, c) for c in upd)))
            touched = con.total_changes - before2
        con.commit()
        try:
            con.execute("DETACH DATABASE dev")
        except Exception:
            pass
        return new_msgs, touched
    except Exception as e:
        log.warning("鍚堝苟璁惧搴撳埌闀滃儚澶辫触: %r", e)
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def sync(device, name, dest_dir=None, keep=3, retries=3):
    """鎶婅澶囦笂鐨勪竴涓簱锛坉b+wal+shm锛夋媺鍒版湰鍦扮紦瀛樸€傝繑鍥炴湰鍦拌矾寰勩€?

    馃敶 涓€鑷存€у潙锛?026-11-02 瀹炴祴锛屽鑷磋繃 `database disk image is malformed`锛夛細
      App 涓€鐩村湪鍐欏簱锛屾垜浠€愭枃浠?pull 鏃讹紝**db 鍜?wal 鎷垮埌鐨勬槸涓や釜涓嶅悓鏃跺埢鐨勭姸鎬?*
      鈫?鏈湴鎵撳紑鏃跺簲鐢?wal 澶辫触 鈫?鏁翠釜搴撴姤 malformed锛屾墍鏈夋煡璇㈠叏宕╋紙daemon 鍋滄憜锛夈€?
    淇硶锛?
      鈶?鍏堝垹鏈湴涓変釜鏂囦欢鍐嶆媺锛堥伩鍏嶆棫鏂囦欢娈嬬暀娣疯繘鏂板簱锛?
      鈶?鎷夊畬绔嬪埢鍋?`PRAGMA integrity_check`
      鈶?鍧忎簡灏遍噸鎷夛紝鏈€澶?retries 娆★紱鍏ㄥけ璐ユ姏寮傚父璁╀笂灞傜煡閬?
    """
    import sqlite3

    dest_dir = Path(dest_dir or CACHE) / name.replace("-DATA.db", "")
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / name

    # 馃敶馃敶馃敶 2026-11-08 10:38锛堢敤鎴风‖瑙勫垯锛氫袱涓处鍙风殑搴撳繀椤诲垎寮€锛屼笉鑳戒覆锛?
    #
    #   銆愪簨鏁呴闃猜锋暟鎹笉鍙仮澶嶃€戣澶囦笂**琚櫥鍑虹殑璐﹀彿锛屽簱浼氳 Soul 娓呯┖/鎴柇**锛?
    #     瀹炴祴 10:35 鈥斺€?96691646 鐧诲嚭鍚庯紝瀹冪殑搴撲粠 14.2MB(20900 鏉? 鎺夊埌 76KB銆?
    #   鑰屼笅闈㈢殑 `_pull_all()` 绗竴姝ュ氨鏄?*鍒犳帀鏈湴涓変釜鏂囦欢**鍐?pull锛?
    #   鎵€浠ュ彧瑕佹湁浜猴紙鎴栧畾鏃朵换鍔★級鍦ㄥ綋鍓嶇櫥褰?402 鐨勬儏鍐典笅璋冧竴娆?
    #   `sync(966鐨勫簱)`锛屾湰鍦?20900 鏉″巻鍙插氨琚?76KB 绌哄簱姘镐箙瑕嗙洊銆?
    #
    #   淇濇姢锛?*鍏堥噺璁惧渚у簱澶у皬锛屽啀鍜屾湰鍦版瘮**銆?
    #     路 璁惧搴?>= 鏈湴 50%  鈫?姝ｅ父澧為噺锛屾斁琛?
    #     路 璁惧搴?<  鏈湴 50%  鈫?鍒ゅ畾銆岃娓呯┖/琚埅鏂€嶏紝**鎷掔粷鍚屾**骞舵姏寮傚父
    #       锛堜笂灞?open_account 浼氭崟鑾烽檷绾э紝杩欎竴杞笉璺戯紝浣嗗巻鍙叉暟鎹繚浣忥級
    #   鍚屾椂鎶婃湰鍦板簱鍏堝彟瀛?`*.keep`锛屼竾涓€鍒ゆ柇澶辫涔熻繕鑳戒汉宸ユ壘鍥炪€?
    #
    #   涓轰粈涔堢敤鏂囦欢澶у皬鑰屼笉鏄鏁帮細琛屾暟瑕佸厛鎵撳紑搴擄紙鍙兘 malformed锛夛紝
    #   澶у皬鐢?`stat` 涓€鏉″懡浠?0.05s锛屼笖 14.2MB鈫?6KB 杩欑閲忕骇宸笉浼氳鍒ゃ€?
    _dev_sz, _loc_sz = 0, 0
    try:
        if local.exists():
            _loc_sz = local.stat().st_size
        # 馃敶 娉ㄦ剰锛氳繖閲屼笉鑳藉啓 "stat -c %%s %s/%s" % (...) 鈥斺€?涓や釜 %s 浼氳
        #   stat 鐨勬牸寮忎覆鍚冩帀锛堝疄娴?TypeError锛夈€傜敤 + 鎷兼帴鏈€绋炽€?
        #
        # 馃敶馃敶 2026-11-08 12:3x锛堜繚鎶ゅけ鏁堢殑鐪熸牴鍥狅紝瀹炴祴鍙戠幇锛夛細
        #   鍘熸潵杩欓噷鍐欑殑鏄?`su -c 'stat ...'`锛屼絾**鏈幆澧冩牴鏈病鏈?su**
        #   锛坄/system/bin/sh: su: inaccessible or not found`锛夛紝
        #   鑰?adb shell 鏈韩灏辨槸 **root**锛坄whoami` 鈫?root锛夛紝
        #   鏍规湰涓嶉渶瑕?su銆傜粨鏋滐細鍛戒护姘歌繙澶辫触 鈫?`_dev_sz` 姘歌繙 0
        #   鈫?涓嬮潰 `_dev_sz > 0` 姘歌繙涓哄亣 鈫?**淇濇姢閫昏緫浠庢湭鐢熸晥杩囦竴娆?*銆?
        #   鍚庢灉锛歋oul 娓呯┖璁惧搴撳悗锛宻ync() 鐓у父 pull锛屾妸鏈湴 14.2MB 鍘嗗彶
        #   瑕嗙洊鎴?76KB 绌哄簱锛堝疄娴?11-08 10:35 涓?12:30 鍚勫彂鐢熶竴娆★級銆?
        #   淇硶锛氬厛璇曚笉甯?su 鐨勮８ stat锛坮oot shell 鐩存帴鍙锛夛紝澶辫触鍐嶉€€鍥?su銆?
        _stat_cmd = "stat -c %s " + DB_DIR_ANDROID + "/" + name
        _rc, _out, _ = device.run(["shell", _stat_cmd], timeout=20)
        if isinstance(_out, (bytes, bytearray)):
            _out = _out.decode("utf-8", "replace")
        _txt = (_out or "").strip().splitlines()
        if not (_txt and _txt[-1].strip().isdigit()):
            # 閫€鍥?su 褰㈡€侊紙鏈変簺璁惧 shell 闈?root锛岄渶瑕?su锛?
            _cmd2 = "su -c 'stat -c %s " + DB_DIR_ANDROID + "/" + name + "'"
            _rc, _out, _ = device.run(["shell", _cmd2], timeout=20)
            if isinstance(_out, (bytes, bytearray)):
                _out = _out.decode("utf-8", "replace")
            _txt = (_out or "").strip().splitlines()
        if _txt and _txt[-1].strip().isdigit():
            _dev_sz = int(_txt[-1].strip())
        else:
            log.debug("閲忚澶囧簱澶у皬澶辫触锛堝師濮嬭緭鍑?%r锛夆€斺€?淇濇姢鏃犳硶鐢熸晥", (_txt or [])[-3:])
    except Exception as _e:
        log.debug("閲忓簱澶у皬澶辫触锛堣烦杩囦繚鎶わ級: %r", _e)
        _dev_sz, _loc_sz = 0, 0

    if _loc_sz > 2 * 1024 * 1024 and _dev_sz > 0 and _dev_sz < _loc_sz * 0.5:
        # 馃敶馃敶 2026-11-08 10:52锛堢敓浜у疄娴嬩慨姝ｏ細鍏?鎷掔粷"浼氳 daemon 瀹屽叏鐦棯锛?
        #
        #   瀹炴祴锛歋oul 鍦?10:25~10:49 鎶?*涓や釜璐﹀彿鐨勫簱閮芥竻绌轰簡**
        #     96691646锛? 涓?session / 50 鏉?chatmsg锛堝師 1500/20900锛?
        #     402857053锛?4 涓?session / 60 鏉?chatmsg锛堝師 1298/10590锛?
        #   濡傛灉杩欓噷鐩存帴 raise锛宍open_account()` 灏辨案杩滄嬁涓嶅埌搴?
        #   鈫?daemon 姣忚疆閮芥姏寮傚父 鈫?鏁翠釜鏈哄櫒浜虹槴鐥紙姣旀暟鎹瑕嗙洊鏇寸碂锛夈€?
        #
        #   姝ｇ‘鍋氭硶锛堟棦淇濇暟鎹張涓嶇槴鐥級锛?
        #     路 鍏堟妸鏈湴闀滃儚澶囦唤鎴?`.keep`锛堜汉宸ュ彲鎵惧洖锛?
        #     路 **涓嶈鐩栨湰鍦板簱**锛岀洿鎺?*缁х画鐢ㄦ湰鍦伴暅鍍?*锛堝畠鏄渶杩戜竴娆＄殑鐪熷疄蹇収锛?
        #     路 鎵?warning 璇存竻銆岃澶囧簱琚竻绌猴紝鏈疆鐢ㄦ湰鍦伴暅鍍忋€?
        #   娉ㄦ剰锛氭湰鍦伴暅鍍忎細姣旇澶囨棫锛屾墍浠?`watch`/`dirty` 鍒ゅ畾瑕佸厑璁歌繖绉嶉檲鏃э紝
        #   鍚﹀垯浼氶櫡鍏ャ€屽簱姣旇澶囨棫 鈫?涓€鐩村己鍒跺埛鏂?鈫?涓€鐩磋蛋杩欐潯鍒嗘敮銆嶇殑寰幆銆?
        try:
            keep = dest_dir / (name + ".keep")
            if not keep.exists():
                import shutil as _sh
                _sh.copy2(str(local), str(keep))
                log.warning("宸叉妸鏈湴闀滃儚鍙﹀瓨涓?%s", keep.name)
        except Exception as _e:
            log.debug("瀛?.keep 澶辫触: %r", _e)
        log.warning(
            "璁惧搴?%s 鍙墿 %.0fKB锛堟湰鍦伴暅鍍?%.1fMB锛夆€斺€?鐤戜技 Soul 宸叉竻绌鸿璐﹀彿璁板綍锛?
            "**淇濈暀鏈湴闀滃儚銆佹湰杞敤瀹冪户缁窇**锛堜笉瑕嗙洊銆佷笉鎶ラ敊锛?,
            name[:28], _dev_sz / 1024.0, _loc_sz / 1048576.0)
        # 馃敶 2026-11-08 21:0x锛?*涓嶅啀鐩存帴 return**銆傞暅鍍忓喕缁撴槸銆屾秷鎭嚑灏忔椂涓嶅洖銆嶇殑
        #   鐪熸牴鍥狅紙璇﹁ _merge_device_into_mirror 娉ㄩ噴锛夈€傝澶囧簱浠嶆槸鏂版秷鎭敮涓€鏉ユ簮锛?
        #   鎶婃柊澧炶骞惰繘闀滃儚鍗冲彲锛氬巻鍙蹭繚鐣?+ 鏂版秷鎭彲瑙侊紝涓や釜鐩爣鍚屾椂婊¤冻銆?
        _mg = _merge_device_into_mirror(device, name, local, dest_dir)
        if _mg is not None:
            log.warning("璁惧搴撶缉姘?鈫?宸插閲忓悎骞惰繘闀滃儚锛氭柊澧炴秷鎭?%d 鏉?/ 鏇存柊浼氳瘽 %d 涓?
                        "锛堝巻鍙茶鍏ㄩ儴淇濈暀锛?, _mg[0], _mg[1])
        else:
            log.warning("璁惧搴撶缉姘?鈫?澧為噺鍚堝苟澶辫触锛屾湰杞户缁敤鏈湴闀滃儚锛堝彲鑳界湅涓嶅埌鏈€鏂版秷鎭級")
        # 馃敶馃敶 2026-11-12锛圖S-07锛氱缉姘村悎骞跺垎鏀己 wal_checkpoint(TRUNCATE)锛?
        #   姝ｅ父 sync 鐨?_pull_all 灏鹃儴锛堣 830 琛岋級浼氬湪鍚堝苟鍚庡仛
        #   `PRAGMA wal_checkpoint(TRUNCATE)`锛屼絾**缂╂按鍒嗘敮**鐩存帴 return local锛?
        #   涓嶇粡杩囧畠 鈥斺€?浜庢槸 `_merge_device_into_mirror` 鍐欏叆涓诲簱鍚庨仐鐣欑殑
        #   -wal/-shm 鑻ユ瘮涓诲簱鏃э紝鍚庣画鍙杩炴帴浼氭寜鏃?shm 鎴柇 wal 灏鹃儴锛?
        #   鎶婂垰骞惰繘闀滃儚鐨勬柊娑堟伅銆岀湅娌′簡銆嶏紙涓?2026-11-04 蹇呭洖鐩插尯鍚屾牴鍥狅級銆?
        #   淇硶锛氫笌 _pull_all 涓€鑷达紝缂╂按鍚堝苟鍚庝篃 checkpoint 涓€娆★紙骞傜瓑銆佸彧璇诲畨鍏級銆?
        try:
            import sqlite3 as _sq
            _c = _sq.connect(str(local), timeout=5)
            try:
                _r = _c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                log.info("缂╂按鍚堝苟鍚?wal checkpoint -> %r", _r)
            finally:
                _c.close()
        except Exception as _e_cp:
            log.warning("缂╂按鍚堝苟鍚?wal checkpoint 澶辫触锛堝彧褰卞搷璇诲埌 wal 灏鹃儴锛? %r", _e_cp)
        return local

    def _pull_all():
        # 馃敶 2026-11-13 淇 DS-03锛圥1 澶辫触鍚屾姣佹帀鏈湴闀滃儚锛夛細**鍒犳湰鍦板墠鍏堝浠?*銆?
        #    鍘熸潵姝ｅ父澧為噺璺緞绗竴姝ュ氨鍒犳湰鍦?db/wal/shm锛?77-784锛夛紝闅忓悗鎵?pull锛?
        #    pull 澶辫触锛坮c!=0锛夋垨 integrity 涓嶈繃鏃讹紝鏈湴鍘嗗彶闀滃儚锛?4.2MB/20900 鏉★級
        #    宸叉案涔呭垹闄や笖鏃犲浠斤紙缂╂按淇濇姢鍙湪銆岃澶?鏈湴 50%銆嶅垎鏀仛 .keep锛夈€?
        #    鏀癸細鍒犲墠 copy2 鍒?`.keep`锛屽け璐ュ悗鑳芥仮澶嶏紙鎴栬嚦灏戜笉涓㈠巻鍙诧級銆?
        _keep_files = []
        for suffix in ("", "-wal"):
            p = dest_dir / (name + suffix)
            if p.exists():
                try:
                    kp = dest_dir / (name + suffix + ".keep")
                    import shutil as _sh
                    _sh.copy2(str(p), str(kp))
                    _keep_files.append(kp)
                except Exception as _ke:
                    log.warning("DS-03 澶囦唤 %s 澶辫触锛堢户缁級: %r", p.name, _ke)
        # 鈶?鍏堝垹锛堟棫 wal 娈嬬暀浼氳鏂板簱琚垽鎹熷潖锛?
        for suffix in ("", "-wal", "-shm"):
            p = dest_dir / (name + suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # 馃敶 2026-11-04锛堝繀鍥炵洸鍖烘牴鍥狅級锛?*涓?pull 璁惧渚х殑 -shm**銆?
        #    瀹炴祴瀵圭収锛堝悓涓€浠?db+wal锛夛細
        #      路 甯︾潃璁惧 shm 鈫?鍙杩炴帴璇绘垚 unread=0銆佹湯鏉?07:02锛堟棫鍊硷級
        #      路 鍙嫹 db+wal   鈫?璇诲埌 unread=2銆?8:12:52銆屾病蹇欎粈涔堛€嶏紙鐪熷€硷級
        #    shm 鏄?App 杩涚▼鐨?mmap 绱㈠紩锛岃法鏈哄櫒/璺ㄦ椂鍒婚兘鏃犳剰涔夛紱涓€鏃︽瘮 wal 鏃э紝
        #    SQLite 灏辨寜瀹冪殑 mxFrame 鎴柇 wal 灏鹃儴 鈬?濂规渶鏂扮殑璇濆湪搴撻噷銆屼笉瀛樺湪銆嶏紝
        #    latest() 鍒ゃ€屾渶鍚庝竴鏉℃槸鎴戝彂鐨勩€嶁啋 candidates 闈欓粯鍚炴帀蹇呭洖銆?
        #    鏈湴 shm 鐢?SQLite 鎵撳紑鏃惰嚜琛岄噸寤猴紝涓嶉渶瑕佷篃涓嶈浠庤澶囨惉銆?
        for suffix in ("", "-wal"):
            src = "%s/%s%s" % (DB_DIR_ANDROID, name, suffix)
            dst = str(dest_dir / (name + suffix))
            rc, out, err = device.run(["pull", src, dst], timeout=120)
            if rc != 0 and suffix == "":
                # 馃敶 DS-03锛歱ull 澶辫触鏃舵仮澶嶅浠斤紝鍒鏈湴闀滃儚瑁稿锛堝巻鍙叉暟鎹紭鍏堬級銆?
                for _k in _keep_files:
                    try:
                        import shutil as _sh2
                        _sh2.copy2(str(_k), str(dest_dir / _k.name[:-5]))
                    except Exception as _re:
                        log.warning("DS-03 鎭㈠澶囦唤 %s 澶辫触: %r", _k.name, _re)
                raise RuntimeError("pull 澶辫触 %s: %r" % (src, err[:160]))
        stale_shm = dest_dir / (name + "-shm")
        if stale_shm.exists():
            try:
                stale_shm.unlink()
            except OSError:
                pass

    def _ok():
        try:
            con = sqlite3.connect(str(local))
            try:
                r = con.execute("PRAGMA integrity_check").fetchone()
                if not r or r[0] != "ok":
                    return False
                con.execute("SELECT COUNT(*) FROM chatmsg").fetchone()
                return True
            finally:
                con.close()
        except Exception:
            return False

    last_err = None
    for i in range(max(1, retries)):
        try:
            _pull_all()
        except Exception as e:
            last_err = e
            log.warning("绗?%d 娆?pull 澶辫触: %r", i + 1, e)
            time.sleep(0.8)
            continue
        if _ok():
            break
        last_err = RuntimeError("鎷変笅鏉ョ殑搴撲笉涓€鑷?)
        log.warning("绗?%d 娆℃媺鍒扮殑搴?integrity 涓嶉€氳繃锛圓pp 姝ｅ湪鍐欙級锛岄噸璇?, i + 1)
        time.sleep(1.0)
    else:
        raise RuntimeError("鎷夊簱杩炵画 %d 娆￠兘涓嶄竴鑷? %r" % (retries, last_err))

# 馃敶 2026-11-04锛堝繀鍥炵洸鍖烘牴娌伙紝瀹炴祴锛夛細鎶?-wal 鍚堝苟杩涗富搴撱€?
#    鐜拌薄锛氳澶囦晶 App 涓€鐩村湪鍐?wal锛屾垜浠€愭枃浠?pull 鍚庢湰鍦?-shm 杩樻槸涓婁竴杞殑鏃х储寮?
#    锛?8:20 閭ｆ sync锛?wal mtime 08:20:35锛?shm 鍗村仠鍦?07:52:37锛夈€係QLite 鎵撳紑鏃?
#    鎸夋棫 shm 鐨?mxFrame 鎴柇 wal 鈬?**鍙杩炴帴鐪嬩笉鍒板ス 08:12銆屾病蹇欎粈涔堛€? 08:17銆孾鐤戞儜][鐤戦棶]銆?*
#    锛堝簱閲屾妸 72803535 璇绘垚 unread=0 / 鏈潯 07:02 鐨勬垜鏂规秷鎭級锛宭atest() 灏卞垽
#    銆屾渶鍚庝竴鏉℃槸鎴戝彂鐨勩€嶁啋 candidates 鐩存帴 skip锛屽繀鍥炶闈欓粯鍚炴帀銆?
#    checkpoint(TRUNCATE) 鍚庝富搴撳嵆瀹屾暣蹇収锛屽彧璇昏繛鎺ヤ笉鍐嶄緷璧?shm/wal銆?
    try:
        _c = sqlite3.connect(str(local), timeout=5)
        try:
            _r = _c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            log.info("wal checkpoint -> %r", _r)
        finally:
            _c.close()
    except Exception as e:
        log.warning("wal checkpoint 澶辫触锛堝彧褰卞搷璇诲埌 wal 灏鹃儴锛? %r", e)

    # 绠€鍗曟竻鐞嗭細鍙暀鏈€杩?keep 浠藉簱锛堟寜 mtime锛?
    files = sorted(dest_dir.glob("*.db*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep * 3:]:
        try:
            p.unlink()
        except OSError:
            pass
    return local


def current_uid(device):
    """褰撳墠鐧诲綍璐﹀彿 uid銆?

    鏉ユ簮锛歚shared_prefs/sp_info_gather.xml` 閲岀殑 <string name="userid">銆?
    瀹炴祴 2026-11-02锛歎I 鏄剧ず銆岀娈囨弿缁樻湭鏉ユ椂鍏夈€嶆椂璇ュ€间负 402857053锛屼竴鑷淬€?
    鍒囧彿鍚庢鍊间細鍙橈紝鎵€浠ユ瘡娆￠兘瑕佺幇璇伙紝涓嶈兘缂撳瓨銆?

    馃敶 2026-11-08 10:42锛堢敓浜у疄娴嬩慨澶嶏級锛?
      shared_prefs 鍚屾牱鏄?u0_a52 绉佹湁鐩綍锛岄潪 root 璇讳笉鍒帮紙瀹炴祴 10:35 杩斿洖绌猴級銆?
      鏀瑰墠鍙瘯浜嗛潪 root 鐨?`cat`锛屼簬鏄?`current_uid()` 鎭掕繑鍥?None
      鈫?`open_account()` 璧?`if not want:` 鍒嗘敮鎷跨涓€涓簱 鈫?**鍙兘鎷块敊璐﹀彿鐨勫簱**銆?
      杩欐鏄敤鎴锋媴蹇冪殑銆岀敤 A 鐨勮亰澶╄褰曞幓 B 璐﹀彿鎼溿€嶃€?
      鏀规硶锛氬厛 `su -c cat`锛屽け璐ュ啀閫€鍥炴櫘閫?`cat`銆?
    """
    for cmd in ("su -c 'cat %s 2>/dev/null'" % SP_INFO,
                "cat %s 2>/dev/null" % SP_INFO):
        try:
            out = device.text(cmd, timeout=30) or ""
        except Exception:
            continue
        m = re.search(r'name="userid">(\d+)<', out)
        if m:
            return m.group(1)
    return None


_LAST = {"ts": 0.0, "db": None, "uid": ""}
REFRESH_S = 300          # 鏈湴搴撶紦瀛樻湁鏁堟湡锛堢敤鎴?2026-11-02锛?~10 鍒嗛挓鍚屾涓€娆″氨澶燂級


# 馃敶馃敶 2026-11-08 10:45锛堢敤鎴风‖瑙勫垯锛氥€屾ā鎷熷櫒鍐呯殑瀹炴椂搴?鍙厑璁歌 涓嶅厑璁稿啓銆嶏級
#
#   閾佸緥钀芥垚浠ｇ爜闂革細浠讳綍鍙戝線**璁惧渚?*鐨?SQL 蹇呴』鍏堣繃杩欓亾妫€鏌ャ€?
#   鐧藉悕鍗?= 鍙厑璁镐互 SELECT / WITH 寮€澶达紙WITH 鐢ㄤ簬 CTE锛屼粛鍙锛夈€?
#   娉ㄦ剰锛氳澶囩 sqlite3 鏄互 **root** 璺戠殑锛坄su -c`锛夛紝涓€鏃﹀啓浜嗘病鏈変换浣曞洖婊氫綑鍦帮紝
#        鎵€浠ラ椄鏀惧湪鏈€澶栧眰锛屽畞鍙鎷︿篃涓嶆斁杩囥€?
_WRITE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"vacuum|reindex|pragma\s+\w+\s*=)\b", re.I)


def _assert_readonly(sql):
    """鎷掔粷浠讳綍闈炲彧璇?SQL锛堝彂寰€璁惧鐨勫簱锛夈€傝繑鍥?True 琛ㄧず瀹夊叏銆?""
    s = (sql or "").strip().lstrip(";").strip()
    if not s:
        return False
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        log.error("鉀?鎷掔粷闈炲彧璇?SQL锛堣澶囧簱鍙锛? %r", s[:120])
        return False
    if _WRITE_RE.search(s):
        log.error("鉀?鎷掔粷鍚啓鎿嶄綔鐨?SQL锛堣澶囧簱鍙锛? %r", s[:120])
        return False
    return True


def _dev_sql(device, dbname, sql, timeout=15):
    """鍦ㄨ澶囦笂瀵规寚瀹氬簱璺戜竴鏉?*鍙** SQL锛岃繑鍥炲師濮嬫枃鏈紙澶辫触杩斿洖 ""锛夈€?

    鎶藉嚭鏉ュ彧涓鸿涓嬮潰鐨勫嚱鏁板皯閲嶅閭ｄ覆 `sqlite3 "璺緞" "SQL"` 鏍锋澘銆?

    馃敶馃敶 2026-11-08 10:45 鐢ㄦ埛纭鍒欙細銆屾ā鎷熷櫒鍐呯殑瀹炴椂搴撳彧鍏佽璇伙紝涓嶅厑璁稿啓銆嶃€?
      鏈嚱鏁版槸鎵€鏈夈€岃澶囦晶 SQL銆嶇殑鍞竴鍑哄彛锛屽洜姝ゅ湪杩欓噷鍔?*寮哄埗鍙闂?*锛?
        路 鍙斁琛?SELECT / WITH 寮€澶?
        路 鍛戒腑 insert/update/delete/drop/alter/create/replace/truncate/
          attach/vacuum/pragma xxx= 浠讳竴鍏抽敭瀛?鈫?鐩存帴鎷掔粷骞?error 鏃ュ織
      杩欐牱鍗充娇灏嗘潵鏈変汉锛堟垨鎴戯級鍐欓敊涓€鍙?UPDATE锛屼篃涓嶄細鐪熺殑鎵撳埌璁惧搴撲笂銆?
      娉ㄦ剰锛氳涔熻蛋 `su -c`锛坲0_a52 绉佹湁鐩綍锛岄潪 root 璇讳笉鍒帮級锛?
      鎵€浠ャ€屽彧璇汇€嶅繀椤荤敱浠ｇ爜淇濊瘉锛屼笉鑳戒緷璧栨枃浠舵潈闄愩€?
    """
    if not _assert_readonly(sql):
        return ""
    # 馃敶馃敶 2026-11-08 12:59锛堢浜屾韪?`su` 杩欎釜鍧戯紝杩欐鏄?*閿欒琚綋鎴愮粨鏋滆繑鍥?*锛?
    #
    #   鏈ā鎷熷櫒涓?**`su` 鏍规湰涓嶅瓨鍦?*锛坅db shell 鏈韩宸茬粡鏄?root锛?
    #   `whoami` 鈫?root锛夛紝鎵€浠?`su -c '...'` 杩斿洖鐨勬槸锛?
    #       /system/bin/sh: su: inaccessible or not found
    #   鑰?`2>&1` 鎶婅繖鍙ラ敊璇?*娣疯繘 stdout**锛宍device.text()` 姝ｅ父杩斿洖浜嗗畠锛?
    #   浜庢槸 `except` 鍒嗘敮姘歌繙涓嶈Е鍙?鈫?涓婂眰鎷垮埌涓€娈点€岀湅璧锋潵鍍忚緭鍑恒€嶇殑鎶ラ敊鏂囨湰锛?
    #   瑙ｆ瀽鍑虹┖闆嗗悎 鈫?`_db_name_for_uid` 姘歌繙杩斿洖 None 鈫?瀛樻椿鏍￠獙姘歌繙闄嶇骇銆?
    #
    #   杩欏拰 imdb.sync() 閲岄偅涓€宻u 涓嶅瓨鍦ㄥ鑷存埅鏂繚鎶ゆ案涓嶇敓鏁堛€嶆槸**鍚屼竴涓牴鍥?*
    #   锛堣 2026-11-08 涓婂崍鐨勪慨澶嶏級銆傚悓涓€涓潙韪╀袱娆★紝鎵€浠ヨ繖娆″湪**鍞竴鍑哄彛**澶勬牴娌伙細
    #     鈶?鍏堣瘯瑁稿懡浠わ紙鏈幆澧?adb 宸叉槸 root锛岀洿鎺ュ氨鑳借锛夛紱
    #     鈶?瑁稿懡浠ゅけ璐?鎶?su 绫婚敊璇紝鍐嶉€€鍥?`su -c`锛堝吋瀹圭湡姝ｉ渶瑕?su 鐨勭幆澧冿級锛?
    #     鈶?浠讳綍鎯呭喌涓嬶紝杈撳嚭閲屽嚭鐜?"su: inaccessible"/"not found"/"Permission denied"
    #        涓€寰嬪垽涓哄け璐ワ紝杩斿洖 ""锛岀粷涓嶅綋鎴愭暟鎹線涓婁紶銆?
    _ERR_MARKS = ("su: inaccessible", "su: not found", "Permission denied",
                  "No such file or directory", "inaccessible or not found")

    def _clean(txt):
        t = (txt or "").strip()
        for m in _ERR_MARKS:
            if m.lower() in t.lower():
                return ""
        return t

    # 鈶?瑁?sqlite3锛堟湰鐜棣栭€夛細adb 宸?root锛?
    try:
        out = _clean(device.text('sqlite3 "%s/%s" "%s" 2>&1'
                                 % (DB_DIR_ANDROID, dbname, sql), timeout=timeout))
        if out:
            return out
    except Exception:
        pass
    # 鈶?閫€鍥?su -c锛堝吋瀹归潪 root adb 鐜锛?
    try:
        return _clean(device.text('su -c \'sqlite3 "%s/%s" "%s"\' 2>&1'
                                  % (DB_DIR_ANDROID, dbname, sql), timeout=timeout))
    except Exception:
        return ""


def _parse_kv(txt):
    """鎶?`a|1` 閫愯瑙ｆ瀽鎴?{a: 1}锛堥潪娉曡鐩存帴璺宠繃锛夈€?""
    out = {}
    for ln in (txt or "").replace("\r", "").splitlines():
        ln = ln.strip()
        if not ln or "|" not in ln:
            continue
        k, _, v = ln.partition("|")
        try:
            out[str(k).strip()] = int(float(v))
        except Exception:
            continue
    return out


# 馃敶馃敶 2026-11-12锛圖S-06锛歭ive-uid 缂撳瓨 TTL 缁熶竴锛?
#   璁惧瀛樻椿 uid 闆嗗悎鐨勭紦瀛樻椂闀裤€俻endingq._device_live_uids 鐢ㄥ畠鍋?120s 缂撳瓨锛?
#   data.pending锛坰hould_reply / unread_sids锛夋寜璁捐**鐜版煡**锛堟瘡娆℃柊椴滐紝淇濊瘉
#   娓呯孩鐐圭洰鏍囧噯纭級鈥斺€?涓よ竟鍏辩敤**鍚屼竴涓?TTL 甯搁噺**锛岄伩鍏嶅皢鏉ヨ皟鏃堕暱鍙敼涓€澶?
#   瀵艰嚧涓よ竟鍙ｅ緞婕傜Щ銆俻ending.py 渚т笉缂撳瓨锛屼粎寮曠敤姝ゅ父閲忎綔涓恒€岃嫢鍔犵紦瀛樺垯鐢ㄥ悓涓€
#   鏃堕暱銆嶇殑绾﹀畾銆?
DEVICE_LIVE_TTL_S = 120.0


def device_live_uids(device, uid, timeout=15):
    """**褰撳墠璐﹀彿鑷繁鐨勮澶囧簱**閲岃繕瀛樺湪鐨?toUserId 闆嗗悎銆傚彇涓嶅埌杩斿洖 None銆?

    馃敶馃敶 2026-11-08 12:56锛圥0锛氭湰鍦伴暅鍍忛噷鐨勩€屾浜恒€嶏級

      瀹炴祴锛堢洿鎺?pull 璁惧搴撳姣旓紝瑙?_final.py锛夛細
        璐﹀彿 96691646锛氭湰鍦伴暅鍍?session 1524 琛?/ 12.2MB
                       璁惧鐪熷疄 session   31 琛?/ 204KB
                       uid 浜ら泦 29锛?*鍙湪鏈湴銆佽澶囦笂宸蹭笉瀛樺湪 = 1495 涓?*
        璐﹀彿 402857053锛氭湰鍦伴暅鍍?1298 鈫?璁惧 55锛堝悓涓€鐜拌薄锛?

      Soul **鐪熺殑鎶婅繖涓处鍙风殑鍘嗗彶浼氳瘽娓呯┖浜?*銆傛湰鍦伴暅鍍忔槸鍘嗗彶蹇収
      锛坄sync()` 鐨勬埅鏂繚鎶ゆ晠鎰忎繚鐣欏畠锛屼笉瑕嗙洊锛夛紝閲岄潰缁濆ぇ澶氭暟浼氳瘽鍦?App 閲?
      宸茬粡涓嶅瓨鍦ㄣ€傛嬁杩欎簺褰撱€屽緟鍥為槦鍒椼€嶁啋 缈诲睆缈讳笉鍒般€佹悳绱㈡悳涓嶅埌 鈫?
      姣忎汉鐧界儳 40~50s锛?*涓€涓汉閮藉洖涓嶆帀**锛堝疄娴嬪€欓€夐噷璁惧涓婅繕娲荤潃鐨?0/1锛夈€?

    **璐﹀彿闅旂閾佸緥锛堢敤鎴峰弽澶嶅己璋冿級**锛氬彧鏌?*鏈处鍙疯嚜宸?*鐨勯偅涓簱銆?
      路 搴撳悕鐢?`uid` 鍙嶆帹锛坄IM-SDK-<base64(uid+鍚庣紑)>-DATA.db`锛夛紝缁濅笉閬嶅巻涓や釜搴擄紱
      路 涓€涓?uid 涓€涓簱锛孉 璐﹀彿鐨?uid 闆嗗悎缁濅笉鐢ㄤ簬 B 璐﹀彿鐨勫€欓€夎繃婊ゃ€?
      杩欐牱鍗充娇涓や釜搴撳悓鏃跺瓨鍦紝涔熶笉浼氬嚭鐜般€屾嬁 A 鐨勪汉鍘?B 璐﹀彿鎼溿€嶃€?

    杩斿洖锛歴et(str uid) 鈥斺€?姝ｅ父
          None        鈥斺€?鍙栦笉鍒帮紙鏃?root / adb 鎶栧姩 / 搴撲笉瀛樺湪锛夛紝璋冪敤鏂归』**闄嶇骇涓嶈繃婊?*
    """
    try:
        name = _db_name_for_uid(device, uid)
    except Exception as e:
        log.debug("device_live_uids: 鍙嶆帹搴撳悕澶辫触 %r", e)
        name = None
    if not name:
        log.debug("device_live_uids: 鎵句笉鍒?uid=%s 瀵瑰簲鐨勮澶囧簱", uid)
        return None
    try:
        txt = _dev_sql(device, name,
                       "select distinct toUserId from session where toUserId>0",
                       timeout=timeout)
    except Exception as e:
        log.debug("device_live_uids: 鏌?%s 澶辫触 %r", name, e)
        return None
    out = set()
    for ln in (txt or "").replace("\r", "").splitlines():
        s = ln.strip()
        if s and s.lstrip("-").isdigit():
            out.add(s)
    if not out:
        # 馃敶馃敶 2026-11-12锛圖S-08 绌洪泦鍒ゆ柇 路 鏈€缁堢粨璁猴細**淇濇寔 None锛屼笉杩囨护**锛?
        #   绌洪泦鍚堟湁涓ょ鍙兘锛氱湡鐨勪竴涓汉閮芥病鏈?/ 鏌ヨ澶辫触銆?
        #   淇硶鍘熸湰鎯虫妸銆屾煡璇㈡垚鍔熶絾 0 浼氳瘽銆嶄笌銆屾煡璇㈠け璐ャ€嶅尯鍒嗗紑锛氭垚鍔熻繑鍥炵┖ set銆?
        #   澶辫触杩斿洖 None锛岃璋冪敤鏂瑰湪銆岃澶囩湡 0 浼氳瘽銆嶆椂杩囨护鎺夊叏閮ㄩ暅鍍忓兊灏搞€?
        #   鈥斺€?浣嗗仛涓嶅埌锛屾牴鍥犲湪 `_dev_sql`锛堟湰鏂囦欢 903锛夛細瀹冪敤 `_clean()` 鎶?
        #   閿欒鏍囪缁熶竴娲楁垚 ""锛屼簬鏄?*銆? 琛屾垚鍔熴€嶅拰銆屾煡璇㈠け璐ャ€嶉兘杩斿洖 ""**锛?
        #   鍒拌繖涓€灞傛牴鏈棤娉曞尯鍒嗐€?
        #   鑻ュ己琛岃繑鍥炵┖ set锛氫竴娆?adb 鎶栧姩/鏌ヨ澶辫触锛堝悓鏍峰緱鍒?""锛変細琚綋鎴?
        #   銆岃澶囩湡娌′細璇濄€嶁啋 璋冪敤鏂硅繃婊ゆ帀**鍏ㄩ儴**鍊欓€?鈫?婕忓洖锛堟渶宸け璐ユā寮忥級銆?
        #   鏉冭　鍚?*瀹佸彲淇濇寔 None锛堟棫琛屼负=闄嶇骇涓嶈繃婊わ級**锛氳澶囩缉姘?962 娆＄殑涓诲洜鏄?
        #   銆岃澶囦粛鏈夊緢澶氫細璇濓紝鍙槸姣旈暅鍍忓皯銆嶏紝device_live_uids 杩斿洖鐨勬槸**闈炵┖**
        #   闆嗗悎锛堜粎缂烘浜猴級鈫?杩囨护渚濈劧鐢熸晥锛涚湡姝ｇ殑銆? 浼氳瘽銆嶆槸缃曡杈圭紭锛屼笉鍊煎緱
        #   涓哄畠鍐掋€屼竴娆?adb 鎶栧姩灏辨紡鍥炲叏閮ㄣ€嶇殑椋庨櫓銆?
        #   HY-13 宸叉妸鍚屼竴璁惧瀛樻椿鏍￠獙琛ュ埌 unread_sids()锛堟竻绾㈢偣鐩爣婧愶級锛?
        #   甯歌缂╂按鍦烘櫙宸茶瑕嗙洊锛涙澶勪繚鐣欐棫琛屼负骞剁暀妗ｃ€?
        return None
    return out


def _db_name_for_uid(device, uid, timeout=15):
    """鍙嶆帹鏌愪釜 uid 瀵瑰簲鐨勮澶囧簱鏂囦欢鍚嶏紙鎵句笉鍒拌繑鍥?None锛夈€?

    璁惧涓婂簱鍚嶅舰濡?`IM-SDK-<base64>-DATA.db`锛宐ase64 娈电敱
    銆寀id + 鍥哄畾鍚庣紑銆嶆嫾鎴愶紝鏃犳硶浠?uid 鐩存帴绠楀嚭锛屾墍浠ワ細
      鈶?鍏堢湅 `device_owner_uid()` 鏄惁姝ｅソ鏄繖涓?uid 鈫?鐩存帴鐢ㄥ畠鐨勫簱
      鈶?鍚﹀垯閬嶅巻搴撳悕锛岄€愪釜鐢?sessionId 鍓嶇紑浼楁暟鍙嶆帹褰掑睘锛屽尮閰?uid 鎵嶈繑鍥?
    **鍙繑鍥炲崟涓簱鍚?*锛岀粷涓嶈繑鍥炲涓?鈥斺€?淇濊瘉璐﹀彿闅旂銆?
    """
    raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    names = [x.strip() for x in raw.replace("\r", "").splitlines()
             if x.strip().endswith("-DATA.db")]
    if not names:
        return None
    want = str(uid)
    for nm in names:
        # 馃敶 2026-11-08 12:58锛堜袱涓潙涓€璧疯俯浜嗭紝閮借涓嬫潵锛夛細
        #   鈶?`toUserId` 鍙兘鏄?*璐熸暟**锛堝畼鏂瑰彿 -10011锛夛紝`length(toUserId)` 绠楃殑鏄?
        #      銆屽甫璐熷彿鐨勯暱搴︺€嶁啋 substr 灏戝垏涓€浣?鈫?prefix 鍙樻垚 '966916464'锛屾案杩滃尮閰嶄笉涓娿€?
        #   鈶?鎯崇敤 `replace(toUserId,'-','')` 鍘绘帀璐熷彿锛岃 `_assert_readonly` 鐨?
        #      `\breplace\b` 瑙勫垯褰撴垚鍐欐搷浣?*鐩存帴鎷掔粷**锛堝畠鏄?INSERT OR REPLACE 鐨勫叧閿瓧锛夈€?
        #      涓嶈兘涓轰簡杩欎釜鍘绘斁瀹藉彧璇婚椄锛堥偅鏄澶囧簱鍞竴鐨勫啓淇濇姢锛夛紝鏀圭敤涓嶈Е鍙戝叧閿瓧鐨勫啓娉曘€?
        #
        #   鏈€缁堝啓娉曪細鐢?`instr(toUserId,'-')` 鍒ゆ柇鏈夋棤璐熷彿锛屾湁鍒欓暱搴?-1锛?
        #   鍏ㄧ▼鍙湁 substr/length/instr锛屾棦姝ｇ‘鍙堣繃鍙闂搞€?
        q = ("select sid_prefix, count(*) c from ("
             "  select substr(sessionId, 1, length(sessionId)"
             "    - length(toUserId) + (case when instr(toUserId,'-')>0 then 1 else 0 end)"
             "  ) sid_prefix"
             "  from session"
             "  where length(sessionId) > length(toUserId)"
             "    - (case when instr(toUserId,'-')>0 then 1 else 0 end)"
             ") group by sid_prefix order by c desc limit 1")
        txt = _dev_sql(device, nm, q, timeout=timeout)
        for ln in (txt or "").replace("\r", "").splitlines():
            ln = ln.strip()
            if "|" in ln:
                pre = ln.split("|")[0].strip()
                if pre == want:
                    return nm
    return None


def _db_owner_uid(device, dbname, uid, timeout=15):
    """鍒ゆ柇鏌愪釜搴撴槸涓嶆槸 **uid 杩欎釜璐﹀彿** 鐨勫簱銆?

    鍒ゆ嵁锛堟帰閽堝疄娴?1261/1261 鎴愮珛锛夛細
        sessionId == str(uid) + str(toUserId)
      鎵€浠ャ€屽簱閲屾弧瓒宠绛夊紡鐨勮鏁?/ 鎬昏鏁般€嶅氨鏄綊灞炵疆淇″害銆?

    馃敶 涓轰粈涔堜笉鐢ㄦ枃浠跺悕鍒ゆ柇锛氭枃浠跺悕鏄?`IM-SDK-<base64 token>-DATA.db`锛?
      token 闅忕櫥褰曟€佸彉鍖栵紝鍜?uid 娌℃湁鍙帹瀵煎叧绯伙紙瀹炴祴涓や釜搴?token 瀹屽叏涓嶅悓锛夈€?
    馃敶 涓轰粈涔堜笉鐢?chatmsg 鎶曠エ锛氬叆鍚戜笉钀?chatmsg 鐨勮处鍙凤紙402857053锛夌エ鏁颁細鍋忎綆銆?
    杩斿洖 (鍛戒腑琛屾暟, 鎬昏鏁?锛涙煡璇㈠け璐ヨ繑鍥?(0, 0)銆?
    """
    if not uid:
        return 0, 0
    q = ("select (select count(*) from session "
         "where sessionId = '%s' || toUserId), (select count(*) from session)"
         % str(uid).replace("'", ""))
    txt = _dev_sql(device, dbname, q, timeout=timeout)
    for ln in (txt or "").replace("\r", "").splitlines():
        ln = ln.strip()
        if "|" not in ln:
            continue
        a, _, b = ln.partition("|")
        try:
            return int(float(a)), int(float(b))
        except Exception:
            continue
    return 0, 0


def device_owner_uid(device, timeout=15):
    """璁惧涓娿€屽綋鍓嶇櫥褰曡处鍙枫€嶇殑 uid锛?.05~0.3s锛岀函鍙锛夈€?

    浼樺厛璇?sp_info_gather.xml锛坄current_uid()`锛屾潈濞佷笖鐩存帴锛夛紱
    璇讳笉鍒版椂閫€鍥炪€岄€愬簱鐢?sessionId 鍓嶇紑鍙嶆帹銆嶁€斺€斾袱涓簱鍚勮嚜鐨勫鏁板墠缂€灏辨槸鍚勮嚜鐨?uid銆?
    閮藉け璐ヨ繑鍥?None锛堣皟鐢ㄦ柟蹇呴』闄嶇骇锛屼笉璁哥瀻鐚滐級銆?
    """
    try:
        u = current_uid(device)
        if u:
            return str(u)
    except Exception as e:
        log.debug("current_uid 澶辫触锛岄€€鍥炲墠缂€鍙嶆帹: %r", e)
    # 鍏滃簳锛氶€愬簱鍙嶆帹锛坰ession 琛ㄩ噷 sid 鍘绘帀 toUserId 鍚庣紑鐨勪紬鏁帮紝鍗?_guess_uid 鐨勮澶囩増锛?
    try:
        raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    except Exception:
        return None
    for nm in [x.strip() for x in raw.replace("\r", "").splitlines()
               if x.strip().endswith("-DATA.db")]:
        q = ("select sid_prefix, count(*) c from ("
             "  select substr(sessionId, 1, length(sessionId)-length(toUserId)) sid_prefix"
             "  from session where toUserId>0 and length(sessionId)>length(toUserId)"
             ") group by sid_prefix order by c desc limit 1")
        txt = _dev_sql(device, nm, q, timeout=timeout)
        for ln in (txt or "").replace("\r", "").splitlines():
            ln = ln.strip()
            if "|" in ln:
                pre = ln.split("|")[0].strip()
                if pre.isdigit():
                    return pre
    return None


def device_unread_map(device, timeout=15, uid=None, strict=True):
    """璁惧绔?sqlite3 鐩存煡銆屾湭璇讳細璇濄€嶁啋 {sid: unread}锛?.05~0.2s锛屼笉璧?pull锛夈€?

    馃敶 2026-11-04锛堢敤鎴峰彛寰勶細杩涘璇濇鍚?root 鑳芥嬁鍒?sid锛夛細
      dumpsys 鐨?Intent 鍙湁 `(has extras)`銆乴ogcat 涓嶆墦 sessionId銆乸refs 涔熸病鏈夛紝
      浣?App **杩涗細璇濅竴瀹氫細鎶婅 sid 鐨?unReadCount 缃?0** 鈥斺€?鎵€浠ャ€岃繘涔嬪墠/杩涗箣鍚庛€?
      鍚勬煡涓€娆℃湭璇婚泦鍚堬紝宸泦灏辨槸鍒氳繘鍘荤殑閭ｄ釜浼氳瘽锛堢簿纭?sid锛屼笉渚濊禆浠讳綍鏂囨湰姣斿锛夈€?
    鏌ヤ笉鍒帮紙鏃?sqlite3 / 鏃?root / 搴撹閿侊級杩斿洖 None锛岃皟鐢ㄦ柟鎸夈€屾棤璇佹嵁銆嶅鐞嗐€侀€€鍥炴枃鏈牎楠屻€?

    馃敶馃敶 2026-11-08 淇 P0锛堣法璐﹀彿涓插簱锛宭ead 瀹炴祴澶嶇幇锛夛細
      銆愭敼鍓嶃€戝鎵€鏈?`-DATA.db` 寰幆锛岀粨鏋滃叏閮?`out[str(sid)] = ...` 鍚堝苟杩涘悓涓€涓?
        dict锛?*娌℃湁浠讳綍 uid 杩囨护**銆傝澶囦笂鍚屾椂瀛樺湪涓や釜璐﹀彿鐨勫簱锛堝疄娴?
        `IM-SDK-SmNjOUhi...`=璐﹀彿1 uid 96691646銆乣IM-SDK-WGpBRi94...`=璐﹀彿2 uid 402857053锛夛紝
        涓や釜搴撶殑 session 琛ㄩ兘瀹屾暣鍙煡 鈥斺€?娣疯**涓嶆姤閿?*锛屽彧浼氶潤榛樿繑鍥炲彟涓€涓处鍙风殑浼氳瘽銆?
      銆愬疄娴嬭瘉鎹€憀ead 鍦?2026-11-08 澶嶇幇锛氬綋鍓嶇櫥褰?402857053锛屼絾鏈嚱鏁拌繑鍥炵殑 23 涓?
        sid 閲屾贩鐫€ `96691646-10011`锛堣处鍙? 鐨勭兢浼氳瘽锛夊拰 `96691646<toUserId>`锛堣处鍙? 浼氳瘽锛夈€?
        鐩存帴瀵瑰簲鏃ュ織閲屻€岃韩浠芥牎楠屽け璐?261 娆°€嶁€斺€?鎷垮埆浜虹殑 sid 鍘诲綋鍓嶇晫闈㈢偣锛屽繀鐒惰繘閿欎汉銆?
      銆愭敼娉曘€戝厛瀹氬綋鍓?uid锛坄device_owner_uid`锛夆啋 閫愬簱鐢?`sessionId=<uid>||toUserId`
        鍙嶆帹褰掑睘 鈫?**鍙煡鍛戒腑鐨勯偅涓€涓簱**锛涘尮閰嶄笉鍒板敮涓€搴撳氨杩斿洖 None锛堥檷绾э級锛岀粷涓嶆贩璇汇€?
      銆愰『甯︺€慡QL 鍔?`and toUserId > 0` 杩囨护缇?瀹樻柟浼氳瘽锛坄96691646-10011` 杩欑被甯︽í鏉?
        鐨?sid锛宼oUserId=-10011 鏄礋鏁帮級銆傝繖绫讳細璇濇竻绾㈢偣浼氱櫧鐑т竴杞繕杩涗笉鍒?chat 椤点€?

    鍙傛暟锛?
      uid    鈥斺€?宸茬煡褰撳墠璐﹀彿 uid 鏃朵紶鍏ワ紙鐪佷竴娆?sp_info 璇伙紝绾?0.1s锛?
      strict 鈥斺€?True锛堥粯璁わ級锛氬畾涓嶅埌 uid 灏辫繑鍥?None锛岀粷涓嶆贩璇伙紱
                False锛氶€€鍥炴棫琛屼负锛堟壂鍏ㄩ儴搴撳悎骞讹級鈥斺€?**鍙敤浜庢帓闅?*锛屼笟鍔′唬鐮佷笉瑕佷紶 False銆?
    """
    try:
        raw = device.text("ls -1 " + DB_DIR_ANDROID, timeout=timeout) or ""
    except Exception as e:
        log.debug("鍒楀簱鐩綍澶辫触: %r", e)
        return None
    dbs = [x.strip() for x in raw.replace("\r", "").splitlines()
           if x.strip().endswith("-DATA.db")]
    if not dbs:
        return None

    # ---- 鈶?瀹氬綋鍓嶈处鍙?----
    want = str(uid) if uid else None
    if not want:
        try:
            want = device_owner_uid(device, timeout=timeout)
        except Exception as e:
            log.debug("瀹氬綋鍓?uid 澶辫触: %r", e)
    if not want:
        if strict:
            log.warning("瀹氫笉鍒板綋鍓嶇櫥褰?uid 鈫?鎷掔粷鎵簱锛堥槻璺ㄨ处鍙蜂覆搴擄級锛屾寜鏃犺瘉鎹鐞?)
            return None
        log.warning("瀹氫笉鍒板綋鍓嶇櫥褰?uid 鈫?闈炰弗鏍兼ā寮忥紝閫€鍥炴壂鍏ㄩ儴搴擄紙鍙兘涓插彿锛?)
        return _unread_scan_all(device, dbs, timeout)

    # ---- 鈶?鎵惧綊灞炲簱锛坰essionId == uid + toUserId锛?---
    owner, best = None, (0, 0)
    for nm in dbs:
        hit, tot = _db_owner_uid(device, nm, want, timeout=timeout)
        if tot <= 0:
            continue
        if hit > best[0]:
            owner, best = nm, (hit, tot)
        if hit >= tot * 0.9:          # 90% 浠ヤ笂琛屾弧瓒?鈫?鐩存帴璁ゅ畾锛屼笉鐢ㄥ啀璇曞埆鐨勫簱
            owner = nm
            break
    if owner is None:
        # 涓€涓簱閮戒笉鍍忚繖涓处鍙风殑 鈫?璇存槑 uid 璇婚敊浜嗘垨搴撹繕娌¤惤鐩?
        if strict:
            log.warning("娌℃湁搴撳綊灞炲綋鍓?uid=%s锛堝悇搴撳懡涓?%s锛夆啋 杩斿洖 None 闄嶇骇", want, best)
            return None
        return _unread_scan_all(device, dbs, timeout)
    log.debug("褰撳墠 uid=%s 鈫?褰掑睘搴?%s锛?d/%d 琛屾弧瓒?sid 鍓嶇紑锛?,
              want, owner, best[0], best[1])

    # ---- 鈶?鍙煡杩欎竴涓簱锛屽苟杩囨护缇?瀹樻柟浼氳瘽 ----
    q = ("select sessionId,unReadCount from session "
         "where unReadCount>0 and toUserId>0")
    got = _parse_kv(_dev_sql(device, owner, q, timeout=timeout))
    return got if got else None


def _unread_scan_all(device, dbs, timeout=15):
    """鏃ц涓猴細鎵叏閮ㄥ簱骞跺悎骞讹紙**浼氳法璐﹀彿涓插簱**锛屼粎渚涙帓闅?闄嶇骇鍏滃簳锛夈€?

    涓氬姟璺緞涓嶈鐩存帴璋冨畠 鈥斺€?瑙?`device_unread_map` 鐨勮鏄庛€?
    """
    out = {}
    for nm in dbs:
        got = _parse_kv(_dev_sql(
            device, nm,
            "select sessionId,unReadCount from session "
            "where unReadCount>0 and toUserId>0", timeout=timeout))
        out.update(got)
    return out if out else None


def open_account(device, name=None, uid=None, max_age=REFRESH_S, force=False):
    """鎵撳紑銆屽綋鍓嶇櫥褰曡处鍙枫€嶅搴旂殑 IM 搴撱€?

    璁惧涓婂悓鏃跺瓨鍦ㄤ袱涓簱锛堟瘡涓处鍙蜂竴涓級锛屽繀椤绘寜 uid 閫夊锛?
    鍚﹀垯浼氭嬁鍙︿竴涓处鍙风殑鏁版嵁鍒ゆ柇銆岃鍥炶皝銆嶃€?

    馃敶 鍚屾鑺傚锛堢敤鎴?2026-11-02锛氥€屾湰鍦板簱 5 鍒嗛挓鍚屾涓€娆″憲鎴栬€?10 鍒嗛挓銆嶏級锛?
      鍘熸潵**姣忎竴杞?cycle 閮介噸鏂?pull**锛堜竴杞?60~90s锛屼竴娆?10MB锛夆€斺€?
      鍙堟參鍙堝鏄撴媺鍒颁笉涓€鑷寸殑搴擄紙App 涓€鐩村湪鍐欙級銆?
      鐜板湪锛?
        鈶?缂撳瓨 5 鍒嗛挓鍐呯洿鎺ュ鐢紙max_age=300锛?
        鈶?鏈夋柊娑堟伅淇″彿鏃?*寮哄埗鍒锋柊**锛坒orce=True锛岀敱 daemon 鍦?dirty 鏃惰皟锛?
      杩欐牱鏃笉婕忔秷鎭紝涔熶笉浼氭瘡杞櫧鎷?10MB銆?
    """
    # 鈶?缂撳瓨鍛戒腑
    if (not force and name is None and _LAST["db"] is not None
            and (time.time() - _LAST["ts"]) < max_age):
        try:
            want_now = uid or current_uid(device)
            if not want_now or str(_LAST["uid"]) == str(want_now):
                return _LAST["db"]
            log.info("璐﹀彿宸插彉锛?s -> %s锛夆啋 寮哄埗閲嶅紑搴?, _LAST["uid"], want_now)
        except Exception as e:
            log.debug("缂撳瓨鏍￠獙寮傚父锛岀洿鎺ラ噸寮€: %r", e)

    names = list_device_dbs(device)
    if not names:
        raise RuntimeError("璁惧涓婃病鏈?IM-SDK 搴?)

    if name is not None:
        if name not in names:
            raise RuntimeError("搴?%s 涓嶅湪璁惧涓婏紙鏈夛細%s锛? % (name, names))
        p = sync(device, name)
        db = IMDB(p, uid=uid)
        db.dev = device
        log.info("宸叉墦寮€鎸囧畾搴?%s uid=%s", name, db.uid)
        return db

    want = uid or current_uid(device)
    log.info("褰撳墠鐧诲綍 uid = %s锛屽叡 %d 涓簱寰呭尮閰?, want, len(names))
    if not want:
        p = sync(device, names[0])
        # 馃敶 2026-11-13 淇 DS-02锛圥1 璁惧瀛樻椿鏍￠獙澶辨晥鍥炴疆锛夛細want 涓虹┖锛坈urrent_uid
        #   璇讳笉鍒帮級鐨勯檷绾у垎鏀紡鎸?db.dev 鈥斺€?姝ｅ父璺緞锛?299/1335锛夐兘鏈?`db.dev=device`锛?
        #   鍞嫭姝ゅ垎鏀病鏈夈€傝€?pending.py 鐨?unread_sids/should_reply 鍙敤
        #   getattr(db,"dev",None)锛屼笉鍥為€€ _DEV_REF 鈫?璁惧瀛樻椿鏍￠獙琚潤榛樿烦杩囷紝
        #   骞界伒浼氳瘽/寰呭洖铏氶珮鍥炴疆锛?1-08 P0 鏍瑰洜锛夈€?
        db = IMDB(p)
        db.dev = device
        return db

    # 馃敶馃敶 2026-11-08 10:36锛堢敤鎴风‖瑙勫垯锛氥€屼袱涓处鍙风殑鏁版嵁搴撹鍒嗗紑锛屼笉瑕佺敤 A 鐨勮亰澶╄褰?
    #   鍘诲叏 B 璐﹀彿鎼溿€嶏級
    #
    #   銆愬彂鐜扮殑鐪熼棶棰樸€戣澶囦笂琚櫥鍑虹殑璐﹀彿锛屽畠鐨勫簱浼氳 Soul **娓呯┖/鎴柇**锛?
    #     瀹炴祴 10:35 鈥斺€?96691646 鐨勫簱浠?14.2MB 鎺夊埌 76KB锛堢櫥鍑哄悗璁板綍琚竻锛夈€?
    #   鑰?`sync()` 鐨勫疄鐜版槸銆屽厛鍒犳湰鍦颁笁涓枃浠?鈫?鍐?pull銆嶏紝
    #   浜庢槸涓嬫 `open_account()` 璧板埌杩欎釜搴撴椂锛屼細**鐢?76KB 鐨勭┖搴撹鐩栨湰鍦?
    #   14.2MB / 20900 鏉″巻鍙查暅鍍?* 鈥斺€?鏁版嵁涓嶅彲鎭㈠锛堥櫎闈炴湁澶囦唤锛夈€?
    #
    #   銆愭敼娉曘€戝垏鍙?寮€搴撴椂锛屽厛姣斿銆岃澶囧簱 vs 鏈湴闀滃儚銆嶇殑琛屾暟锛?
    #     璁惧搴撴槑鏄炬洿灏忥紙< 鏈湴 50% 涓斿皯浜?200 鏉′互涓婏級鈫?**鍒ゅ畾涓鸿娓呯┖**锛?
    #     鎷掔粷瑕嗙洊锛屾姏寮傚父璁╀笂灞傞檷绾э紙瀹佸彲杩欎竴杞笉璺戯紝涔熶笉鑳芥瘉鎺夊巻鍙叉暟鎹級銆?
    #     鍚屾椂鎶婃湰鍦伴暅鍍忓彟瀛樹竴浠?`.keep`锛屼繚璇佷汉宸ラ殢鏃惰兘鎵惧洖銆?
    #
    #   娉ㄦ剰锛氭甯稿閲忓悓姝ワ紙璁惧搴撴洿澶э級涓嶅彈褰卞搷銆?
    _skipped = []
    for n in names:
        try:
            p = sync(device, n)
        except RuntimeError as _e:
            # sync() 鐨勩€屾嫆缁濈敤绌哄簱瑕嗙洊鍘嗗彶銆嶄繚鎶わ紙瑙佽鍑芥暟鍐?2026-11-08 娉ㄩ噴锛?
            # 杩欎釜搴撴槸宸茬櫥鍑鸿处鍙风殑锛岃烦杩囧畠缁х画鎵惧綋鍓嶈处鍙风殑搴撳嵆鍙€?
            log.warning("璺宠繃搴?%s锛?s", n[:28], _e)
            _skipped.append(n)
            continue
        db = IMDB(p)
        db.dev = device
        if str(db.uid) == str(want):
            log.info("鍖归厤鍒板簱 %s (uid=%s, %.1fMB)", n, db.uid, os.path.getsize(p) / 1e6)
            _LAST["db"] = db
            _LAST["ts"] = time.time()
            _LAST["uid"] = str(db.uid)
            return db
        db.close()

    raise RuntimeError("涓や釜搴撶殑 uid 閮戒笉绛変簬褰撳墠璐﹀彿 %s锛堣烦杩囩殑搴擄細%s锛?
                       % (want, _skipped))


def health(db, quick=True):
    """搴撳畬鏁翠綋妫€銆傝繑鍥?True/False銆?

    涓轰粈涔堣鑳戒富鍔ㄦ煡锛歚database disk image is malformed` 涓€鏃﹀彂鐢燂紝
    鎵€鏈夋煡璇紙鍞ら啋鍊欓€?寰呭洖/浼氳瘽鍒楄〃锛夊叏宕╋紝daemon 绛変簬鐦棯涓旀病浜虹煡閬撱€?
    quick=True 鏃跺彧鍋?integrity_check + 璇曟煡涓€寮犺〃銆?
    """
    try:
        r = db.con.execute("PRAGMA integrity_check").fetchone()
        if not r or str(r[0]).lower() != "ok":
            return False
        db.con.execute("SELECT COUNT(*) FROM chatmsg LIMIT 1").fetchone()
        return True
    except Exception as e:
        log.warning("搴撲綋妫€澶辫触: %r", e)
        return False


def invalidate():
    """涓㈡帀鏈湴搴撶紦瀛橈紙搴撴崯鍧?鍒囧彿鏃惰皟锛夈€?""
    _LAST["db"] = None
    _LAST["ts"] = 0.0
    _LAST["uid"] = ""
