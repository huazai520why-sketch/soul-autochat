# -*- coding: utf-8 -*-
"""娓呯孩鐐?+ 蹇呭洖 娴佺▼銆?
鐢ㄦ埛瀹氱殑纭鍒欙紙2026-11-02锛夛細
  杩涘叆瀵硅瘽妗嗗悗锛岃嫢鏈€鍚庝竴鏉℃槸**瀵规柟**鍙戠殑 鈫?蹇呴』鍥炲锛屼笉鑳芥竻瀹岀孩鐐瑰氨璧般€?
鍒ゅ畾鐢ㄤ袱鏉＄嫭绔嬭瘉鎹紝浜掔浉鏍￠獙锛?  鈶?OCR 姘旀场宸﹀彸锛坸2>=700 = 鎴戯紝x1<=210 = 瀵规柟锛?  鈶?鐢?OCR 璇诲埌鐨勬秷鎭枃鏈弽鏌ユ暟鎹簱 chatmsg 鈫?sender

瀹夊叏杈圭晫锛?  - dry_run=True 鏃跺彧鐢熸垚涓嶅彂閫侊紝鐢ㄤ簬浜哄伐纭
  - 鍙戦€佸墠鏍￠獙锛氫細璇濇纭?+ 瀛楀凡鐏屽叆 + 鍙戦€佹寜閽瓨鍦?  - 鍙戦€佸悗鏍￠獙锛氳緭鍏ユ娓呯┖ + 鏁版嵁搴撳嚭鐜版柊娑堟伅
"""
import os
import time

from brain import reply as R
from brain import voice as V
from core.log import get_logger
from eyes import chat as E
from hands.input import Input

log = get_logger("brain.flow")


class Outcome(object):
    __slots__ = ("nick", "last_text", "side", "sid", "reply", "sent", "err", "kind",
                 "burst", "lines")

    def __init__(self):
        self.nick = ""
        self.kind = "text"      # text / voice / image / emoji / other / tip
        self.last_text = ""     # 鍚堝苟鍚庣殑銆屽ス杩欒疆璇寸殑璇濄€嶏紙鍙兘鍚鏉★級
        self.burst = []         # 濂硅繛鍙戠殑鍘熸枃鍒楄〃锛堝崟鏉℃椂涓洪暱搴?1锛?        self.lines = []         # 鎴戣繖娆″疄闄呭彂鍑虹殑鍑犳潯
        self.side = "?"
        self.sid = ""
        self.reply = ""
        self.sent = False
        self.err = ""

    def __repr__(self):
        return ("<Outcome %r side=%s reply=%r sent=%s %s>"
                % (self.nick, self.side, (self.reply or "")[:20], self.sent, self.err))


def _device_last_side(device, uid, sid):
    """鐩存帴闂?*璁惧搴?*杩欎釜浼氳瘽鏈€鍚庝竴鏉℃槸璋佸彂鐨勶細杩斿洖 (side, text)锛屽け璐?(None, "")銆?
    馃敶 2026-11-08 21:2x锛堛€屽垰鍥炲畬鍙堝洖涓€閬嶃€嶇殑鏍瑰洜锛屽疄娴嬶級锛?      鏈湴闀滃儚鏄?pull 缂撳瓨锛圧EFRESH_S=300s锛夛紝鎴戜滑鑷繁鍒氬彂鍑哄幓鐨勯偅鍙?*杩樻病杩涢暅鍍?*锛?      浜庢槸杩涗細璇濇椂鍑虹幇銆孫CR=her / 搴?me銆嶏紝鏃ч€昏緫鍒ゃ€岄噸鎷夊悗浠嶅啿绐?鈫?鎸夊ス鍙戜簡澶勭悊
      锛堝繀鍥炰紭鍏堬級銆嶁啋 5 鍒嗛挓閲屽鍚屼竴涓汉杩炲洖 3 鏉★紙瀹炴祴 鐢滅殑鑻﹀挅鍟?      21:14:41 '鎴戜笉瀹堬紝娌′汉瀹? 鈫?21:17:55 '涓€涓汉鐨勬椿锛屾病浜烘浛' 鈫?21:19:3x 绗笁娆★級銆?
      璁惧搴撴墠鏄湡鍊硷紝鑰屼笖寰堝皬锛堜竴娆?SQL 0.05~0.3s锛岃 data/imdb._dev_sql 鐨勫彧璇婚椄锛夈€?      鍐茬獊鏃堕棶瀹冧竴鍙ュ氨鑳借鍐筹紝涓嶇敤闈犮€屽畞鍙鍥炪€嶅厹搴曘€?    """
    try:
        from data import imdb as _IM
        name = _IM._db_name_for_uid(device, uid)
        if not name:
            return None, ""
        sql = ("select senderId, ifnull(text,'') from chatmsg where sessionId='%s' "
               "order by localTime desc limit 1" % str(sid))
        txt = _IM._dev_sql(device, name, sql, timeout=12) or ""
        line = ""
        for ln in txt.replace("\r", "").splitlines():
            if ln.strip():
                line = ln.strip()
        if not line or "|" not in line:
            return None, ""
        sender, _, text = line.partition("|")
        return ("me" if sender.strip() == str(uid) else "her"), text
    except Exception as e:
        log.debug("璁惧搴撴湯鏉℃煡璇㈠け璐? %r", e)
        return None, ""


def her_burst(db, sid, uid, max_n=None):
    """濂?*鏈€鏂拌繛鍙?*鐨勫嚑鏉★紙浠庢渶鍚庝竴鏉″線鍓嶏紝閬囧埌鎴戝彂鐨勫氨鍋滐級銆?
    鐢ㄦ埛 2026-11-02锛氥€屽ス鍒氬彂鏉ョ殑杩欎竴鍙ユ湁鍙兘鏄嚑鍙ワ紝涓嶈鍥哄畾鍙戜簡澶氬皯鍠傚灏戙€嶃€?    鈬?濂瑰湪绛夊洖澶嶆湡闂磋繛鍙戜簡 3 鏉★紝灏辫鎶?3 鏉′竴璧风湅锛屼笉鑳藉彧绛旀渶鍚庝竴鏉?      锛堝彧绛旀渶鍚庝竴鏉℃椂锛屽墠闈㈤偅鍙ョ殑闂灏辨案杩滄病浜烘帴锛屽ス杩樺緱澶氶棶涓€閬嶏級銆?
    璺宠繃绯荤粺鎻愮ず鍗＄墖锛坙ittle_tip 涓嶆槸濂硅璇濓級銆傝繑鍥炴寜鏃堕棿姝ｅ簭銆?    """
    limit = max_n or R.HER_BURST_MAX
    if not sid:
        return []
    try:
        rows = db.con.execute(
            "SELECT * FROM chatmsg WHERE sessionId=? ORDER BY localTime DESC LIMIT 24",
            (sid,)).fetchall()
    except Exception as e:
        log.debug("鍙栧ス杩炲彂澶辫触: %r", e)
        return []

    from data.imdb import Msg
    out = []
    for r in rows:
        try:
            m = Msg(r)
        except Exception:
            continue
        if str(m.sender) == str(uid):
            break                      # 鎴戣鐨?鈫?杩炲彂鍒拌繖閲屼负姝?        t, how = V.her_msg_of(m, db=db, sid=sid)
        if how == "tip":
            continue                   # 绯荤粺鎻愮ず涓嶇畻濂硅璇?        if t:
            out.append(t)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def her_last_real(db, sid, uid):
    """db 鏈潯鏄郴缁熸彁绀哄崱鐗囨椂锛屽線鍓嶆壘濂规渶鍚庝竴鏉?*鐪熷疄**娑堟伅銆?
    涓轰粈涔堥渶瑕侊紙2026-11-05 瀹炴祴 uid=***銆岀儫鑺辨槗鍐枫€嶏級锛?      濂?22:26 璇淬€屼激鍛愩€嶏紝绱ц窡涓€寮犵郴缁熸彁绀哄崱鐗囷紙宸茶/浜掑姩锛夈€?      flow 涓?pendingq 閮戒互銆屾湯鏉℃槸 tip銆嶄负鐢辫烦杩?鈫?濂圭殑璇濇案涔呮病浜烘帴锛?      8.2 灏忔椂鏈洖锛涗笖鍥犱负娌¤蛋鍥炲璺緞锛宻ync_turns 涓嶈窇锛?      turns.md 閲屼篃鐪嬩笉鍑哄緟鍥烇紙鏈浠嶆槸鎴戯級銆?
    璇箟涓?her_burst 涓€鑷达細璺宠繃 tip 寰€鍓嶆壂锛涢亣鍒版垜鍙戠殑 鈫?None锛堝凡鍥烇級銆?    杩斿洖 Msg锛堝彲鑳芥槸璇煶/鍥剧墖锛岀被鍨嬪垽鏂氦缁欒皟鐢ㄦ柟锛夛紝娌℃湁鍒?None銆?    """
    if not sid:
        return None
    try:
        rows = db.con.execute(
            "SELECT * FROM chatmsg WHERE sessionId=? ORDER BY localTime DESC LIMIT 12",
            (str(sid),)).fetchall()
    except Exception as e:
        log.debug("鍙栧ス鏈€鍚庝竴鏉＄湡瀹炴秷鎭け璐? %r", e)
        return None
    from data.imdb import Msg
    for r in rows:
        try:
            m = Msg(r)
        except Exception:
            continue
        if str(m.sender) == str(uid):
            return None
        _t, _how = V.her_msg_of(m, db=db, sid=sid)
        if _how == "tip":
            continue
        return m
    return None


def take_burst(db, out):
    """缁?out 濉?burst / last_text锛堝悎骞跺鏉★級銆傝繑鍥炴潯鏁般€?""
    if not out.sid:
        out.burst = [t for t in [out.last_text] if t]
        return len(out.burst)
    burst = her_burst(db, out.sid, db.uid)
    if not burst:
        burst = [t for t in [out.last_text] if t]
    out.burst = burst
    if burst:
        out.last_text = R.merge_burst(burst)
    return len(burst)


def read_session(actor):
    """璇诲綋鍓嶄細璇濓細娑堟伅鍒楄〃 + 鏈€鍚庝竴鏉°€傝繑鍥?(bubbles, last, png)銆?
    馃敶 2026-11-08 22:4x锛堢櫧鐑?OCR锛夛細
      鍘熸潵鍐欑殑鏄?`bs = E.bubbles(png)` 涔嬪悗鍙?`last = E.last_bubble(png)`銆?      浣?eyes/chat.py 閲?last_bubble() 鐨勫疄鐜板氨鏄?`bs = bubbles(png); return bs[-1]`
      鈥斺€?绛変簬瀵?*鍚屼竴寮?png 璺戜簡绗簩閬?OCR**锛堝疄娴嬬害 3.5s/娆★紝姣忚繘涓€涓細璇濈櫧鑺变竴娆★級銆?      bubbles() 宸叉寜 cy 鍗囧簭鎺掑ソ锛岀洿鎺ュ彇 bs[-1] 涓?last_bubble() 瀹屽叏绛変环銆?    """
    png = actor.dev.screencap()
    bs = E.bubbles(png)
    last = bs[-1] if bs else None
    return bs, last, png


# 鍒楄〃琛岄噷涓嶈鐢ㄦ潵鍙嶆煡鐨勬枃鏈?_SKIP_LABELS = {"澶村儚", "鍖归厤", "鍒氬垰鍦ㄧ嚎", "鍦ㄧ嚎", "鎵嬫満淇″彿婊℃牸銆?, "WLAN 淇″彿婊℃牸銆?}

# 馃敶 2026-11-05锛歴id 鍙嶆煡澶辫触鍚庣殑銆屽己鍒堕噸鎷夊簱銆嶈妭娴侊紙60s 涓€娆★級銆?#    OCR 鎷垮埌鐨勭煭鏂囨湰/琛ㄦ儏鍒蜂笉鍑哄€欓€夋椂涓嶈兘鍙嶅寮烘媺锛堜竴娆?pull 鍑犵锛屼細鎷栧灝娓呯孩鐐癸級銆?_SID_REFRESH_LAST = {"t": 0.0}


def sid_from_row(db, row):
    """**杩涗細璇濆墠**鐢ㄥ垪琛ㄨ鏂囨湰鍙嶆煡 sid锛屽懡涓敮涓€鎵嶈繑鍥炪€?
    馃敶 鎻愰€熷叧閿紙2026-11-02锛夛細鍘熸潵蹇呴』杩涗細璇?-> 鎴浘 OCR(3.5s) -> 鎷挎皵娉℃枃鏈弽鏌ワ紝
    鑰屽垪琛ㄨ鐨勩€屾秷鎭瑙堛€嶆湰韬氨鏄?chatmsg.text 鍘熸枃锛堢煭娑堟伅涓嶆埅鏂級锛?    鐩存帴鎷挎潵绮剧‘鍖归厤灏辫兘鎷垮埌 sid -> 鐪佹帀涓€娆℃埅鍥?+ 涓€娆?OCR銆?    鍙嶆煡涓嶅敮涓€锛堝父瑙佷簬銆屽棷銆嶃€屾槸鐨勩€嶈繖绉嶏級灏辫繑鍥?None锛岄€€鍥?OCR 鎱㈣矾寰勩€?    """
    labels = []      # 闀挎枃鏈紙>=4 瀛楋級锛屽叏鍒楄〃鍙敤
    short = []       # 2~3 瀛楋紝鍙湪**绾㈢偣浼氳瘽**閲岃锛堥槻鎾炶溅锛?    for t in row.labels:
        t = (t or "").strip()
        if len(t) < 2 or t in _SKIP_LABELS:
            continue
        if E.TS_RE.fullmatch(t) or t.endswith("鏃?) or ":" in t[:6]:
            continue
        (labels if len(t) >= 4 else short).append(t)
    if not labels and not short:
        return None
    try:
        hits = db.sessions_for_texts(labels, min_len=4) if labels else []
        if not hits and short:
            # 馃敶 2026-11-04锛氬ス鍒氬彂鐨勮瘽甯稿父鍙湁 2~3 瀛楋紙銆屾棭銆嶃€屽湪鍚椼€嶃€岋紵銆嶏級锛?            #    鍘熸潵 <4 瀛楃洿鎺ヤ涪 鈫?蹇呯劧鍙嶆煡涓嶅埌 鈫?钀借繘鎱㈣矾寰?OCR銆?            #    鐭枃鏈彧鍦ㄣ€屾湁绾㈢偣銆嶇殑浼氳瘽閲岃锛堢孩鐐?濂瑰垰鍙戯紝鍊欓€夊皯銆佷笉鏄撴挒杞︼級銆?            hits = db.sessions_for_texts(short, min_len=2, unread_only=True)
    except Exception as e:
        log.warning("琛屾枃鏈弽鏌ュ紓甯? %r", e)
        return None
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0][0]
    if hits[0][1] > hits[1][1]:          # 鍛戒腑鏁版槑鏄炬洿楂樻墠绠?        return hits[0][0]
    return None


def _enter(actor, row, timeout=8.0, retries=2):
    """杩涘叆浼氳瘽骞剁‘璁よ惤鍦?chat 椤点€傝繑鍥?(snap, page)銆?
    馃敶 2026-11-02 瀹炴祴锛氳澶囧崱鏃讹紙dump 2~4s锛夌偣鍑诲悗 4s 鍐呭彲鑳借繕娌¤烦杞紝
      鍘熸潵鐩存帴鍒ゃ€岃繘鍏ュ悗涓嶆槸 chat 椤点€嶅氨鏀惧純浜嗭紝绾㈢偣鐣欑潃涓嬫鍐嶆挒銆?      鐜板湪瓒呮椂鏀惧鍒?8s锛屽苟涓斿け璐ュ悗**閲嶆柊鍙栨爲鎷挎柊鍧愭爣鍐嶇偣涓€娆?*銆?    """
    # 馃敶 2026-11-04锛堟彁閫燂級锛氳繖閲屽師鏉ュ厛 dump 涓€娆?actor.snap(force=True)锛?    #   浣嗚繑鍥炲€煎湪寰幆閲屽繀琚?wait_page 瑕嗙洊銆佷笂灞備篃鍙敤 page 鈫?绾櫧鐑т竴娆?dump(2~3.5s)銆?    snap, pg = None, None
    for i in range(retries):
        # settle 1.6(脳slow_factor 2.5=4s) -> 0.25锛氱揣璺?wait_page 杞锛?        #   鑰屼竴娆?dump 鏈韩灏辫 3s 杩滃ぇ浜庤浆鍦?0.5s锛岀瓑涓ら亶绾睘閲嶅銆?        actor.hand.tap_node(row.node, settle=0.25)
        snap, pg = actor.wait_page(("chat",), timeout=timeout)
        if pg == "chat":
            return snap, pg
        if i + 1 < retries:
            log.warning("绗?%d 娆¤繘浼氳瘽澶辫触锛?s锛夛紝閲嶆柊鍙栨爲閲嶈瘯", i + 1, pg)
            time.sleep(1.0)
            s2 = actor.snap(force=True)
            located = False
            try:
                from eyes.chatlist import rows as _rows
                from eyes.page import detect as _detect
                if _detect(s2) == "chatlist":
                    cand = [r for r in _rows(s2)
                            if 200 <= r.center[1] <= 1500
                            and (r.nickname or "") == (row.nickname or "")]
                    if cand:
                        row = cand[0]
                        located = True
            except Exception as e:
                log.warning("閲嶆柊瀹氫綅琛屽紓甯? %r", e)
            if not located:
                # 馃敶 2026-11-08 22:42 鐢熶骇瀹炶瘉锛堣瑙?楼198 璁㈤槄椤电殑**鐩存帴鍘熷洜**锛夛細
                #   鏃т唬鐮佷笉绠￠噸瀹氫綅鎴愬姛涓庡惁锛屼笅涓€杞兘缁х画 `tap_node(row.node)` 鈥斺€?                #   鑰?row.node 鏄?*涓婁竴妫垫爲**閲岀殑鍧愭爣銆傛鍒婚〉闈㈡棭宸蹭笉鏄?chatlist
                #   锛坉etect 杩斿洖 unknown/chat锛夛紝鍚屼竴涓潗鏍囪惤鍒板埆鐨勬帶浠朵笂锛?                #   瀹炴祴 22:42:53 鐐?(x,316) 姝ｅソ鏄細璇濋〉椤堕儴閭ｆ灇**閾墝** 鈫?                #   鐩存帴鎵撳紑 H5Activity銆屾垜鐨勮秴绾ф槦浜洪摥鐗?/ 闄愭椂6.6鎶?楼198銆嶄粯璐归〉锛?                #   璇ラ〉鍚炶繑鍥為敭銆佸簳鏍忔秷澶憋紝鏁磋疆鎶ュ簾鍙兘閲嶅惎 App銆?                #   鈬?閲嶅畾浣嶄笉鍒板氨**涓嶈鍐嶇偣**锛屾妸 page 鍘熸牱浜よ繕涓婂眰鍘诲鑸€?                log.warning("閲嶆柊瀹氫綅涓嶅埌 '%.10s' 鐨勮锛堝綋鍓嶉〉 %s锛夆啋 涓嶅啀鐢ㄦ棫鍧愭爣涔辩偣",
                            (row.nickname or ""), pg)
                break
    return snap, pg


def handle_one(actor, db, row, dry_run=True, nick=""):
    """澶勭悊涓€涓孩鐐逛細璇濓細杩涘叆 -> 鍒ゅ畾 -> 鐢熸垚 -> (鍙戦€? -> 杩斿洖銆?
    涓ゆ潯璺緞锛?      蹇矾寰勶紙榛樿锛夛細鍒楄〃琛岄瑙堝弽鏌?sid -> 搴撻噷鎷挎渶鍚庝竴鏉?-> 鐩存帴鍒ゅ畾鍑鸿瘽锛堜笉鍋?OCR锛?      鎱㈣矾寰勶紙鍙嶆煡澶辫触锛夛細杩涗細璇?OCR 璇绘皵娉?+ 鏂囨湰鍙嶆煡
    瀹炴祴蹇矾寰勬瘮鎱㈣矾寰勭渷 3~4s/浜恒€?    """
    out = Outcome()
    out.nick = nick or row.nickname

    # ---------- 蹇矾寰?----------
    sid_fast = sid_from_row(db, row)
    # 馃敶 2026-11-04锛氭湯鏉″彇 latest锛坈hatmsg 涓?session 鎽樿閲屾洿鏂扮殑閭ｄ釜锛夈€?    #    402857053 鍙峰叆鍚戜笉钀?chatmsg 鏃讹紝鍙 chatmsg 浼氭妸銆屽ス鍒氳鐨勮瘽銆嶅綋绌烘皵銆?    db_last, _src = db.latest(sid_fast) if sid_fast else (None, "")
    if sid_fast and db_last is not None:
        out.sid = sid_fast
        if out.nick:
            try:
                from brain.pendingq import remember_nick
                remember_nick(sid_fast, out.nick)
            except Exception:
                pass
        side = "me" if str(db_last.sender) == str(db.uid) else "her"
        out.side = side
        # 璇煶锛坱ype=5锛夌殑 text 閫氬父涓虹┖锛屽繀椤昏蛋 voice 灞傝浆鏂囧瓧锛屽惁鍒欎細琚綋鎴?鏃犺瘽鍙"
        out.last_text, how = V.her_msg_of(db_last, db=db, sid=sid_fast)
        out.kind = how
        nb = take_burst(db, out)
        log.info("[%s] 蹇矾寰?sid=%s 鏈潯=%s %r锛?s/%s锛屽ス杩炲彂 %d 鏉★級",
                 out.nick, sid_fast, side, (out.last_text or "")[:28], how, _src, nb)

        # 绯荤粺鎻愮ず鍗＄墖锛坙ittle_tip / 寮曞锛変笉鏄ス璇磋瘽銆?        # 馃敶 2026-11-05锛堝繀鍥炴紡娲烇紝瀹炴祴 8.2h 鏈洖锛夛細涓嶈兘鐩存帴鏀惧純 鈥斺€?        #   濂硅瀹岃瘽鍚庡彲鑳界揣璺熶竴寮犲崱鐗囷紙宸茶/浜掑姩锛夛紝鐩存帴 return 浼氳濂圭殑璇?        #   姘镐箙娌′汉鎺ワ紱涓斾笉瑙﹀彂 sync_turns锛屾。妗堥噷涔熺湅涓嶅嚭寰呭洖銆?        #   寰€鍓嶆壘濂规渶鍚庝竴鏉＄湡瀹炴秷鎭紝鎵惧埌浜嗗氨缁х画璧版甯告祦绋嬨€?        if how == "tip":
            _real = her_last_real(db, out.sid, db.uid)
            _rt, _rh = (V.her_msg_of(_real, db=db, sid=out.sid)
                        if _real is not None else ("", "tip"))
            if _rh != "text" or not _rt:
                log.info("[%s] 鏈潯鏄郴缁熷崱鐗囷紝鍓嶉潰鏄?%s 鈫?涓嶅湪姝ゅ鐞?, out.nick, _rh or "鏃?)
                actor.hand.back(settle=0.9)
                return out
            # 濂瑰彲鑳借繛鍙戝嚑鏉★紙鐢ㄦ埛 2026-11-02锛氳涓€璧风湅锛屼笉鑳藉彧绛旀渶鍚庝竴鏉★級
            _burst = her_burst(db, out.sid, db.uid) or [_rt]
            out.burst = _burst
            out.last_text = R.merge_burst(_burst)
            out.kind = "text"
            out.side = "her"
            how = "text"
            log.info("[%s] 鏈潯鏄郴缁熷崱鐗囷紝浣嗗墠鏈夊ス鏈帴鐨?%d 鍙?鈫?缁х画鍑鸿瘽: %r",
                     out.nick, len(_burst), out.last_text[:40])

        snap, page = _enter(actor, row)
        if page != "chat":
            out.err = "杩涘叆鍚庝笉鏄?chat 椤? %s" % page
            log.warning("[%s] %s", out.nick, out.err)
            # 馃敶馃敶 2026-11-12锛圖S-02 / HY-06锛氳繘浼氳瘽澶辫触琛?back + 鐭喎鍗达級
            #   鐜拌薄锛歱age!="chat" 鏃跺彧璁?err 涓?back/涓嶅喎鍗?鈫?UI 鍋滃湪 unknown锛?            #   涓斾笅涓€涓€欓€夎繕鍦ㄦ帓闃燂紝鍙嶅杩涘け璐ヤ細璇?鈫?鐧界儳銆?            #   淇硶锛氶€€鍥炲垪琛?+ 璁扮煭鍐峰嵈锛圗NTER_RETRY_H=0.5h锛宲endingq 宸叉湁甯搁噺锛夛紝
            #   璁┿€岃繘涓嶅幓鐨勪細璇濄€嶇煭鏃堕棿涓嶅啀琚€夛紝UI 澶嶄綅銆?            try:
                actor.hand.back(settle=0.9)
            except Exception as _b:
                log.debug("DS-02 back 澶辫触: %r", _b)
            try:
                if out.sid:
                    from brain import pendingq as _PQ2
                    _PQ2.mark_skip(str(out.sid), (out.last_text or ""),
                                   "enter_fail", hours=_PQ2.ENTER_RETRY_H)
            except Exception as _m:
                log.debug("DS-02 璁扮煭鍐峰嵈澶辫触: %r", _m)
            return out

        # 馃敶 2026-11-13 淇 DS-01锛圥1 婕忓洖锛夛細tip 鎭㈠鍧楋紙314-329锛夊凡鎶?        #   out.side 缃?"her"锛屼絾杩欓噷鍘熷垽灞€閮ㄥ彉閲?`side`锛?00 琛屽畾鏍?"me"锛夆€斺€?        #   tip 鍗＄墖 sender 鎭颁负鏈汉鏃讹紝`side` 浠嶆槸 "me"锛屽ス鐪熷疄鏈帴鐨勮瘽琚悶銆?        #   鏀圭敤 out.side锛坱ip 鎭㈠鍚庡凡鏇存柊涓?"her"锛夈€?        if out.side == "me":
            log.info("[%s] 鏈€鍚庝竴鏉℃槸鎴戝彂鐨?-> 鏃犻渶鍥炲", out.nick)
            actor.hand.back(settle=0.9)
            return out
        # 濂规渶鍚庝竴鏉℃病鏂囨湰锛堣闊?鍥剧墖锛?> 閫€鍥炴參璺緞閲嶆柊鍒?        if not out.last_text:
            log.info("[%s] 搴撻噷鏈潯鏃犳枃鏈紝閫€鍥炴參璺緞", out.nick)
            return _slow_path(actor, db, out, dry_run)
        return _reply_and_send(actor, db, out, dry_run)

    # ---------- 鎱㈣矾寰?----------
    snap, page = _enter(actor, row)
    if page != "chat":
        out.err = "杩涘叆鍚庝笉鏄?chat 椤? %s" % page
        log.warning("[%s] %s", out.nick, out.err)
        # 馃敶馃敶 2026-11-12锛圖S-02 / HY-06锛夛細鍚屼笂锛岃繘浼氳瘽澶辫触琛?back + 鐭喎鍗淬€?        #   鎱㈣矾寰勬鏃?sid 鍙兘杩樻病瀹氾紙out.sid 鏈繀鏈夛級锛岃兘瀹氭墠璁板喎鍗淬€?        try:
            actor.hand.back(settle=0.9)
        except Exception as _b:
            log.debug("DS-02 back 澶辫触: %r", _b)
        try:
            if out.sid:
                from brain import pendingq as _PQ3
                _PQ3.mark_skip(str(out.sid), (out.last_text or ""),
                               "enter_fail", hours=_PQ3.ENTER_RETRY_H)
        except Exception as _m:
            log.debug("DS-02 璁扮煭鍐峰嵈澶辫触: %r", _m)
        return out
    return _slow_path(actor, db, out, dry_run)


def _slow_path(actor, db, out, dry_run):
    """OCR 璇绘皵娉?-> 鍙嶆煡 sid -> 鍒ゅ畾 -> 鍑鸿瘽銆?""
    bs, last, png = read_session(actor)
    if last is None:
        out.err = "璇讳笉鍒版秷鎭?
        log.warning("[%s] %s", out.nick, out.err)
        actor.hand.back(settle=0.9)
        return out
    out.last_text, out.side = last[0], last[1]

    texts = [t for t, s, it in bs]
    cands = db.sessions_for_texts(texts)
    if not cands and time.time() - _SID_REFRESH_LAST["t"] >= 60:
        # 馃敶 2026-11-05锛氬簱鏄?300s 鎷夊彇缂撳瓨锛屽ス鍒氬彂鐨勮瘽澶氬崐杩樻病杩?        #    session.lastMsgText / chatmsg 鈫?鍙嶆煡蹇呯劧钀界┖ 鈫?sid 绌?        #    鈫?turns/绠€鎶?浜嬪疄/warm 鏁存潯妗ｆ閾炬柇锛堝疄娴?05:15~08:20 鍏?20 娆★級銆?        #    寮烘媺涓€娆″啀鏌ワ紙涓庝笅闈?OCR 鍐茬獊澶勭悊鍚屼竴鎷涳級锛?0s 鑺傛祦銆?        _SID_REFRESH_LAST["t"] = time.time()
        try:
            from data.imdb import open_account as _oa
            _db2 = _oa(actor.dev, force=True)
            cands = _db2.sessions_for_texts(texts)
            if cands:
                log.info("[%s] 鍙嶆煡锛氬己鎷夊簱鍚庡懡涓?sid=...%s", out.nick, str(cands[0][0])[-8:])
        except Exception as _e:
            log.warning("[%s] 鍙嶆煡锛氬己鎷夊簱澶辫触 %r", out.nick, _e)
    if cands and len(cands) > 1 and (out.nick or "").strip():
        # 2026-11-13锛氭枃鏈挒杞︽椂鍏堢敤鍒楄〃琛屾樀绉板啀绛涗竴娆°€傚彧鎺ュ彈鍞竴鍛戒腑锛?        # 浠嶄笉鍞竴灏辩户缁?fail-closed锛屼笉鑳戒负浜嗏€滃鍥炲嚑涓€濆啋涓插彴椋庨櫓銆?        try:
            from brain.pendingq import nick_of as _nick_of, _norm_nick as _nn
            target = _nn(out.nick)
            narrowed = []
            for c in cands:
                sid = str(c[0])
                ses = db.session(sid)
                to_uid = str(getattr(ses, "to_uid", "") or "")
                nk = _nick_of(db, sid, to_uid)
                if target and nk and _nn(nk) == target:
                    narrowed.append(c)
            if narrowed:
                cands = narrowed
                log.info("[%s] 鍙嶆煡澶氬懡涓悗鐢ㄦ樀绉版敹绐勪负 %d 涓?, out.nick, len(cands))
        except Exception as e:
            log.debug("[%s] 鏄电О鏀剁獎寮傚父: %r", out.nick, e)

    if cands:
        if len(cands) == 1:
            out.sid = cands[0][0]
            log.info("[%s] 鍙嶆煡鍞竴鍛戒腑 sid=...%s", out.nick, str(out.sid)[-8:])
        else:
            # 馃敶 2026-11-12 澶滅彮淇锛圖2锛夛細澶氬懡涓畞鍙笉鍐欙紝涓嶅彲鍐欓敊浜猴紙濂戠害 v1.2 钀界偣#3锛?            #   鏀瑰墠锛歚out.sid = cands[0][0]` 鈥斺€?澶氬懡涓ぇ姒傜巼鏄挒杞︾煭鍙ワ紝鍙栫涓€鍙兘杩涢敊浼氳瘽锛?            #   鎶婄敳鐨勫巻鍙茶瘽鍙戠粰涔欙紙涓插彴锛夈€傝繚鍙嶃€屽畞鍙笉鍐欎笉鍙啓閿欎汉銆嶃€?            _top = [str(c[0])[-8:] for c in cands[:5]]
            log.warning("[%s] 鍙嶆煡澶氬懡涓?%d 涓紙%s锛夆啋 鏀惧純锛屼笉杩涢敊浼氳瘽",
                        out.nick, len(cands), _top)
            out.err = "鍙嶆煡澶氬懡涓紝鏀惧純"
            try:
                actor.hand.back(settle=0.9)
            except Exception:
                pass
            return out
    else:
        out.err = "鍙嶆煡涓嶅埌 sessionId"
        log.warning("[%s] %s", out.nick, out.err)

    db_last, _src = db.latest(out.sid) if out.sid else (None, "")
    forced_her = False
    if db_last is not None:
        db_side = "me" if str(db_last.sender) == str(db.uid) else "her"
        if db_side != out.side and out.side != "?":
            mode = os.environ.get("SOUL_OCR_CONFLICT", "her")
            log.warning("[%s] OCR 涓庡簱涓嶄竴鑷达細OCR=%s 搴?%s锛堝缃?%s锛?,
                        out.nick, out.side, db_side, mode)
            # 馃敶 2026-11-03锛堢敤鎴锋斁琛岋級锛氬簱鏄?pull 缂撳瓨锛圧EFRESH 300s锛夛紝鍙兘婊炲悗浜?            #    濂瑰垰鍙戠殑閭ｆ潯銆傚厛寮哄埗閲嶆媺涓€娆″簱鍐嶅垽锛涗粛鍐茬獊鍒欐寜銆屽ス鍙戜簡銆嶅鐞?            #    锛堝繀鍥炰紭鍏堬級锛屼絾鍙湪 OCR 纭疄璇诲埌濂归偅鍙ユ枃鏈椂鎵嶈繖涔堝仛銆?            if mode != "db":
                try:
                    from data.imdb import open_account as _oa
                    _db2 = _oa(actor.dev, force=True)
                    _last2, _src2 = _db2.latest(out.sid) if out.sid else (None, "")
                    if _last2 is not None:
                        db_last = _last2
                        db_side = "me" if str(db_last.sender) == str(db.uid) else "her"
                        log.info("[%s] 鍐茬獊閲嶆媺搴撳悗鏈潯 side=%s", out.nick, db_side)
                except Exception as _e:
                    log.warning("[%s] 鍐茬獊閲嶆媺搴撳け璐? %r", out.nick, _e)
                if db_side != out.side and (out.last_text or "").strip():
                    # 馃敶 2026-11-08 21:2x锛氬啿绐佹渶缁堣鍐充氦缁?*璁惧搴?*锛堢湡鍊硷級銆?                    #   璁惧搴撹銆屾垜鍙戠殑銆嶁啋 涓嶉噸澶嶅洖澶嶏紱璇淬€屽ス鍙戠殑銆嶁啋 蹇呭洖锛?                    #   璁惧搴撴煡涓嶅埌锛坅db 鎶栧姩锛夋墠閫€鍥炲師鏉ョ殑銆屽繀鍥炰紭鍏堛€嶃€?                    _dside, _dtxt = _device_last_side(actor.dev, db.uid, out.sid)
                    if _dside == "me":
                        db_side = "me"
                        log.info("[%s] 鍐茬獊瑁佸喅锛堣澶囧簱锛夛細鏈潯鏄垜 %r 鈫?涓嶅洖锛堥槻閲嶅鍥炲锛?,
                                 out.nick, (_dtxt or "")[:20])
                    elif _dside == "her":
                        db_side = "her"
                        forced_her = True
                        log.warning("[%s] 鍐茬獊瑁佸喅锛堣澶囧簱锛夛細鏈潯鏄ス %r 鈫?蹇呭洖",
                                    out.nick, (_dtxt or "")[:20])
                    else:
                        forced_her = True
                        log.warning("[%s] 閲嶆媺鍚庝粛鍐茬獊涓旇澶囧簱涓嶅彲鐢?鈫?鎸夈€屽ス鍙戜簡銆嶅鐞嗭紙蹇呭洖浼樺厛锛?,
                                    out.nick)
        out.side = "her" if forced_her else db_side
        if forced_her:
            her_msg, how = (out.last_text or ""), "text"
        else:
            her_msg, how = V.her_msg_of(db_last, db=db, sid=out.sid)
        out.kind = how
        if how == "tip":
            # 馃敶 2026-11-05锛氬悓蹇矾寰?鈥斺€?鏈潯鏄崱鐗囨椂寰€鍓嶆壘濂圭湡瀹炵殑璇濓紝
            #   鏈夋湭鎺ョ殑灏辩户缁嚭璇濓紝鍒濂圭殑璇濊涓€寮犲崱鐗囨尅姝汇€?            _real = her_last_real(db, out.sid, db.uid)
            _rt, _rh = (V.her_msg_of(_real, db=db, sid=out.sid)
                        if _real is not None else ("", "tip"))
            if _rh != "text" or not _rt:
                log.info("[%s] 鏈潯鏄郴缁熷崱鐗囷紝鍓嶉潰鏄?%s 鈫?涓嶅湪姝ゅ鐞?, out.nick, _rh or "鏃?)
                actor.hand.back(settle=0.9)
                return out
            _burst = her_burst(db, out.sid, db.uid) or [_rt]
            her_msg = R.merge_burst(_burst)
            out.burst = _burst
            how = "text"
            out.side = "her"
            out.kind = "text"
            log.info("[%s] 鏈潯鏄郴缁熷崱鐗囷紝浣嗗墠鏈夊ス鏈帴鐨?%d 鍙?鈫?缁х画鍑鸿瘽: %r",
                     out.nick, len(_burst), her_msg[:40])
        if how == "none" and V.is_voice(db_last):
            log.info("[%s] 璇煶杞啓澶辫触锛岀敤鍗犱綅璇濇湳鐓ф牱鍥?, out.nick)
        elif not her_msg:
            her_msg = out.last_text
            out.side = "?"
    else:
        her_msg = out.last_text
        log.warning("[%s] 鏃犲簱鏁版嵁锛屼粎鍑?OCR 鍒ゅ畾 side=%s", out.nick, out.side)

    if out.side == "me":
        log.info("[%s] 鏈€鍚庝竴鏉℃槸鎴戝彂鐨?-> 鏃犻渶鍥炲", out.nick)
        actor.hand.back(settle=0.9)
        return out
    out.last_text = her_msg or out.last_text
    nb = take_burst(db, out)
    if nb > 1:
        log.info("[%s] 鎱㈣矾寰勶細濂硅繛鍙?%d 鏉?鈫?鍚堝苟澶勭悊", out.nick, nb)
    return _reply_and_send(actor, db, out, dry_run)


# 馃敶 蹇呭洖鍏滃簳璇濇湳锛氭棫寮曟搸鍋跺皵杩斿洖绌猴紝鎸夈€屽繀鍥炪€嶉搧寰嬩笉鑳芥矇榛樸€?#   2026-11-14 鎸?GLM 瀹¤鎹㈡帀鍘熸潵鐨勭伃鐏彞锛堝湪鐨?鍒氱湅鍒?鍡垜鍚潃锛夛細
#   鏅€氬満鏅粰鈥滄壙鎺ヨ鈥濓紝濂?鈮? 瀛楁垨鏀跺熬鏃跺彟璧扮煭鍏滃簳锛岄伩鍏嶅厹搴曟湰韬妸濂规寜浣忋€?FALLBACK_LINES = (
    "浣犵户缁锛屾垜鎺ョ潃鍚?,
    "浣犺繖鍙ユ垜鎺ヤ綇浜?,
    "閭ｆ垜浠妸鐪煎墠杩欎欢璇存竻妤?,
    "琛岋紝鎴戜笉缁曪紝鐩存帴璇存垜鐨勬兂娉?,
)
SHORT_FALLBACK_LINES = ("閭ｅ氨鍏堝ソ濂界潯", "琛岋紝浣犲厛姝囩潃", "濂斤紝鍚綘鐨?)

# 闈炴枃鏈秷鎭殑鍥哄畾璇濇湳銆?# 涓轰粈涔堜笉浜ょ粰寮曟搸鐜扮敓鎴愶細鍗犱綅涓诧紙銆屽ス鍙戞潵涓€寮犲浘鐗囥€嶏級鍠傝繘鍘伙紝璞嗗寘瀹规槗缂栭€?# 鍥剧墖鍐呭锛?浣犵┛杩欒韩鐪熷ソ鐪? 缁撴灉濂瑰彂鐨勬槸涓€寮犺〃鎯呭寘锛夛紝鎵€浠ョ敤瀹夊叏鐭彞銆?MEDIA_REPLIES = {
    "image": ("杩欏浘鍟ユ剰鎬濆憖[绗慮", "鎷嶅緱杩樻尯鏈夋剰鎬?, "杩欐槸鍝効鍛€"),
    "emoji": ("杩欒〃鎯呭暐鎰忔€濆摝", "鍝堝搱锛屾敹涓嬩簡", "浣犺繖琛ㄦ儏鎴戠湅鎳備簡"),
    "other": ("浣犲彂鐨勫暐鍛€锛屾垜杩欒竟娌＄湅娓?, "鍒氶偅鏉℃垜娌＄湅鏄庣櫧"),
}


def _short_fallback(her_msg):
    import re
    s = re.sub(r"\s+", "", str(her_msg or ""))
    close = ("鐫′簡", "鏅氬畨", "鍥颁簡", "涓嶈亰浜?, "鍛婅緸", "鎷滄嫓", "鍘诲繖浜?)
    return len(s) <= 4 or any(k in s for k in close)


def fallback_line(her_msg=""):
    import random
    if _short_fallback(her_msg):
        return random.choice(SHORT_FALLBACK_LINES)
    return random.choice(FALLBACK_LINES)


def _send_lines(actor, lines, nick, page_checked=False, sid=""):
    """渚濇鍙戝嚭澶氭潯銆傝繑鍥?(鎴愬姛鏉℃暟, 閿欒璇存槑)銆?
    page_checked=True锛氳皟鐢ㄦ柟**鍒?*鐢?wait_page 纭杩囨槸 chat 椤点€?    涓斾腑闂存病鏈変换浣?UI 鍔ㄤ綔锛堝彧鏈夋ā鍨嬭皟鐢?搴撹鍐欙級鈫?鐪佹帀涓€娆?dump(2~3.5s)銆?    2026-11-04锛堟彁閫燂級锛氬疄娴嬩竴娆?dump 3s锛屼竴涓洖澶嶈 dump 6 娆★紝杩欓」鍗?1/6銆?
    鐢ㄦ埛 2026-11-02锛氥€屽洖澶嶅唴瀹逛篃鏄彲浠ュ彂澶氭潯锛屼笉瑕佸浐瀹氫竴鏉°€嶃€?    澶氭潯涔嬮棿鐣?1.6s 闂撮殧 鈥斺€?澶瘑浼氳褰撴垚鍒峰睆锛圫oul 鏈夎繛鍙戦檺鍒讹級锛?    澶暱濂瑰張浼氳寰楀闈㈠湪鎸ょ墮鑶忥紝1.5~2s 鎺ヨ繎鐪熶汉鎵撳瓧鑺傚銆?    """
    # 搂104 璺熻繘闃舵锛氬彂閫佸墠鍏堣繃闂革紙椤甸潰鏍￠獙涔嬪墠锛夈€傚綊妗ｆ垨棰濆害鐢ㄥ敖鍒欎竴鏉′笉鍙戯紱
    #    棰濆害涓嶈冻鏃舵寜 allow 杩斿洖鐨?n 鎴柇 lines锛圖ecision.n 宸叉寜棰濆害鎴柇锛夈€?    #    sid="" 涓烘棤涓讳細璇濓紝鏀捐涓斾笉绾冲叆棰濆害锛涘彴璐﹀紓甯镐竴寰嬮檷绾ф斁琛岋紝
    #    缁濅笉璁╂柊鍙拌处鎶娿€屽繀鍥炪€嶉摼璺帎姝汇€?    try:
        from brain import sendgate as SG
        if SG.ON and sid:
            # 馃敶 2026-11-10锛堢敤鎴峰彛寰勩€岄兘璇诲疄鏃跺簱锛屾湰鍦板簱娌℃湁鐢ㄣ€嶏級锛氶暅鍍忔粸鍚庝細璁?            #    verdict 鐨?C2銆屽ス鍐嶅彂鈫掓竻闆躲€嶇湅涓嶅埌濂瑰垰鍙戠殑浜嬪疄 鈫?following 璇嫤
            #    锛堝疄娴?13:49 绛変竴鏉熷厜 13:42銆屽枩娆㈠惉浣犺銆嶈 2/2 鎷︽埅锛屽己鎷夐暅鍍忎粛
            #    銆屾柊澧?0 鏉°€嶏級銆傚彂閫佸墠鐢?data.imdb._dev_sql **鐩存煡璁惧搴?session
            #    琛?*锛?.05~0.3s锛屼笉璧?pull锛夛細timestamp 鏄捐憲鏅氫簬鎴戞柟鏈€鍚庡彂閫?            #    锛?5s锛夆噿 鏈潯蹇呮槸濂?鈬?浣滀负 her_ts_ms 鍠傞椄锛孋2 娓呴浂姝ｅ父鐢熸晥銆?            #    鏌ヤ笉鍒?瑙ｆ瀽澶辫触 鈫?涓嶅杺锛屾寜鍘熷彴璐﹁蛋锛岃涓哄悜鍚庡吋瀹广€?            _her_ts_feed = None
            try:
                from data import imdb as _IM
                from data import reply_state as _RS
                _uid_now = _IM.current_uid(actor.dev)
                _name = _IM._db_name_for_uid(actor.dev, _uid_now)
                _last_send = 0.0
                try:
                    _sends = (_RS.get(sid) or {}).get("sends") or []
                    _last_send = max(_sends) if _sends else 0.0
                except Exception:
                    pass
                if _name:
                    _raw = _IM._dev_sql(
                        actor.dev, _name,
                        "select ifnull(timestamp,0) from session where sessionId='%s' limit 1"
                        % str(sid), timeout=8) or ""
                    _line = ""
                    for _ln in _raw.replace("\r", "").splitlines():
                        if _ln.strip():
                            _line = _ln.strip()
                    if _line:
                        _ts = float(_line.split("|")[0] or 0)
                        _ts_s = _ts if _ts < 1e11 else _ts / 1000.0
                        if _ts_s > _last_send + 5:
                            _her_ts_feed = _ts_s * 1000.0
                            log.info("瀹炴椂搴撴牳瀵?sid=...%s锛歴ession.ts=%.0f > 鎴戞柟鏈彂 %.0f"
                                     " 鈫?濂瑰垰鍙戯紝鎸?C2 娓呴浂鍠傞椄", str(sid)[-8:], _ts_s, _last_send)
            except Exception as _e:
                log.debug("瀹炴椂搴撴牳瀵瑰け璐ワ紙鎸夊彴璐﹁蛋锛? %r", _e)
            _d = SG.allow(sid, len(lines), her_ts_ms=_her_ts_feed)
            if not _d.ok:
                log.info("[%s] 璺熻繘闃舵鎷︽埅 sid=%s state=%s锛?s锛?, nick, sid, _d.state, _d.reason)
                return 0, "璺熻繘闃舵鎷︽埅(%s)" % _d.state
            if _d.n < len(lines):
                lines = lines[:_d.n]
    except Exception:
        pass
    # 馃敶 鐏屽瓧鍓嶅繀椤荤‘璁ゅ湪浼氳瘽椤碉細鎼滅储椤典篃鏈夎緭鍏ユ锛屼竴鏃﹂〉闈㈡病閫€骞插噣锛?    #    鏁村彞璇濅細鐏岃繘鎼滅储妗嗭紙瀹炴祴鎴浘閲屾悳绱㈡娈嬬暀銆岃繖濞冨効绗戣捣鏉ヤ箹寰楀緢鎾掞紝浣犮€嶏級锛?    #    娑堟伅姘歌繙鍙戜笉鍑哄幓锛岃繕浼氭妸鎼滅储鐘舵€佸交搴曟悶涔便€?    if not page_checked:
        try:
            from eyes.page import detect as _det
            _pg = _det(actor.snap())
            if _pg != "chat":
                log.warning("[%s] 鐏屽瓧鍓嶉〉闈?%s锛堜笉鏄?chat锛夆啋 鏀惧純鍙戦€?, nick, _pg)
                return 0, "涓嶅湪浼氳瘽椤?%s)" % _pg
        except Exception as e:
            log.debug("椤甸潰鏍￠獙寮傚父锛堢户缁級: %r", e)

    inp = Input(actor.dev)
    sent = 0
    # 馃敶 鍙戦€?*鍓?*灏卞０鏄庛€屾帴涓嬫潵杩欎簺搴撳啓鍏ユ槸鎴戣嚜宸辩殑銆嶁€斺€?    #    鍙戦€佺灛闂?App 灏卞啓搴擄紝鐩戞帶绾跨▼ 1.5s 涓€杞紝绛夊彂瀹屽啀 mark 宸茬粡鏅氫簡锛?    #    浼氳鍒ゆ垚銆屾湁鏂版秷鎭€嶆妸鍚庨潰鐨勫姩浣滃叏鎵撴柇锛堝疄娴嬪敜閱?娓呯孩鐐归兘涓繃锛夈€?    try:
        from data import watch as _W
        _W.mark_self_write(15.0)
    except Exception:
        pass
    try:
        for i, line in enumerate(lines):
            if i:
                time.sleep(1.6)
            # 姣忔潯鐙珛鍏滃簳锛氱 2 鏉℃姏寮傚父涓嶈兘鎶娿€屽凡鍙?1 鏉°€嶇殑浜嬪疄涔熶竴璧峰悶鎺?            try:
                ok, got = inp.type_and_verify(line, actor)
                if not ok:
                    return sent, "绗?d鏉＄亴瀛楀け璐?%r)" % (i + 1, got)
                # settle 1.2(脳2.5=3s) -> 0.25锛氱揣璺?sent_ok锛坰leep 0.7 + dump 3s锛夊凡鍦ㄧ瓑
                if not inp.tap_send(actor, settle=0.25):
                    inp.clear()
                    return sent, "绗?d鏉℃壘涓嶅埌鍙戦€佹寜閽? % (i + 1)
                # 馃敶 2026-11-04锛堥棴鐜級锛氭寜涓夋€佽璐︼紝涓?pendingq.py 鐨勫彂閫佽矾寰勪繚鎸佷竴鑷淬€?                #   sent_ok 鐨勪笁鎬佽 hands/input.py锛歰k / unknown / residual銆?                #   unknown锛堣浆鍦哄抚璇讳笉鍒拌緭鍏ユ锛夊ぇ姒傜巼宸插彂鍑?鈫?蹇呴』璁拌处锛屽惁鍒欎笅杞噸鍙?= 閲嶅娑堟伅锛?                #   鍙湁 residual锛堟閲岃繕鏈夊瓧锛? 鏄庣‘娌″彂鍑?鈫?涓嶈璐︺€佺暀缁欎笅杞噸璇曘€?                _ok = inp.sent_ok(actor, line, timeout=4)
                _why = getattr(inp, "last_reason", "") or ""
                if (not _ok) and _why == "residual":
                    inp.clear()
                    return sent, "绗?d鏉＄‘璁ゆ湭鍙戝嚭锛堣緭鍏ユ浠嶆湁鍐呭锛? % (i + 1)
                if not _ok:
                    log.warning("[%s] 绗?d鏉″彂閫佺‘璁よ涓嶅埌杈撳叆妗?鈫?鎸夊凡鍙戝嚭璁拌处锛堥槻閲嶅锛?,
                                nick, i + 1)
            except Exception as e:
                log.warning("[%s] 绗?d鏉″彂閫佸紓甯? %r", nick, i + 1, e)
                try:
                    inp.clear()
                except Exception:
                    pass
                return sent, "绗?d鏉″紓甯?%r)" % (i + 1, e)
            sent += 1
            log.info("[%s] 宸插彂閫?%d/%d): %r", nick, i + 1, len(lines), line)
            try:
                from data import watch as _W
                _W.mark_self_write(6.0)      # 鑷繁鍐欑殑搴撳彉鍖栵紝鍒綋鎴愬埆浜烘潵娑堟伅
            except Exception:
                pass
            try:
                from brain import ratelimit as _RL
                _RL.note_sent()
            except Exception:
                pass
    finally:
        # 搂104 璺熻繘闃舵锛氭寜鐪熷疄鍙戝嚭鏉℃暟璁拌处锛岃鐩栦笂闈?for 閲屾墍鏈?return 鏃╅€€璺緞銆?        #    鍙湪鏈熬璁颁竴娆′細婕忚鏃╅€€鏃跺凡鍙戝嚭鐨勬潯鏁帮紝棰濆害浼氳鍑荤┛銆?        #    sid="" 鎴?SOUL_FOLLOWUP_ON=0 鏃?SG.note_sent 鍐呴儴鑷璺宠繃锛屼笉钀借处銆?        #    鍙拌处寮傚父涓€寰嬪悶鎺夛紝缁濅笉鏀瑰彉鏈嚱鏁版棦瀹氱殑杩斿洖缁撴灉锛堝繀鍥為搧寰嬶級銆?        if sent:
            try:
                from brain import sendgate as SG
                SG.note_sent(sid, sent)
            except Exception:
                pass
    return sent, ""


def _describe_image(db, out):
    """鍥剧墖娑堟伅璇嗗浘锛圖eepSeek 瑙嗚锛夈€傝繑鍥炲浘鐗囨弿杩版枃鏈紱澶辫触/寮傚父杩斿洖 ""銆?
    2026-11-04锛氬浘鐗囨秷鎭笉鍐嶅浐瀹氳瘽鏈紝璇嗗浘鎴愬姛鍚庢寜鍥惧唴瀹硅蛋寮曟搸鍑鸿瘽锛堜繚鎸佷汉璁撅級銆?    澶辫触蹇呴』杩斿洖 ""锛堝洖閫€鍥哄畾璇濇湳锛夛紝缁濅笉鑳藉洜璇嗗浘澶辫触鑰屼笉鍥烇紙蹇呭洖閾佸緥锛夈€?    """
    try:
        db_last, _src = db.latest(out.sid) if out.sid else (None, "")
        # latest 鍦?session 鎽樿鏇存柊鏃朵細杩斿洖鍚堟垚 Msg锛坢sgContent=""锛夛紝鍥剧墖 URL 浼氫涪锛?        # 姝ゆ椂 fallback 鐩存帴璇?chatmsg 鏈潯銆?        if db_last is None or not V.image_url(db_last):
            db_last = db.last_message(out.sid) if out.sid else None
        if db_last is None:
            return ""
        url = V.image_url(db_last)
        if not url:
            log.warning("[%s] 鍥剧墖娑堟伅鏃?URL锛屾棤娉曡瘑鍥?, out.nick)
            return ""
        b = R.engine()
        if b is None:
            return ""
        fn = getattr(b, "describe_image", None) or getattr(b, "brain_describe_image", None)
        if fn is None:
            return ""
        desc = fn(url, timeout=25) or ""
        if desc:
            log.info("[%s] 璇嗗浘鎴愬姛 %d 瀛? %r", out.nick, len(desc), desc[:40])
        else:
            log.info("[%s] 璇嗗浘杩斿洖绌?, out.nick)
        return desc
    except Exception as e:
        log.warning("[%s] 璇嗗浘寮傚父: %r", out.nick, e)
        return ""


def _reply_and_send(actor, db, out, dry_run):
    """鍑鸿瘽 + 鍙戦€?+ 杩斿洖銆傝皟鐢ㄥ墠椤诲凡鍦ㄤ細璇濋〉銆?""
    if out.sid:
        msgs = db.messages(out.sid, limit=12)
        hist = R.build_hist(msgs, db.uid)
    else:
        hist = []
    # 濂硅繖鍙ュ彲鑳藉彧瀛樺湪浜?session 鎽樿锛坈hatmsg 娌℃湁锛夆啋 琛ヨ繘鍘嗗彶鏈熬锛屽埆璁╂ā鍨?    # 鐪嬪埌銆屽巻鍙蹭互鎴戠粨灏俱€嶈繕纭帴璇濓紙2026-11-04锛岀函浜嬪疄琛ュ叏锛夈€?    hist = R.hist_with_her(hist, out.last_text)

    # 2026-11-03锛堢敤鎴锋寚鍑猴級锛氭湰鍦颁笁鎶€鑳藉簲鍦?*妫€娴嬪埌鏂版秷鎭殑绗竴鏃堕棿**灏辨帓闃燂紝
    #   涓嶆槸绛夊洖澶嶅彂瀹屽啀璺戙€傝繖閲屽凡鎷垮埌 sid + 濂硅繖鍙ヨ瘽锛岀珛鍒讳涪杩涘崟绾跨▼闃熷垪
    #   锛坰oul_localq锛屽悓浼氳瘽宸插湪闃熷垪浼氳嚜鍔ㄨ烦杩囷級锛岀劧鍚庣収甯稿嚭璇?鈥斺€?    #   鏈湴璺?~28s锛堢敾鍍?L0 + 鏂规 L1锛夛紝鍦ㄧ嚎鍑鸿瘽鍙 1~3s锛屼袱鏉＄嚎骞惰銆?    #   鈿狅笍 绗竴鏉℃秷鎭粛鐢?*鐜版垚妗ｆ**鍑鸿瘽锛堟湰鍦拌刀涓嶄笂锛夛紝鏇存柊鍚庣殑妗ｆ渚涗笅涓€鏉＄敤銆?    if out.sid:
        try:
            R.warm_local(out.sid, db, her_msg=out.last_text, nick=out.nick)
        except Exception as e:
            log.debug("鏈湴鍒嗘瀽鎶曢€掑紓甯革紙涓嶅奖鍝嶅洖澶嶏級: %r", e)

    # 馃摑 2026-11-03锛堢敤鎴峰彛寰勩€屽璇濆巻鍙插繀椤诲疄鏃舵洿鏂般€嶏級锛?    #   濂硅繖鍙ヨ瘽鍦?*鍑鸿瘽涔嬪墠**灏卞啓杩?L2銆傚師鏉ヨ绛夊洖澶嶅彂鍑哄幓鎵嶅啓锛堝湪涓嬮潰锛夛紝
    #   浜庢槸 V9 璇诲埌鐨勩€屼綘淇╃殑鍏ㄩ儴瀵硅瘽銆嶆案杩滅己濂规渶鏂拌繖涓€鍙?鈥斺€?鍘嗗彶鏄粸鍚庣殑銆?    if out.sid and (out.last_text or "").strip():
        try:
            from brain.pack import store as _PKlive
            # 鈶?鍏堟寜 DB 娓告爣鎶婃柊娑堟伅琛ラ綈锛堝箓绛夛紝涓嶄細閲嶅鍐欙級
            _PKlive.sync_turns(out.sid, msgs, getattr(db, "uid", ""))
            # 鈶?濂规渶鏂拌繖鍙ュ彲鑳藉彧瀛樺湪浜?session 鎽樿锛坈hatmsg 杩樻病钀藉簱锛夆啋 鎵嬪伐琛ヤ竴琛屻€?            #    涓嶆帹杩?last_ts_ms锛屼笅涓€杞?sync 闈犳湯琛屽幓閲嶈烦杩囧畠銆?            t = (out.last_text or "").strip()
            if t and _PKlive.last_her_line(out.sid) != t:
                _PKlive.append_turns(
                    out.sid, [(time.strftime("%m-%d %H:%M"), "濂?, t[:200])])
        except Exception as e:
            log.debug("瀵硅瘽钀界洏澶辫触锛堜笉褰卞搷鍑鸿瘽锛? %r", e)

    # 2026-11-04锛氬浘鐗囨秷鎭厛 DeepSeek 璇嗗浘锛涙垚鍔熷垯鎸夊浘鍐呭璧板紩鎿庡嚭璇濓紙淇濇寔浜鸿锛夛紝
    #   澶辫触鍥為€€鍥哄畾璇濇湳锛堣瘑鍥惧け璐ョ粷涓嶈兘瀵艰嚧涓嶅洖锛屽繀鍥為搧寰嬶級銆?    if out.kind == "image":
        _desc = _describe_image(db, out)
        if _desc:
            out.kind = "text"
            out.last_text = "锛堝ス鍙戞潵涓€寮犲浘鐗囷紝鍥鹃噷鏄細%s锛? % _desc
            log.info("[%s] 鍥剧墖璇嗗浘鎴愬姛 鈫?鎸夊唴瀹瑰嚭璇?, out.nick)

    if out.kind in MEDIA_REPLIES:
        import random as _rnd
        lines = [_rnd.choice(MEDIA_REPLIES[out.kind])]
        log.info("[%s] %s 娑堟伅 鈫?鍥哄畾璇濇湳 %r", out.nick, out.kind, lines[0])
    else:
        # 鐢ㄦ埛 2026-11-02锛氬ス杩炲彂鍑犳潯鎴戝彲浠ュ鍥炲嚑鏉★紝涓嶅浐瀹氫竴鏉°€?        # 鏉℃暟鎸夊ス鐨勫唴瀹硅嚜閫傚簲锛坱arget_n锛夛紝涓婇檺 ADAPT_CAP=3銆?        # 馃敶 2026-11-03锛氳繛鍙戝凡鍚堝苟鎴愪竴鍙ヨ瘽锛堜笂闄?10 鏉★級锛屽悎骞跺悗闀垮害浼氳鎾戝ぇ锛?        #    鑻ユ嬁鍚堝苟鏂囨湰绠?target_n 浼氫竴璺垽鎴?3 鏉?鈫?濂瑰彂鍑犳潯鎴戝氨鍥炰笁鏉★紝鍍忓埛灞忋€?        #    鎵€浠ユ潯鏁板彧鐪?*濂规渶鍚庝竴鏉?*锛堝ス涓€娆¤瀹岀殑钀借剼鐐癸級銆?        _tn_in = [out.burst[-1]] if out.burst else [out.last_text]
        n = R.target_n(_tn_in, hist)
        lines = R.generate(out.sid or ("x" + str(int(time.time()))),
                           out.last_text, hist=hist, n_cand=n)
        if lines:
            log.info("[%s] 濂硅鍥?%d 鏉?鈫?寮曟搸缁欎簡 %d 鏉? %r",
                     out.nick, n, len(lines), " | ".join(lines)[:60])
    if not lines:
        # 蹇呭洖閾佸緥锛氬紩鎿庝笉缁欒瘽涔熷繀椤诲彂涓€鍙ワ紝涓嶈兘娌夐粯
        lines = [fallback_line(out.last_text)]
        # 馃敶 2026-11-11锛團AIL 鍣０锛夛細寮曟搸鍑鸿瘽**鏃犱骇鍑?*宸茶鍏滃簳璇濇湳瀹屽叏鎺ヤ綇鈥斺€?        #   蹇呭洖閾佸緥淇濊瘉涓€瀹氬彂涓€鍙ワ紙fallback_line 姘镐笉绌猴級锛屼笉鏄晠闅滐紝涓?PR#13
        #   闄嶇骇鐨勩€屽凡鍏滀綇銆嶈矾寰勫悓绫汇€傜敤銆屾棤浜у嚭銆嶅彇浠ｃ€屽け璐ャ€嶉伩鍏嶈 nightly_collect
        #   鐨?FAIL 鍏抽敭瀛楄璁★紱鐪熸鐨勫彂閫佸け璐ョ敱 _send_lines 鐨?err 鍙﹁ WARN銆?        log.warning("[%s] 寮曟搸鏃犱骇鍑?鈫?鐢ㄥ厹搴曡瘽鏈?%r", out.nick, lines[0])
    out.lines = list(lines)
    out.reply = " | ".join(lines)

    if dry_run:
        log.info("[%s] DRY 灏嗗洖澶?%d 鏉? %r", out.nick, len(lines), out.lines)
        actor.hand.back(settle=0.9)
        return out

    # 馃摲 濂硅鏄富鍔ㄨ鐓х墖 鈫?鍏堝彂涓€寮狅紙鐢ㄦ埛 2026-11-02 閰嶄簡妗岄潰 1/2/3.jpg锛?    _pic_sent = False
    try:
        from brain import picreq as _PR
        _pic_sent, _why = _PR.try_send(actor, actor.dev, out.sid or out.nick, out.last_text)
        if _pic_sent:
            log.info("[%s] 宸叉寜濂硅鐨勫彂浜嗙収鐗?, out.nick)
    except Exception as _e:
        log.warning("鍙戝浘鍒ゆ柇寮傚父锛堢户缁彂鏂囧瓧锛? %r", _e)

    # 鍒氬垰 _enter/wait_page 宸茬‘璁?chat 椤碉紱涓棿鍙湁妯″瀷涓庡簱鎿嶄綔锛屾病鏈?UI 鍔ㄤ綔銆?    # 渚嬪锛歱icreq 鐪熷彂浜嗙収鐗囷紙鍔ㄨ繃 UI锛夆啋 涓嶅鐢紝鑰佽€佸疄瀹炲啀鏍￠獙涓€娆°€?    sent_n, err = _send_lines(actor, out.lines, out.nick,
                              page_checked=not _pic_sent, sid=out.sid or "")
    if sent_n:
        out.sent = True
    if err:
        out.err = err
        log.warning("[%s] %s锛堝凡鍙?%d/%d 鏉★級", out.nick, err, sent_n, len(out.lines))

    # 馃 鏈湴妯″瀷锛氭妸杩欎竴杞柊瀵硅瘽鍠傜粰鐢诲儚(L0)/鏂规(L1)銆?    #    鐢ㄦ埛 2026-11-02銆屾湰鍦版ā鍨嬭ˉ瀵规柟浜鸿鈥︿篃瑕佹帴鍏ャ€嶁€斺€斿悗鍙板崟绾跨▼璺戯紝
    #    涓嶉樆濉炲洖澶嶏紱涓嬩竴杞嚭璇濆氨鑳借鍒版洿鏂板悗鐨勭敾鍍忋€?    # 馃摑 妗堟儏鍖?L2锛氭妸杩欎竴杞€屽ス璇寸殑 / 鎴戝彂鐨勩€嶈拷鍔犺繘鍘汇€?    #    2026-11-03 淇細1.0 浠庢潵娌¤皟杩?append_l2锛孡2 鍐荤粨鍦ㄦ棫鐗堟渶鍚庝竴娆″啓鍏ョ殑鏃跺埢锛?    #    鑰屾棫寮曟搸鐢?L2 褰撱€屼綘淇╃殑鍏ㄩ儴瀵硅瘽銆嶆敞鍏ャ€佸苟鍥犳涓㈡帀鐪熷疄 hist
    #    鈫?妯″瀷鎺ョ潃 4~6 澶╁墠鐨勮瘽棰樿璇濓紙鐥呬緥锛歀2 鍋滃湪 10-27銆岀倰闈€嶁啋 杈撳嚭銆屾兂灏濅竴鍙ｃ€嶏級銆?    if sent_n and out.sid:
        try:
            from brain.pack import store as _PK
            # 鍙**瀹為檯鍙戝嚭鍘?*鐨勯偅鍑犳潯锛坰ent_n锛夆€斺€斻€屾墦绠楀彂浣嗗彂閫佸け璐ャ€嶇殑鍙ュ瓙
            # 鑻ュ啓杩涘璇濆彶锛屼笅涓€杞ā鍨嬩細寮曠敤涓€鍙ュス浠庢病瑙佽繃鐨勩€屾垜璇寸殑銆嶃€?            _PK.note_my_reply(out.sid, " / ".join(out.lines[:sent_n])[:200])
        except Exception as e:
            log.debug("鎴戝彂鐨勮瘽钀界洏澶辫触锛堜笉褰卞搷鍥炲锛? %r", e)

    # 锛堟湰鍦板垎鏋愬凡鍦?_reply_and_send 鍏ュ彛鎶曢€掕繃 鈥斺€?瓒婃棭璺戣秺鍙兘璧朵笂涓嬩竴杞級

    # 馃彔 涓汉涓婚〉锛氭病鏈夋。妗堢殑琛ヤ竴娆★紙鐢ㄦ埛 2026-11-02 瑕佹眰锛夈€?    #    鈿狅笍 蹇呴』鍦?*杩樺湪浼氳瘽椤?*鏃跺仛 鈥斺€?visit_profile 鐨勫叆鍙ｆ槸浼氳瘽椤靛彸涓?    #    銆屾煡鐪嬩富椤点€?澶村儚锛岃€屼笖瀹冭嚜宸变細閫€鍥炰細璇濋〉銆?    #    宸叉湁妗ｆ鏃?has_profile() 鍙涓€涓枃浠讹紝0 鎴愭湰銆?    if sent_n and out.sid:
        try:
            from brain import casepack as _CP
            if _CP.ensure_profile(actor, out.sid, db):
                log.info("[%s] 宸茶ˉ寤轰釜浜轰富椤垫。妗?, out.nick)
        except Exception as e:
            log.debug("琛ュ缓涓婚〉寮傚父锛堜笉褰卞搷涓绘祦绋嬶級: %r", e)

    actor.hand.back(settle=1.0)
    return out
