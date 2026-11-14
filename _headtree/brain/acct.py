# -*- coding: utf-8 -*-
"""璐﹀彿杞浆锛氭Θ骞查厤棰?鎴?寮哄埗 8 灏忔椂鍒囧彿銆?

鏃у彛寰勶紙soul_daemon 2026-10-05 鎷嶆澘锛岃繖閲屽師鏍峰鍒伙級锛?

  路 鍒囧彿鍓嶆彁 = **涓夋潯鍚屾椂鎴愮珛**锛屼笖鎸佺画 `dry_hold_min`(30) 鍒嗛挓锛?
      鈶?鏃犱汉鍙亰锛堢湡寰呭洖 = 0锛?
      鈶?娌′汉鍙敜閱掞紙鍞ら啋姹?= 0锛屾垨姹犻噷鏈変汉浣嗛兘杩樺湪鍐峰嵈 鈥斺€?鍏抽敭鏄€屽綋涓嬭蛋涓嶈蛋寰楅€氥€嶏級
      鈶?娌℃湁鍖归厤娆℃暟锛堜粖鏃ュ墿浣?= 0锛?
  路 杩炵画鍦ㄧ嚎 鈮?8h 鈫?**寮哄埗鍒囧彿**锛堜笉绛変笁鏉′欢锛?
  路 鍒囪蛋鍚?4h 鍐呬笉寰楀垏鍥炶鍙凤紱涓ゆ鍒囧彿闂撮殧 鈮?30min
  路 鍙湁 2 涓彿 鈫?鐩爣鍗炽€屽彟涓€涓€嶏紱鏃犲彿鍙垏鍒欏師鍦颁笉鍔紙瀹佸彲绛夛紝缁濅笉涔卞垏锛?

鐢ㄦ埛 2026-11-02 琛ュ厖锛氥€岄櫎闈炴棤浜哄彲鑱婏紝涓嶇劧涓嶈鍑虹幇绌虹儳 / 闀挎椂闂寸瓑寰呫€嶃€?
  鈫?涓夋潯浠惰瘎浼版槸**姣忚疆閮藉仛**锛堝緢渚垮疁锛氬緟鍥?鍞ら啋姹犻兘鏌ユ湰鍦板簱锛夛紝
    鍙湁绗?鈶?鏉¤寮€ UI 璇绘槦鐞冮〉锛岄檺棰?10 鍒嗛挓銆?
"""
import os
import time

from core.log import get_logger
from core.paths import STATE, SOUL_PKG

log = get_logger("brain.acct")

QUOTA_CHECK_EVERY = 600      # 璇诲尮閰嶆鏁帮紙瑕佸紑鏄熺悆椤碉級鏈€瀵?10 鍒嗛挓涓€娆?
FORCE_SWITCH_H = 8.0         # 杩炵画鍦ㄧ嚎瓒呰繃 8h 寮哄埗鍒囧彿
FORCE_HARD_H = 10.0          # 纭《锛氳秴杩?10h 涓嶇鏈夋病鏈夌孩鐐归兘鍒囷紙璐﹀彿椋庢帶浼樺厛锛?
                             # 涓轰粈涔堣鏈夛細鍒囧彿宸蹭笅绉诲埌銆屽洖澶嶄箣鍚庛€嶏紝鑰岀孩鐐瑰嚑涔庢案杩滄竻涓嶅畬
                             # 鈫?鑻ヤ互绾㈢偣涓哄敮涓€鏉′欢锛岃处鍙蜂細涓€鐩村湪绾夸笉鍒囷紙瀹炴祴 42h 鏈垏锛夈€?
DRY_HOLD_MIN = 30            # 涓夋潯浠舵寔缁?30 鍒嗛挓鎵嶅垏
# 鈿狅笍 2026-11-08锛歋WITCH_COOL_H **娌℃湁瀹炵幇**銆傚叏浠撳彧鏈夎繖閲屽畾涔?+ daemon.py:401 鐨?
#   涓€鍙ユ敞閲婂湪寮曠敤瀹冿紝娌℃湁浠讳綍浠ｇ爜璇诲畠鏉ュ仛銆屽垏璧板悗 4h 鍐呬笉鍒囧洖璇ュ彿銆嶇殑鍒ゅ畾銆?
#   淇濈暀绗﹀彿鏄洜涓?daemon.py 鐨勬敞閲婇潬瀹冭鏄庤璁℃剰鍥撅紱鐪熻鍋氬喎鍗磋鏄惧紡瀹炵幇骞舵帴绾匡紝
#   鍒互涓烘敼杩欎釜鏁板瓧灏变細鐢熸晥銆?
SWITCH_COOL_H = 4.0          # 璁捐鍊硷細鍒囪蛋鍚?4h 鍐呬笉鍒囧洖璇ュ彿锛堟湭鎺ョ嚎锛?
MIN_GAP_MIN = 10             # 涓ゆ鍒囧彿鑷冲皯闂撮殧 10 鍒嗛挓锛堢敤鎴?2026-11-02 鎷嶆澘閫?2锛?
                             # 涓€涓彿寰?5 鍒嗛挓鈫掑垏鈫掑啀寰?5 鍒嗛挓锛岃疆杞揩浣嗕笉鑷充簬楂橀鍒囧彿鎾炶溅锛?
# 馃敶 鐢ㄦ埛 2026-11-02锛氥€屾暣涓祦绋嬭蛋瀹屼箣鍚?5 鍒嗛挓娌℃湁鏂版秷鎭氨鍒囧彿鍚с€?
#    杩欐槸"姒ㄥ共"鐨勫彟涓€绉嶈〃杈?鈥斺€?杩欎釜鍙峰凡缁忔病鏈轰細浜嗭紝鎹竴涓户缁壘銆?
# 馃敶馃敶 2026-11-08锛氫笅闈㈣繖琛屽師鏉ュ啓 `IDLE_SWITCH_MIN = 5`锛岀劧鍚庡湪鏂囦欢绗?220 琛?
#   鍙堣 `IDLE_SWITCH_MIN = float(os.environ.get("SOUL_IDLE_SWITCH_MIN","30") or 30)`
#   鏁翠釜瑕嗙洊鎺?鈥斺€?妯″潡绾т唬鐮侊紝import 瀹屽氨鏄?30銆備篃灏辨槸璇磋繖閲岀殑 5 **浠庢潵娌℃湁鐢熸晥杩?*锛?
#   鑰屾敼杩欎竴琛岀殑浜轰細浠ヤ负鏀逛簡锛堥櫡闃憋級銆傜幇鍦ㄥ垹鎺?5锛屽敮涓€鐨勫畾涔夌暀鍦ㄧ 220 琛岋紙鍙
#   鐜鍙橀噺瑕嗙洊锛夈€傝璋冪┖闂插垏鍙烽槇鍊硷細璁?SOUL_IDLE_SWITCH_MIN锛屽埆鏀硅繖閲屻€?
# 馃敶 2026-11-04锛堥棴鐜級锛?*鍒囧彿灏濊瘯澶辫触瑕侀€€閬?*銆?
#   瀹炴祴 02:06~02:12 寮哄埗鍒囧彿杩炵画澶辫触锛堢偣鍑诲悗 uid 娌″彉锛夛紝鍥犱负鎴愬姛鎵嶆洿鏂?last_switch锛?
#   澶辫触涓嶇暀鐥?鈫?涓嬩竴杞張閲嶅紑璐﹀彿闈㈡澘銆佺偣琛屻€侀噸鍚?App锛屾瘡娆?30~60s 鍏ㄧ櫧鐑э紝
#   杩樻妸璁惧鍗犵潃璁╁洖澶嶆洿鎱€傜幇鍦ㄥけ璐ヤ篃璁版椂闂达紝閫€閬?30 鍒嗛挓鍐呬笉鍐嶈瘯銆?
FORCE_RETRY_GAP_MIN = 30

# 馃敶 2026-11-10锛圥0 淇锛夛細涓€娆″垏鍙锋渶澶氱偣鍑犱釜鍊欓€夎处鍙疯銆?
#   鍘熶唬鐮佹槸纭紪鐮?`for attempt in range(2)` 鈥斺€?闈㈡澘閲屾湁 3 涓彿鏃剁 3 涓?*姘歌繙鐐逛笉鍒?*銆?
#   澶滈棿瀹炴祴锛?1-09 22:00~11-10 07:12锛夛細06:27 / 07:01 涓ゆ寮哄埗鍒囧彿锛屾棩蹇楅兘鏄?
#     銆岄潰鏉垮€欓€夎处鍙疯 3 涓€嶁啋銆屽皾璇曞垏鍒扮 1/2 涓€嶁啋銆屽垏瀹?uid 娌″彉銆嶁啋 閫€閬?30 鍒嗛挓銆?
#   涓€鏅氱┖杞?4 娆★紝鍚屼竴璐﹀彿纭墰 9.8h锛堣秺杩?8h 寮哄埗闃堝€?4 娆★級銆備笂闄?6 鍙槸闃插憜銆?
SWITCH_MAX_TRY = 6

SWITCH_FILE = STATE / "switch_book.json"


def _switch_backoff_left():
    """涓婃鍒囧彿**灏濊瘯澶辫触**鍚庣殑鍓╀綑閫€閬垮垎閽燂紙0 = 涓嶅湪閫€閬匡級銆?""
    try:
        d = _load()
        t = float(d.get("last_switch_try") or 0)
        if not t:
            return 0.0
        return max(0.0, FORCE_RETRY_GAP_MIN - (time.time() - t) / 60.0)
    except Exception:
        return 0.0


# ---------------- 鍒囧彿鍙拌处 ----------------
def _load():
    import json
    try:
        return json.loads(SWITCH_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _save(d):
    import json
    try:
        SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        SWITCH_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        log.warning("淇濆瓨鍒囧彿鍙拌处澶辫触: %r", e)


def online_hours():
    """鏈处鍙疯繛缁湪绾挎椂闀匡紙浠庣涓€娆¤鍒板畠鐨勬椂闂寸畻锛夈€?""
    d = _load()
    return (time.time() - float(d.get("online_since") or time.time())) / 3600.0


def note_online(uid):
    """璁板綍褰撳墠璐﹀彿鐨勫湪绾胯捣鐐癸紙鎹㈠彿鏃舵竻闆堕噸绠楋級銆?""
    d = _load()
    if str(d.get("cur_uid") or "") != str(uid):
        d["cur_uid"] = str(uid)
        d["online_since"] = time.time()
        _save(d)
        log.info("璐﹀彿 %s 鍦ㄧ嚎璁℃椂寮€濮?, uid)


def last_switch_ago_min():
    d = _load()
    ts = float(d.get("last_switch") or 0)
    return (time.time() - ts) / 60.0 if ts else 1e9


# ---------------- 涓夋潯浠惰瘎浼?----------------
def read_quota(actor):
    """璇绘槦鐞冮〉**鐏甸瓊鍖归厤**鍗＄墖鐨勩€屼粖鏃ュ墿浣?N 娆°€嶃€傝繑鍥?(鍓╀綑, 鏄惁璇诲埌)銆?

    馃敶 2026-11-08 21:3x锛堝垏鍙疯鍗℃鐨勭湡鏍瑰洜锛屽疄娴嬫埅鍥?+ UI 鏍戯級锛?
      鏄熺悆椤电幇鍦ㄦ槸**涓ゅ紶鍗″苟鎺?*锛?
        宸︼細鐏甸瓊鍖归厤 / 銆岀珛鍗冲鎵炬噦浣犵殑浜恒€嶏紙App 鏀圭増鍚?*涓嶅啀鏄剧ず娆℃暟**锛?
        鍙筹細璇煶鍖归厤 / 銆屼粖鏃ュ墿浣?娆°€?
      鏃у疄鐜版妸鏁撮〉鏂囨湰鎷艰捣鏉ユ壘銆屽墿浣?N 娆°€嶏紝鎶撳埌鐨勬槸**璇煶鍖归厤**鐨?3锛?
      浜庢槸 preflight 涓€鐩存姤銆屼粖鏃ヨ繕鍓?3 娆″尮閰嶃€嶁啋 姘镐笉鍒囧彿锛?
      鑰?daemon 渚х殑璁板綍鏄€屼粖鏃ュ尮閰嶉搴﹀凡鐢ㄥ畬銆嶃€備袱杈规墦鏋讹紝浜哄崱鍦ㄥ悓涓€涓彿涓娿€?
      淇硶锛氬彧鍦?*宸﹀崐杈癸紙鐏甸瓊鍖归厤鍗＄墖锛?*閲屾壘娆℃暟锛涙壘涓嶅埌灏辫€佸疄杩斿洖銆岃涓嶅埌銆嶃€?
    """
    from brain import nav

    snap, pg = nav.to_tab(actor, "鏄熺悆")
    if pg != "planet":
        return None, False
    import re

    # 鐏甸瓊鍖归厤鍗＄墖鐨勫彸杈圭晫锛氱敤鏍囬鑺傜偣鐨勫嚑浣曞畾锛屽畾涓嶅埌灏卞彇灞忓箷宸﹀崐
    left_max = 450.0
    for n in snap.nodes:
        if n.visible and (n.text or "").strip() == "鐏甸瓊鍖归厤":
            left_max = (n.bounds[0] + n.bounds[2]) / 2.0 + 60
            break

    for n in snap.nodes:
        if not n.visible:
            continue
        t = (n.text or "").strip()
        if not t or n.bounds[0] >= left_max:
            continue
        m = re.search(r"鍓╀綑\s*(\d+)\s*娆?, t)
        if m:
            return int(m.group(1)), True
    for n in snap.nodes:
        if not n.visible or n.bounds[0] >= left_max:
            continue
        t = (n.text or "").strip()
        if "娆℃暟宸茬敤瀹? in t or "娆℃暟鐢ㄥ畬" in t:
            return 0, True
    return None, False


def evaluate(actor, db, st, force_quota=False):
    """涓夋潯浠惰瘎浼般€傝繑鍥?(should, why)銆?

    鍙锛屼笉鍋氫换浣曞啓鎿嶄綔锛涜涓嶅埌鐨勪竴寰嬪綋銆屾湭鐭?-> 涓嶅垏銆嶏紙鏃т唬鐮佽俯杩囷細
    璇诲簱澶辫触琚綋鎴?姹犵┖浜?鈫?璇垏鍙凤級銆?
    """
    now = time.time()

    # 鈶?鏃犱汉鍙亰
    try:
        pend = db.pending()
        real = [p for p in pend if not p[0].is_official]
        if real:
            return False, "鏈変汉鍙亰(%d)" % len(real)
    except Exception as e:
        return False, "pending 鎺㈡祴澶辫触锛堟湭鐭ワ級: %r" % e

    # 鈶?娌′汉鍙敜閱掞紙姹犵┖ 鎴?閮藉湪鍐峰嵈锛?
    try:
        from brain import wake as W
        cands = W.candidates(db, limit=6)
        if cands:
            gap = W.WAKE_EVERY if hasattr(W, "WAKE_EVERY") else 60
            last = float(st.get("last_wake", 0) or 0)
            if last and (now - last) < gap:
                pass                      # 鍐峰嵈涓?-> 杩欐潯璺篃绠楀牭
            else:
                return False, "鍞ら啋姹?%d 浜猴紙鍙敜锛? % len(cands)
    except Exception as e:
        return False, "鍞ら啋姹犳湭鐭?-> 涓嶅垏鍙? %r" % e

    # 鈶?娌℃湁鍖归厤娆℃暟锛堥檺棰戣 UI锛?
    rec = _load().setdefault("quota", {})
    q, ok = None, False
    if not force_quota and rec.get("q") is not None and (now - float(rec.get("t") or 0)) < QUOTA_CHECK_EVERY:
        q, ok = rec["q"], True
        log.info("鍖归厤娆℃暟锛堢紦瀛?%.0fs 鍓嶏級: %s", now - float(rec.get("t") or 0), q)
    else:
        q, ok = read_quota(actor)
        if ok:
            d = _load()
            d["quota"] = {"q": q, "t": now}
            _save(d)
            log.info("鍖归厤娆℃暟锛堢幇璇伙級: %s", q)
    if not ok:
        # 馃敶 2026-11-08 21:3x锛堢敤鎴峰彛寰勩€岃剼鏈垏鍙枫€? App 鏀圭増锛夛細
        #   宸﹀崱锛堢伒榄傚尮閰嶏級鏀圭増鍚庝笉鍐嶆樉绀哄墿浣欐鏁?鈫?璇讳笉鍒版槸**甯告€?*锛屼笉鏄紓甯搞€?
        #   鏃х瓥鐣ャ€岃涓嶅埌灏变笉鍒囥€嶄細璁╁彿姘歌繙鍗″湪鍚屼竴涓处鍙凤紙瀹炴祴 18:07~18:57 杩炵画 9 娆★級銆?
        #   鏂扮瓥鐣ワ細璇讳笉鍒版椂鐢?*绌洪棽鏃堕暱**鍏滃簳 鈥斺€?宸茬粡绌洪棽 鈮?0 鍒嗛挓涓旀病鏈夊彲澶勭悊鐨勪汉锛?
        #   灏卞厑璁稿垏鍙凤紙鐢ㄦ埛瑕佺殑鏄?杩欎釜鍙锋病娲诲共浜嗗氨鎹?锛屼笉鏄?璇讳笉鍒板氨姝荤瓑"锛夈€?
        if _idle_minutes(st) >= IDLE_SWITCH_MIN:
            log.warning("鍖归厤娆℃暟璇讳笉鍒帮紝浣嗗凡绌洪棽 %.0f 鍒嗛挓锛堚墺%.0f锛夆啋 鍏佽鍒囧彿鍏滃簳",
                        _idle_minutes(st), IDLE_SWITCH_MIN)
            return True, "娆℃暟鏈煡 + 绌洪棽 %.0f 鍒嗛挓" % _idle_minutes(st)
        return False, "鍖归厤娆℃暟璇讳笉鍒帮紙鏈煡锛?> 涓嶅垏鍙凤紙绌洪棽 %.0f 鍒嗛挓锛? % _idle_minutes(st)
    if q and q > 0:
        return False, "杩樻湁 %d 娆″尮閰? % q

    return True, "涓夋潯浠舵垚绔嬶紙鏃犱汉鍙亰 / 鏃犱汉鍙敜閱?/ 鍖归厤娆℃暟 0锛?


def _quota_cached(actor, force=False):
    """璇诲尮閰嶉搴︼紙甯︾紦瀛橈紝10 鍒嗛挓鍐呬笉閲嶅寮€鏄熺悆椤碉級銆傝繑鍥?(娆℃暟, 鏄惁璇诲埌)銆?""
    now = time.time()
    rec = _load().get("quota") or {}
    if (not force and rec.get("q") is not None
            and (now - float(rec.get("t") or 0)) < QUOTA_CHECK_EVERY):
        return rec["q"], True
    q, ok = read_quota(actor)
    if ok:
        d = _load()
        d["quota"] = {"q": q, "t": now}
        _save(d)
    return q, ok


IDLE_SWITCH_MIN = float(os.environ.get("SOUL_IDLE_SWITCH_MIN", "30") or 30)
_LAST_ACTIVE = {"t": 0.0}


def mark_active():
    """涓诲惊鐜瘡澶勭悊涓€浠朵簨锛堝洖娑堟伅/鍖归厤/鍞ら啋锛夊氨璋冧竴娆★紝鐢ㄦ潵绠椼€岀┖闂插涔呫€嶃€?""
    _LAST_ACTIVE["t"] = time.time()


def _idle_minutes(st):
    """绌洪棽鍒嗛挓鏁帮細浼樺厛鐢ㄦ渶杩戜竴娆′笟鍔℃椿鍔ㄦ椂闂达紝閫€鍥為杞椂闂淬€?""
    t = max(_LAST_ACTIVE["t"], float(st.get("round0", 0) or 0))
    if not t:
        return 0.0
    return max(0.0, (time.time() - t) / 60.0)


def preflight(actor, db, st):
    """鍒囧彿鍓嶄綋妫€锛氱‘璁よ繖涓彿鐪熺殑娌℃椿骞蹭簡銆?

    馃敶 鐢ㄦ埛 2026-11-02锛氥€屽垏鍙蜂箣鍓嶄竴瀹氳纭褰撳墠璐﹀彿鏄惁杩樻湁鏈洖鐨勬秷鎭€?
       鍖归厤棰濆害鏄惁褰掗浂銆佸敜閱掑ソ鍙嬫槸鍚﹀畬鎴愮瓑绛変竴绯诲垪闂銆嶃€?
    鍘熷疄鐜伴噷銆岀┖闂?5 鍒嗛挓鍒囧彿銆嶉偅鏉¤矾**鐩存帴鍒?*锛岃烦杩囦簡涓夋潯浠舵鏌?鈥斺€?
    鍝€曡繕鏈?9 鏉℃湭璇汇€佽繕鏈?20 娆″尮閰嶉搴︼紝涔熶細琚垏璧般€傝繖涓嚱鏁板氨鏄ˉ杩欎釜娲炪€?

    杩斿洖 (ok, [鏈畬鎴愰」])銆傝涓嶅埌鐨勪竴寰嬪綋浣溿€屾湭瀹屾垚銆嶏紙淇濆畧锛屽畞鍙笉鍒囷級銆?
    """
    blockers = []

    # 鈶?搴撻噷鏈 鈥斺€?鍙畻**鐪熶汉寰呭洖**锛堣澶囪繕鍦?+ 鏈潯鏄ス + 涓嶅湪鍐峰嵈锛?
    #
    # 馃敶 2026-11-08 21:3x锛堢敤鎴峰彛寰勩€岃剼鏈垏鍙枫€嶅垏涓嶅姩鐨勭湡鏍瑰洜锛夛細
    #   鏃у疄鐜扮洿鎺?`SELECT COUNT(*) ... unReadCount>0`锛屾妸**鍍靛案浼氳瘽**涔熺畻杩涘幓锛?
    #   Soul 娓呰繃鍘嗗彶鐨勫簱閲岋紝闀滃儚浠嶆湁 1300 涓細璇濓紝鍏朵腑 211 涓湪 App 閲屾棭灏变笉瀛樺湪锛?
    #   瀹冧滑鐨?unReadCount 姘歌繙 >0 鈫?鍒囧彿闂镐竴鐩存姤銆屽簱閲?12 涓細璇濇湭璇汇€嶁啋 姘镐笉鍒囧彿銆?
    #   瀹炴祴 18:07~18:57 杩炵画 9 娆°€岀┖闂?130~180 鍒嗛挓锛屼絾杩樻湁 3 椤规病鍋氬畬 鈫?鍏堜笉鍒囧彿銆嶏紝
    #   鍖归厤棰濆害鏃╁氨鐢ㄥ畬锛屽彿涓€鐩村崱鍦ㄥ悓涓€涓处鍙蜂笂銆?
    #   鐜板湪鍙ｅ緞鍜屻€岀孩鐐归椄 / candidates()銆嶇粺涓€锛氬彧鏈夌湡鑳藉幓鍥炵殑浜烘墠绠楁湭瀹屾垚銆?
    try:
        from brain import pendingq as PQ
        from data import imdb as _IM
        _devref = getattr(db, "dev", None)
        _live = _IM.device_live_uids(_devref, db.uid) if _devref is not None else None
        _rows = db.con.execute(
            "SELECT sessionId, toUserId FROM session WHERE unReadCount > 0").fetchall()
        _real = []
        for _sid, _to in _rows:
            _sid = str(_sid)
            if _live is not None and str(_to or "") not in _live:
                continue                      # App 閲屽凡缁忔病鏈夎繖涓細璇濓紙鍍靛案锛?
            _last, _src = db.latest(_sid)
            if _last is None or str(_last.sender) == str(db.uid):
                continue                      # 鏈潯鏄垜鍙戠殑 / 娌℃湁娑堟伅
            if PQ.should_skip(_sid, getattr(_last, "text", "") or ""):
                continue                      # 鍐峰嵈涓紙鍒氭壘杩囨病鎵惧埌锛?
            _real.append(_sid)
        if _real:
            blockers.append("搴撻噷 %d 涓細璇濇湭璇伙紙鐪熶汉寰呭洖锛? % len(_real))
    except Exception as e:
        blockers.append("璇绘湭璇绘暟澶辫触锛堟湭鐭ワ級: %r" % e)

    # 鈶?寰呭洖锛堟湯鏉℃槸濂瑰彂鐨勶紝鍚凡璇绘湭鍥烇級
    try:
        from brain import pendingq as PQ
        cands = PQ.candidates(db, limit=3)
        if cands:
            blockers.append("%d 涓緟鍥炴湭澶勭悊" % len(cands))
    except Exception as e:
        blockers.append("寰呭洖鎺㈡祴澶辫触锛堟湭鐭ワ級: %r" % e)

    # 鈶?UI 涓婅繕鏈夋病鏈夌孩鐐?
    try:
        from brain import clear as CL
        # 馃敶 2026-11-08锛堝簱鐩磋 P0锛夛細浼?db 璧板簱鍒ゅ畾 鈥斺€?灞忓箷琛屽唴绾㈢偣
        #   `unread_msg_number` 瀹炴祴 4/4 杞?0 涓妭鐐癸紝鏃у垽鎹亽 False锛?
        #   浼氳鍒囧彿闂歌浠ヤ负銆屽凡娓呭共鍑€銆嶃€?
        has_dot, badge, ndots = CL.has_dot_now(actor, db=db)
        if has_dot:
            blockers.append("鑱婂ぉ瑙掓爣 %s锛堝綋鍓嶅睆绾㈢偣 %d锛? % (badge, ndots))
    except Exception as e:
        log.debug("绾㈢偣鎺㈡祴澶辫触: %r", e)

    # 鈶?鍖归厤棰濆害娌℃Θ骞?
    try:
        q, qok = _quota_cached(actor)
        if not qok:
            blockers.append("鍖归厤棰濆害璇讳笉鍒帮紙鏈煡锛?)
        elif q and q > 0:
            blockers.append("浠婃棩杩樺墿 %d 娆″尮閰? % q)
    except Exception as e:
        blockers.append("鍖归厤棰濆害寮傚父锛堟湭鐭ワ級: %r" % e)

    # 鈶?鍞ら啋杩樻病璺戯紙鍒氳窇杩囧氨涓嶇畻闃诲锛屽惁鍒欎汉澶氱殑鏃跺€欐案杩滃垏涓嶄簡锛?
    try:
        from brain import wake as W
        last_wake = float(st.get("last_wake", 0) or 0)
        recently = (time.time() - last_wake) < 600      # 10 鍒嗛挓鍐呭敜杩?= 鏈疆宸插仛
        if not recently and W.candidates(db, limit=1):
            blockers.append("杩樻湁鍙敜閱掔殑鑰佸弸娌″敜锛堜笂娆″敜閱掑湪 %.0f 鍒嗛挓鍓嶏級"
                            % ((time.time() - last_wake) / 60 if last_wake else -1))
    except Exception as e:
        log.debug("鍞ら啋鎺㈡祴澶辫触: %r", e)

    return (len(blockers) == 0), blockers


def maybe_switch(actor, dev, db, st, force_quota=False):
    """鍐冲畾骞舵墽琛屽垏鍙枫€傝繑鍥?(switched, why)銆?""
    from brain import nav

    # 鍐峰嵈涓庨棿闅?
    if last_switch_ago_min() < MIN_GAP_MIN:
        return False, "璺濅笂娆″垏鍙?%.0f 鍒嗛挓锛? %d锛? % (last_switch_ago_min(), MIN_GAP_MIN)
    _bo = _switch_backoff_left()
    if _bo > 0:
        return False, "涓婃鍒囧彿澶辫触锛岄€€閬夸腑锛堝墿 %.0f 鍒嗛挓锛? % _bo

    # 绌洪棽鍒囧彿鐨勬椂闂村熀鍑?+ 褰撳墠鍦ㄧ嚎鏃堕暱
    idle_min = (time.time() - float(st.get("last_msg_ts") or 0)) / 60.0
    oh = online_hours()

    # 鈴?8h 寮哄埗鍒囧彿锛氭渶楂樹紭鍏堬紝**涓嶇瓑浠讳綍鏉′欢**锛堢敤鎴?2026-11-04 鎷嶆澘锛氬己鍒跺氨鏄己鍒讹級
    #    鍘熸潵杩欓噷涔熻蛋 preflight锛岃銆屽簱閲屾湭璇?鍖归厤棰濆害銆嶆嫤浣?鈫?涓€涓彿杩炵画鍦ㄧ嚎 40h+
    #    閮戒笉鍒囷紙瀹炴祴 online_since=11-02 07:52锛宎cct.log 姣忚疆閮芥姤銆屾殏缂撳己鍒跺垏鍙枫€嶏級銆?
    if oh >= FORCE_SWITCH_H:
        log.warning("鈴?宸茶繛缁湪绾?%.1fh锛堚墺%.0fh锛夆啋 寮哄埗鍒囧彿锛堜笉绛変笁鏉′欢/浣撴锛?,
                    oh, FORCE_SWITCH_H)

    # 馃挙 绌洪棽鍒囧彿锛氭暣杞祦绋嬮兘璧板畬 + 5 鍒嗛挓娌℃柊娑堟伅
    #    蹇呴』鍏堜綋妫€锛堢敤鎴?2026-11-02锛夆€斺€?涓嶄綋妫€鐨勮瘽鍝€曡繕鏈夋湭璇?棰濆害/鍙敜閱掍篃鐓ф牱鍒囥€?
    elif idle_min >= IDLE_SWITCH_MIN:
        ok, blockers = preflight(actor, db, st)
        if not ok:
            log.info("馃挙 绌洪棽 %.1f 鍒嗛挓锛屼絾杩樻湁 %d 椤规病鍋氬畬 鈫?鍏堜笉鍒囧彿锛?s",
                     idle_min, len(blockers), "锛?.join(blockers))
            return False, "鏈畬鎴?%d 椤? %s" % (len(blockers), blockers[0])
        log.warning("馃挙 绌洪棽 %.1f 鍒嗛挓涓旂‘璁ゆ病娲诲共锛堟棤鏈/鏃犲緟鍥?棰濆害 0/宸插敜閱掞級鈫?鍒囧彿",
                    idle_min)

    # 馃敟 姒ㄥ共锛氫笁鏉′欢鎴愮珛骞舵寔缁?30 鍒嗛挓
    else:
        should, why = evaluate(actor, db, st, force_quota=force_quota)
        if not should:
            st["dry_since"] = 0
            return False, why
        since = float(st.get("dry_since") or 0)
        if not since:
            st["dry_since"] = time.time()
            return False, "涓夋潯浠舵垚绔嬶紝寮€濮嬭鏃讹紙闇€鎸佺画 %d 鍒嗛挓锛? % DRY_HOLD_MIN
        held = (time.time() - since) / 60.0
        if held < DRY_HOLD_MIN:
            return False, "涓夋潯浠跺凡鎴愮珛 %.0f 鍒嗛挓锛堥渶 %d锛? % (held, DRY_HOLD_MIN)
        log.warning("馃敟 璐﹀彿宸叉Θ骞诧紙涓夋潯浠舵寔缁?%.0f 鍒嗛挓锛夆啋 鍒囧彿", held)

    # 鎵ц锛堜笁涓垎鏀兘姹囧悎鍒拌繖閲岋紝缁熶竴鏇存柊鍙拌处锛涗慨鎺変簡鍘熴€岀┖闂插垏鍙风洿鎺?return
    #       涓嶈 last_switch銆嶇殑闅愭偅锛?
    ok, why = switch_account(actor, dev)
    if ok:
        d = _load()
        d["last_switch"] = time.time()
        d["prev_uid"] = d.get("cur_uid")
        d["online_since"] = time.time()     # 鏂板彿閲嶆柊璁℃椂
        d["dry_since"] = 0
        d["last_switch_try"] = 0            # 鎴愬姛 鈫?娓呮帀澶辫触閫€閬?
        _save(d)
        st["dry_since"] = 0
        st["last_match"] = 0
        st["last_wake"] = 0
    else:
        # 馃敶 2026-11-04锛堥棴鐜級锛氬け璐ヤ篃鐣欑棔锛屽惁鍒欎笅涓€杞張閲嶅紑闈㈡澘绌虹儳 30~60s
        #   锛堝疄娴?02:06~02:12 杩炵画 3 娆″皾璇曞叏澶辫触锛屾瘡杞櫧鐑э級銆?
        d = _load()
        d["last_switch_try"] = time.time()
        _save(d)
        log.warning("鍒囧彿澶辫触锛?s锛夆啋 閫€閬?%d 鍒嗛挓鍐呬笉鍐嶈瘯", why, FORCE_RETRY_GAP_MIN)
    return ok, why


def force_switch_if_due(actor, dev, db, st):
    """8h 寮哄埗鍒囧彿锛堢敤鎴?2026-11-04 鎷嶆澘锛夛細姣忚疆 cycle 鏃╂湡璋冪敤锛屽埌鐐瑰氨鍒囥€?

    涓轰粈涔堝崟鐙媶鍑烘潵锛歮aybe_switch 鍦?cycle 绗懃姝ワ紝鍓嶉潰鍙鏈夊洖澶?鍞ら啋/鍖归厤
    灏?return锛屾案杩滆蛋涓嶅埌 鈥斺€?瀹炴祴涓€涓彿杩炵画鍦ㄧ嚎 41h+ 閮戒笉鍒囥€傚己鍒跺垏鍙峰繀椤诲湪
    姣忚疆鏃╂湡妫€鏌ワ紝涓嶅仛 preflight/evaluate锛堝己鍒跺氨鏄己鍒讹紝涓嶇瓑浠讳綍鏉′欢锛夈€?
    杩斿洖 (switched, why)銆?
    """
    if last_switch_ago_min() < MIN_GAP_MIN:
        return False, "璺濅笂娆″垏鍙?%.0f 鍒嗛挓锛? %d锛? % (last_switch_ago_min(), MIN_GAP_MIN)
    _bo = _switch_backoff_left()
    if _bo > 0:
        return False, "涓婃鍒囧彿澶辫触锛岄€€閬夸腑锛堝墿 %.0f 鍒嗛挓锛? % _bo
    oh = online_hours()
    if oh < FORCE_SWITCH_H:
        return False, "鍦ㄧ嚎 %.1fh锛?%.0fh锛? % (oh, FORCE_SWITCH_H)
    log.warning("鈴?宸茶繛缁湪绾?%.1fh锛堚墺%.0fh锛夆啋 寮哄埗鍒囧彿锛堜笉绛変笁鏉′欢/浣撴锛?,
                oh, FORCE_SWITCH_H)
    ok, why = switch_account(actor, dev)
    if ok:
        d = _load()
        d["last_switch"] = time.time()
        d["prev_uid"] = d.get("cur_uid")
        d["online_since"] = time.time()     # 鏂板彿閲嶆柊璁℃椂
        d["dry_since"] = 0
        d["last_switch_try"] = 0            # 鎴愬姛 鈫?娓呮帀澶辫触閫€閬?
        _save(d)
        st["dry_since"] = 0
        st["last_match"] = 0
        st["last_wake"] = 0
    else:
        # 馃敶 2026-11-04锛堥棴鐜級锛氬け璐ヤ篃鐣欑棔锛屽惁鍒欎笅涓€杞張閲嶅紑闈㈡澘绌虹儳 30~60s
        #   锛堝疄娴?02:06~02:12 杩炵画 3 娆″皾璇曞叏澶辫触锛屾瘡杞櫧鐑э級銆?
        d = _load()
        d["last_switch_try"] = time.time()
        _save(d)
        log.warning("鍒囧彿澶辫触锛?s锛夆啋 閫€閬?%d 鍒嗛挓鍐呬笉鍐嶈瘯", why, FORCE_RETRY_GAP_MIN)
    return ok, why


def switch_account(actor, dev):
    """鍒囧埌鍙︿竴涓处鍙凤紙UI锛夈€傝繑鍥?(ok, why)銆?

    瀹炴祴璺緞锛?026-11-02锛夛細
      銆岃嚜宸便€嶉〉 鈫?宸︿笂銆屽垏鎹㈢敤鎴枫€嶅浘鏍?鈫?闈㈡澘閲岀偣鍙︿竴涓处鍙疯 鈫?钀界偣杩樻槸銆岃嚜宸便€嶉〉銆?
    鈿狅笍 蹇呴』**鍏堟粦鍒伴《閮?*鍐嶇偣锛氶〉闈㈡粴鍔ㄦ椂鑺傜偣鍧愭爣浼氬亸 40+ px锛屼細鐐瑰埌銆岃鎵腑蹇冦€嶃€?
    """
    from brain import nav

    try:
        snap, pg = nav.to_tab(actor, "鑷繁")
        if pg != "me":
            log.warning("鍥炰笉鍒般€岃嚜宸便€嶉〉锛?s锛?, pg)
            return False, "鍥炰笉鍒拌嚜宸遍〉(%s)" % pg

        # 婊戝埌椤讹紙鍏抽敭锛?
        for _ in range(3):
            actor.hand.swipe(450, 400, 450, 1300, duration=0.18, settle=0.5)

        snap = actor.snap(force=True)
        n = snap.hit(desc="鍒囨崲鐢ㄦ埛") or snap.hit(text="鍒囨崲鐢ㄦ埛")
        if n is None:
            # 鍏滃簳锛氬乏涓婅閭ｄ釜鍥炬爣锛堝疄娴嬩腑蹇?62,98锛?
            cands = [x for x in snap.nodes
                     if x.clickable and x.center[1] < 160 and x.center[0] < 160]
            n = cands[0] if cands else None
        if n is None:
            log.warning("鎵句笉鍒般€屽垏鎹㈢敤鎴枫€嶅叆鍙?)
            return False, "鎵句笉鍒板垏鎹㈢敤鎴峰叆鍙?

        log.info("鐐瑰垏鎹㈢敤鎴?%s", n.bounds)
        actor.hand.tap_node(n, settle=2.0)

        # 馃敶 2026-11-08 21:3x锛堝疄娴嬶細闈㈡澘鍏跺疄寮€浜嗭紝鏄垽瀹氬お鎬ワ級锛?
        #   鐐瑰畬銆屽垏鎹㈢敤鎴枫€嶅悗鏃т唬鐮佸彧 snap 涓€娆★紱璁惧鎱竴鐐癸紙dump 0.5~2s锛?
        #   灏变細鎷垮埌涓婁竴甯?鈫?璇姤銆岃处鍙烽潰鏉挎病鎵撳紑銆嶁啋 鐩存帴鏀惧純鍒囧彿銆?
        #   瀹炴祴鎵嬪姩鐐瑰悓涓€涓叆鍙?1.5s 鍚庡氨鑳界湅鍒般€屽垏鎹㈣处鍙?/ 娣诲姞璐﹀彿銆嶃€?
        #   鏀规垚鏈€澶氳疆璇?4 娆★紙姣忔 1.2s锛夈€?
        s = actor.snap(force=True)
        for _w in range(4):
            if "娣诲姞璐﹀彿" in "\n".join(s.texts()):
                break
            time.sleep(1.2)
            s = actor.snap(force=True)
        if "娣诲姞璐﹀彿" not in "\n".join(s.texts()):
            log.warning("璐﹀彿闈㈡澘娌℃墦寮€锛堣疆璇?4 娆′粛鏈嚭鐜般€屾坊鍔犺处鍙枫€嶏級")
            return False, "璐﹀彿闈㈡澘娌℃墦寮€"

        rows = [x for x in s.nodes
                if x.clickable and x.visible
                and (x.bounds[2] - x.bounds[0]) > 700
                and 100 <= (x.bounds[3] - x.bounds[1]) <= 200]
        rows.sort(key=lambda x: x.bounds[1])
        if len(rows) < 2:
            return False, "闈㈡澘閲屽彧鏈変竴涓处鍙凤紙娌″彿鍙垏锛?

        # 馃敶 涓嶈兘闈犮€屽綋鍓嶈处鍙峰湪绗竴琛屻€嶈繖绉嶇‖鍋囪 鈥斺€?鍒囬敊鍙蜂唬浠峰お澶с€?
        #    鍋氭硶锛氬厛璁颁笅褰撳墠 uid锛屽垏瀹屽啀璇讳竴娆?uid 瀵规瘮锛涙病鍙樺氨鎹㈠彟涓€涓处鍙疯鍐嶈瘯銆?
        from data.imdb import open_account
        try:
            before = str(open_account(dev).uid)
        except Exception as e:
            log.warning("鍒囧彿鍓嶈 uid 澶辫触锛堜粛鐒剁户缁級: %r", e)
            before = ""

        # 鍊欓€夎处鍙疯锛堟帓闄ゃ€屾坊鍔犺处鍙枫€嶏級
        def _cand_rows(sn):
            _rows = [x for x in sn.nodes
                     if x.clickable and x.visible
                     and (x.bounds[2] - x.bounds[0]) > 700
                     and 100 <= (x.bounds[3] - x.bounds[1]) <= 200]
            _rows.sort(key=lambda x: x.bounds[1])
            _cand = [r for r in _rows if "娣诲姞璐﹀彿" not in (r.label or "")
                     and "娣诲姞璐﹀彿" not in (r.desc or "")]
            return _cand or _rows

        # 馃敶 2026-11-10锛圥0 淇锛夛細鍘熸潵 range(2) 鈥斺€?闈㈡澘閲屾湁 3 涓处鍙锋椂锛?
        #   绗?3 涓€欓€?*姘歌繙鐐逛笉鍒?*锛堣 SWITCH_MAX_TRY 娉ㄩ噴閲岀殑澶滈棿瀹炴祴锛夈€?
        tried_rows = 0
        for attempt in range(SWITCH_MAX_TRY):
            if attempt == 0:
                s = actor.snap(force=True)
            else:
                snap, pg = nav.to_tab(actor, "鑷繁")
                if pg != "me":
                    return False, "鍥炰笉鍒拌嚜宸遍〉(%s)" % pg
                for _ in range(3):
                    actor.hand.swipe(450, 400, 450, 1300, duration=0.18, settle=0.5)
                # 馃敶 2026-11-08 03:45 淇锛歛ttempt-1 鍘熸潵鎵句笉鍒般€屽垏鎹㈢敤鎴枫€嶅氨鐩存帴鏀惧純锛?
                #    浣?attempt-0 鏈夈€屽乏涓婅鍥炬爣銆嶅厹搴曡€?attempt-1 娌℃湁 鈥斺€?涓嶅绉般€?
                #    瀹炴祴绗竴娆″垏鎹㈠氨鏄鍦ㄨ繖閲岋紙闈㈡澘鍏充簡銆佸叆鍙ｈ繕鍦ㄥ師浣嶏級銆?
                #    鐜板湪琛ヤ笂鍚屾牱鐨勫厹搴?+ 閲嶈瘯涓ゆ銆?
                _n = None
                for _try in range(2):
                    snap = actor.snap(force=True)
                    _n = snap.hit(desc="鍒囨崲鐢ㄦ埛") or snap.hit(text="鍒囨崲鐢ㄦ埛")
                    if _n is None:
                        _cands = [x for x in snap.nodes
                                  if x.clickable and x.center[1] < 160 and x.center[0] < 160]
                        _n = _cands[0] if _cands else None
                    if _n is not None:
                        break
                    time.sleep(2.0)
                if _n is None:
                    return False, "鎵句笉鍒板垏鎹㈢敤鎴峰叆鍙?
                actor.hand.tap_node(_n, settle=2.0)
                s = actor.snap(force=True)
                if "娣诲姞璐﹀彿" not in "\n".join(s.texts()):
                    return False, "璐﹀彿闈㈡澘娌℃墦寮€"

            cand = _cand_rows(s)
            log.info("闈㈡澘鍊欓€夎处鍙疯 %d 涓?, len(cand))
            # 馃敶 2026-11-10锛堣ˉ璇佹嵁锛夛細鍘熸潵澶辫触鍙暀涓€鍙ャ€寀id 娌″彉銆嶏紝瀹屽叏鐪嬩笉鍑?
            #   鐐圭殑鏄摢涓€琛屻€侀潰鏉夸笂鍒板簳鍑犱釜鍙枫€佽瘑鍒埌鐨勬樀绉板涓嶅銆傚闂存帓闅滄椂
            #   鍙兘闈犵寽銆傜幇鍦ㄦ妸姣忚鐨?bounds / 鏄电О / 鎻忚堪閮芥墦鍑烘潵锛?
            #   涓嬫澶辫触鑳界洿鎺ュ垽鏂€岀偣閿欒銆嶈繕鏄€岀偣浜嗘病鍙嶅簲銆嶃€?
            for _i, _r in enumerate(cand):
                try:
                    log.info("   闈㈡澘琛?d bounds=%s nick=%r desc=%r",
                             _i, _r.bounds, (_r.label or "")[:16], (_r.desc or "")[:24])
                except Exception:
                    log.info("   闈㈡澘琛?d bounds=%s锛堣鏍囩澶辫触锛?, _i, getattr(_r, "bounds", "?"))
            # 馃敶 2026-11-08 21:3x锛堝疄娴嬶級锛氶潰鏉跨涓€琛屽氨鏄?*褰撳墠璐﹀彿**锛?
            #   鐐瑰畠褰撶劧銆寀id 娌″彉銆嶏紝鐧借窇涓€杞?+ 涓€娆?app 閲嶅惎銆?
            #   鐜板湪浠庣浜岃寮€濮嬬偣锛堝彧鏈変竴涓彿鏃舵墠鍥炶惤鍒扮涓€琛岋級銆?
            order = (cand[1:] + cand[:1]) if len(cand) > 1 else cand
            if attempt >= len(order):
                break
            target = order[attempt]
            tried_rows += 1
            log.info("灏濊瘯鍒囧埌绗?%d 涓处鍙?%s", attempt + 1, target.bounds)
            actor.hand.tap_node(target, settle=1.5)

            t0 = time.time()
            while time.time() - t0 < 40:
                time.sleep(2.5)
                try:
                    dev.u2().app_start(SOUL_PKG, wait=True)
                except Exception:
                    pass
                s2, pg2 = nav.to_tab(actor, "鑷繁")
                if pg2 != "me":
                    continue
                # 馃敶 2026-11-10锛圥0 璇垽淇锛夛細鍘熸潵鍙涓€娆?uid 灏变笅缁撹銆?
                #   搴撴槸 pull 缂撳瓨锛圧EFRESH_S=300锛夛紝鍒囧彿鍚?App 鍒氶噸鍚€佸簱杩樻病鍚屾锛?
                #   绗竴娆¤鍒扮殑杩樻槸鏃?uid 鈫?鍒ゃ€屾病鍙樸€嶁啋 break 鈫?鎹笅涓€涓彿鐧界偣銆?
                #   鐜板湪璇?3 娆★紙闂撮殧 1.5s锛夛紝骞舵妸銆岃涓嶅埌銆嶄笌銆岀湡鐨勬病鍙樸€嶅垎寮€鎶ャ€?
                after = ""
                for _k in range(3):
                    try:
                        after = str(open_account(dev).uid or "")
                    except Exception as _e:
                        log.warning("   鍒囧彿鍚庤 uid 澶辫触(%d/3): %r", _k + 1, _e)
                        after = ""
                    if after and after != before:
                        break
                    if _k < 2:
                        time.sleep(1.5)
                if before and after and after != before:
                    log.info("鉁?鍒囧彿鎴愬姛锛?s -> %s", before, after)
                    return True, "宸插垏鍙?%s -> %s" % (before, after)
                if not before and pg2 == "me":
                    log.info("鉁?鍒囧彿鍚庡洖鍒拌嚜宸遍〉锛堝垏鍙峰墠灏辫涓嶅埌 uid锛屾棤娉曟牎楠岋級")
                    return True, "宸插垏鍙凤紙鏃?uid 鏍￠獙锛?
                if not after:
                    log.warning("   鍒囧彿鍚?3 娆￠兘璇讳笉鍒?uid锛堝簱鏈埛鏂帮級鈫?鏈鍒ゅけ璐ワ紝"
                                "浣?*涓嶇‘瀹?*鏄惁鐪熸病鍒囪繃鍘?)
                else:
                    log.info("   鍒囧畬 uid 娌″彉锛堜粛鏄?%s锛夆啋 杩欎竴琛屼笉鏄洰鏍囧彿锛屾崲涓嬩竴琛?, after)
                break
        return False, "宸茶瘯 %d 涓€欓€夎处鍙凤紝uid 閮芥病鍙? % tried_rows
    except Exception as e:
        log.warning("鍒囧彿寮傚父: %r", e)
        return False, repr(e)
