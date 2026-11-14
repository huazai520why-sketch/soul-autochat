# -*- coding: utf-8 -*-
"""娓呯孩鐐癸紙= 杩涗細璇濄€佸垽鏈潯銆佽鍥炲氨鍥烇級銆?

馃敶 鐢ㄦ埛 2026-11-02 鐨勭‖鍙ｅ緞锛?
  銆屾竻绾㈢偣**涓嶆槸杩涘叆杩斿洖**锛屾槸**杩涘叆鐒跺悗鍥炴秷鎭?*銆?
  銆岃繘鍏ュ璇濇鍚庯紝濡傛灉鏈€鍚庝竴鏉℃槸瀵规柟鍙戞潵鐨勶紝閭ｄ箞涓€瀹氳鍋氬洖澶嶃€?

鎵€浠ユ湰妯″潡涓嶆槸銆岀偣杩涘幓鍐嶉€€鍑烘潵銆嶏紝鑰屾槸
    鍙屽嚮鑱婂ぉ tab锛堣烦绾㈢偣閿氱偣锛夆啋 閫愪釜杩涘甫绾㈢偣鐨勪細璇?鈫?handle_one锛堝繀鍥炲垽鏂級鈫?鍥炴潵

鏃ф灦鏋勫搴旓細`eyes/soul_clear_unread.py` + daemon 鐨?`do_reply`銆?
"""
import os
import re
import time
import threading

from brain import flow
from core.log import get_logger
from eyes import popup as P
from eyes.chatlist import rows
from eyes.page import badges, detect

log = get_logger("brain.clear")

LIST_TOP, LIST_BOTTOM = 200, 1500     # 浼氳瘽琛屾湁鏁堢旱鍚戣寖鍥?
MAX_ENTER = 8                         # 鍗曟 sweep 鏈€澶氳繘鍑犱釜浜?

# 馃敶 娓呯孩鐐?*鍙敤鍙屽嚮**锛岀粷涓嶆粦鍔紙鐢ㄦ埛 2026-11-02 鍙嶅寮鸿皟锛屼笉姝㈠崄娆★級銆?
#   鍙屽嚮鐨勫疄娴嬭涔夛細璺冲埌涓嬩竴涓湁绾㈢偣鐨勪綅缃紱娌℃湁绾㈢偣灏卞師鍦颁笉鍔紱
#   鍦ㄧ孩鐐瑰尯闂村唴涓€娆℃帹杩涚害 1 琛屻€傛墍浠ュ畠鏄€岀孩鐐瑰鑸敭銆嶏紝
#   浣嶇疆涓嶅灏卞鐐瑰嚑娆★紝**涓嶈鏀圭敤婊戝姩鍘绘壘**銆?
MAX_DOUBLE = 5                        # 鍙屽嚮涓婇檺锛堢敤鎴?2026-11-02锛? 娆¤冻澶熸竻瀹岋級


# 鍒楄〃閲岃繖浜?*涓嶆槸鐪熶汉浼氳瘽**锛氱偣杩涘幓涓嶆槸鑱婂ぉ椤碉紙瀹炴祴銆岀灛闂淬€嶆槸鍔熻兘鍏ュ彛锛?
# 鏈夌孩鐐逛絾姘歌繙杩涗笉鍒?chat 椤?鈫?姣忚疆 23s 绌鸿浆锛屽疄娴嬭繛缁┖杞?47 杞級銆?
# 馃敶 2026-11-04锛堢敤鎴凤細銆屽垏鍙峰畬鎴愬悗搴斾紭鍏堝鐞嗙孩鐐广€嶏級锛氬垏鍙峰悗鏂板彿鍒楄〃椤堕儴
#    鏈夈€孲oul閫氱煡銆嶃€孲oul绌洪棿绔欍€嶇瓑绯荤粺鍙?鍔熻兘鍏ュ彛甯︾孩鐐癸紝杩涗笉鍘?chat 椤?
#    鈫?鐧界儳 20s 杩樻妸銆屽亣绾㈢偣銆嶈鏁伴《婊?鈫?鍐峰嵈 15 鍒嗛挓 鈫?鐪熶汉绾㈢偣琚€借銆?
#    銆岄敠椴ら┚鍒般€嶆槸瀹樻柟钀ラ攢鍙凤紙chat 椤典絾鏈€鍚庝竴鏉℃槸绯荤粺鎺ㄩ€?鎴戝彂鐨勶級锛屽悓鐥呫€?
# 馃敶 2026-11-04锛堝繀鍥炴紡鐐逛慨澶嶏級锛氥€岄敠椴ら┚鍒般€嶅師浠ヤ负钀ラ攢鍙凤紝瀹炴祴鏄?*鐪熶汉**
#    锛坣ick 琛?uid=*** name=閿﹂菠椹惧埌锛屾垜浠兘璺熷ス姝ｅ父鏉ュ洖锛屽ス浠婂ぉ杩樺彂浜?
#     銆屼笂鐝笉澶氥€嶏級銆傛妸濂瑰啓杩涢粦鍚嶅崟绛変簬銆屾案涓嶅洖澶嶃€嶏紝鐩存帴杩濊儗蹇呭洖銆?
#    鐪熸璇ユ嫤鐨勬槸**鍔熻兘鍏ュ彛**锛氱灛闂?Soul閫氱煡/Soul绌洪棿绔?鍦?nick 琛ㄩ噷鏍规湰涓嶅瓨鍦紝
#    璇存槑瀹冧滑涓嶆槸鐪熶汉浼氳瘽銆傚畼鏂硅惀閿€鍙峰彟鏈夊彿娈甸椄 SKIP_UID_PREFIX(2042683)
#    + Session.is_official锛堟枃妗堝懡涓墺2 涓惀閿€璇嶏級銆?
NOT_CHAT_NICKS = ("鐬棿", "Soul閫氱煡", "Soul绌洪棿绔?)

# 馃敶 2026-11-12锛埪?18 宸ュ崟 P1锛夛細銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶅垪琛ㄨ鏄?*鍔熻兘鍏ュ彛**锛?
#    涓嶆槸鐪熶汉浼氳瘽銆傜偣杩涘幓鏄?LoveBellChatListActivity锛堢◢鍚庡啀鑱婂垪琛ㄩ〉锛夛紝
#    涓嶆槸 ConversationActivity 鈫?閫氱敤銆岃繘浼氳瘽銆嶈矾寰?100% 鏍￠獙澶辫触鐧界儳
#    锛堝疄娴?brain.flow.log 鍏ㄥぉ 24 娆°€岃繘鍏ュ悗涓嶆槸 chat 椤? unknown銆嶏級銆?
#    鍙湪銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶅叆鍙ｈ鐐瑰嚮鍓嶈瘑鍒烦杩囷紝浜ょ粰 bell 涓撶敤璺緞澶勭悊銆?
#    `nick` 褰㈠銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶆垨銆屽閬囬搩 绋嶅悗鍐嶈亰銆嶇瓑銆?
_BELL_ROW_RE = re.compile(r"濂囬亣閾?{0,4}绋嶅悗")


def dots(snap):
    """褰撳墠灞忓甫绾㈢偣鐨勪細璇濊锛堣繃婊ゆ帀涓嶆槸鑱婂ぉ鐨勫姛鑳藉叆鍙ｏ級銆?

    鈿狅笍鈿狅笍 2026-11-12锛圚Y-12锛夛細**鏈嚱鏁板湪 Soul 6.41.0 涓婂疄娴嬫亽绌猴紝浠呬綔鍏滃簳**銆?
      鐩爣鏉ユ簮宸叉敼涓哄簱锛坄_lib_unread_sids`锛夛紝灞忓箷绾㈢偣鍒ゆ嵁淇濈暀鍙负涓囦竴鏌愬ぉ
      res-id `unread_msg_number` 鍥炴潵浜嗕篃涓嶆紡銆備换浣曚緷璧?dots() 璁℃暟/缁撴灉鐨?
      閫昏緫閮藉簲鎸夈€屾亽绌恒€嶆潵鍐欙紝鍒妸瀹冨綋涓诲垽鎹€?

    鈿狅笍鈿狅笍 2026-11-08 瀹炴祴锛?*杩欎釜鍑芥暟鍦ㄥ綋鍓?Soul 6.41.0 涓婃亽杩斿洖绌?*銆?
      `Row.has_dot` 渚濊禆琛屽唴 res-id `unread_msg_number`锛坈hatlist.py:63锛夛紝
      鑰岃繛缁?4 杞?dump 閲岃 id **鍑虹幇 0 娆?*锛堝叏灞忓彧鏈夊簳鏍忕殑 me_red_point /
      red_text / square_red_point锛夈€傚簱鏈鐨?10 鏉?lastMsgText 鎷垮幓灞忎笂
      textContains 鍙嶆煡 鈫?**鍛戒腑 0/10**锛堝垪琛ㄨ婊氬埌 8 澶╁墠锛屽ス鐨勮瘽娌℃覆鏌擄級銆?
      鈬?娓呯孩鐐硅嫢浠ユ湰鍑芥暟涓哄敮涓€鐩爣婧愶紝鏁存潯閾捐矾**绌鸿浆**銆?

    淇濈暀鏈嚱鏁帮紙鏈夎皟鐢ㄧ偣锛屼笖鏄敮涓€鑳借瘑鍒€屾敹鍒扮殑鏂版嫑鍛笺€嶈繖绫昏仛鍚堣鐨勫湴鏂癸級锛?
    浣?*鐩爣鏉ユ簮鏀逛负搴?*锛氳 `sweep()` 閲岀殑 `_lib_targets()`銆?
    """
    out = []
    for r in rows(snap):
        if not (LIST_TOP <= r.center[1] <= LIST_BOTTOM):
            continue
        if not r.has_dot:
            continue
        if (r.nickname or "").strip() in NOT_CHAT_NICKS:
            continue
        out.append(r)
    return out


def _lib_unread_sids(db):
    """搴撻噷鐨勬湭璇讳細璇?sid锛?*鏇夸唬灞忓箷绾㈢偣**鐨勭洰鏍囨簮锛?.05s锛夈€?

    馃敶 2026-11-08锛堝簱鐩磋 P0锛夛細`dots()` 鎭掔┖ 鈫?鐩爣蹇呴』浠庡簱鏉ャ€?
      瀹炴祴鍚屼竴鐬棿锛氬簱 11 涓湭璇讳細璇?/ 50 鏉℃湭璇伙紝灞忎笂 10 琛?0 涓孩鐐广€?
    """
    try:
        from data import pending as _P
        return _P.unread_sids(db)
    except Exception as e:
        log.debug("搴撴湭璇绘竻鍗曚笉鍙敤: %r", e)
        return []


def pending_summary(db):
    """daemon 鏃ュ織鐢細銆岀幇鍦ㄦ湁鍑犱釜浜哄湪绛夋垜鍥炪€嶃€傚簱涓嶅彲鐢ㄨ繑鍥?'寰呭洖 ? 浜?銆?""
    try:
        from data import pending as _P
        return _P.summary(db)
    except Exception as e:
        log.debug("寰呭洖缁熻涓嶅彲鐢? %r", e)
        return "寰呭洖 ? 浜猴紙搴撲笉鍙敤锛?


def count_pending(db, real_total=True, max_age_h=None):
    """寰呭洖浜烘暟锛涘簱涓嶅彲鐢ㄨ繑鍥?-1銆?

    real_total=True锛堥粯璁わ級= **鐪熷疄寰呭洖鎬婚噺**锛堝惈鍐峰嵈涓?宸插洖杩囨湭鍥炲啓锛夛紝
      鐢ㄤ簬銆岃繕鏈夋病鏈変汉绛夈€嶇殑闂?鈥斺€?涓嶈兘鐢ㄣ€屾湰杞彲澶勭悊鏁般€嶅綋闂革紝
      鍚﹀垯鍐峰嵈鏈熶竴杩囧氨璇垽銆屾病浜虹瓑銆嶁啋 瑙﹀彂鍋囩孩鐐瑰喎鍗淬€?
    real_total=False = 鏈疆鐪熻兘澶勭悊鐨勪汉鏁般€?

    馃敶 2026-11-08 03:50锛圥0 姝婚攣锛夛細鏂板 max_age_h 閫忎紶缁?data.pending.count_pending銆?
      绾㈢偣闂搁棬蹇呴』鎸夈€岃繕鍥炲緱鎺夌殑浜恒€嶈锛?4h 鍐咃級锛屽惁鍒?7 澶╃獥鍙ｇ殑鍍靛案绉帇
      浼氳杩欎釜鍑芥暟鎭?> 0 鈫?鍖归厤姘歌繙琚尅锛堝疄娴嬭繛缁尮閰嶅垰璧锋灏辫鎵撴柇锛夈€?
    """
    try:
        from data import pending as _P
        try:
            return _P.count_pending(db, real_total=real_total, max_age_h=max_age_h)
        except TypeError:
            return _P.count_pending(db, real_total=real_total)
    except Exception as e:
        log.debug("寰呭洖璁℃暟涓嶅彲鐢? %r", e)
        return -1


def should_reply_list(db, limit=0):
    """銆岃鍥炶皝銆嶆竻鍗曪紙搴撳垽瀹氾紝瀹屽叏涓嶇湅灞忥級銆傝繑鍥?[PendingItem, ...]銆?""
    try:
        from data import pending as _P
        return _P.should_reply(db, limit=limit)
    except Exception as e:
        log.warning("搴撳垽瀹氬緟鍥炲け璐? %r", e)
        return []


def badge_chat(snap):
    return badges(snap).get("鑱婂ぉ") or 0


def _blob_key(txt):
    """鍒楄〃棰勮姣斿涓诧細鍘绘帀 [琛ㄦ儏]锛涙礂鎴愮┖锛堢函琛ㄦ儏/璇煶锛夊氨閫€鍥炲師鏂囥€?

    涓?`ensure_fresh._key` 鍚屼竴鍙ｅ緞 鈥斺€?閭ｆ潯璺緞宸插湪鐢熶骇楠岃瘉杩囷紙鑳藉垽銆屽垪琛ㄦ槸鍚﹁窡涓婂簱銆嶏級銆?
    """
    raw = (txt or "").strip()
    t = re.sub(r"\[[^\]]{1,6}\]", "", raw).strip()[:8]
    return t or raw[:8]


def _rows_for_lib(snap, db, lib_sids, handled=None, limit=0):
    """鎶?*搴撻噷鐨勬湭璇?sid** 鏄犲皠鎴愬睆骞曚笂鐨勪細璇濊锛堝簱瀹氱洰鏍囷紝灞忓箷瀹氬潗鏍囷級銆?

    馃敶 2026-11-08锛堝簱鐩磋 P0 鐨勩€屽畾浣嶅眰銆嶏級锛?
      搴撹兘 0.05s 璇村嚭銆岃鍥炶皝銆嶏紝浣嗙偣鍑讳粛鐒堕渶瑕佷竴涓睆骞曡妭鐐广€?
      鏄犲皠鏂瑰紡娌跨敤 `ensure_fresh` 宸插湪鐢熶骇楠岃瘉鐨勫姙娉曪細**鐢ㄥ簱閲岀殑 lastMsgText
      鍓嶇紑鍘诲尮閰嶈 blob**锛堝垪琛ㄩ瑙堝氨鏄?lastMsgText 鍘熸枃锛岀煭娑堟伅涓嶆埅鏂級銆?
      杩欐瘮 `flow.sid_from_row()` 渚垮疁寰楀锛堥偅涓瘡琛岃璺?4 鏉?SQL锛夛紝
      鑰屼笖鏂瑰悜鏄弽鐨勶細搴撳凡鐭ョ瓟妗堬紝灞忓箷鍙渶璁ら銆?

    杩斿洖 [(row, sid), ...]锛屾寜 lib_sids 鐨勯『搴忥紙= 搴撶殑浼樺厛绾э級銆?
    灞忎笂鎵句笉鍒扮殑 sid 浼氳璺宠繃锛堣鏄庡垪琛ㄦ病婊氬埌閭ｉ噷 鈫?鐢辫皟鐢ㄦ柟鍒锋柊/缈诲睆锛夈€?
    """
    handled = handled or set()
    if not lib_sids or db is None:
        return []
    rows_ = [r for r in rows(snap)
             if LIST_TOP <= r.center[1] <= LIST_BOTTOM
             and (r.nickname or "").strip() not in NOT_CHAT_NICKS]
    if not rows_:
        return []
    out, used = [], set()
    for sid in lib_sids:
        if limit and len(out) >= limit:
            break
        try:
            dig = db.session_digest(sid) or {}
            key = _blob_key(dig.get("text"))
        except Exception:
            continue
        if not key:
            continue
        for r in rows_:
            if id(r) in used:
                continue
            if (r.nickname or "") in handled:
                continue
            if key in (r.blob or ""):
                used.add(id(r))
                out.append((r, sid))
                break
    return out


def _prune_dead_lib_sids(db, lib_sids, claimed):
    """鍓旈櫎璁惧搴撻噷**宸蹭笉瀛樺湪**鐨勬湭璇?sid锛岄伩鍏嶆瘡杞弽澶嶇┖杞€?

    馃敶 2026-11-12锛圚Y-01锛夛細娓呯孩鐐圭洰鏍囨潵鑷簱锛坃lib_unread_sids锛夛紝浣嗗睆涓婅棰嗕笉鍒版椂
      鑻ラ潤榛樿惤绌猴紝浼氬弽澶嶈蛋銆屽弻鍑昏烦閿氱偣銆嶅垎鏀┖杞紙瀹炴祴锛氬簱 5 涓湭璇?/ 灞忕孩鐐?0 /
      杩?0 浜猴級銆傝繖閲屽彧鍓旈櫎**璁惧搴撳凡鏌ヤ笉鍒?*鐨?sid 鈥斺€?浜哄凡鍒犲彿/浼氳瘽宸叉秷澶憋紝
      瀹冧滑姘歌繙涓嶄細鍐嶈璁ら鍒帮紝鐣欑潃鍙細姣忚疆鐧界儳銆?
      浠嶅瓨娲讳絾鍙槸娌℃覆鏌撳埌褰撳墠灞忕殑 sid **淇濈暀**锛堢湡瀹炵洰鏍囷紝鍒楄〃鍒锋柊鍚庤兘璁ら锛夛紝
      涓嶈鏉€銆佷笉鏀瑰彉鐪熷疄寰呭洖鍙ｅ緞銆?
    """
    if not lib_sids or db is None:
        return
    removed = []
    for sid in list(lib_sids):
        if sid in claimed:
            continue
        try:
            if db.session(sid) is None:
                lib_sids.remove(sid)
                removed.append(sid)
        except Exception:
            continue
    if removed:
        log.info("鍓旈櫎璁惧搴撳凡涓嶅瓨鍦ㄧ殑鏈 sid %s锛堥伩鍏嶅弽澶嶇┖鐑э級", removed)


def to_list(actor, tries=3):
    """纭繚鍋滃湪浼氳瘽鍒楄〃锛涙湁寮圭獥鐐逛富鎸夐挳銆?

    馃敶 2026-11-09锛堢敤鎴枫€屾搷浣滃眰涔辩偣銆嶇殑绗簩澶勬牴鍥狅紝瀹炶瘉 23:59:17~27锛夛細
       10 绉掑唴鐩茬偣銆岃亰澶┿€峵ab 6 娆″叏閮ㄦ湭鍛戒腑锛屾瘡娆¤繕璺熺潃鎸変竴娆?back銆?
       detect=unknown 鏃?UI 鏍戦噷**鏍规湰娌℃湁搴曟爮**锛孉ctor.tap_tab 璧?
       `n is None` 鍒嗘敮鐩存帴杩斿洖 `(None, unknown)`锛涙棫浠ｇ爜涓嶇湅杩欎釜淇″彿锛?
       鐓ф牱 hand.back() 鈫?椤甸潰浠嶆槸 unknown 鈫?涓嬩竴杞啀鐐癸紝褰㈡垚鐧界偣寰幆銆?
       鑰?unknown 椤垫寜 back 杩樻湁鎶?App 閫€鍒版闈㈢殑椋庨櫓锛堟棩蹇?157 娆?
       銆孲oul 涓嶅湪鍓嶅彴銆嶅嵆姝ょ被锛夈€?

       鏀规硶涓?brain/nav.py 鍚屽彛寰勶細
         鈶?鐐瑰墠鍏堢‘璁ゅ簳鏍忓瓨鍦紝娌℃湁灏?*涓嶇偣**锛堜笉浜х敓鏃犳晥鎵嬪娍锛夛紱
         鈶?鏄庣‘鍦ㄤ細璇濋〉 chat 鈫?back 涓€娆★紙蹇笖涓嶄細閫€鍒版闈級锛?
         鈶?鍏朵綑鏃犲簳鏍忛〉 鈫?am start --activity-clear-top 鍥炰富妗嗘灦锛?*缁濅笉 back**锛?
         鈶?鎭㈠鍙仛涓€娆★紝浠嶄笉琛屽氨浜ゅ洖涓婂眰锛坰weep 鏈?detect!=chatlist 淇濇姢锛?
            浼氳烦杩囨湰杞紝涓嶄細鎷?unknown 蹇収涔辩偣銆佹洿涓嶄細璇彂娑堟伅锛夈€?
    """
    from brain.nav import goto_main      # 灞€閮ㄥ鍏ワ細瑙勯伩 clear 鈫?nav 鐨?import 鏃跺簭
    recovered = False
    for _ in range(tries):
        snap = actor.snap()
        pg = detect(snap)
        if pg == "chatlist":
            return snap
        p = P.detect(snap)
        if p is not None:
            btn = (p.primary or p.secondary)
            if btn:
                log.info("澶勭悊寮圭獥: %s", btn[0][0])
                actor.hand.tap_node(btn[0][1], settle=1.2)
                continue

        # 搴曟爮閮戒笉鍦?鈫?杩欎竴涓?tab 蹇呯劧鐐逛笉涓紝缁濅笉鐩茬偣
        if snap is None or snap.tab("鑱婂ぉ") is None:
            if pg == "chat":
                log.info("[clear] 鍦ㄤ細璇濋〉锛宐ack 鍥炲垪琛?)
                actor.hand.back(settle=1.0)
                continue
            if recovered:
                log.warning("[clear] 鎭㈠鍚庝粛鏃犲簳鏍?%s) 鈫?鏀惧純鏈疆锛屼笉绌虹儳", pg)
                return snap if snap is not None else actor.snap()
            recovered = True
            log.warning("[clear] 鏃犲簳鏍?%s) 鈫?涓嶇洸鐐?tab / 涓?back锛?
                        "am start clear-top 鍥炰富妗嗘灦", pg)
            try:
                goto_main(actor.dev)
            except Exception as e:
                log.warning("[clear] clear-top 鎭㈠澶辫触锛堜氦鍥炰笂灞傝烦杩囨湰杞級: %r", e)
                return snap if snap is not None else actor.snap()
            continue

        log.info("涓嶅湪鍒楄〃椤?%s)锛岀偣搴曟爮鑱婂ぉ", pg)
        snap2, pg2 = actor.tap_tab("鑱婂ぉ", settle=1.2)
        if pg2 == "chatlist":
            return snap2
        # 鐐逛簡娌″埌锛氫笉 back锛屼笅涓€杞噸鏂板彇鏍戝啀鍒わ紙椤甸潰鍙兘姝ｅ湪鍒囨崲锛?
    return actor.snap()


def _pull_down(actor, n=1, budget=12.0):
    """鍦ㄤ細璇濆垪琛ㄩ《閮ㄤ笅鎷夊埛鏂帮紝**绉掔骇瓒呮椂銆佺粷涓嶉樆濉炰富娴佺▼**銆?

    馃敶 2026-11-04 浜嬫晠锛堝繀椤讳繚鐣欒繖娈佃鏄庯紝鍚﹀垯浼氳浜恒€屼紭鍖栥€嶅洖鍘伙級锛?
      08:20:50 鐨勮繖娆′笅鎷夊埛鏂?*鍗′簡鏁存暣 10 鍒嗛挓** 鈥斺€?uiautomator2 鐨?HTTP 璇锋眰
      榛樿瑕佺瓑 600s 鎵嶆姏 TimeoutError銆傛暣杞?cycle 琚畠鎷栨锛岄偅 10 鍒嗛挓閲?
      濂?08:12銆屾病蹇欎粈涔堛€? 08:17銆孾鐤戞儜][鐤戦棶]銆嶄袱鏉℃柊娑堟伅涓€鏉℃病澶勭悊锛?
      鑰屼笖澶辫触鍚庣揣鎺ョ潃鍙堥噸璇?#2锛岀瓑浜庢棤闄愭寕璧枫€?
      鎵€浠ワ細鈶?client 瓒呮椂鍘嬪埌 8s 鈶?鏁翠釜鎵嬪娍鍐嶅绾跨▼ join(budget) 鍏滃簳
      鈶?澶辫触鍗宠繑鍥?False锛岀敱 ensure_fresh 鏀惧純鏈疆锛堝畞鍙垪琛ㄦ棫锛屼篃涓嶈兘蹇呭洖鍋滄憜锛夈€?
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("涓嬫媺鍒锋柊鍙?u2 澶辫触: %r", e)
        return False
    # 馃敶 2026-11-04锛坉uration 鍗曚綅浜嬫晠锛岃繖灏辨槸 08:20 鍗?10 鍒嗛挓鐨勭湡鍥狅級锛?
    #   u2 鐨?duration 鏄?*绉?*锛堟簮鐮?steps = int(duration * 200)锛屾瘡 step 绾?5ms锛夈€?
    #   鍘熸潵浼?duration=700 鈫?绛変环 **700 绉?*鐨勬墜鍔匡紝绾跨▼ join(12s) 鍚庢斁寮冿紝
    #   浣嗘墜鍔胯繕鍦ㄨ澶囦笂璺戯紝鏁存満鐐瑰嚮鍏ㄩ儴鎺掗槦 鈥斺€?琛ㄧ幇涓恒€屾暣杞仠鎽?10 鍒嗛挓銆嶃€?
    #   鍙︼細`d._client.timeout` 鍦?u2 3.7.1 閲屼笉瀛樺湪锛堢┖鎿嶄綔锛夛紝宸插垹銆?

    box = {"ok": False, "err": None}

    def _job():
        try:
            for _ in range(max(1, n)):
                d.swipe(450, 380, 450, 1200, duration=0.55)   # 绉掞紒
                time.sleep(0.8)
            box["ok"] = True
        except Exception as e:      # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_job, name="pulldown", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("涓嬫媺鍒锋柊鎵嬪娍瓒呮椂锛?%.0fs锛夛紝鏀惧純鏈鍒锋柊锛屼笉闃诲涓绘祦绋?, budget)
        return False
    if not box["ok"]:
        log.warning("涓嬫媺鍒锋柊鎵嬪娍澶辫触: %r", box["err"])
        return False
    return True


def _to_top(actor, rounds=4, budget=12.0):
    """鎶婁細璇濆垪琛ㄦ粴鍥?*椤堕儴**锛堢敤鎴?2026-11-04 鍙ｅ緞锛氬厛鍥為《鍐嶆竻褰撳墠灞忕孩鐐癸級銆?

    馃敶 涓轰粈涔堝繀椤绘湁锛氭竻绾㈢偣鍘熸潵鏄€屽湪褰撳墠灞忔壘绾㈢偣銆嶁€斺€斿鏋滃垪琛ㄥ仠鍦ㄤ腑闂达紝
      椤堕儴閭ｄ簺鍒氭潵鐨勭孩鐐癸紙鏈€鏂版秷鎭兘鍦ㄦ渶涓婇潰锛夋牴鏈笉鍦ㄨ閲庨噷锛?
      鏈疆灏变細銆屾病绾㈢偣鍙竻 鈫?鍙屽嚮 鈫?涔熻烦涓嶅埌銆嶇洿鎺ョ┖杞€?
    瀹炵幇涓?_pull_down 涓€鑷达細u2 鎵嬪娍 + 绾跨▼ join 鍏滃簳锛屽け璐ョ珛鍒昏繑鍥?False銆?
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("鍥為《鍙?u2 澶辫触: %r", e)
        return False
    box = {"ok": False}
    stop = {"hit": False}

    def _job():
        try:
            for _ in range(max(1, rounds)):
                if stop["hit"]:
                    break
                d.swipe(450, 380, 450, 1250, duration=0.5)   # 绉掞紒鎵嬫寚涓嬫粦 = 鐪嬫洿涓婇潰
                time.sleep(0.5)
                # 椤堕儴鍐嶆粦涔熶笉鍔ㄦ椂锛屽啀鍔犳粦涓€娆″氨鏄氮璐?鈥斺€?鐢辫皟鐢ㄦ柟鎸夎鎸囩汗鍒ゆ柇
            box["ok"] = True
        except Exception:
            box["ok"] = False

    t = threading.Thread(target=_job, name="totop", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("鍥為《鎵嬪娍瓒呮椂锛?%.0fs锛夛紝鏀惧純鏈", budget)
        return False
    return box["ok"]


def ensure_fresh(actor, db, rounds=1):
    """纭繚浼氳瘽鍒楄〃 UI 璺熷簱鍚屾锛岃繑鍥炴渶鏂扮殑涓€娆?snap銆?

    馃敶 2026-11-04 瀹炴祴锛?02857053锛?7:50锛夛細db 閲?session 鏈€鏂?07:27锛?
      鑰屽垪琛ㄩ琛岃繕鍋滃湪 05:10 鈥斺€?UI 钀藉悗 2.5 灏忔椂銆傚悗鏋滄槸涓変釜鍏ュ彛涓€璧峰け鐏碉細
        路 瑙掓爣=4 鑰岃鍐呯孩鐐?0 涓?鈫?clear 杩?0 浜?
        路 鍙屽嚮銆岃烦绾㈢偣銆嶈烦涓嶅姩锛堝垪琛ㄩ噷娌℃湁閭ｄ簺琛岋級
        路 find_row 鍏ㄨ惤绌?鈫?閫€鍖栧幓鎼滅储锛岃€屾悳绱篃娌℃湁杩欎簺娑堟伅鐨勭储寮?

    馃敶 2026-11-04 浜屼慨锛?9:34 璇煶浜嬫晠锛夛細鍒ゆ嵁鍘熸潵鍙姹傘€屾湭璇婚噷浠绘剰涓€鏉″懡涓€嶏紝
      涓ゅ婕忥細
        鈶?璇煶/绾〃鎯呯殑 lastText锛?[璇煶]'锛夎琛ㄦ儏姝ｅ垯娲楁垚绌轰覆鍚?*鐩存帴璺宠繃**锛?
        鈶?鍙鏈変竴鏉¤€佹湭璇诲懡涓氨鍒ゃ€屽凡璺熶笂銆嶏紝鍝€?*鏈€鏂伴偅鏉℃牴鏈笉鍦ㄥ睆涓?*銆?
      瀹炴祴 uid=*** 09:34:36 鐨勮闊冲洜姝?12 鍒嗛挓娌′汉绠★紙灞忎笂娌＄孩鐐广€佷篃娌′汉鍒锋柊锛夈€?
      鐜板湪锛氭礂鎴愮┖涓插氨閫€鍥炲師鏂囧弬涓庡尮閰嶏紱骞剁‖鏍￠獙銆屽簱閲屾渶鏂扮殑浼氳瘽蹇呴』鍦ㄥ綋鍓嶅睆銆嶃€?

    鍒ゆ嵁锛氬簱閲屾湁鏈浼氳瘽锛屼絾褰撳墠灞忎笂涓€琛岄兘瀵逛笉涓?/ 缂烘渶鏂颁細璇?鈫?鍒ゅ畾杩囨湡銆?
    瀵瑰緱涓婂氨浠€涔堥兘涓嶅仛锛堜笉棰濆澧炲姞鎵嬪娍锛岄伩鍏嶆墦鏂甯告祦绋嬶級銆?
    """
    if db is None:
        return actor.snap()
    try:
        unread = [s for s in db.sessions(unread_only=True, include_official=False)
                  if (s.last_text or "").strip()][:8]
        newest = [s for s in db.sessions(limit=3, include_official=False)
                  if (s.last_text or "").strip()][:1]
    except Exception:
        return actor.snap()
    if not unread and not newest:
        return actor.snap()

    def _key(txt):
        """鍒楄〃棰勮鐢ㄧ殑姣斿涓诧細鍘绘帀 [琛ㄦ儏]锛涙礂鎴愮┖锛堢函琛ㄦ儏/璇煶锛夊氨閫€鍥炲師鏂囥€?""
        raw = (txt or "").strip()
        t = re.sub(r"\[[^\]]{1,6}\]", "", raw).strip()[:8]
        return t or raw[:8]

    for i in range(max(1, rounds)):
        snap = actor.snap(force=True)
        if detect(snap) != "chatlist":
            return snap
        blob = "\n".join((r.blob or "") for r in rows(snap))
        hit = 0
        for s in unread:
            t = _key(s.last_text)
            if t and t in blob:
                hit += 1
        # 纭牎楠岋細搴撻噷鏈€鏂扮殑閭ｆ潯浼氳瘽蹇呴』鍑虹幇鍦ㄥ綋鍓嶅睆锛堝惁鍒欑孩鐐逛篃涓嶄細娓叉煋锛?
        if newest:
            t0 = _key(newest[0].last_text)
            if t0 and t0 not in blob:
                log.info("鍒楄〃缂烘渶鏂颁細璇濓紙搴撻噷鏈€鏂?%r 涓嶅湪灞忎笂锛夆啋 鍒ゅ畾杩囨湡", t0)
                hit = 0
        if hit:
            log.info("鍒楄〃宸茶窡涓婂簱锛堟湭璇?%d 涓紝鍛戒腑 %d 涓級", len(unread), hit)
            return snap
        log.warning("鍒楄〃姣斿簱鏃э紙鏈 %d 涓紝灞忎笂娌℃湁鏈€鏂伴偅鏉★級鈫?涓嬫媺鍒锋柊 #%d",
                    len(unread), i + 1)
        if not _pull_down(actor):
            # 馃敶 2026-11-04锛氭墜鍔垮け璐ュ氨鏀惧純鏈疆锛堝師鏉ヨ繕浼氬啀 #2 娆★紝姣忔鍙兘鎸?10 鍒嗛挓锛夈€?
            #    鍒楄〃鏃у彧鏄畾浣嶅彉闅撅紝杩樿兘璧版悳绱㈠厹搴曪紱鎶婃暣杞嫋姝荤瓑浜庡繀鍥炲仠鎽嗐€?
            log.warning("涓嬫媺鍒锋柊涓嶅彲鐢?鈫?鏈疆鏀惧純鍒锋柊锛岀户缁敤褰撳墠鍒楄〃")
            break
        time.sleep(1.2)
    return actor.snap(force=True)


def handle_greeting(actor, dev, dry_run=False, max_people=4):
    """澶勭悊銆屾敹鍒扮殑鏂版嫑鍛笺€嶏紙NewGreetingDetailActivity锛夈€?

    鐢ㄦ埛 2026-11-02锛氳繖鏉＄郴缁熸秷鎭?*鐐硅繘鍘昏繕瑕佸啀鐐逛竴娆?*鎵嶈繘瀵硅瘽椤点€?
    椤甸潰缁撴瀯锛堝疄娴嬶級锛?
        銆屾敹鍒扮殑鏂版嫑鍛笺€?銆屽彂娑堟伅鍚庡璇濇灏嗕細琚斁鍑哄摝銆?
        姣忎汉涓€鏁磋 ViewGroup(0, y, 900, y+153) 鈥斺€?鐐瑰畠杩?ConversationActivity
    娉ㄦ剰锛?*鍙戞秷鎭悗杩欎釜浜烘墠浼氳鏀捐繘姝ｅ父浼氳瘽鍒楄〃**锛屾墍浠ュ繀椤诲彂锛屼笉鑳藉彧鐐瑰紑閫€鍑恒€?
    杩斿洖鍙戝嚭鐨勬潯鏁般€?
    """
    from brain import match as M

    snap = actor.snap(force=True)
    if "鏀跺埌鐨勬柊鎷涘懠" not in "\n".join(snap.texts()):
        return 0

    done, tried = 0, set()
    for _ in range(max_people):
        s = actor.snap(force=True)
        if "鏀跺埌鐨勬柊鎷涘懠" not in "\n".join(s.texts()):
            break
        rows_ = [n for n in s.nodes
                 if n.clickable and n.visible
                 and (n.bounds[2] - n.bounds[0]) >= 700
                 and 120 <= (n.bounds[3] - n.bounds[1]) <= 220
                 and n.bounds[1] > 150
                 and tuple(n.bounds) not in tried]
        if not rows_:
            break
        rows_.sort(key=lambda n: n.bounds[1])
        n = rows_[0]
        tried.add(tuple(n.bounds))
        log.info("鏂版嫑鍛?-> 鐐圭 %s 琛?, n.bounds)
        actor.hand.tap_node(n, settle=2.5)
        s2, pg = actor.wait_page(("chat",), timeout=8.0)
        if pg != "chat":
            log.warning("娌¤繘瀵硅瘽椤碉紙%s锛夛紝杩斿洖", pg)
            actor.hand.back(settle=1.5)
            continue

        text = M.pick_opener()
        if dry_run:
            log.info("[dry] 浼氬彂 %r", text)
        else:
            # 鏂颁細璇濆紑鍦虹櫧鏃?sid 鈫?璧?match.send 鐨?sid="" 鍒嗘敮锛岃繃闂镐絾涓嶅崰璺熻繘棰濆害
            ok, why = M.send(actor, dev, text)
            log.info("鏂版嫑鍛煎彂閫?%r -> %s %s", text, ok, why)
            if ok:
                done += 1
                time.sleep(0.8)

        actor.hand.back(settle=1.5)
        for _ in range(4):                      # 绛夊洖鍒版柊鎷涘懠椤?
            s3 = actor.snap(force=True)
            if "鏀跺埌鐨勬柊鎷涘懠" in "\n".join(s3.texts()):
                break
            time.sleep(0.8)

    return done


def sweep(actor, db, dry_run=False, max_enter=MAX_ENTER, dev=None, budget_s=240.0):
    """娓呬竴杞孩鐐癸紙杩涗細璇?+ 蹇呭洖锛夈€傝繑鍥?dict(entered, replied, left, results)銆?""
    out = {"entered": 0, "replied": 0, "left": None, "results": []}

    snap = to_list(actor)
    if detect(snap) != "chatlist":
        log.warning("鍥炰笉鍒颁細璇濆垪琛紝璺宠繃娓呯孩鐐?)
        out["left"] = -1
        return out
    # 馃敶 2026-11-04锛氬垪琛?UI 浼氳惤鍚庝簬搴擄紙瀹炴祴钀藉悗 2.5h锛夆啋 绾㈢偣/琛屽畾浣嶅叏澶辩伒銆?
    #    瀵逛笉涓婂氨涓嬫媺鍒锋柊涓€娆★紝涓嶉澶栧鍔犳墜鍔垮紑閿€銆?
    # 馃敶 2026-11-04锛堜慨椤哄簭路涓嬫媺鍒锋柊蹇呴』鍦ㄥ垪琛ㄩ《閮ㄦ墠鏈夋晥锛夛細鍘熸潵鍏?ensure_fresh
    #    锛堜笅鎷夊埛鏂帮級鍐?_to_top锛堝洖椤讹級鈥斺€斾絾涓嬫媺鍒锋柊瑕佸垪琛ㄥ湪椤堕儴鎵嶈Е鍙戯紝鍦ㄤ腑闂?swipe
    #    鍙槸鎶婂垪琛ㄥ線涓嬫粴銆佷笉瑙﹀彂鍒锋柊锛屼袱涓棤鏁堜笅鎷夊埛鏂版瘡杞櫧鐑?~20s銆?
    #    鏀规垚鍏堝洖椤讹紙鏈€鏂版秷鎭笂灞忥級鍐?ensure_fresh 妫€鏌ワ細鍛戒腑灏卞畬鍏ㄤ笉鍒枫€?
    try:
        if _to_top(actor, rounds=3):
            snap = actor.snap(force=True)
    except Exception as e:
        log.warning("鍥為《澶辫触锛堢户缁敤褰撳墠灞忥級: %r", e)
    snap = ensure_fresh(actor, db)

    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            log.warning("鏈皬鏃跺彂閫佸凡杈句笂闄?鈫?鏈疆涓嶆竻绾㈢偣锛堥伩鍏嶅皝鍙凤級")
            out["left"] = badge_chat(actor.snap())
            return out
    except Exception:
        pass

    handled = set()
    handled_sids = set()   # 宸插鐞嗙殑搴?sid锛堝簱鐩磋璺緞鐢紱涓?handled 鏄电О闆嗗悎骞惰锛?
    doubles = 0
    stall = 0          # 杩炵画鍑犳鍙屽嚮銆岃鏍囧拰绾㈢偣閮芥病鍙樺寲銆嶁啋 鍒ゅ畾鎺ㄤ笉鍔紝鎻愬墠鏀跺伐
    idle = 0           # 杩炵画鍑犳杩涗細璇濋兘鏃犻渶鍥炲 -> 鍒ゅ畾鍋囩孩鐐?
    her_stuck = 0      # 杩炵画鍑犳銆屾湯鏉℃槸濂逛絾鍙戜笉鍑恒€?> 涔熻鐔旀柇锛屽惁鍒欐棤闄愯繘鍚屼竴浜?
    interrupted = False  # 鏈疆鏄惁琚€屽簱鏈夊彉鍖栥€嶆墦鏂紙鎵撴柇 鈮?鍋囩孩鐐癸級
    t_budget = time.monotonic()   # 鐢ㄦ埛 2026-11-02锛氫竴鍒嗛挓鍐呮病杩涘睍灏辫繘涓嬩竴姝ユ祦绋?
    reuse_snap = False   # 鍙屽嚮鍒嗘敮宸叉嬁鍒版渶鏂板揩鐓?-> 涓嬩竴杞埆鍐?dump 涓€娆?

    # 馃敶馃敶 2026-11-08锛堝簱鐩磋 P0锛夛細娓呯孩鐐圭殑**鐩爣鏉ユ簮**浠庛€屽睆骞曚笂鎵剧孩鐐硅銆?
    #   鏀逛负銆屽簱閲屾煡鏈浼氳瘽銆嶃€傚師鍥狅紙瀹炴祴锛屾帰閽?L/M/N锛夛細
    #     鈶?`Row.has_dot` 渚濊禆鐨?`unread_msg_number` 鍦?dump 閲岃繛缁?4 杞?**0 涓妭鐐?*
    #        鈫?dots() 鎭掔┖ 鈫?鍘熼€昏緫銆屾病绾㈢偣灏卞弻鍑昏烦閿氱偣銆嶁啋 绌鸿浆鍒?MAX_DOUBLE 鏀跺伐銆?
    #     鈶?鍚屼竴鐬棿搴撴湁 11 涓湭璇讳細璇?/ 50 鏉℃湭璇伙紝灞忎笂 10 琛?0 涓孩鐐广€?
    #   鐜板湪锛氬簱缁?sid 娓呭崟锛?.05s锛夛紝灞忓箷鍙礋璐ｃ€屾妸杩欒鎵惧埌骞剁偣杩涘幓銆嶃€?
    #   灞忓箷绾㈢偣浠嶄繚鐣欏仛**鍏滃簳**锛堜竾涓€鏌愬ぉ res-id 鍥炴潵浜嗭紝涔熶笉浼氭紡锛夈€?
    lib_sids = _lib_unread_sids(db)
    if lib_sids:
        log.info("娓呯孩鐐圭洰鏍囨潵鑷簱锛?d 涓湭璇讳細璇濓紙灞忓箷绾㈢偣鏁?%d锛?,
                 len(lib_sids), len(dots(snap)))
    else:
        log.info("搴撴湭璇绘竻鍗曚负绌?涓嶅彲鐢?鈫?閫€鍥炲睆骞曠孩鐐瑰垽鎹紙瀹炴祴澶氬崐涔熸槸 0锛?)

    while out["entered"] < max_enter:
        if time.monotonic() - t_budget > budget_s and out["entered"] > 0:
            log.info("娓呯孩鐐瑰凡鐢?%.0fs锛?%.0fs 棰勭畻锛夆啋 鏈疆鍏堝仠锛屽墿涓嬬殑涓嬩竴杞户缁?,
                     time.monotonic() - t_budget, budget_s)
            break
        if time.monotonic() - t_budget > budget_s * 2:
            log.warning("娓呯孩鐐?%.0fs 涓€涓汉閮芥病杩涘幓 鈫?鐩存帴鏀跺伐锛堝紓甯革級",
                        time.monotonic() - t_budget)
            break
        if reuse_snap:
            reuse_snap = False
        else:
            snap = actor.snap()
        if detect(snap) != "chatlist":
            snap = to_list(actor)
            if detect(snap) != "chatlist":
                break

        todo = [r for r in dots(snap) if r.nickname not in handled]
        # 馃敶馃敶 2026-11-08锛堝簱鐩磋 P0锛夛細**搴撳垽瀹氫紭鍏堬紝灞忓箷绾㈢偣鍏滃簳**銆?
        #   鏀瑰墠锛氬彧璁?dots(snap)锛堣鍐?unread_msg_number锛夆€斺€?瀹炴祴 4/4 杞?0 涓妭鐐?
        #        鈫?todo 鎭掔┖ 鈫?璧般€屽弻鍑昏烦閿氱偣銆嶅垎鏀?鈫?绌鸿浆鍒?MAX_DOUBLE 鏀跺伐銆?
        #   鏀瑰悗锛氬厛鐢ㄥ簱閲岀殑鏈 sid 娓呭崟鏄犲皠鎴愬睆骞曡锛堝簱瀹氱洰鏍囥€佸睆骞曞畾鍧愭爣锛夛紱
        #        搴撴嬁涓嶅埌 / 灞忎笂璁ら涓嶅埌锛屾墠閫€鍥炲師绾㈢偣鍒ゆ嵁銆?
        #   鈿狅笍 MAX_DOUBLE=5 涓庛€屽彧鍙屽嚮涓嶆粦鍔ㄣ€嶆槸鐢ㄦ埛閾佸緥锛屾湰鏀瑰姩**鏈Е纰?*銆?
        _want = [s for s in lib_sids if s not in handled_sids]
        lib_pairs = _rows_for_lib(snap, db, _want, handled=handled)
        if lib_pairs:
            r = lib_pairs[0][0]
            _sid_hint = lib_pairs[0][1]
            log.info("搴撳畾鐩爣 sid=%s 鈫?灞忎笂绗?%d 琛?%r锛堝簱鍓╀綑 %d 涓湭璇伙級",
                     _sid_hint, r.center[1], r.nickname,
                     len([s for s in lib_sids if s not in handled_sids]))
        else:
            # 馃敶 2026-11-12锛圚Y-01锛夛細鏈銆岃棰嗕笉鍒般€嶇殑搴撶洰鏍囬噷锛岃澶囧簱宸叉煡涓嶅埌
            #   鐨?sid 鐩存帴鍓旈櫎锛堝菇鐏典細璇濓紝姘歌繙涓嶄細琚棰嗗埌锛岀暀鐫€姣忚疆鐧界儳锛夛紱
            #   浠嶅瓨娲讳絾鍙槸娌℃覆鏌撳埌褰撳墠灞忕殑**淇濈暀**锛堝垪琛ㄥ埛鏂板悗鑳借棰嗭級銆?
            #   handled_sids = 鏈疆宸插鐞嗚繃鐨勶紝涓嶇畻銆岃棰嗕笉鍒般€嶏紝璺宠繃涓嶅墧銆?
            _prune_dead_lib_sids(db, lib_sids, handled_sids)
            r = todo[0] if todo else None
            _sid_hint = None
        if r is None:
            b = badge_chat(snap)
            if b == 0:
                break
            # 褰撳墠灞忔病绾㈢偣浣嗚鏍囪繕鏈?-> 鍙屽嚮璺抽敋鐐癸紙鐢ㄦ埛瀹氱殑娓呯孩鐐规墜娈碉級
            if doubles >= MAX_DOUBLE:
                log.info("鍙屽嚮 %d 娆′粛娌℃壘鍒扮孩鐐癸紙瑙掓爣=%s锛夛紝鏈疆鏀惧純", doubles, b)
                break
            doubles += 1
            # 馃敶 2026-11-04锛堟彁閫熉穊ug锛夛細杩欓噷鍘熸潵鐢?len(dots(snap))锛?*鏈繃婊?* handled锛夛紝
            #   鑰屼笅闈?nd 鐢ㄧ殑鏄?*杩囨护鍚?*鐨勬暟閲?鈥斺€?鍙ｅ緞涓嶄竴鑷?鈫?灞忎笂鍙鏈夈€屽垰鍥炶繃鐨勪汉銆?
            #   鐨勭孩鐐规畫鐣欙紝before=(1,1)/after=(1,0) 鎭掍笉绛?鈫?stall 姣忔琚竻闆?鈫?
            #   鐔旀柇姘镐笉瑙﹀彂锛屽繀椤昏€楁弧 MAX_DOUBLE=5 娆★紙瀹炴祴鐧界儳 63s锛夈€?
            #   鏀规垚涓?nd 鍚屽彛寰勩€?
            before_key = (b, len([r for r in dots(snap) if r.nickname not in handled]))
            snap, pg = actor.double_tap_tab("鑱婂ぉ", expect="chatlist", settle=1.0)
            if snap is None:
                break
            nd = len([r for r in dots(snap) if r.nickname not in handled])
            nb = badge_chat(snap)
            log.info("鍙屽嚮绗?d娆?-> 瑙掓爣=%s 绾㈢偣=%d", doubles, nb, nd)
            if (nb, nd) == before_key:
                stall += 1
                if stall >= 3:
                    log.info("杩炵画 %d 娆″弻鍑绘棤杩涘睍锛堣鏍?%s 绾㈢偣=%d锛夆啋 鍒ゅ畾鎺ㄤ笉鍔紝鏈疆鏀跺伐",
                             stall, nb, nd)
                    break
            else:
                stall = 0
            # double_tap_tab 杩斿洖鐨勫氨鏄弻鍑诲悗鐨勬柊鍒楄〃蹇収 鈫?涓嬩竴杞洿鎺ョ敤瀹冿紝
            # 涓嶅啀鍦ㄥ惊鐜紑澶撮噸鏂?dump锛堢渷涓€娆?3s锛?
            reuse_snap = True
            continue

        handled.add(r.nickname)
        if _sid_hint:
            handled_sids.add(_sid_hint)

        # 鐗逛緥锛氥€屾敹鍒扮殑鏂版嫑鍛笺€嶆槸绯荤粺鑱氬悎琛岋紝鐐硅繘鍘昏繕瑕佸啀鐐逛竴娆′汉
        if "鏂版嫑鍛? in r.blob:
            log.info("閬囧埌銆屾敹鍒扮殑鏂版嫑鍛笺€嶏紝璧颁簩绾ц矾寰?)
            n = handle_greeting(actor, actor.dev, dry_run=dry_run)
            out["replied"] += n
            out["entered"] += 1
            snap = to_list(actor)
            reuse_snap = True      # to_list 宸茬粰鏂板揩鐓э紝鍒啀 dump 涓€娆?
            continue

        # 馃敶 2026-11-04锛堝厹搴曪級锛氬畼鏂?钀ラ攢鍙凤紙鍛ㄦ姤銆佹椿鍔ㄦ帹閫佺瓑锛夊湪鍒楄〃閲屼篃鏈夌孩鐐癸紝
        #    鏄电О涓嶄竴瀹氬湪 NOT_CHAT_NICKS 榛戝悕鍗曢噷銆傝繘浼氳瘽鍓嶇敤鍒楄〃琛岄瑙堟枃鏈弽鏌?
        #    sid锛岃兘鍒ゅ畾鏄畼鏂瑰彿灏辩洿鎺ヨ烦杩団€斺€斾笉杩涖€佷笉绌鸿浆銆佷笉璁″亣绾㈢偣銆?
        #    鍙嶆煡涓嶅埌锛堥瑙堟埅鏂?涓嶅敮涓€锛夊垯鎸夊師閫昏緫璧帮紝涓嶄細璇激鐪熶汉銆?
        # 馃敶 2026-11-08锛堝簱鐩磋锛夛細**搴撳凡缁忕粰浜?sid 灏辩洿鎺ョ敤**锛屼笉鍐嶅弽鏌ャ€?
        #    sid_from_row 姣忚瑕佽窇 4 鏉?SQL锛坰ession 绮剧‘/鍓嶇紑 + chatmsg 绮剧‘/鍓嶇紑锛夛紝
        #    鑰屽簱鐩磋璺緞涓?sid 鏈潵灏辨槸宸茬煡绛旀 鈥斺€?鍙嶆煡绾睘鐧界儳锛岃繕浼氬洜
        #    銆屽棷銆嶃€屾槸鐨勩€嶈繖绫荤煭鏂囨湰鎾炶溅杩斿洖 None锛堝疄娴嬭繖灏辨槸璧版參璺緞 OCR 鐨勬潵婧愶級銆?
        _sid = _sid_hint
        if _sid:
            log.debug("搴撶洿璇昏矾寰勶細sid=%s 宸茬煡锛岃烦杩囨枃鏈弽鏌?, _sid)
        else:
            try:
                _sid = flow.sid_from_row(db, r)
            except Exception as _e:
                log.debug("琛屾枃鏈弽鏌ュけ璐? %r", _e)
                _sid = None
        try:
            _sess = db.session(_sid) if _sid else None
            if _sess is not None and _sess.is_official:
                log.info("璺宠繃瀹樻柟/钀ラ攢鍙?%r锛堜笉杩涗細璇濄€佷笉璁″亣绾㈢偣锛?, r.nickname)
                reuse_snap = True  # 娌″仛浠讳綍 UI 鍔ㄤ綔锛屽垪琛ㄦ病鍙?
                continue
        except Exception as _e:
            log.debug("瀹樻柟鍙烽鍒ゅけ璐ワ紙缁х画鍘熼€昏緫锛? %r", _e)

        # 馃敶 2026-11-12锛埪?18 宸ュ崟 P1锛夛細銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶅垪琛ㄨ鏄?*鍔熻兘鍏ュ彛**锛?
        #    涓嶆槸鐪熶汉浼氳瘽銆傜偣杩涘幓鏄?LoveBellChatListActivity锛堢◢鍚庡啀鑱婂垪琛ㄩ〉锛夛紝
        #    涓嶆槸 ConversationActivity 鈫?閫氱敤銆岃繘浼氳瘽銆嶈矾寰?100% 鏍￠獙澶辫触鐧界儳銆?
        #    鐐瑰嚮鍓嶈瘑鍒烦杩囷紙reuse_snap=True锛氭病鍋氫换浣?UI 鍔ㄤ綔锛屽垪琛ㄦ病鍙橈級锛?
        #    鍙厑璁?bell 涓撶敤璺緞杩涖€傞粯璁ゅ紑锛涜 SOUL_SKIP_BELL_ROW=0 鍙叧銆?
        # 馃敶 2026-11-12锛圚Y-07锛夛細鍒ゆ嵁鏀圭敤鏁磋鏂囨湰 r.blob锛屼笉鍐嶅彧璁?r.nickname銆?
        #    r.nickname 鍦?chatlist 淇樀绉拌瘑鍒悗鎵嶅彲闈狅紱鏃╂湡甯ч噷璇ヨ鐨?name res-id
        #    缂哄け鏃?nickname 浼氶€€鍖栨垚娑堟伅棰勮锛堝銆屾湁鏂版湅鍙嬬瓑浣犲拰Ta寮€鍚璇濄€嶏級锛?
        #    姝ｅ垯鍖归厤涓嶅埌 鈫?璺宠繃澶辨晥 鈫?鐧界儳銆俠lob 鍚樀绉?棰勮+鏍囩锛岃鐩栧叏閮ㄥ舰鎬併€?
        _bell_hit = (os.environ.get("SOUL_SKIP_BELL_ROW", "1") == "1" and (
            _BELL_ROW_RE.search(str(r.blob or ""))
            or _BELL_ROW_RE.search(str(r.nickname or ""))))
        if _bell_hit:
            log.info("璺宠繃銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶈锛氬畠鏄叆鍙ｄ笉鏄細璇濓紝鍙厑璁?bell 涓撶敤璺緞杩?)
            reuse_snap = True
            continue

        log.info("杩涗細璇?%r 绾㈢偣=%s", r.nickname, r.badge)
        # 馃敶 2026-11-10锛堟樀绉扮紦瀛樼殑涓昏鏉ユ簮锛夛細
        #   娓呯孩鐐硅繖鏉¤矾**瀹氫綅鏈€鍙潬**锛堝簱瀹?sid + 灞忎笂琛岋紝100% 鑳借繘锛夛紝
        #   鑰屼笖杩涗箣鍓嶅睆骞曚笂鏈夌湡瀹炴樀绉般€傚師鏉ュ彧鏈?pendingq 鎴愬姛鍚庢墠 remember_nick锛?
        #   鑰?pendingq 鎭版伆鏄渶缂烘樀绉扮殑閭ｆ潯璺?鈥斺€?褰㈡垚銆岃秺缂鸿秺琛ヤ笉涓娿€嶇殑姝诲惊鐜€?
        #   杩欓噷姣忚繘涓€涓汉灏辫惤鐩樹竴涓?sid鈫掓樀绉帮紝pendingq 涓嬩竴杞氨鑳界敤鏄电О鐩存帴瀹氫綅銆?
        try:
            from brain.pendingq import remember_nick as _RN
            if _sid:
                _RN(_sid, r.nickname)
        except Exception as _e_rn:
            log.debug("璁版樀绉板け璐ワ紙涓嶅奖鍝嶈繘浼氳瘽锛? %r", _e_rn)
        # 馃敶 2026-11-03 淇 P0锛堢┖鐑ф牴鍥狅級锛氳繘浼氳瘽閭ｄ竴涓?App 浼?*鏍囧凡璇诲苟鍐欏簱**銆?
        #    杩欓噷涓嶅厛澹版槑銆岃繖娈靛啓鍏ユ槸鎴戣嚜宸遍€犳垚鐨勩€嶏紝寰幆鏈熬鐨?_W.urgent() 浼?
        #    鎶婅嚜宸辨墦鏂?鈫?缁熻鎴愩€岃繘 1 浜?/ 鍥?0 鏉°€嶁啋 鍏滃簳鍐嶅垽銆屽亣绾㈢偣銆嶃€?
        #    瀹炴祴涓€澶?48 娆′腑鏂€?2 娆¤鍒ゃ€傜獥鍙?20s 瑕嗙洊杩涘叆+鍒ゅ畾+鍑鸿瘽銆?
        try:
            from data import watch as _W0
            _W0.mark_self_write(20.0)
        except Exception:
            pass
        # 鍗曚汉寮傚父涓嶈兘涓鏁磋疆娓呮壂锛堝惁鍒欐湰杞墿浣欑孩鐐瑰叏鏀惧純锛?
        try:
            res = flow.handle_one(actor, db, r, dry_run=dry_run)
        except Exception as e:
            log.warning("[%s] 杩涗細璇濆鐞嗗紓甯革紙璺宠繃姝や汉锛岀户缁湰杞級: %r", r.nickname, e)
            out["entered"] += 1
            try:
                actor.hand.back(settle=1.0)
            except Exception:
                pass
            continue
        out["results"].append(res)
        # 璁℃暟蹇呴』鍦ㄣ€屽彲鑳?break 鐨勬鏌ャ€嶄箣鍓?鈥斺€?鍚﹀垯涓柇鏃朵汉浼氭紡璁?
        # 锛堝疄娴嬫棩蹇楀嚭鐜般€岃繘 0 浜恒€嶄絾瀹為檯杩涗簡骞跺洖浜嗘秷鎭級
        out["entered"] += 1
        if res.sent or (dry_run and res.reply):
            out["replied"] += 1
            idle = 0
            her_stuck = 0
        else:
            # 馃敶 2026-11-02 瀹炴祴锛歎I 鏍戦噷鐨勩€岀孩鐐广€嶄細璇垽锛堟煇琛岀殑瑁呴グ FrameLayout
            #    琚綋鎴愮孩鐐癸級锛岃繘浼氳瘽鍚庡彂鐜版渶鍚庝竴鏉℃槸鎴戝彂鐨?鈫?浠€涔堥兘娌″彂灏遍€€鍑恒€?
            #    瑙掓爣鏄?0 鍗存瘡杞?23s 绌鸿浆 47 杞€傝繖閲岃繛缁?2 娆＄┖杞氨鍒ゃ€屽亣绾㈢偣銆嶏紝
            #    杩炲悓鍐峰嵈 15 鍒嗛挓锛屼氦缁?pendingq锛堟煡搴擄級缁х画鍏滃簳锛屼笉浼氭紡娑堟伅銆?
            # 馃敶 2026-11-03锛氭湯鏉℃槸銆屽ス銆嶅嵈娌″彂鍑鸿瘽 鈥斺€?閭ｄ笉鏄亣绾㈢偣锛屾槸鐪熉峰緟鍥炪€?
            #    瀹炴祴 11-02 20:10 / 20:17 / 11-03 澶滈棿 61 娆★細濂瑰彂鏉ユ秷鎭?鈫?杩涗細璇濆嵆宸茶銆?
            #    瑙掓爣褰掗浂 鈫?绋嬪簭鍒ゃ€屾渶鍚庝竴鏉℃槸鎴戝彂鐨勩€嶆病鍙?鈫?璁版垚鍋囩孩鐐?鈫?鍐峰嵈 15 鍒嗛挓 鈫?婕忓洖銆?
            if getattr(res, "side", "?") == "her":
                her_stuck += 1
                log.warning("[%s] 鏈潯鏄ス浣嗘病鍙戝嚭璇濓紙绗?%d 娆★級鈫?涓嶅垽鍋囩孩鐐癸紝鐣欑粰宸茶鏈洖",
                            getattr(res, "nick", "?") or "?", her_stuck)
                if her_stuck >= 3:
                    log.warning("杩炵画 %d 娆°€屾湯鏉℃槸濂逛絾鍙戜笉鍑恒€嶁啋 鏈疆鍏堝仠锛屼氦缁欏凡璇绘湭鍥?,
                                her_stuck)
                    break
            else:
                idle += 1
                if idle >= 2:
                    _FAKE_DOT["until"] = time.time() + FAKE_DOT_COOL_S
                    log.warning("杩炵画 %d 娆¤繘浼氳瘽閮芥棤闇€鍥炲 鈫?鍒ゅ畾鍋囩孩鐐癸紝"
                                "娓呯孩鐐瑰喎鍗?%.0f 鍒嗛挓", idle, FAKE_DOT_COOL_S / 60.0)
                    break
        if res.err:
            log.warning("[%s] %s", res.nick, res.err)

        # 馃敶 2026-11-04锛堢敤鎴峰彛寰劼疯繛缁竻绾㈢偣锛夛細鍘熸潵涓€鏈夊簱鍙樺寲灏?break锛屽洖鍘?
        #    閲嶆柊 to_list 鍥為《 + ensure_fresh锛堟瘡杞櫧鐑?20~30s 鍥哄畾寮€閿€锛夛紝瀹為檯姣忚疆
        #    鍙兘杩?1~2 浜恒€傜孩鐐瑰惊鐜鐞嗙殑灏辨槸鏈€鏂版秷鎭紙鏂版秷鎭繀鐒跺甫绾㈢偣锛夛紝缁х画鍦?
        #    鏈惊鐜噷 snap 灏辫兘鐪嬪埌鏂扮孩鐐硅 鈥斺€?涓嶅繀 break 鍥炲幓閲嶆潵銆?
        #    interrupted 浠嶇疆 True锛堜緵涓嬮潰銆屽埆璇垽鍋囩孩鐐广€嶇敤锛夛紝鍙槸涓嶅啀 break銆?
        try:
            from data import watch as _W
            if _W.urgent():
                interrupted = True
                log.info("鈿?搴撴湁鍙樺寲锛堝彲鑳芥柊娑堟伅锛夆啋 缁х画鏈睆娓呮壂锛堟柊绾㈢偣涓嬩竴鍦堝彲瑙侊級")
                _W.consume()
        except Exception:
            pass

        # 馃敂 鏃ф灦鏋勯搧寰嬨€屾尅璺簡涔熻鍏堝閬囬搩銆嶏細姣忓洖瀹屼竴涓汉灏辩瀯涓€鐪奸搩锛?
        #    鏈夊氨绔嬪埢鎻掗槦澶勭悊锛堜竴杞洖 5 涓汉瑕?80s锛岄搩鍙兘涓€斿脊鍑烘潵锛夈€?
        try:
            from brain import bell as _BELL
            _dev = dev or actor.dev
            if _BELL.is_bell(actor.snap(force=True), dev=_dev):
                log.info("鈿?鍥炲閫斾腑鏉ヤ簡濂囬亣閾?鈫?涓柇娓呮壂鍏堝鐞?)
                _ok, _why = _BELL.handle(actor, _dev)
                log.info("鈿?閾冨鐞?ok=%s %s", _ok, _why)
                snap = to_list(actor)
                continue
        except Exception as e:
            log.warning("杞唴閾冩鏌ュ紓甯革紙缁х画娓呮壂锛? %r", e)

        snap = to_list(actor)
        time.sleep(0.3)

    snap = actor.snap()
    out["left"] = badge_chat(snap) if detect(snap) == "chatlist" else None
    # 馃敶 2026-11-08锛堟敼鍔?4锛氱粰 daemon 涓€涓€岃鍥炰汉鏁般€嶆寚鏍囷級
    #   鐢ㄦ埛瑕佽兘涓€鐪肩湅鍑恒€岀幇鍦ㄦ湁 27 涓汉鍦ㄧ瓑鎴戝洖銆嶃€傚簱鍒ゅ畾锛屼笉渚濊禆灞忓箷銆?
    #   鏀捐繘 out 閲岃璋冪敤鏂癸紙daemon锛夌洿鎺ュ彇鐢紝鍚屾椂鎵撲竴琛屾棩蹇椼€?
    # 馃敶 2026-11-12锛圚Y-04锛夛細sweep 缁撴潫鏃ュ織鐨?count_pending 鍘熸潵**娌′紶 max_age_h**
    #   涓旂敤榛樿 real_total=True锛? 澶╃獥鍙?+ 鍚凡鍥?鍐峰嵈锛夆啋 铏氶珮 鈫?鍋囩孩鐐瑰厹搴?
    #   `_pend <= 0` 鍑犱箮涓嶆垚绔嬨€傛敼浼?real_total=False + max_age_h=STALE_GIVEUP_H锛?
    #   涓庡€欓€夐槦鍒楀悓涓€鍙ｅ緞锛堝彧鏁般€屾湰杞湡鑳藉鐞嗐€嶇殑锛夛紝鍏滃簳鎵嶈兘姝ｇ‘鐢熸晥銆?
    try:
        from brain import pendingq as _PQG
        _max_age = _PQG.STALE_GIVEUP_H
    except Exception:
        _max_age = None
    out["pending"] = count_pending(db, real_total=False, max_age_h=_max_age)
    log.info("娓呯孩鐐圭粨鏉燂細杩?%d 浜?/ 鍥?%d 鏉?/ 鍓╀綑瑙掓爣=%s / %s",
             out["entered"], out["replied"], out["left"], pending_summary(db))

    # 馃敶 鍏滃簳鏀舵暃锛氳繘浜嗕汉鍗翠竴鏉℃病鍙戙€佽鏍囪繕鏄?0 鈫?UI 鏍戦噷鐨勩€岀孩鐐广€嶆槸璇垽
    #    锛堝疄娴嬨€岀灛闂淬€嶈繖绫诲姛鑳藉叆鍙ｃ€佹垨瑁呴グ FrameLayout 琚綋鎴愮孩鐐癸級銆?
    #    涓嶈鍐峰嵈鐨勮瘽姣忚疆 23s 鐧借浆锛岀敤鎴锋槑纭姹傘€屼笉瑕佷竴鐩村仠鍦ㄩ偅閲屼笉鍔ㄣ€嶃€?
    # 馃敶 2026-11-03 淇 P2锛氭鍏滃簳鍘熷厛浼氭妸銆屾湯鏉℃槸濂逛絾鍙戜笉鍑恒€嶏紙鐪熷緟鍥烇紝her_stuck>0锛?
    #    涔熷垽鎴愬亣绾㈢偣 鈫?鍐峰嵈 15 鍒嗛挓 鈫?婕忓洖銆傚姞 her_stuck==0 鏉′欢锛氬彧鏈夊叏绋?
    #    銆屾湯鏉℃槸鎴?鏃犻渶鍥炲銆嶆墠绠楀亣绾㈢偣锛涙湁鐪熷緟鍥炲氨浜ょ粰宸茶鏈洖鍏滃簳銆?
    # 馃敶 2026-11-03 淇锛氳鏂版秷鎭墦鏂?鈮?鍋囩孩鐐广€傚師鏉ュ彧瑕併€岃繘浜嗕汉銆佹病鍙戣瘽銆佽鏍囧綊闆躲€?
    #    灏卞垽鍋囩孩鐐瑰苟鍐峰嵈 15 鍒嗛挓锛涜€?琚墦鏂?姝ｅソ钀借繘杩欎釜鍒嗘敮锛堝疄娴?32 娆?鏃ワ級銆?
    # 馃敶馃敶 2026-11-08锛堝簱鐩磋 P0锛屽繀椤诲悓鏃朵慨锛夛細涓婇潰 `(out["left"] or 0) <= 0` 鐢ㄧ殑鏄?
    #    搴曟爮銆岃亰澶┿€嶈鏍?鈥斺€?瀹炴祴璇ヨ鏍?*鎭掍负 0**锛坙ead 澶嶇幇锛歜adges={'骞垮満': 7}锛?
    #    鑱婂ぉ tab 瀹屽叏鏃犺鏍囷級銆備簬鏄€岃繘浜嗕汉銆佹病鍙戣瘽銆嶅繀鐒惰鍒ゃ€屽亣绾㈢偣銆嶁啋 鍐峰嵈 15 鍒嗛挓
    #    鈫?鑰岃繖 15 鍒嗛挓閲屽簱閲屽彲鑳借繕鏈?27 涓汉鍦ㄧ瓑銆傚姞搴撳垽瀹氾細搴撹杩樻湁浜虹瓑锛屽氨**涓嶈**
    #    鍒ゅ亣绾㈢偣锛堝喎鍗翠細鎶婄湡寰呭洖涓€璧峰喕浣忥級銆?
    _pend = out.get("pending", -1)
    if (out["entered"] > 0 and out["replied"] == 0 and her_stuck == 0
            and not interrupted and (out["left"] or 0) <= 0
            and _pend <= 0):
        _FAKE_DOT["until"] = time.time() + FAKE_DOT_COOL_S
        log.warning("杩涗簡 %d 浜轰竴鏉℃病鍙戙€佽鏍?0銆佸簱鏃犲緟鍥?鈫?鍒ゅ畾鍋囩孩鐐癸紝娓呯孩鐐瑰喎鍗?%.0f 鍒嗛挓",
                    out["entered"], FAKE_DOT_COOL_S / 60.0)
    elif out["entered"] > 0 and out["replied"] == 0 and _pend > 0:
        log.info("杩涗簡 %d 浜烘病鍙戣瘽锛屼絾搴撻噷杩樻湁 %d 涓緟鍥?鈫?**涓嶅垽鍋囩孩鐐?*锛堜笉鍐峰嵈锛?,
                 out["entered"], _pend)
    return out


# 鍋囩孩鐐瑰喎鍗达紙杩炵画杩涗細璇濋兘鏃犻渶鍥炲 鈫?UI 鏍戦噷鐨勩€岀孩鐐广€嶆槸璇垽锛?
_FAKE_DOT = {"until": 0.0}

FAKE_DOT_COOL_S = 900          # 鍐峰嵈 15 鍒嗛挓


def fake_dot_cooling():
    """鏄惁杩樺湪銆屽亣绾㈢偣銆嶅喎鍗存湡銆?""
    return time.time() < _FAKE_DOT["until"]


def has_dot_now(actor, db=None):
    """褰撳墠鏄惁杩樻湁鑱婂ぉ绾㈢偣锛堢敤浜庛€屾湁绾㈢偣灏变笉鍖归厤銆嶇殑闂革級銆?

    馃敶 2026-11-03 淇 P0锛氬喎鍗村師鏉ュ彧鍦?`瑙掓爣<=0` 鏃剁敓鏁堬紝鑰?瑙掓爣铏氶珮"
      锛圓pp 渚х疮璁℃湭璇伙紝鏈彿闀挎湡鏈夛級鎭版伆鏄渶甯歌鐨勬儏褰?鈬?鍐峰嵈褰㈠悓铏氳锛?
      姣忚疆缁х画鍙屽嚮 5 娆℃壘涓嶅瓨鍦ㄧ殑绾㈢偣銆傜幇鍦ㄥ喎鍗存湡鍐?*鍙褰撳墠灞忕湡瀹炶鍐呯孩鐐?*锛?
      鐪嬩笉瑙佸氨浜ょ粰 pendingq锛堟寜搴撳垽"鏈潯鏄ス"锛屼笉渚濊禆绾㈢偣锛夛紝涓嶄細婕忔秷鎭€?

    馃敶馃敶 2026-11-08 淇 P0锛堝簱鐩磋锛屽疄娴嬪鐜帮級锛?
      銆愭敼鍓嶃€慲d = len(dots(snap))` 鈥斺€?鑰岃鍐呯孩鐐?res-id `unread_msg_number`
        鍦?dump 閲岃繛缁?4 杞?**0 涓妭鐐?*锛堝叏灞忓彧鏈夊簳鏍?me_red_point / red_text /
        square_red_point锛夛紝涓斿簳鏍忋€岃亰澶┿€嶈鏍囦篃鎭掍负 0锛坙ead 瀹炴祴 badges={'骞垮満':7}锛夈€?
        鈬?鏈嚱鏁?*鎭掕繑鍥?(False, 0, 0)** = 銆屾病鏈夌孩鐐广€嶁啋 涓婂眰浠ヤ负娓呭畬浜嗐€?
        瀹炴祴鍚屼竴鐬棿搴撻噷杩樻湁 11 涓湭璇讳細璇?/ 4 涓繀椤诲洖 / 23 涓凡璇绘湭鍥炪€?
      銆愭敼鍚庛€戜紶鍏?db 鏃朵互**搴?*涓哄噯锛坄data.pending.count_pending`锛?.05s锛夛細
        鏈夌湡浜哄緟鍥炲氨绠楁湁绾㈢偣銆俤b 涓?None 鏃堕€€鍥炴棫琛屼负锛堝睆骞曞垽鎹級淇濇寔鍏煎銆?
      銆愬吋瀹广€戠鍚嶅彧鍔犱簡鍙€夊弬鏁?`db=None`锛屾墍鏈夌幇鏈夎皟鐢ㄧ偣 `has_dot_now(actor)` 涓嶅彉銆?

    杩斿洖 (鏄惁鏈夌孩鐐? bool, 瑙掓爣: int, 灞忓箷绾㈢偣鏁? int)銆?
    """
    snap = actor.snap()
    if detect(snap) != "chatlist":
        snap = to_list(actor)
    b = badge_chat(snap)
    d = len(dots(snap))
    # ---- 搴撳垽瀹氫紭鍏堬紙搴撲笉鍙敤/娌′紶 db 鎵嶇湅灞忓箷锛?---
    # 馃敶馃敶 2026-11-08 03:50锛圥0 姝婚攣路鏈€鍚庝竴澶勬紡缃戯級
    #
    #   鏀瑰墠锛歚count_pending(db)` 鐢ㄧ殑鏄?**7 澶╃獥鍙?+ 鍚喎鍗?+ 鍚凡鍥?*锛坮eal_total=True锛夛紝
    #        瀹炴祴鎭掍负 63~65 浜恒€傝€岀湡姝ｈ兘鍥炵殑鍊欓€夛紙candidates 鎸?STALE_GIVEUP_H=24h 娣樻卑鍚庯級
    #        鍙墿 6 涓€備袱杈瑰彛寰勫樊 10 鍊?鈬?杩欏嚱鏁版亽杩斿洖 True銆?
    #
    #   鍚庢灉锛堟棩蹇楀疄璇侊紝杩炵画鍖归厤鍒氫慨濂藉張琚畠鎸′綇锛夛細
    #     `鈿?杩炵画鍖归厤閫斾腑鍑虹幇绾㈢偣 鈫?绔嬪埢鍋滀笅鍥炲幓鍥炲锛堝凡鍖归厤 0 涓級`
    #     鈥斺€?姣忚疆鍖归厤鍒氳捣姝ュ氨琚墦鏂紝涓€娆￠兘娌″尮閰嶆垚銆?
    #
    #   鏀瑰悗锛氫笌鍊欓€夐槦鍒楀悓涓€鍙ｅ緞锛堝彧鏁?24h 鍐呫€佷笉鍚喎鍗?宸插洖鐨勭湡浜猴級锛?
    #        杩欐牱銆屾湁浜虹湡鐨勫湪绛夋垜鍥炪€嶆墠鎸″尮閰嶏紝鍍靛案绉帇涓嶅啀鎸°€?
    _max_age = None
    try:
        from brain import pendingq as _PQG
        _max_age = _PQG.STALE_GIVEUP_H
    except Exception:
        _max_age = None
    try:
        # 馃敶 2026-11-12锛圚Y-03锛夛細count_pending 榛樿 real_total=True锛堝惈宸插洖杩?鍐峰嵈锛?
        #   鈫?鎭?>0 鈫?涓婂眰銆屾湁绾㈢偣灏变笉鍖归厤銆嶆案杩滄尅鍖归厤銆傛敼 real_total=False锛?
        #   鍙暟鏈疆鐪熻兘澶勭悊鐨勶紙涓庡€欓€夐槦鍒楀悓鍙ｅ緞锛夛紝鍍靛案绉帇涓嶅啀鎸″尮閰嶃€?
        n_lib = count_pending(db, real_total=False, max_age_h=_max_age) if db is not None else -1
    except TypeError:
        # 鍏煎鏃х鍚嶏紙count_pending(db) 娌℃湁 max_age_h / real_total锛?
        # 馃敶 2026-11-12锛團-05锛夛細鍥為€€鍒嗘敮涔熸樉寮忎紶 real_total=False + 绐楀彛锛?
        #   鍚﹀垯榛樿 real_total=True + 7 澶╃獥鍙?鈫?铏氶珮銆屾亽鏈夌孩鐐广€嶁啋 鍥炲埌鍘嗗彶姝婚攣銆?
        n_lib = (count_pending(db, real_total=False, max_age_h=_max_age)
                 if db is not None else -1)
    if n_lib >= 0:
        if n_lib > 0:
            # 搴撻噷鏈夌湡浜哄緟鍥?鈫?涓€瀹氥€屾湁绾㈢偣銆嶏紝涓嶇灞忓箷娓叉煋鎴愪粈涔堟牱
            return True, b, d
        # 搴撹 0 涓汉绛?鈫?鍗充娇搴曟爮瑙掓爣铏氶珮涔熶笉绠楋紙瑙掓爣鏄?App 渚х疮璁″€硷紝浼氳櫄楂橈級
        return False, b, d
    # ---- 搴撲笉鍙敤锛氶€€鍥炲睆骞曞垽鎹紙瀹炴祴澶氬崐澶辨晥锛屼絾鎬绘瘮宕╁ソ锛?---
    if fake_dot_cooling():
        return d > 0, b, d
    return (b > 0 or d > 0), b, d
