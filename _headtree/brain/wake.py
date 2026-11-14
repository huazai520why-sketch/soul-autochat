# -*- coding: utf-8 -*-
"""鍞ら啋锛氱粰銆岃亰杩囦絾鍐蜂簡寰堜箙銆嶇殑浜轰富鍔ㄥ彂涓€鍙ャ€?
鏃ф灦鏋勫畾涔夛紙soul_daemon 娉ㄩ噴锛夛細
  鍞ら啋鑰佽仈绯讳汉 = 閫夈€岃亰杩団墺10鍙?涓?鍐封墺12h銆嶇殑浜?+ jianghua 寮€鍦?  鑺傚锛氭渶灏忛棿闅?10min銆佹瘡娆?2 浜恒€佸崟鎵归绠?240s

鏈ā鍧楀彧璐熻矗銆岄€変汉 + 鍑鸿瘽銆嶏紱鍙戦€佺敱 hands/input 瀹屾垚锛岃皟搴︾敱涓婂眰璐熻矗銆?"""
import json
import os
import time

from brain import reply as R
from core.log import get_logger
from core.paths import STATE
from data.imdb import SYS_TYPES

log = get_logger("brain.wake")

MIN_MSGS = 10          # 鑱婅繃鑷冲皯 10 鍙ワ紙鏂囨湰娑堟伅锛?COLD_HOURS = 12        # 鍐峰嵈鑷冲皯 12 灏忔椂
MAX_PER_ROUND = 2      # 姣忔鍞ら啋 2 浜猴紙瀵归綈鏃ф灦鏋?WAKE_N锛?WOKE_COOLDOWN_H = 24   # 鍚屼竴涓汉 24 灏忔椂鍐呭彧鍞ら啋涓€娆★紙鐢ㄦ埛 2026-11-02 瀹氥€屾寜浜鸿銆嶏級
# 馃敶 2026-11-05锛堢敤鎴峰畾锛夛細杩炵画鍞ら啋 N 娆″ス閮戒笉鍥?鈫?鏀惧純锛屼笉鍐嶄富鍔ㄦ壘浠栥€?#    鍙拌处 data/state/woke.json 閲?"c<uid>" 瀛樿繛缁棤鍥炲簲娆℃暟锛氬彂閫佹垚鍔?+1锛?#    濂瑰洖杩囨秷鎭氨娓呴浂锛坮eset_if_replied锛夈€傚埌涓婇檺鍚?candidates 鐩存帴璺宠繃銆?#    濂瑰摢澶╀富鍔ㄦ潵淇?鈫?璁℃暟娓呴浂 鈫?鑷姩鎭㈠鍊欓€夎祫鏍硷紙涓嶆槸姘镐箙鎷夐粦锛夈€?MAX_NO_REPLY = int(os.environ.get("SOUL_WAKE_MAX_NO_REPLY", "3"))

WOKE_FILE = STATE / "woke.json"


def _load_woke():
    try:
        return json.loads(WOKE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save_woke(d):
    try:
        WOKE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        log.warning("淇濆瓨鍞ら啋鍙拌处澶辫触: %r", e)


# 馃敶 2026-11-08 03:45锛堢敤鎴峰彛寰勶細銆屽ソ鍙嬪敜閱?*涓夋锛屼竴澶╀竴娆?*銆嶏級
#
#   鏀瑰墠锛氬け璐ュ彧鍐峰嵈 1200s锛?0 鍒嗛挓锛夆€斺€?鍚屼竴涓汉涓€澶╅噷鑳借璇曞嚑鍗佹锛?#        鏃笉鏄€屼竴澶╀竴娆°€嶏紝涔熸槸鐜扮綉绌虹儳鐨勪竴澶ф潵婧愶紙瀹炴祴鍚屼竴浜哄闂磋閲嶈瘯 20+ 娆★級銆?#   鏀瑰悗锛?*涓嶇鎴愬姛杩樻槸娌℃壘鐫€浜猴紝杩欎釜浜洪兘绠椼€屼粖澶╁凡缁忓敜閱掕繃涓€娆°€?*锛?#        涓嬩竴娆℃満浼氬湪 24h 鍚庛€傞厤鍚?MAX_NO_REPLY=3 鈫?涓夋鍗虫案涔呮斁寮冦€?#
#   娉ㄦ剰锛氬け璐ヤ粛淇濈暀涓€涓煭淇濋櫓涓濓紙WOKE_FAIL_COOL_S锛岄粯璁?20 鍒嗛挓锛夌敤浜?#    **鍚屼竴杞唴鐨勯噸璇曚繚鎶?*锛堥伩鍏嶅潖椤甸潰琚繛缁寷鎾烇級锛屼絾瀹冧笉鍐嶅喅瀹氥€屼笅娆¤兘涓嶈兘鍞ら啋銆嶏紝
#    鑳戒笉鑳藉敜閱掔敱 WOKE_COOLDOWN_H(24h) 鍗曠嫭璇翠簡绠楋紝瑙?_cooling()銆?WOKE_FAIL_COOL_S = float(os.environ.get("SOUL_WAKE_FAIL_COOL", "1200"))
# 澶辫触绠椾笉绠椼€屼粖澶╁凡缁忓敜閱掕繃銆嶏紙榛樿绠?= 涓ユ牸涓€澶╀竴娆★級
WOKE_FAIL_COUNTS_AS_WAKE = os.environ.get("SOUL_WAKE_FAIL_COUNTS", "1") != "0"


def _cooling(woke, uid, now=None, hours=WOKE_COOLDOWN_H):
    """杩欐鍞ら啋杩樺湪涓嶅湪鍐峰嵈鏈熴€?
    馃敶 2026-11-08 03:45锛堢敤鎴峰彛寰勩€屼竴澶╀竴娆★紝涓夋鏀惧純銆嶏級锛?      鏀瑰墠 鈥斺€?澶辫触鍙尅 20 鍒嗛挓锛坒<uid>锛夛紝杩?20 鍒嗛挓鍙堣兘鍐嶈瘯銆?      鏀瑰悗 鈥斺€?澶辫触涔熺畻銆屼粖澶╁敜杩囦竴娆°€嶏細
        路 鎴愬姛锛氭寜 str(uid) 璁版椂闂存埑 鈫?24h 鍐呬笉鍐嶆壘浠?        路 鎵句笉鍒颁汉锛?*鍚屾椂鍐?f<uid> 鍜?str(uid)**锛堣 _bump_miss锛夛紝
          浜庢槸鍚屾牱鍙?24h 绾︽潫 鈬?鐪熸鍋氬埌銆屼竴澶╀竴娆°€?        路 f<uid> 浠呬綔涓鸿疆鍐呴噸璇曠殑鐭繚闄╀笣淇濈暀锛?0 鍒嗛挓锛?    杩欐牱鍚屼竴涓汉涓€澶╂渶澶氳灏濊瘯涓€娆★紝涓夋娌℃垚 鈫?is_given_up() 姘镐箙璺宠繃銆?    """
    now = time.time() if now is None else now
    ts = float(woke.get(str(uid)) or 0)
    if ts and (now - ts) < hours * 3600:
        return True
    fts = float(woke.get("f" + str(uid)) or 0)
    return bool(fts and (now - fts) < WOKE_FAIL_COOL_S)


def _no_reply_count(woke, uid):
    """杩炵画澶氬皯娆″敜閱掑ス閮借繕娌″洖銆?""
    try:
        return int(woke.get("c" + str(uid)) or 0)
    except Exception:
        return 0


def _her_last_ts(db, sid, limit=8):
    """濂瑰湪杩欎釜浼氳瘽閲屾渶杩戜竴鏉℃秷鎭殑鏃堕棿锛堟绉掞級锛涘彇涓嶅埌杩斿洖 0銆?
    馃敶 2026-11-08锛堝璁℃紡娲炰慨澶嶏紝瑙?reset_if_replied锛夛細
      **涓嶈兘**鎷裤€屼細璇濇渶澶?localTime銆嶅綋銆屽ス鍥炶繃璇濄€嶇殑璇佹嵁 鈥斺€?閭ｉ噷闈㈠寘鍚?      鎴戣嚜宸卞垰鍙戠殑鍞ら啋璇€傚敜閱掍竴鍙戝嚭鍘伙紝浼氳瘽鏈€澶ф椂闂村氨鍙樻垚鎴戠殑娑堟伅锛?      涓嬩竴杞壂鎻忓氨浼氭妸瀹冨綋鎴愩€屽ス鍥炰簡銆嶃€?
    涓ょ骇鍙栬瘉锛堥『搴忓緢閲嶈锛夛細
      鈶?`db.latest(sid)` 鈥斺€?宸茶瀺鍚?chatmsg 鏈潯涓?session 鎽樿锛屼笖**鍒よ繃 sender**
         锛堝惈銆屾枃鏈懡涓垜鏈€杩戝彂鐨勩€嶄氦鍙夐獙璇侊級銆傚叆鍚戜笉钀?chatmsg 鐨勮处鍙?         锛堝疄娴?402857053锛夊彧鏈夎繖涓€璺兘鐪嬪埌濂圭殑鏂拌瘽锛屽繀椤诲厛鐢ㄥ畠銆?      鈶?鍏滃簳鍐嶆壂鏈€杩戝嚑鏉?chatmsg锛岀瓫鍑洪潪鎴戝彂鐨勬渶澶ф椂闂淬€?    涓よ矾閮藉彇涓嶅埌 鈫?杩斿洖 0锛?*涓嶆竻闆?*锛氬畞鍙涓€涓敜涓嶉啋鐨勪汉澶氱暀涓€杞紝
      涔熶笉鑳芥妸銆屾垜鍙戠殑銆嶅綋鎴愩€屽ス鍥炵殑銆嶈€岃涓夋鏀惧純澶辨晥锛夈€?    """
    best = 0
    try:
        last, _src = db.latest(sid)
        if last is not None and str(last.sender) != str(db.uid):
            best = int(getattr(last, "ts", 0) or 0)
    except Exception as e:
        log.debug("db.latest 鍙栧ス鐨勬湯鏉″け璐?s=%s: %r", sid, e)
    if best:
        return best
    try:
        msgs = db.messages(sid, limit=limit)
    except Exception as e:
        log.debug("鍙栧ス鐨勬湯鏉℃椂闂村け璐?s=%s: %r", sid, e)
        return 0
    for m in (msgs or []):
        try:
            if str(m.sender) == str(db.uid):
                continue
            ts = int(getattr(m, "ts", 0) or 0)
        except Exception:
            continue
        if ts > best:
            best = ts
    return best


def reset_if_replied(woke, uid, her_ts_ms):
    """鍞ら啋涔嬪悗**濂?*鍥炶繃娑堟伅 鈫?娓呴浂璁℃暟銆佽В闄?24h 鍐峰嵈銆傝繑鍥炴槸鍚︽竻闆躲€?
    鈿狅笍 her_ts_ms 蹇呴』鏄€屽ス鍙戠殑娑堟伅銆嶇殑鏃堕棿锛?*涓嶈兘**浼犱細璇濇渶澶ф椂闂淬€?       璋冪敤鏂圭敤 `_her_last_ts()` 鍙栵紙瑙?candidates锛夈€?
    馃敶 2026-11-08 04:05锛堟牳瀵规椂鍙戠幇鐨勯€昏緫婕忔礊锛夛細
      鏀瑰墠鍙?`pop("c"+uid)` 娓呴浂鏀惧純璁℃暟锛?*涓嶅姩 str(uid) 鐨?24h 鍐峰嵈**銆?      浜庢槸锛氬ス鏄ㄥぉ鍥炰簡鎴?鈫?璁℃暟娓呴浂锛堝ソ锛夆啋 浣嗕粖澶╂兂鍐嶅敜閱掑ス鏃讹紝
      浠嶈鏄ㄥぉ閭ｆ鍞ら啋鐨?24h 鍐峰嵈鎸′綇 鈥斺€?瀵?*鏈夊洖搴?*鐨勪汉鍙嶈€屾洿鎱紝
      涓庣敤鎴枫€屼笁娆℃病鍥炲簲鎵嶆斁寮冦€嶇殑鎰忓浘鐩稿弽锛堝ス鍥炲簲浜嗗氨璇ユ仮澶嶆甯歌妭濂忥級銆?      鏀瑰悗锛氬ス鍥炶繃娑堟伅 鈬?璁℃暟娓呴浂 **涓?* 瑙ｉ櫎鍐峰嵈锛岀珛鍒绘仮澶嶅€欓€夎祫鏍笺€?      锛堜笉瑙ｉ櫎 f<uid> 鐭繚闄╀笣锛岄偅鏄槻鍧忛〉闈㈢殑锛屼笌涓氬姟璇箟鏃犲叧銆傦級

    馃敶馃敶 2026-11-08 11:05锛堟湰鍑芥暟涓婁竴鐗堜粛鏈夎嚧鍛芥紡娲烇紝宸蹭慨锛夛細
      涓婁竴鐗堢敱 `candidates()` 浼犲叆 `last_ts` = `MAX(localTime)`锛堝惈鎴戣嚜宸辩殑娑堟伅锛夈€?      璁惧鐨?localTime 鏉ヨ嚜鎵嬫満銆乼s 鏉ヨ嚜涓绘満锛屼袱鑰呭父鏈夌绾у亸宸紱
      鍙鎵嬫満姣斾富鏈哄揩 >1 绉掞紝銆屾垜鍒氬彂瀹岀殑鍞ら啋璇€嶅氨浼氳鍒ゆ垚銆屽ス鍥炰簡銆嶏細
        路 c<uid> 琚嚜宸辨竻闆?鈫?**銆屼笁娆℃斁寮冦€嶆案杩滄敀涓嶆弧**
        路 str(uid) 琚垹 鈫?24h 鍐峰嵈琚В闄?鈫?鍚屼竴涓汉褰撳ぉ琚弽澶嶅敜閱?      瀹炴祴绐楀彛锛堝璁?48h锛歚杩樹笉鐫 35 杩炲彂 0 鍥炲锛夋涓庤繖鏉″惢鍚堬細
      涓€涓粠涓嶅洖璇濈殑浜哄彲浠ヨ璁℃暟鍦?1鈫? 涔嬮棿鏃犻檺寰幆銆?      鐜板湪鍒ゆ嵁鏀逛负銆?*濂?*鏈€杩戜竴鏉℃秷鎭殑鏃堕棿銆嶏紝涓旂敱璋冪敤鏂规樉寮忔彁渚涖€?    """
    ts = float(woke.get(str(uid)) or 0)
    if ts and float(her_ts_ms or 0) / 1000.0 > ts + 1:
        _changed = False
        if woke.pop("c" + str(uid), None) is not None:
            _changed = True
        if woke.pop(str(uid), None) is not None:
            _changed = True        # 鈫?瑙ｉ櫎 24h 鍐峰嵈锛氬ス鍥炲簲浜嗭紝鎭㈠姝ｅ父鑺傚
        # 馃敶 2026-11-08 11:10锛氳繛甯︽竻鎺?f<uid> 鐭繚闄╀笣銆?        #   鏀瑰墠鍙竻 c 鍜?str(uid)锛宖<uid>锛堝け璐ヤ繚闄╀笣锛岄粯璁?20 鍒嗛挓锛変粛鐣欑潃锛?        #   濂规槑鏄庡洖璇濅簡锛岃繖涓汉杩樿鍐嶈鎸℃渶澶?20 鍒嗛挓鎵嶈兘閲嶆柊杩涘叆鍊欓€夈€?        #   淇濋櫓涓濇湰鎰忔槸銆岄槻鍧忛〉闈㈣杩炵画鐚涙挒銆嶏紝濂逛竴鍥炶瘽灏辫鏄庨〉闈㈡槸濂界殑銆?        #   浜轰篃鎵惧緱鍒?鈥斺€?娌℃湁浠讳綍鐞嗙敱缁х画鎸°€備笉娓呭畠锛?b) 鐨勩€屽ス鍥炰竴娆″氨鎭㈠銆?        #   灏卞彧鏄崐鎭㈠锛堣鏁版竻浜嗭紝浣嗗喎鍗磋繕鍦級銆?        if woke.pop("f" + str(uid), None) is not None:
            _changed = True
        if _changed:
            log.info("濂瑰洖杩囪瘽锛堝ス鏈潯 %.0fs 鏅氫簬鏈鍞ら啋锛塽id=%s 鈫?璁℃暟娓呴浂銆佽В闄ゅ喎鍗?淇濋櫓涓?,
                     float(her_ts_ms or 0) / 1000.0 - ts, uid)
        return _changed
    return False


def is_given_up(woke, uid):
    """杩炵画鏃犲洖搴旇揪鍒颁笂闄?鈫?鏀惧純銆?""
    return _no_reply_count(woke, uid) >= MAX_NO_REPLY


def already_woke(uid, hours=WOKE_COOLDOWN_H):
    return _cooling(_load_woke(), uid, hours=hours)


def mark_woke(uid, failed=False):
    """璁颁竴娆″敜閱掋€傛垚鍔?= 鎸変汉鍐峰嵈 24h锛涘け璐?= 鐭喎鍗达紙榛樿 20 鍒嗛挓锛夈€?
    澶辫触鐢?"f<uid>" 閿崟鐙瓨锛屾垚鍔熸椂娓呮帀锛屼袱鑰呬簰涓嶈鐩栥€?    """
    d = _load_woke()
    now = time.time()
    if failed:
        d["f" + str(uid)] = now
        log.info("鍞ら啋澶辫触鍙拌处 uid=%s锛?.0f 鍒嗛挓鍐呬笉鍐嶈瘯锛?, uid, WOKE_FAIL_COOL_S / 60.0)
    else:
        d[str(uid)] = now
        d.pop("f" + str(uid), None)
        # 杩炵画鏃犲洖搴?+1锛堝ス鍥炶繃浼氳 reset_if_replied 娓呴浂锛?        try:
            d["c" + str(uid)] = int(d.get("c" + str(uid)) or 0) + 1
        except Exception:
            d["c" + str(uid)] = 1
    # 椤烘墜娓呯悊 30 澶╁墠鐨勶紝閬垮厤鏂囦欢鏃犻檺澧為暱
    # 鈿?"c<uid>" 鏄鏁颁笉鏄椂闂存埑锛屾寜鏃堕棿杩囨护浼氭妸 c=3 褰撴垚 1970 骞村垹鎺夛紱
    #   鏈夎鏁扮殑 uid 杩炲畠鐨勫敜閱掓椂闂翠篃瑕佺暀浣忥紝鍚﹀垯 reset_if_replied 鎷夸笉鍒板熀鍑嗐€?    cutoff = now - 30 * 24 * 3600
    _cnt_uids = {k[1:] for k in d if k.startswith("c")}
    d = {k: v for k, v in d.items()
         if k.startswith("c") or str(k) in _cnt_uids or float(v or 0) > cutoff}
    _save_woke(d)


# 馃敶馃敶 2026-11-08 03:40锛堢敤鎴峰彛寰勶細銆屼笁娆℃病鏈夊洖搴?**鎴栬€呭敜閱掔殑鏃跺€欐壘涓嶅埌浜?* 鈫?姘镐箙鏀惧純銆嶏級
#
#   鏀瑰墠锛氬彧鏈夈€岀湡鐨勫彂鍑哄幓浜嗐€佸ス娌″洖銆嶆墠绱姞 c<uid>锛堣 mark_woke(failed=False)锛夛紱
#        銆屾悳绱㈡棤缁撴灉 / 杩涗笉鍘讳細璇?/ 韬唤鏍￠獙澶辫触銆嶈繖浜?*鎵句笉鍒颁汉**鐨勬儏鍐?#        璧扮殑鏄?mark_woke(failed=True) 鈥斺€?鍙 20 鍒嗛挓鐭喎鍗达紝**涓嶈鍏ユ斁寮冭鏁?*銆?#   鍚庢灉锛氬畾浣嶄笉鍒扮殑浜轰細琚棤闄愭閲嶈瘯锛屾瘡娆＄櫧鐑?15~40s锛堣繖姝ｆ槸鐜扮綉
#        銆?33 娆＄炕灞忔湭鍛戒腑 + 598 娆?notfound銆嶇殑涓€閮ㄥ垎鏉ユ簮锛夛紝鑰屼笖姘歌繙涓嶆斁寮冦€?#
#   鐜板湪锛氭妸銆屾壘涓嶅埌浜恒€嶄篃绠椾綔涓€娆?*澶辫触鍞ら啋**锛岃鍏ュ悓涓€涓斁寮冭鏁般€?#     路 鎵句笉鍒颁汉 = 鎼滅储鏃犵粨鏋?/ 鏈繘鍏ヤ細璇?/ 涓嶅湪浼氳瘽椤?/ 韬唤鏍￠獙澶辫触 / 娌℃湁鍙敤鍏抽敭璇?#     路 涓夌被澶辫触閮借蛋 _bump_miss()锛歝<uid> +1 涓旇 20min 鐭喎鍗?#     路 杩炵画婊?MAX_NO_REPLY(3) 娆?鈫?is_given_up() 鎴愮珛 鈫?candidates() 姘镐箙璺宠繃
#   娉ㄦ剰锛氬ス鍙**鍥炶繃涓€娆℃秷鎭?*锛宺eset_if_replied() 灏辨妸璁℃暟娓呴浂锛岄噸鏂扮粰鏈轰細
#        锛堣繖鏄€屼笉姘镐箙鎷夐粦娲讳汉銆嶏紝涓庛€屾斁寮冭繖涓敜涓嶉啋鐨勪汉銆嶅苟涓嶇煕鐩撅級銆?def _bump_miss(uid, why=""):
    """璁颁竴娆°€屽敜閱掓病鎴愩€嶏紙鍚壘涓嶅埌浜猴級銆傝鍏ユ斁寮冭鏁帮紝骞惰惤瀹炪€屼竴澶╀竴娆°€嶃€?
    馃敶 2026-11-08 03:45锛堢敤鎴凤細涓夋銆佷竴澶╀竴娆°€佹壘涓嶅埌浜轰篃绠楋級锛?      路 鍐?str(uid) = now  鈫?涓庢垚鍔熷敜閱掑悓涓€鎶?24h 鍐峰嵈閿?鈬?鐪熴€屼竴澶╀竴娆°€?      路 鍐?c<uid> += 1     鈫?杩炵画娌℃垚璁℃暟锛屾弧 3 娆℃案涔呰烦杩?      路 鍐?f<uid> = now    鈫?杞唴鐭繚闄╀笣锛?0min锛夛紝闃插潖椤甸潰琚繛鎾?    濂瑰彧瑕佸洖杩囦竴娆?鈫?reset_if_replied() 娓呴浂 c<uid>锛岄噸鏂扮粰鏈轰細銆?    """
    d = _load_woke()
    now = time.time()
    if WOKE_FAIL_COUNTS_AS_WAKE:
        d[str(uid)] = now          # 鈫?鍏抽敭锛氬崰鎺変粖澶╃殑鍚嶉
    d["f" + str(uid)] = now
    try:
        d["c" + str(uid)] = int(d.get("c" + str(uid)) or 0) + 1
    except Exception:
        d["c" + str(uid)] = 1
    _n = d["c" + str(uid)]
    cutoff = now - 30 * 24 * 3600
    _cnt_uids = {k[1:] for k in d if k.startswith("c")}
    d = {k: v for k, v in d.items()
         if k.startswith("c") or str(k) in _cnt_uids or float(v or 0) > cutoff}
    _save_woke(d)
    if _n >= MAX_NO_REPLY:
        log.warning("鍞ら啋鏀惧純 uid=%s锛堣繛缁?%d 娆℃病鎴愶細%s锛夆啋 涓嶅啀涓诲姩鎵句粬", uid, _n, why)
    else:
        log.info("鍞ら啋娌℃垚 uid=%s锛堢 %d/%d 娆★細%s锛夆啋 浠婂ぉ涓嶅啀鎵句粬",
                 uid, _n, MAX_NO_REPLY, why)
    return _n


class Candidate(object):
    __slots__ = ("sid", "uid", "msgs", "last_ts", "last_text", "last_side", "kws")

    def __init__(self, sid, uid, msgs, last_ts, last_text, last_side, kws=None):
        self.sid = sid
        self.uid = uid
        self.msgs = msgs
        self.last_ts = last_ts
        self.last_text = last_text
        self.last_side = last_side
        # 鎼滅储鍏抽敭璇嶅€欓€夛紙鎸夊懡涓鐜囨帓搴忥紝瑙?_kw_list锛?        self.kws = list(kws or [])

    @property
    def cold_h(self):
        return (time.time() * 1000 - float(self.last_ts)) / 3600000.0

    def __repr__(self):
        return "<Cand uid=%s msgs=%d cold=%.1fh %r>" % (
            self.uid, self.msgs, self.cold_h, (self.last_text or "")[:16])


def candidates(db, min_msgs=MIN_MSGS, cold_hours=COLD_HOURS, limit=12,
               scan=800):
    """閫夊嚭鍙敜閱掔殑浜猴細鏂囨湰娑堟伅鏁?>= min_msgs銆佹渶鍚庝竴鏉℃秷鎭棭浜?cold_hours 鍓嶃€?
    棰濆瑕佹眰锛氭渶鍚庝竴鏉℃槸**鎴戝彂鐨?*锛堝惁鍒欏鏂瑰湪绛夋垜鍥烇紝閭ｅ睘浜庛€屽繀鍥炪€嶄笉鏄€屽敜閱掋€嶏級銆?
    馃敶 2026-11-03锛歀IMIT 鍙槸**鎵弿绐楀彛**锛屼笉鑳藉綋缁撴灉涓婇檺銆?       鍘熸潵鍐?LIMIT limit*4锛?32锛夛細鎸?last 鍊掑簭鏈€杩?32 涓喎浼氳瘽閲岋紝
       31 涓凡杩?24h 鍙拌处銆? 涓渶鍚庝竴鏉℃槸濂?-> 姘歌繙杩斿洖绌恒€?       鐜板満璇ュ簱鏈?136 涓悎鏍煎€欓€夛紝daemon 鍗存瘡 60s 鎶ャ€屾病鏈夊€欓€夈€嶇┖杞€?       鐜板湪鎵?scan 鏉★紙榛樿 800锛岃鐩栧叏搴?797 涓湁鏂囨湰鐨勪細璇濓級锛?       鍙拌处涓€娆℃€ц浇鍏ュ唴瀛樺垽瀹氾紝涓嶅啀姣忎釜鍊欓€夎涓€閬?json銆?    """
    # 璺熻繘闃舵鎺ョ嚎锛埪?04-B1锛夛細涓€娆℃€у彇褰掓。闆嗗悎锛坱ry/except 鍏滃簳鎴愮┖闆嗭級銆?    #    鍙戦€侀搴︾粺涓€鐢?sendgate 瑁佸喅锛歐OKE_COOLDOWN_H / MAX_NO_REPLY 鍙
    #    銆屽涔呮寫涓€娆′汉銆嶏紝鑳藉彂鍑犳潯/鑳戒笉鑳藉彂鐢?SG.allow 鍦ㄧ湡姝ｅ彂閫佸墠鎷嶆澘锛?    #    杩欓噷鍙寜銆屽凡褰掓。 / 瓒?72h 褰掓。鎬併€嶇瓫鎺変笉璇ュ敜閱掔殑鍊欓€夈€?    try:
        from brain import sendgate as SG
        from brain import verdict as V
        _arch = set(SG.archived_sids())          # SOUL_FOLLOWUP_ON=0 鏃惰繑鍥炵┖闆?        _ARCHIVE_H = float(V.ARCHIVE_H)
    except Exception:
        _arch = set()
        _ARCHIVE_H = 72.0
        SG = V = None

    cutoff_ms = (time.time() - cold_hours * 3600) * 1000
    # 馃敶 2026-11-03 淇 P2锛氬師鏉?`MAX(localTime)` 鍙畻鏂囨湰娑堟伅锛圵HERE msgType=1锛夛紝
    #    鎴戞渶杩戝彂鐨勬槸鍥剧墖/璇煶/绀肩墿鏃讹紝鏂囨湰鏃堕棿鎴冲凡鍐?鈫?璇垽銆屽喎銆嶈€屽敜閱掋€?    #    鏀规垚锛歯 浠嶅彧璁℃枃鏈秷鎭紱last 鍙栥€岄潪绯荤粺娑堟伅銆嶇殑鏈€澶ф椂闂达紙鍚浘鐗?璇煶锛夛紝
    #    绯荤粺鍗＄墖锛?7/35锛夌殑 localTime 寰堟柊锛屼細姹℃煋鍐峰垽鎹紝蹇呴』鎺掗櫎銆?    rows = db.con.execute(
        "SELECT sessionId, "
        "SUM(CASE WHEN msgType = 1 AND text IS NOT NULL AND text != '' THEN 1 ELSE 0 END) n, "
        "MAX(CASE WHEN msgType NOT IN (?, ?) THEN localTime END) last "
        "FROM chatmsg "
        "GROUP BY sessionId HAVING n >= ? AND last <= ? "
        "ORDER BY last DESC LIMIT ?",
        (int(SYS_TYPES[0]), int(SYS_TYPES[1]), min_msgs, cutoff_ms, scan)).fetchall()

    woke = _load_woke()
    now = time.time()
    out = []
    _woke_dirty = False
    for sid, n, last_ts in rows:
        s = db.session(sid)
        if s is None or s.is_official:
            continue
        # 鍞ら啋涔嬪悗濂瑰洖杩囨秷鎭?-> 娓呴浂鏃犲洖搴旇鏁帮紙鑷姩鎭㈠鍊欓€夎祫鏍硷級
        # 鈿狅笍 蹇呴』浼犮€?*濂?*鐨勬湯鏉℃椂闂淬€嶏紝涓嶈兘浼?last_ts锛堥偅鏄細璇濇渶澶ф椂闂达紝
        #    鍖呭惈鎴戣嚜宸卞垰鍙戠殑鍞ら啋璇?鈥斺€?浼氭妸銆屾垜鍙戠殑銆嶈鍒ゆ垚銆屽ス鍥炵殑銆嶏紝
        #    瀵艰嚧涓夋鏀惧純姘歌繙鏀掍笉婊°€?4h 鍐峰嵈琚嚜宸辫В闄ゃ€傝 reset_if_replied 娉ㄩ噴锛夈€?        # 鍙湁鍙拌处閲岀湡鐨勬湁璁板綍鎵嶉渶瑕佸垽瀹氾細娌¤杩囪处灏辨病浠€涔堝彲娓呯殑锛?        # 涔熼伩鍏嶅鍏ㄥ簱鍊欓€夛紙scan 榛樿 800锛夐€愪釜澶氳涓€娆″簱銆?        if woke.get(str(s.to_uid)) or woke.get("c" + str(s.to_uid)):
            if reset_if_replied(woke, s.to_uid, _her_last_ts(db, sid)):
                _woke_dirty = True
        # 杩炵画 N 娆″敜涓嶉啋 -> 鏀惧純锛堢敤鎴?2026-11-05 瀹氾級
        if is_given_up(woke, s.to_uid):
            continue
        if _cooling(woke, s.to_uid, now):
            continue            # 24h 鍐呭凡鍞ら啋杩?/ 20min 鍐呭け璐ヨ繃 -> 璺宠繃
        # 馃敶 2026-11-04锛歭atest 鈥斺€?鍏ュ悜涓嶈惤 chatmsg 鐨勮处鍙峰彧鏈?session 鎽樿鑳藉弽鏄犳渶鏂颁竴鍙?        last, _src = db.latest(sid)
        if last is None:
            continue
        side = "me" if str(last.sender) == str(db.uid) else "her"
        if side != "me":
            continue            # 瀵规柟鍦ㄧ瓑鎴?-> 浜ょ粰蹇呭洖锛屼笉鍞ら啋
        # 璺熻繘闃舵鎺ョ嚎锛埪?04-B1锛夛細宸插綊妗?/ 瓒?72h 褰掓。鎬?鈫?涓嶅敜閱掞紱
        #    涓嶄富鍔?set_archived锛堝綊妗ｅ啓鍏ョ敱 pendingq 璐熻矗锛夛紝鏁存闄嶇骇鏀捐銆?        _her_ts = 0
        try:
            if SG is not None and SG.ON:
                if str(sid) in _arch:
                    log.info("鍞ら啋鍊欓€夎烦杩?sid=%s锛堝凡褰掓。锛屼笉鍞ら啋锛?, sid)
                    continue
                _her_ts = _her_last_ts(db, sid)
                if _her_ts and (time.time() * 1000 - _her_ts) / 3600000.0 >= _ARCHIVE_H:
                    _v = SG.state_of(str(sid), her_ts_ms=_her_ts, has_human=True)
                    if getattr(_v, "state", "") == V.ARCHIVED:
                        log.info("鍞ら啋鍊欓€夎烦杩?sid=%s锛坅ge>=%gh 褰掓。锛屼笉鍞ら啋锛?, sid, _ARCHIVE_H)
                        continue
        except Exception:
            pass            # 鎷夸笉鍒?her_ts / 鍙拌处鐘舵€佹満寮傚父 鈫?涓嶆嫤锛堥檷绾ф斁琛岋級
        # 馃敶 2026-11-12锛團-02锛夛細璺熻繘闃舵閲?FOLLOWING/AWAITING锛堝ス姝ｅ湪绛夋垜鍥?/
        #    鎴戝湪璺熻繘濂癸級鈫?涓嶅敜閱掋€傚師鏉?candidates() 鍙护 ARCHIVED锛屽埌 send_wake
        #    鐨?SG.allow 鎵嶆嫤锛岀劧鍚?_bump_miss 鎶娿€岄搴﹀凡婊?绛夊ス鍥炪€嶉敊璁℃垚銆屽敜涓嶉啋銆?        #    鈫?c<uid>+1 + 24h 鍐峰嵈锛? 娆″悗瀵逛粛瀛樻椿鐨勭湡浜烘案涔呮斁寮冿紙瀹炴祴
        #    銆屽敜閱掕璺熻繘闃舵鎷︽埅 following/awaiting 65 娆°€嶏級銆傚悓娆?try/except
        #    闄嶇骇鏀捐锛氭嬁涓嶅埌 state 鈫?涓嶆嫤銆?        try:
            if SG is not None and SG.ON and _her_ts:
                _st = SG.state_of(str(sid), her_ts_ms=_her_ts, has_human=True)
                _stn = getattr(_st, "state", "")
                if _stn in (V.FOLLOWING, V.AWAITING):
                    log.info("鍞ら啋鍊欓€夎烦杩?sid=%s锛坰tate=%s锛屼笉鍞ら啋锛?, sid, _stn)
                    continue
        except Exception:
            pass            # 鍙拌处鐘舵€佹満寮傚父 鈫?涓嶆嫤锛堥檷绾ф斁琛岋級
        out.append(Candidate(sid, s.to_uid, n, last_ts, last.text, side,
                             kws=_kw_list(db, sid, db.uid)))
        if len(out) >= limit:
            break
    if _woke_dirty:
        _save_woke(woke)
    return out


def _kw_list(db, sid, uid, limit=2):
    """鎼滅储鍏抽敭璇嶅€欓€夛紙鎸夊懡涓鐜囨帓搴忥級銆?
    馃敶 2026-11-09 P0 淇锛堢幇鍦哄疄璇侊級锛氭棫瀹炵幇鍙栥€屾渶杩?24 鏉￠噷鏈€闀跨殑涓€鏁村彞銆嶏紝
       鍋忓亸鏈€瀹规槗鎸戜腑甯﹀叏瑙掗€楀彿/闂彿鐨勫畬鏁磋瘽鏈紙銆岄攨閲岀殑姘磋繕娌″紑锛屼綘閭ｈ竟鏅嬩腑鍜嬫牱浜嗐€嶏級锛?       鎴栨垜鏂圭兢鍙戝紑鍦虹櫧妯℃澘 鈥斺€?涓よ€呭湪 Soul 鎼滅储閲屽疄娴嬪繀鐒?notfound銆?       缁撴灉 15:00~15:32 杩炵画 53 娆°€屾湭鎵惧埌鐩稿叧缁撴灉銆? 56 娆＄偣銆屽彇娑堛€嶉€€鍑猴紝
       灞忓箷涓婂氨鏄敤鎴风湅鍒扮殑銆岀瀻鎿嶄綔涔辩偣銆嶏紝鑰屼竴鏉℃秷鎭兘娌″彂鍑哄幓銆?       鐜扮粺涓€澶嶇敤 brain/pendingq.kw_of()锛堢幇缃?5~8 瀛楀懡涓巼 74.1% 鐨勫彛寰勶級锛?       鍘婚灏炬爣鐐?/ 鍘嬬┖鏍?/ 鍘昏〃鎯?/ 5 瀛椾笅闄?/ 闈炵函鏁板瓧 / 缇ゅ彂妯℃澘杩囨护 /
       浼樺厛銆屽ス銆嶇殑鍘嗗彶闀垮彞銆倀xt 浼犵┖鍗冲己鍒惰蛋鍘嗗彶闀垮彞鍏滃簳銆?    """
    try:
        from brain.pendingq import kw_of
    except Exception:
        return []
    try:
        k = (kw_of(db, sid, "", min_len=5) or "").strip()
    except Exception as e:
        return []
    return [k] if 5 <= len(k) <= 20 else []


def opening(db, cand, nick=""):
    """绾湰鍦扮敓鎴愬紑鍦虹櫧銆傚け璐ヨ繑鍥?""銆?""
    b = R.engine()
    if b is None or not hasattr(b, "opening_line"):
        log.warning("鏃у紩鎿庝笉鏀寔 opening_line")
        return ""
    msgs = db.messages(cand.sid, limit=8)
    hist = R.build_hist(msgs, db.uid, limit=8)
    t0 = time.time()
    try:
        t, _ms = b.opening_line(sid=cand.sid, nick=nick, hist=hist, kind="wake")
    except Exception as e:
        log.warning("opening_line 寮傚父: %r", e)
        return ""
    t = (t or "").strip()
    log.info("寮€鍦虹櫧 %.1fs %r", time.time() - t0, t[:30])
    return t


def plan(db, n=MAX_PER_ROUND):
    """鏈疆鍞ら啋璁″垝锛歔(鍊欓€? 寮€鍦虹櫧)]锛屾渶澶?n 涓€?""
    out = []
    for c in candidates(db, limit=8):
        if len(out) >= n:
            break
        op = opening(db, c)
        if op:
            out.append((c, op))
    return out


# ---------------- 鎵ц锛氭悳绱㈠畾浣?-> 杩涗細璇?-> 鍙戦€?----------------
def send_wake(actor, dev, cand, text, db=None):
    """鎸?last_text 鎼滅储瀹氫綅 -> 杩涗細璇?-> 鍙戦€併€傝繑鍥?(ok, 璇存槑)銆?
    涓轰粈涔堢敤鎼滅储鑰屼笉鏄粴鍔ㄥ垪琛紙鐢ㄦ埛 2026-11-02 瀹氱殑鏂规锛夛細
    鍒楄〃 1100+ 浼氳瘽锛屾粴鍔ㄥ畾浣嶆參涓斿鏄撹烦杩囷紱鎼滅储妗嗚兘鐩存帴鎼滆亰澶╄褰曪紝
    瀹炴祴涓€娆″懡涓紙鍓嶆彁锛氳璐﹀彿娌￠€€鍑鸿繃锛岀储寮曞畬鏁达級銆?
    db 浼犲叆鏃跺仛**韬唤鏍￠獙**锛堟悳绱㈢粨鏋滀笉淇濊瘉鏄洰鏍囦汉锛夛紱涓嶄紶鍒欒烦杩囷紙鍏煎鏃ц皟鐢級銆?    """
    from brain import nav
    from brain import search as S
    from hands.input import Input

    # 馃敶 2026-11-03 淇锛氬敜閱?鍖归厤涓ゆ潯閾捐矾鍘熸潵瀹屽叏涓嶆鏌ラ檺娴侊紝
    #    鍙湁 clear/pendingq 璋?can_send()锛屽皬鏃朵笂闄愬瀹冧滑鏃犳晥銆?    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            return False, "鏈皬鏃跺彂閫佸凡杈句笂闄?
    except Exception:
        pass

    # 馃敶 2026-11-03锛氬叧閿瘝鏀逛负澶氬€欓€夛紙濂瑰師璇?鈫?鎴戝師璇濓級锛岄€愪釜璇曘€?    #    鍘熸潵鍙敤 cand.last_text锛? 鎴戝彂鐨勬渶鍚庝竴鍙ワ級锛?~2 瀛楁椂鐩存帴鏀惧純銆?    kws = [k for k in (getattr(cand, "kws", []) or []) if len(k) >= 2]
    if not kws:
        t = (cand.last_text or "").strip()
        if 2 <= len(t) <= 18:
            kws = [t]
    if not kws:
        _bump_miss(cand.uid, "娌℃湁鍙敤鍏抽敭璇?)
        return False, "娌℃湁鍙敤鍏抽敭璇嶏紙濂瑰拰鎴戞渶杩戠殑璇濋兘澶煭锛?

    # 馃敶 浠庢悳绱㈠紑濮嬪氨鎶娿€屾垜閫犳垚鐨勫簱鍙樺寲銆嶅皝浣忥細
    #    鐐硅繘浼氳瘽閭ｄ竴涓?App 浼氭爣宸茶鍐欏簱锛岀瓑鐏屽瓧鍓嶅啀 mark 宸茬粡鏅氫簡锛坉irty 宸茬疆浣嶏級
    #    鈫?鍞ら啋寰幆绔嬪埢鍒ゃ€屾湁鏂版秷鎭€嶄腑鏂紝涓€鍙ヨ瘽閮藉彂涓嶅嚭鍘汇€?    try:
        from data import watch as _W
        _W.mark_self_write(40.0)
    except Exception:
        pass

    # 馃敶 2026-11-02锛氬師鏉ヨ繖閲岃嚜寤轰簡涓€濂楁悳绱紙鐏屽瓧鍚庡彧 sleep 2.2 绉掑氨鍒ゃ€屾棤缁撴灉銆嶏級锛?    #   鑰屾帴鍙ｅ疄娴嬭 11~14.7 绉掓墠杩斿洖 鈬?鍞ら啋渚ф悳绱㈠熀鏈叏搴熴€?    #   鐜板湪鍙蛋 brain.search 涓€澶勫疄鐜帮紝绛夊緟绐楀彛涓庡叾浠栧叆鍙ｅ畬鍏ㄤ竴鑷淬€?    if not S.open_search(actor):
        snap, pg = nav.to_chatlist(actor)          # 鍏滃簳锛氬厛鍥炲垪琛ㄥ啀鎵句竴娆℃斁澶ч暅
        if pg != "chatlist" or not S.open_search(actor):
            _bump_miss(cand.uid, "鎵撲笉寮€鎼滅储椤?)
            return False, "鎵撲笉寮€鎼滅储椤?
    hit_kw = ""
    for kw in kws[:2]:
        if S.search(actor, dev, kw):
            hit_kw = kw
            break
        log.warning("鎼滅储 %r 鏃犵粨鏋?瓒呮椂锛坮eason=%s锛夆啋 鎹笅涓€涓叧閿瘝",
                    kw, getattr(S, "LAST_REASON", "?"))
        S.leave(actor)
        if not S.open_search(actor):
            log.warning("鎹㈠叧閿瘝澶辫触锛氭墦涓嶅紑鎼滅储椤?)
            break
    if not hit_kw:
        _bump_miss(cand.uid, "鎼滅储鏃犵粨鏋?)
        return False, "鎼滅储鏃犵粨鏋滐紙璇曚簡 %d 涓叧閿瘝锛? % min(len(kws), 2)
    log.info("鎼滅储鍛戒腑锛堝叧閿瘝=%r锛夛紝鐐圭涓€鏉＄粨鏋滆繘浼氳瘽", hit_kw)
    # 馃敶馃敶 2026-11-08 12:4x锛圥0 淇€岃韩浠芥牎楠屽け璐ャ€?4% 鐨勫亣鍚﹀喅锛?    #
    #   瀹炴祴锛坰earch-diagnostician 鍏ㄩ噺鍙栬瘉锛宊team/search_diag.md 搂2.6锛夛細
    #     路 104 娆°€岃繘鐨勬槸鍒殑浼氳瘽銆嶉噷 **98 娆℃潵鑷?wake**锛宲endingq 渚у彧鍗?6 娆?    #     路 鍚屼竴銆屾湭璇绘竻闆舵寚绾广€嶈法 **39 涓笉鍚岀洰鏍囦汉**閲嶅鍑虹幇 鈫?鏄庢樉鏄檲鏃у揩鐓?    #     路 wake.py **浠庢湭璋冪敤杩?mark_before_enter()**锛屾墍浠?    #       `_sid_by_unread_clear()` 璇诲埌鐨?`_UNREAD_BEFORE["set"]` 鏄?    #       **pendingq 涓婁竴娆＄暀涓嬬殑鏃у揩鐓?*锛屼笉鏄€岃繘杩欎釜浼氳瘽涔嬪墠銆嶇殑鐪熷疄鐘舵€?    #       鈫?宸垎绠楀嚭鏉ョ殑銆屾竻闆堕泦鍚堛€嶅繀鐒舵槸閿欑殑 鈫?韬唤鏍￠獙蹇呯劧澶辫触
    #       鈫?鍙戜笉鍑哄幓 鈫?`_bump_miss` 璁板け璐ュ彴璐?鈫?杩欎釜浜鸿鍐峰嵈锛屾案杩滃洖涓嶄簡
    #
    #   pendingq 渚х簿纭巼 91%锛?9 閫氳繃 / 6 鍚﹀喅锛夛紝鍒ゆ嵁鏈韩娌￠棶棰橈紝
    #   缂虹殑灏辨槸杩欎竴琛屻€岃繘浼氳瘽鍓嶅厛鎷嶆湭璇诲揩鐓с€嶃€傝ˉ涓婂嵆鍙紝涓嶆敼鍒ゆ嵁銆?    if db is not None:
        try:
            from brain import pendingq as _PQ0
            _PQ0.mark_before_enter(actor)
        except Exception as _e:
            log.warning("wake: 杩涗細璇濆墠璁版湭璇诲揩鐓уけ璐ワ紙韬唤鏍￠獙浼氶€€鍥炴枃鏈垽鎹級: %r", _e)
    s2, pg2 = S.enter_first(actor)
    if pg2 != "chat":
        S.leave(actor)
        _bump_miss(cand.uid, "鏈繘鍏ヤ細璇?%s)" % pg2)
        return False, "鏈繘鍏ヤ細璇?%s)" % pg2

    # 浜屾纭鐪熺殑鍦ㄤ細璇濋〉锛堟悳绱㈤〉涔熸湁杈撳叆妗嗭紝鐏岄敊鍦版柟灏辨案杩滃彂涓嶅嚭鍘伙級
    from eyes.page import detect as _det
    if _det(actor.snap(force=True)) != "chat":
        log.warning("鐏屽瓧鍓嶄笉鍦ㄤ細璇濋〉 鈫?鏀惧純锛堥伩鍏嶇亴杩涙悳绱㈡锛?)
        S.leave(actor)
        _bump_miss(cand.uid, "涓嶅湪浼氳瘽椤?)
        return False, "涓嶅湪浼氳瘽椤?

    # 馃敶 2026-11-03 淇 P1锛堥槻涓插彴锛夛細鎼滅储缁撴灉鎸夊叧閿瘝鎺掑簭锛岀涓€鏉′笉淇濊瘉鏄洰鏍囦汉銆?    #    pendingq 宸叉湁鍚屾鏍￠獙锛屽敜閱掕繖鏉′竴鐩寸己 鈥斺€?鍏抽敭璇嶆挒杞﹀氨浼氭妸鍞ら啋璇彂缁欏埆浜恒€?    #    fail-closed锛氱‘璁や笉浜嗗氨涓嶅彂锛堣澶辫触鍙拌处銆?0 鍒嗛挓鍚庨噸璇曪級锛岀粷涓嶅彂閿欎汉銆?    if db is not None and os.environ.get("SOUL_WAKE_IDCHECK", "1") != "0":
        try:
            from brain import pendingq as _PQ
            if not _PQ._session_matches(actor, db, cand.sid):
                # 馃敶 2026-11-12锛圚Y-15锛夛細`_session_matches` 澶辫触鍏堝仛**瀵硅瘽椤垫爣棰樻樀绉?*
                #   浜屾纭銆俙_session_matches` 绗竴椤轰綅鏄湭璇绘竻闆跺樊鍒嗭紝杩涢敊浜烘椂缁?                #   False锛屼絾**鐩爣浼氳瘽娌℃湁鏈**鏃惰繑鍥?None 璧版枃鏈厹搴曪紝鐭秷鎭湪搴撻噷
                #   鎾炶溅涔熶細杩斿洖 False 鈫?璇垽涓插彴 鈫?鐧界儳+鍐峰嵈銆?                # 馃敶 2026-11-12锛團-03锛夛細鏄电О涓€鑷村彧鏄?*蹇呰**鏉′欢锛屼笉鑳藉崟鐙斁琛?鈥斺€?                #   鍚屽悕/杩戝悕鑱旂郴浜烘爣棰樹竴鑷村嵆涓插彴銆傛樀绉版斁琛屽墠鍙犲姞銆屽簱鍐?sid 涓庣洰鏍?                #   sid 涓€鑷淬€嶆牎楠岋細璇诲綋鍓嶄細璇濇皵娉★紝鐢?db.digest_matches 纭灞忓箷浼氳瘽
                #   灏辨槸 cand.sid锛涚‘璁や笉浜?sid 鈫?缁存寔 fail-closed 涓嶆斁琛屻€?                _released = False
                try:
                    _nn = _PQ.nick_of(db, cand.sid, cand.uid)
                    if _nn:
                        _nm = _PQ._nick_matches(actor, _nn)
                        if _nm is True:
                            _bs = []
                            try:
                                from eyes import chat as _CH
                                _png = actor.dev.screencap()
                                _bs = [t for t, _sd, _it in _CH.bubbles(_png)
                                       if _sd in ("her", "me") and len(t) >= 2]
                            except Exception as _be:
                                log.debug("F-03 璇诲綋鍓嶄細璇濇皵娉″け璐ワ紙涓嶆斁琛岋級: %r", _be)
                            _sid_ok = False
                            if _bs:
                                try:
                                    _sid_ok = bool(db.digest_matches(cand.sid, _bs, min_len=2))
                                except Exception as _de:
                                    log.debug("F-03 sid 鏍￠獙寮傚父锛堜笉鏀捐锛? %r", _de)
                            if _sid_ok:
                                log.info("鍞ら啋韬唤鏍￠獙澶辫触浣嗘樀绉颁竴鑷翠笖搴撳唴 sid 纭锛?r锛夆啋 鏀捐 sid=%s",
                                         _nn, cand.sid)
                                _released = True
                            else:
                                log.warning("鍞ら啋鏄电О涓€鑷翠絾鏃犳硶纭搴撳唴 sid=%s 鈫?涓嶆斁琛?, cand.sid)
                except Exception as _e:
                    log.debug("鍞ら啋鏄电О浜屾纭寮傚父锛堟寜澶辫触澶勭悊锛? %r", _e)
                if not _released:
                    log.warning("鍞ら啋韬唤鏍￠獙澶辫触锛堟悳绱㈢粨鏋滀笉鏄洰鏍囦細璇濓級鈫?涓嶅彂閫?uid=%s", cand.uid)
                    actor.hand.back(settle=1.0)
                    S.leave(actor)
                    _bump_miss(cand.uid, "韬唤鏍￠獙澶辫触")
                    return False, "韬唤鏍￠獙澶辫触"
        except Exception as e:
            # 馃敶 2026-11-13 淇 HY-02锛圥1 涓插彴锛夛細韬唤鏍￠獙浠讳綍寮傚父閮藉繀椤?fail-closed銆?            #   鍘熸潵 `log.debug("...鎸夐€氳繃澶勭悊")` 涓嶄腑姝㈠彂閫?鈥斺€?鎼滅储缁撴灉鎸夊叧閿瘝鎺掑簭锛?            #   绗竴鏉′笉淇濊瘉鏄洰鏍囦汉锛?47-549 娉ㄩ噴鑷锛夛紝鏍￠獙寮傚父涓€鏃︽斁寮€灏卞彲鑳芥妸
            #   鍞ら啋璇彂缁欓敊璇殑浜恒€傛敼锛氬紓甯稿嵆 back + leave + 璁板け璐ュ彴璐︼紝缁濅笉鏀捐銆?            log.warning("鍞ら啋韬唤鏍￠獙寮傚父锛坒ail-closed锛屼笉鍙戦€侊級uid=%s: %r", cand.uid, e)
            try:
                actor.hand.back(settle=1.0)
            except Exception:
                pass
            try:
                S.leave(actor)
            except Exception:
                pass
            try:
                _bump_miss(cand.uid, "韬唤鏍￠獙寮傚父")
            except Exception:
                pass
            return False, "韬唤鏍￠獙寮傚父(fail-closed)"

    # 璺熻繘闃舵鎺ョ嚎锛埪?04-B2锛夛細鐪熸鐏屽瓧鍓嶈繃鍙戦€侀椄锛屽彂閫侀搴︾粺涓€鐢?sendgate 瑁佸喅銆?    #    has_human=True锛氬敜閱掗潰鍚戠湡浜鸿€佸弸锛屼笉鎸夌郴缁熷崱鍙ｅ緞闄嶇骇锛?    #    寮傚父闄嶇骇鏀捐锛堝彴璐?鐘舵€佹満鍑洪棶棰樼粷涓嶆帎鏂敜閱掗摼璺級銆?    try:
        from brain import sendgate as SG
        if SG.ON:
            _d = SG.allow(cand.sid, 1, has_human=True)
            if not _d.ok:
                log.info("鍞ら啋琚窡杩涢樁姊嫤鎴?sid=%s state=%s锛?s锛?,
                         cand.sid, _d.state, _d.reason)
                # 馃敶 2026-11-12锛圚Y-08锛夛細鍘熸潵杩欓噷鍙?back 灏?return False锛?                #   涓?mark_woke(failed=True) 鈫?24h 鍐峰嵈娌¤ 鈫?涓嬩竴杞張閫変腑鍙堟嫤鎴?                #   鈫?鍙嶅鐧界儳锛堝疄娴嬪敜閱掗樁姊嫤鎴?following 65 娆★級銆傜幇鍦細
                #   鈶?璁板け璐ュ彴璐︼紙鍚?24h 鍐峰嵈 + 鏀惧純璁℃暟锛夛紝浠婂ぉ涓嶅啀鎵句粬锛?                #   鈶?纭繚鍥炲埌浼氳瘽鍒楄〃锛坆ack 涓€娆?+ nav.to_chatlist 鍏滃簳锛夛紝
                #      缁濅笉鍋滃湪浼氳瘽椤佃涓嬩竴杞粠閿欒椤甸潰璧锋墜銆?                # 闂镐箣鍓嶅凡瀹屾垚瀵艰埅/杩涗細璇濓紙瑙佷笂鏂?S.search / _enter锛夛紝
                # 鍏堟寜鎴愬姛璺緞鍚屾 back 閫€涓€灞傦紱寮傚父鍚炴帀涓嶆敼鍙樿繑鍥炲€艰涔夈€?                try:
                    actor.hand.back(settle=1.2)
                except Exception:
                    pass
                try:
                    from brain import nav as _nav
                    _snap, _pg = _nav.to_chatlist(actor)
                    if _pg != "chatlist":
                        log.warning("璺熻繘闃舵鎷︽埅鍚庡洖鍒楄〃澶辫触锛坧age=%s锛夆啋 宸插敖鍔涜繑鍥?,
                                    _pg)
                except Exception as _e:
                    log.debug("璺熻繘闃舵鎷︽埅鍚庡洖鍒楄〃寮傚父锛堝凡灏藉姏锛? %r", _e)
                # 馃敶 2026-11-12锛團-02锛夛細SG.allow 鎷︽埅 = 棰濆害/璺熻繘闃舵闂锛坒ollow/
                #   awaiting锛夛紝**涓嶆槸銆屾壘涓嶅埌浜恒€?* 鈫?涓嶈 _bump_miss锛堝惁鍒?c<uid>+1
                #   + 24h 鍐峰嵈锛? 娆″悗瀵逛粛瀛樻椿鐨勭湡浜烘案涔呮斁寮冿級銆傚彧璁版棩蹇?+ back +
                #   to_chatlist锛圚Y-08 宸蹭繚鐣欙級銆傚€欓€変晶宸插湪 candidates() 鎻愬墠婊ゆ帀
                #   FOLLOWING/AWAITING锛岃蛋鍒拌繖閲岃鏄庢槸杞唴鐘舵€佸彉鍖?杈圭晫鎯呭喌锛?                #   鏈疆涓嶅彂閫侊紝浣?*涓嶉€掑鏀惧純璁℃暟**锛屼笅杞€欓€変粛浼氬洖鏉ャ€?                return False, "璺熻繘闃舵鎷︽埅(%s)" % _d.state
    except Exception:
        pass

    inp = Input(dev)
    ok, got = inp.type_and_verify(text, actor)
    if not ok:
        inp.clear()
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "鐏屽瓧澶辫触")
        return False, "鐏屽瓧澶辫触(%r)" % (got,)
    if not inp.tap_send(actor, settle=1.6):
        inp.clear()
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "鎵句笉鍒板彂閫佹寜閽?)
        return False, "鎵句笉鍒板彂閫佹寜閽?
    # 馃敶 2026-11-12锛團-01锛夛細sent_ok 鏄笁鎬侊紙ok/unknown/residual锛岃 hands/input.py锛夈€?    #   鍙湁 residual锛堣緭鍏ユ杩樻湁瀛?= 鏄庣‘娌″彂锛夋墠绠楀け璐ュ苟璁?_bump_miss锛?    #   unknown锛堣浆鍦哄抚璇讳笉鍒拌緭鍏ユ锛屽ぇ姒傜巼宸插彂锛夋寜宸插彂璁拌处锛岄伩鍏嶃€屽疄闄呭凡鍙戝嵈
    #   琚澶辫触銆嶁啋 娆℃棩閲嶅鍞ら啋/閲嶅鍙戞秷鎭€?    _ok = inp.sent_ok(actor, text, timeout=6)
    _why = getattr(inp, "last_reason", "") or ""
    if (not _ok) and _why == "residual":
        actor.hand.back(settle=1.0)
        _bump_miss(cand.uid, "鍙戦€佸悗杈撳叆妗嗘湭娓呯┖(娈嬬暀)")
        return False, "鍙戦€佸悗杈撳叆妗嗘湭娓呯┖(娈嬬暀)"
    # ok 鎴?unknown锛堝ぇ姒傜巼宸插彂锛夆啋 鎸夊凡鍙戣璐?
    # 馃敶 鑷繁鍙戞秷鎭篃浼氬啓搴?鈫?涓嶆姂鍒剁殑璇濓紝鍞ら啋寰幆閲屻€屽簱鏈夊彉鍖栥€嶇珛鍒讳腑鏂紝
    #    姣忔鍞ら啋鍙兘鍙?1 涓汉灏遍€€鍑猴紙瀹炴祴鏃ュ織锛氬敜閱?OK 鍚庨┈涓娿€屾娴嬪埌鏂版秷鎭€嶏級銆?    try:
        from data import watch as _W
        _W.mark_self_write(6.0)
    except Exception:
        pass
    try:
        from brain import ratelimit as _RL
        _RL.note_sent()
    except Exception:
        pass

    actor.hand.back(settle=1.2)      # 浼氳瘽鍐?back 鏄畨鍏ㄧ殑
    mark_woke(cand.uid)
    # 璺熻繘闃舵鎺ョ嚎锛埪?04-B2锛夛細鍙湁鐪熸鍙戦€佹垚鍔熸墠鎸夌湡瀹炴潯鏁拌璐︼紝
    #    鍙戦€侀搴︾粺涓€鐢?sendgate 瑁佸喅锛涘紓甯稿悶鎺変笉璁拌处锛岀粷涓嶆敼鍙樺師鏈夎繑鍥炲€艰涔夈€?    try:
        from brain import sendgate as SG
        if SG.ON:
            SG.note_sent(cand.sid, 1)
    except Exception:
        pass
    log.info("宸茶鍞ら啋鍙拌处 uid=%s锛?4h 鍐呬笉鍐嶆壘浠栵級", cand.uid)
    return True, "宸插彂閫?
