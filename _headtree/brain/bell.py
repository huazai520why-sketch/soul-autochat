# -*- coding: utf-8 -*-
"""濂囬亣閾冿細鍏ㄥ眬鏈€楂樹紭鍏堢骇锛堟棫鏋舵瀯閾捐矾閲岀殑绗?鈶?浣嶏級銆?

鏃у彛寰勶紙soul_daemon + 鐢ㄦ埛 2026-09-29 閾佸緥锛夛細
  鈶?濂囬亣閾? 鍏ㄥ眬鏈€楂橈細寮归搩**绔嬪埢涓柇**褰撳墠鍔ㄤ綔锛堝洖娑堟伅/鍖归厤/鍞ら啋锛夛紝澶勭悊瀹屽啀鍥炲師娴佺▼
  鈶?澶勭悊鏂版秷鎭?/ 娑堥櫎绾㈢偣
  鈶?鍞ら啋鑰佸弸
  鈶?鍖归厤

馃敶 2026-11-02 瀹炲脊瀹炴祴锛堝叧閿級锛?
  閾冩槸**鑷粯寮圭獥**锛孶I 鏍戦噷鏍规湰娌℃湁銆岀珛鍗崇鑱娿€嶆寜閽妭鐐?鈥斺€?
  鏍戦噷鍙湁銆屽叧闂脊绐?/ 鍚屽煄濂囬亣 / 鑴夎剦鐨勫悓娓镐箰鍦?/ 鏈夎叮鐨勭伒榄傜瓑浣犲彂鐜般€嶈繖浜涙枃鏈€?
  鎵€浠ワ細
    路 **鍒ゆ嵁**锛歎I 鏍戝嚭鐜般€屽悓鍩庡閬?/ 鍏抽棴寮圭獥 / 濂囬亣閾冦€嶁啋 鍙兘鏄搩锛堝揩锛? 鎴愭湰锛?
    路 **瀹氫綅鎸夐挳蹇呴』鐢?OCR**锛氭埅鍥鹃噷銆岀珛鍗崇鑱娿€嶅湪 (450, 653)锛孫CR 涓€娆?~2s
  瀹炲脊鎴浘瀵圭収锛?
      x=171 y=143  'Soul濂囬亣閾冨悓鍩庡閬?
      x=450 y=298  '鑴夎剦鐨勫悓娓镐箰鍦?      鈫?瀵规柟鏄电О
      x=450 y=431  '鏈夎叮鐨勭伒榄傜瓑浣犲彂鐜?
      x=450 y=653  '绔嬪嵆绉佽亰'            鈫?鎸夐挳涓績

澶勭悊鍔ㄤ綔锛氱偣銆岀珛鍗崇鑱娿€嶁啋 **宸插湪璇ヤ汉浼氳瘽椤碉紝鐩存帴鍙?*锛堟棫鏋舵瀯鏍藉湪"鍏堝洖鍒楄〃鎵句汉"锛夆啋 閫氱敤寮€鍦虹櫧 鈫?寤烘。銆?
"""
import json
import os
import re
import tempfile
import time

from core.log import get_logger
from core.paths import LOGS, STATE
from eyes import ocr
from eyes.page import detect

log = get_logger("brain.bell")

BELL_BTN = "绔嬪嵆绉佽亰"
BELL_HINTS = ("濂囬亣閾?, "鍚屽煄濂囬亣", "鍏抽棴寮圭獥")

# 馃敶 2026-11-08 11:2x锛堢敤鎴凤細銆屽閬囬搩 绋嶅悗鍐嶈亰 閲岄潰鏈変笁涓汉绛夌潃瀵硅瘽鍟?浼樺厛绾у閬囬搩涓嶆槸鏈€楂樺悧銆嶏級
#
#   瀹炲脊瀹炴祴锛氱偣浼氳瘽鍒楄〃閲屻€屽閬囬搩-绋嶅悗鍐嶈亰銆嶈繖涓€琛岋紝杩涚殑鏄?
#     cn.soulapp.android/.component.chat.lovebelll.LoveBellChatListActivity
#   椤甸潰缁撴瀯锛?00x1600锛?026-11-08 瀹炴祴 dump锛夛細
#     鏍囬銆屽閬囬搩-绋嶅悗鍐嶈亰銆? 鍙充笂銆屾洿澶氬閬囥€? 鎻愮ず銆屼粎淇濈暀鏈€杩?澶╀綘鐩存帴鍏抽棴鐨勭敤鎴峰摝銆?
#     琛岋細鏄电О(160~310, y=240~281) + 鏍囩銆屽悓鍩庣殑浠栵紝鍘绘墦涓嫑鍛笺€嶆垨銆屽悓鍩庡閬囥€? 鏃堕棿(810, ...)
#   鐐硅 鈫?鐩存帴杩?ConversationActivity锛堝鏂逛細璇濋〉锛岃繕娌′换浣曟秷鎭級鈫?鐏屽紑鍦虹櫧鍗冲彲銆?
#
#   涓轰粈涔堝繀椤诲仛锛氳繖鏉￠摼璺槸**濂囬亣閾冪殑涓€閮ㄥ垎**锛岃€岀敤鎴峰彛寰勩€屽閬囬搩鍏ㄥ眬鏈€楂樹紭鍏堢骇銆嶃€?
#   鍘熸潵 bell.is_bell 鍙寮圭獥閲岀殑銆岀珛鍗崇鑱娿€嶆寜閽紝瀵广€岀◢鍚庡啀鑱娿€嶅垪琛ㄥ畬鍏ㄦ棤鎰?
#   鈬?3 涓凡缁忛€佸埌鍢磋竟鐨勪汉涓€鐩存病浜虹悊锛堝疄娴嬪垪琛ㄩ噷 3 琛岋紝鏃堕棿 10:26 / 09:53 / 09:48锛夈€?
BELL_LIST_HINTS = ("濂囬亣閾?绋嶅悗鍐嶈亰", "鏇村濂囬亣")
BELL_ROW_TAGS = ("鍚屽煄濂囬亣", "鍚屽煄鐨勪粬锛屽幓鎵撲釜鎷涘懠")
BELL_LIST_SKIP = ("濂囬亣閾?绋嶅悗鍐嶈亰", "鏇村濂囬亣", "澶村儚", "鍏抽棴寮圭獥",
                  "浠呬繚鐣欐渶杩?澶╀綘鐩存帴鍏抽棴鐨勭敤鎴峰摝")

# 2026-11-13 鐢ㄦ埛鍙ｅ緞锛氬閬囬搩閲岀殑浜鸿灏介噺娓呯┖锛屼笉鍐嶅崱姝诲湪 3 浜?澶┿€?
# 涓€杞粛鍙鐞嗕竴灏忔壒锛岄伩鍏嶆妸鍥炲/绾㈢偣/鍖归厤娈垫暣杞尋鎺夛紱鍚庣画杞缁х画娓呫€?
def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except Exception:
        return int(default)


BELL_BATCH_MAX = max(1, _env_int("SOUL_BELL_BATCH_MAX", 8))
BELL_DAILY_MAX = max(BELL_BATCH_MAX, _env_int("SOUL_BELL_DAILY_MAX", 40))
BELL_LIST_LEDGER_TTL_S = 4 * 24 * 3600
BELL_FAIL_RETRY_S = 30 * 60

# 涓婚〉鏄庣‘鍐欎簡鈥滀笉鎾?涓嶇害鈥濈殑浜轰笉鍐嶅己寮€锛岄伩鍏嶆妸宸茬粡鎷掔粷鏆ф槯鐨勪汉鎷夎繘鏉ャ€?
PROFILE_BLOCK_WORDS = ("涓嶆挬", "涓嶇害", "鎷掓挬", "鎷掔粷鏆ф槯", "涓嶇綉鎭?)


def _uid_key(uid):
    """鍙彇璐﹀彿 uid 鐨勬暟瀛楅儴鍒嗗仛鏂囦欢鍚嶏紝閬垮厤绌哄€?鐗规畩瀛楃銆?""
    s = "".join(ch for ch in str(uid or "") if ch.isdigit())
    return s or "unknown"


def _ledger_file(uid):
    return STATE / ("bell_list_opened_%s.json" % _uid_key(uid))


def _row_key(nick, tag="", ts=""):
    """鍒楄〃琛岀殑绋冲畾閿€傛樀绉?鏍囩+鍘熷鏃堕棿瓒充互瑕嗙洊鍚屼竴璐﹀彿鍐呯殑閲嶅琛屻€?""
    return "|".join(str(x or "").strip() for x in (nick, tag, ts))


def _log_ts(line, now=None):
    """瑙ｆ瀽鏃ュ織琛?`MM-DD HH:MM:SS`锛岃繑鍥炵绾?epoch锛涘け璐ヨ繑鍥?0銆?""
    m = re.match(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})", line or "")
    if not m:
        return 0
    now = now or time.localtime()
    try:
        return time.mktime((now.tm_year, int(m.group(1)), int(m.group(2)),
                            int(m.group(3)), int(m.group(4)), int(m.group(5)),
                            0, 0, -1))
    except Exception:
        return 0


def _bootstrap_nicks_from_log(uid, data):
    """鎸変粖澶╂墍鏈夎处鍙峰尯闂翠粠鏃ュ織琛ユ樀绉板彴璐︼紝閬垮厤璺ㄥ娆″垏鍙烽噸鍙戙€?""
    if _uid_key(uid) == "unknown":
        return
    day = time.strftime("%m-%d")
    if data.get("bootstrap_day") == day:
        return
    nicks = data.setdefault("nicks", {})

    midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    current = None
    start = midnight
    intervals = []
    gp = LOGS / "guard.daemon.log"
    try:
        with open(gp, "rb") as f:
            gl = f.read().decode("utf-8", "replace").splitlines()
        for line in gl:
            if not line.startswith(day + " "):
                continue
            ts = _log_ts(line)
            mcur = re.search(r"褰撳墠璐﹀彿 uid=([0-9]+)", line)
            if mcur:
                if current is None:
                    current = mcur.group(1)
                continue
            if "璐﹀彿宸插彉" in line or "宸插垏鍙? in line:
                msw = re.search(r"([0-9]{6,})\s*(?:鈫抾->)\s*([0-9]{6,})", line)
                if not msw:
                    continue
                frm, to = msw.group(1), msw.group(2)
                if current is None:
                    current = frm
                if current and ts >= start:
                    intervals.append((current, start, ts))
                current = to
                start = ts
        if current:
            intervals.append((current, start, time.time() + 1))
    except Exception as e:
        log.debug("濂囬亣閾冨彴璐?bootstrap 璇?guard 鏃ュ織澶辫触: %r", e)

    mine = [(a, b) for who, a, b in intervals if who == str(uid)]
    bp = LOGS / "brain.bell.log"
    added = 0
    try:
        with open(bp, "rb") as f:
            bl = f.read().decode("utf-8", "replace").splitlines()
        for line in bl:
            if not line.startswith(day + " ") or "绋嶅悗鍐嶈亰宸插彂" not in line:
                continue
            ts = _log_ts(line)
            if not ts or not any(a <= ts <= b for a, b in mine):
                continue
            m = re.search(r"绋嶅悗鍐嶈亰宸插彂 '([^']+)'", line)
            if m:
                nick = m.group(1).strip()
                if nick:
                    nicks[nick] = {"at": ts, "status": "sent"}
                    added += 1
    except Exception as e:
        log.debug("濂囬亣閾冨彴璐?bootstrap 璇?bell 鏃ュ織澶辫触: %r", e)
    data["bootstrap_day"] = day
    if added:
        log.info("濂囬亣閾冨彴璐﹁縼绉伙細鎸変粖鏃ヨ处鍙峰尯闂磋ˉ鍏?%d 鏉″凡鍙戣褰曪紙uid=%s锛?,
                 added, uid)


def _ledger_load(uid):
    needs_save = False
    path = _ledger_file(uid)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("opened"), dict):
            raise ValueError("bad ledger")
    except Exception:
        data = {"version": 1, "opened": {}}

    now = time.time()
    opened = data["opened"]
    for k, v in list(opened.items()):
        at = float((v or {}).get("at", 0) or 0)
        if not at or now - at > BELL_LIST_LEDGER_TTL_S:
            opened.pop(k, None)
    nicks = data.setdefault("nicks", {})
    before_nicks = len(nicks)
    for k, v in list(nicks.items()):
        at = float((v or {}).get("at", 0) or 0)
        if not at or now - at > BELL_LIST_LEDGER_TTL_S:
            nicks.pop(k, None)
    _bootstrap_nicks_from_log(uid, data)
    if len(nicks) != before_nicks:
        needs_save = True
    data["version"] = 3
    if needs_save:
        _ledger_save(uid, data)
    return data


def _ledger_save(uid, data):
    path = _ledger_file(uid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_bell_", suffix=".swp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
                f.write("\n")
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
    except Exception as e:
        log.warning("淇濆瓨濂囬亣閾冨彴璐﹀け璐?uid=%s: %r", uid, e)


def _ledger_seen(uid, key, nick="", data=None):
    data = data or _ledger_load(uid)
    v = data.get("opened", {}).get(key)
    if v:
        if v.get("status") == "failed":
            if time.time() < float(v.get("retry_after", 0) or 0):
                return True
        else:
            return True
    nv = data.get("nicks", {}).get((nick or "").strip())
    if nv and nv.get("status") != "failed":
        return True
    return False


def bell_daily_count(uid, day=None):
    """鎸夎处鍙风粺璁′粖澶╃湡瀹炲彂鍑哄幓鐨勫紑鍦虹櫧鏁般€?""
    day = day or time.strftime("%Y-%m-%d")
    data = _ledger_load(uid)
    n = 0
    for v in data.get("nicks", {}).values():
        if (v or {}).get("status") != "sent":
            continue
        at = float((v or {}).get("at", 0) or 0)
        if time.strftime("%Y-%m-%d", time.localtime(at)) == day:
            n += 1
    return n


def profile_block_reason(prof):
    """涓婚〉鏄庣‘鎷掔粷鏆ф槯/绾︿細鏃惰繑鍥炲懡涓殑璇嶏紱鏅€氣€滃凡濠氣€濅笉鍗曠嫭鍛戒腑銆?""
    p = prof or {}
    bits = []
    for k in ("nick", "grav", "gravity", "soul"):
        if p.get(k):
            bits.append(str(p[k]))
    for k in ("tags", "moments"):
        v = p.get(k) or []
        if isinstance(v, (list, tuple)):
            bits.extend(str(x) for x in v)
        elif v:
            bits.append(str(v))
    txt = " ".join(bits)
    for w in PROFILE_BLOCK_WORDS:
        if w in txt:
            return w
    return ""


def _save_profile_after_send(actor, dev, db, prof, text, nick=""):
    """鎸夊垰鍙戝嚭鐨勬枃鏈弽鏌ュ敮涓€ sid锛屽啀鎶婁富椤靛啓杩涙鎯呭寘銆?""
    if not db or not prof:
        return None
    try:
        from brain import casepack as CP
        sid = CP.find_sid(db, text, device=dev, tries=2)
        if sid:
            CP.save_profile(sid, prof)
            log.info("馃敂 涓婚〉宸插啓鍏ユ鎯呭寘 %r sid=%s", nick or prof.get("nick") or "?", sid)
        else:
            log.warning("馃敂 涓婚〉宸叉姄鍒颁絾鍙嶆煡涓嶅埌鍞竴 sid锛屾殏涓嶅啓锛堝畞鍙笉鍐欎笉鍙啓閿欎汉锛?)
        return sid
    except Exception as e:
        log.warning("馃敂 淇濆瓨涓婚〉妗ｆ寮傚父: %r", e)
        return None


def _ocr_hit(dev, keyword):
    """鎴睆 OCR 鎵惧惈鍏抽敭瀛楃殑鏂囨湰鍧楋紝杩斿洖 (x, y, text) 鎴?None銆?""
    try:
        png = dev.screencap()
        for it in ocr.read(png):
            if keyword in it.text:
                return it.cx, it.cy, it.text
    except Exception as e:
        log.warning("OCR 鎵弿寮傚父: %r", e)
    return None


# 馃敶 2026-11-12锛圚Y-11锛夛細閾冩秷澶卞悗 UI 鏍戦噷杩樻畫鐣欍€屽悓鍩庡閬?/ 鍏抽棴寮圭獥銆嶆枃鏈紝
#   鑻ユ瘡杞兘鍘?OCR 鎵俱€岀珛鍗崇鑱娿€嶏紝涓€娆＄櫧鐑?~2.5s锛堝疄娴嬶級銆傝繖閲屽仛**鏈€杩戜竴娆?
#   OCR 纭疄娌℃壘鍒版寜閽?*鐨勮蹇嗭細娈嬬暀鏂囨湰 + 鍒?OCR 杩囦笖娌℃寜閽?鈫?鐩存帴鍒ゃ€屽凡娑堝け銆?
#   璺宠繃 OCR锛岀洿鍒拌繃浜?RESIDUAL_SKIP_S 鍐嶇粰涓€娆℃満浼氾紙閾冪湡寮瑰嚭鏃舵寜閽細鍥炴潵锛夈€?
#   鍙奖鍝嶃€岀渷涓€娆?OCR銆嶏紝缁濅笉鏀瑰彉 is_bell 鐨勮繑鍥炶涔夈€?
RESIDUAL_SKIP_S = float(os.environ.get("SOUL_BELL_RESIDUAL_SKIP", "30") or 30)
_RESIDUAL = {"ts": 0.0}


def is_bell(snap=None, dev=None):
    """褰撳墠鏄笉鏄脊鐫€濂囬亣閾冦€?

    馃敶 鍒ゆ嵁浼樺厛绾э紙2026-11-02 瀹炲脊鏁欒锛夛細
      閾冩秷澶卞悗锛孶I 鏍戦噷**杩樻畫鐣?*銆屽悓鍩庡閬?/ 鍏抽棴寮圭獥銆嶈繖浜涙枃鏈妭鐐癸紝
      鍙寜鏍戝垽鏂細涓€鐩存姤銆屾湁閾冦€嶏紝鐒跺悗 OCR 鍙堟壘涓嶅埌鎸夐挳 鈫?绌鸿浆銆?
      鎵€浠ワ細**缁欎簡 dev 灏变互 OCR 鎵惧埌銆岀珛鍗崇鑱娿€嶄负鍑?*锛堟寜閽瓨鍦ㄦ墠鏄湡閾冿級锛?
      娌＄粰 dev 鎵嶉€€鍥炴爲鍒ゆ柇锛堜緵涓嶉渶瑕佺偣鍑荤殑鍦哄悎鐢級銆?

    馃敶 2026-11-12锛圚Y-11锛夛細娈嬬暀鏂囨湰 + 鏈€杩戜竴娆?OCR 娌℃壘鍒版寜閽?鈫?鐩存帴 False锛?
      涓嶅啀姣忔鑺?2.5s OCR锛堥搩娑堝け鍚庢畫鐣欏彲鑳芥寔缁ソ鍑犱釜鍔ㄤ綔杞級銆?
    """
    import time as _t
    try:
        hinted = None
        if snap is not None:
            txt = " ".join(snap.texts())
            hinted = any(k in txt for k in BELL_HINTS)
            # 鏍戦噷涓€鐐硅抗璞￠兘娌℃湁 -> 鐩存帴 False锛屼笉蹇呰姳 2.5s 鍘?OCR
            if not hinted and dev is not None:
                return False
        if dev is not None:
            if hinted:
                # 娈嬬暀鏂囨湰浣嗗垰 OCR 杩囦笖娌℃寜閽?鈫?瑙嗕负宸叉秷澶憋紝璺宠繃鏈 OCR
                if _t.time() - _RESIDUAL["ts"] < RESIDUAL_SKIP_S:
                    return False
            hit = find_button(dev)
            if hit is None:
                _RESIDUAL["ts"] = _t.time()   # 璁颁綇銆岃繖娆℃病鎵惧埌鎸夐挳銆?
            return hit is not None
        return bool(hinted)
    except Exception as e:
        log.warning("閾冭瘑鍒紓甯革紙鎸夋棤閾冨鐞嗭級: %r", e)
    return False


def find_button(dev):
    """OCR 鎵俱€岀珛鍗崇鑱娿€嶆寜閽€傝繑鍥?(x, y, text) 鎴?None銆?""
    return _ocr_hit(dev, BELL_BTN)


def find_nick(dev):
    """OCR 璇婚搩涓婄殑瀵规柟鏄电О锛堟寜閽笂鏂归偅涓€琛屽ぇ瀛楋級銆?

    瀹炲脊甯冨眬锛氭樀绉?y鈮?98锛屾寜閽?y鈮?53銆傚彇銆屾寜閽笂鏂?80~450px 涔嬮棿銆?
    闀垮害 2~16銆佷笉鏄浐瀹氭枃妗堛€嶇殑閭ｄ竴琛屻€?
    """
    try:
        png = dev.screencap()
        items = ocr.read(png)
    except Exception:
        return ""
    btn_y = None
    for it in items:
        if BELL_BTN in it.text:
            btn_y = it.cy
            break
    if btn_y is None:
        return ""
    skip = ("鍦ㄧ嚎", "濂囬亣閾?, "鍚屽煄濂囬亣", "鏈夎叮鐨勭伒榄?, "Soul")
    cands = [it for it in items
             if 60 < btn_y - it.cy < 450
             and 2 <= len(it.text.strip()) <= 16
             and not any(s in it.text for s in skip)]
    if not cands:
        return ""
    # 鏈€闈犺繎鎸夐挳鐨勯偅涓€琛岋紙y 鏈€澶э級
    cands.sort(key=lambda it: -it.cy)
    return cands[0].text.strip()


def handle(actor, dev, dry_run=False, db=None):
    """澶勭悊涓€涓閬囬搩銆傝繑鍥?(ok, 璇存槑)銆?

    缁濅笉鎶涘紓甯稿嚭鍘?鈥斺€?閾冨鐞嗗け璐ヤ笉鑳芥嫋鍨富娴佺▼銆?
    """
    try:
        hit = find_button(dev)
        if hit is None:
            log.warning("璁ゅ嚭鐤戜技閾冿紝浣?OCR 鎵句笉鍒般€岀珛鍗崇鑱娿€嶏紙鍙兘宸叉秷澶憋級")
            return False, "鎵句笉鍒版寜閽?
        bx, by, _ = hit
        nick = find_nick(dev)
        log.info("馃敂 濂囬亣閾冿細瀵规柟=%r锛屾寜閽?(%d,%d)", nick or "?", bx, by)

        actor.hand.tap_xy(bx, by, settle=2.5)
        s2, pg = actor.wait_page(("chat",), timeout=8.0)
        if pg != "chat":
            log.warning("鐐圭珛鍗崇鑱婂悗娌¤繘浼氳瘽锛?s锛?, pg)
            return False, "娌¤繘浼氳瘽(%s)" % pg

        from brain import match as M
        try:
            said, bubbles = M.said_already(dev, s2)
        except Exception as e:
            log.warning("濂囬亣閾冨凡鏈夋秷鎭鏌ュけ璐ワ紙鎸夋湭鍙戝鐞嗭級: %r", e)
            said, bubbles = False, []
        if said:
            log.info("馃敂 濂囬亣閾冨璞″凡鏈夋秷鎭紙姘旀场 %d 鏉★級鈫?涓嶉噸澶嶅彂", len(bubbles))
            actor.hand.back(settle=1.0)
            return True, "宸叉湁娑堟伅"

        # 鐢ㄦ埛鍙ｅ緞锛氬閬囬搩涔熻鍏堢湅涓婚〉锛涗富椤垫槑纭€滀笉鎾?涓嶇害鈥濈殑鐩存帴璺宠繃銆?
        prof = None
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("馃敂 閾冨璞′富椤? %r %r", prof.get("nick"), prof.get("tags"))
        except Exception as e:
            log.warning("閾冨璞″缓妗ｅ紓甯革紙缁х画鍙戦€侊級: %r", e)
        block = profile_block_reason(prof)
        if block:
            log.info("馃敂 璺宠繃濂囬亣閾冨璞?%r锛氫富椤垫槑纭啓銆?s銆?, nick or "?", block)
            actor.hand.back(settle=1.0)
            return True, "涓婚〉鎷掔粷鏆ф槯(%s)" % block

        if dry_run:
            log.info("[dry] 宸茶繘閾冧細璇濓紝涓嶅彂閫?)
            actor.hand.back(settle=1.0)
            return True, "dry"

        text = M.pick_opener()
        # 鏂颁細璇濆紑鍦虹櫧鏃?sid 鈫?璧?match.send 鐨?sid="" 鍒嗘敮锛岃繃闂镐絾涓嶅崰璺熻繘棰濆害
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("鉁?濂囬亣閾冨凡鍙? %r", text)
            _save_profile_after_send(actor, dev, db, prof, text, nick)
        else:
            log.warning("濂囬亣閾冨彂閫佸け璐? %s", why)

        actor.hand.back(settle=1.2)
        return ok, why
    except Exception as e:
        log.warning("濂囬亣閾冨鐞嗗紓甯革紙宸插厹浣忥級: %r", e)
        try:
            actor.hand.back(settle=1.0)
        except Exception:
            pass
        return False, repr(e)


def _find_list_entry(snap):
    for n in snap.nodes:
        if not n.visible:
            continue
        if (n.text or "").strip() == "濂囬亣閾?绋嶅悗鍐嶈亰":
            return n
    return None


def open_list(actor, max_scrolls=4):
    """浠庝細璇濆垪琛ㄧ偣杩涖€屽閬囬搩-绋嶅悗鍐嶈亰銆嶃€傝繑鍥?(ok, 璇存槑)銆?

    瀹炴祴锛?026-11-08 11:24锛夛細浼氳瘽鍒楄〃閲屾湁涓€琛?
        濂囬亣閾?绋嶅悗鍐嶈亰 / 鏈夋柊鏈嬪弸绛変綘鍜孴a寮€鍚璇?/ 10:26
    鐐瑰畠 鈫?LoveBellChatListActivity銆?
    鈿狅笍 娉ㄦ剰瀹?*涓嶆槸** chatlist.Row锛堟病鏈?/name銆?time res-id 鐨勬櫘閫氳缁撴瀯涔熷彲鑳芥湁锛夛紝
       鎵€浠ヨ繖閲屼笉璧?chatlist.rows()锛岀洿鎺ュ湪鏍戦噷鎸夋枃鏈壘鑺傜偣锛岀ǔ涓斾笉鍙楄楂橀椄褰卞搷銆?
    """
    try:
        snap = actor.snap(force=True)
    except Exception as e:
        return False, repr(e)
    if is_bell_list(snap):
        return True, "宸插湪绋嶅悗鍐嶈亰鍒楄〃"
    if detect(snap) != "chatlist":
        try:
            from brain import nav
            snap, pg = nav.to_chatlist(actor)
            if pg != "chatlist":
                return False, "涓嶅湪浼氳瘽鍒楄〃(%s)" % pg
        except Exception as e:
            return False, "鍥炰細璇濆垪琛ㄥけ璐? %r" % e

    node = _find_list_entry(snap)

    # 2026-11-13 瀹炴祴锛氭竻瀹岀孩鐐瑰悗鍒楄〃甯稿仠鍦ㄤ腑闂达紝鍏ュ彛鏄庢槑瀛樺湪鍗村彧鎼滃綋鍓嶅睆
    # 浼氳鎶モ€滄病鏈夊叆鍙ｂ€濄€傚厛鍚戜笅婊戝洖椤堕儴锛屽啀鍚戜笂缈诲嚑灞忥紱姣忔閲嶆柊 dump銆?
    if node is None:
        for _ in range(max(1, max_scrolls)):
            try:
                actor.hand.swipe(450, 420, 450, 1340, duration=0.18, settle=0.5)
            except Exception:
                break
            snap = actor.snap(force=True)
            node = _find_list_entry(snap)
            if node is not None:
                break

    if node is None:
        for _ in range(max(1, max_scrolls)):
            try:
                actor.hand.swipe(450, 1320, 450, 520, duration=0.35, settle=0.7)
            except Exception:
                break
            snap = actor.snap(force=True)
            if is_bell_list(snap):
                return True, "宸插湪绋嶅悗鍐嶈亰鍒楄〃"
            node = _find_list_entry(snap)
            if node is not None:
                break
            if detect(snap) != "chatlist":
                break

    if node is None:
        return False, "浼氳瘽鍒楄〃娌℃湁銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶅叆鍙?
    log.info("馃敂 浼氳瘽鍒楄〃鍙戠幇銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶁啋 鐐硅繘鍘?)
    actor.hand.tap_node(node, settle=2.5)
    s2 = actor.snap(force=True)
    if not is_bell_list(s2):
        return False, "鐐硅繘鍘诲悗涓嶆槸绋嶅悗鍐嶈亰椤?%s)" % detect(s2)
    return True, "宸茶繘鍏ョ◢鍚庡啀鑱婂垪琛?


def preempt(actor, dev=None):
    """闀垮姩浣滀箣闂存彃涓€鍙ユ鏌ワ細鏈夐搩灏卞厛澶勭悊銆傝繑鍥炴槸鍚﹀鐞嗕簡銆?""
    dev = dev or actor.dev
    try:
        if not is_bell(actor.snap(force=True), dev=dev):
            return False
    except Exception:
        return False
    log.info("鈿?妫€娴嬪埌濂囬亣閾?鈫?涓柇褰撳墠鍔ㄤ綔鍏堝鐞?)
    ok, why = handle(actor, dev)
    return ok


# ---------------- 濂囬亣閾冦€岀◢鍚庡啀鑱娿€嶅垪琛紙2026-11-08 鏂板锛?----------------
def is_bell_list(snap):
    """褰撳墠灞忔槸涓嶆槸銆屽閬囬搩-绋嶅悗鍐嶈亰銆嶅垪琛ㄩ〉銆?

    瀹炴祴鐗瑰緛锛?026-11-08 11:24 dump锛夛細鏍囬銆屽閬囬搩-绋嶅悗鍐嶈亰銆? 鍙充笂銆屾洿澶氬閬囥€嶏紝
    涓斿垪琛ㄨ甯︺€屽悓鍩庡閬?/ 鍚屽煄鐨勪粬锛屽幓鎵撲釜鎷涘懠銆嶆爣绛俱€?
    鍒ゆ嵁鍙栥€屾爣棰?+ 鏇村濂囬亣銆嶄袱鏉″悓鏃跺懡涓紝閬垮厤鍜屾櫘閫氫細璇濆垪琛ㄦ贩娣嗐€?
    """
    try:
        txt = " ".join(snap.texts())
    except Exception:
        return False
    return all(k in txt for k in BELL_LIST_HINTS)


def bell_list_rows(snap):
    """瑙ｆ瀽銆岀◢鍚庡啀鑱娿€嶅垪琛紝杩斿洖 [(nick, cx, cy, tag, time_str)]锛堣嚜涓婅€屼笅锛夈€?

    瀹炴祴琛岀粨鏋勶紙900x1600锛夛細
        澶村儚 (32,232,136,336) desc=澶村儚
        鏄电О (160,240,310,281)  e.g. 鍌诲瓙鐪嬪偦瀛?
        鏍囩 (318,246,542,274)  e.g. 鍚屽煄鐨勪粬锛屽幓鎵撲釜鎷涘懠 / 鍚屽煄濂囬亣
        鏃堕棿 (810,244,868,277)  e.g. 10:26
    琛屼腑蹇?y 鍙栨樀绉颁腑蹇冿紱鐐瑰嚮鐐瑰彇鏁磋涓績锛坸=450, y=鏄电О y锛夈€?
    """
    out = []
    nodes = [n for n in snap.nodes if n.visible]
    nicks = [n for n in nodes
             if n.text.strip()
             and n.text.strip() not in BELL_LIST_SKIP
             and not any(t in n.text for t in BELL_ROW_TAGS)
             and 150 <= n.bounds[0] <= 400
             and 2 <= len(n.text.strip()) <= 16
             and n.bounds[3] - n.bounds[1] < 60]
    # 馃敶 2026-11-10 搂111锛圥0 璇彂锛夛細鍚屼竴琛岀殑銆屾樀绉?/ 鐩稿悓鐐癸細xxx / Ta璺濈Nkm銆嶄笁涓枃鏈?
    #   鑺傜偣鍏ㄩ儴婊¤冻涓婇潰鐨勭瓫閫夋潯浠?鈫?琚綋鎴?3 涓汉 鈫?姣忎釜閮界偣鍚屼竴琛屻€佸悇鍙戜竴鏉″紑鍦虹櫧
    #   锛堝疄娴?16:35 缁欍€岄檲闄堟槦銆嶈繛鍙?3 鏉★細銆屾垜杩欒竟鍒氬繖瀹屸€︺€嶃€屾垜鍙互鍏堣璁叉垜鑷繁鈥︺€?
    #    銆屾垜杩欎汉璇濅笉澶氣€︺€嶏級銆傚疄娴嬭楂樼害 104px銆佺湡瀹炰袱琛屼腑蹇冪浉璺?~164px锛?
    #   鎵€浠ユ寜琛屼腑蹇?y 鑱氱被锛堥槇鍊?60锛夛紝鍚屼竴琛屽彧鐣?*鏈€闈犱笂**鐨勯偅涓紙涓讳綋鏄电О锛夈€?
    _picked = []
    for _n in sorted(nicks, key=lambda x: (x.bounds[1], x.bounds[0])):
        _cy = (_n.bounds[1] + _n.bounds[3]) // 2
        if any(abs(_cy - _p[0]) <= 60 for _p in _picked):
            continue
        _picked.append((_cy, _n))
    nicks = [x[1] for x in _picked]
    for n in nicks:
        t = n.text.strip()
        cy = (n.bounds[1] + n.bounds[3]) // 2
        tag = ""
        ts = ""
        for m in nodes:
            if abs(((m.bounds[1] + m.bounds[3]) // 2) - cy) > 45:
                continue
            mt = m.text.strip()
            if any(x in mt for x in BELL_ROW_TAGS):
                tag = mt
            elif m.bounds[0] >= 780 and mt:
                ts = mt
        out.append((t, (n.bounds[0] + n.bounds[2]) // 2, cy, tag, ts))
    out.sort(key=lambda x: x[2])
    return out


def handle_list(actor, dev, dry_run=False, limit=None, db=None, uid="", max_scrolls=8):
    """鎶娿€屽閬囬搩-绋嶅悗鍐嶈亰銆嶉噷鐨勪汉閫愪釜鑱婅捣鏉ャ€傝繑鍥?(n_ok, 璇存槑)銆?

    鐢ㄦ埛 2026-11-08锛氥€屽閬囬搩 绋嶅悗鍐嶈亰 閲岄潰鏈変笁涓汉绛夌潃瀵硅瘽鍟婏紝浼樺厛绾у閬囬搩涓嶆槸鏈€楂樺悧銆?
    鈥斺€?杩欐潯閾捐矾蹇呴』骞跺叆濂囬亣閾冩渶楂樹紭鍏堢骇锛屼笖姣忎釜閮借**鍙戝紑鍦虹櫧 + 杩涗富椤靛缓妗?*銆?

    2026-11-13 鐢ㄦ埛鍙ｅ緞锛氳繖閲岀殑浜鸿灏介噺娓呯┖锛屼笉鍐嶆寜 3 浜?澶╃‖鎴柇銆?
    涓€杞彧鍋氫竴灏忔壒锛圔ELL_BATCH_MAX锛夛紝鍚庣画杞缁х画锛涘悓涓€浜虹敤涓夋€佸幓閲嶏細
      鈶?浼氳瘽閲屽凡鏈夋垜鐨勬皵娉?鈫?涓嶅彂锛?
      鈶?鎸佷箙鍙拌处璁板綍宸插彂/宸茶烦杩囷紱
      鈶?鍙戦€佸け璐ュ喎 30 鍒嗛挓鍐嶈瘯銆?

    姣忓鐞嗕竴涓細鐐硅 鈫?纭杩涗細璇?鈫?宸叉湁娑堟伅妫€鏌?鈫?鍏堢湅涓婚〉 鈫?鍙戝紑鍦虹櫧
    鈫?鍙嶆煡鍞竴 sid 鍐欐鎯呭寘 鈫?杩斿洖鍒楄〃銆?
    澶勭悊瀹屼竴涓悗**閲嶆柊 dump 鍒楄〃**锛堣浼氭秷澶?涓婄Щ锛屼笉鑳界紦瀛樺潗鏍囷級銆?
    """
    from brain import match as M

    limit = max(1, int(limit or BELL_BATCH_MAX))
    done = 0
    skipped = 0
    attempted = 0
    tried = set()
    known_keys = set()
    max_rows = 0
    scrolls = 0
    ledger = _ledger_load(uid)

    def _mark(key, status, nick="", tag="", row_ts="", retry_after=0):
        at = time.time()
        ledger["opened"][key] = {
            "at": at,
            "status": status,
            "nick": nick,
            "tag": tag,
            "row_ts": row_ts,
            "retry_after": retry_after,
        }
        if nick:
            ledger.setdefault("nicks", {})[nick] = {
                "at": at,
                "status": status,
                "retry_after": retry_after,
            }
        _ledger_save(uid, ledger)

    max_loops = max(12, limit * 4 + max_scrolls)
    for _ in range(max_loops):
        if done >= limit:
            break
        snap = actor.snap(force=True)
        if not is_bell_list(snap):
            if done == 0:
                return 0, "涓嶅湪绋嶅悗鍐嶈亰鍒楄〃(%s)" % detect(snap)
            break

        rows = bell_list_rows(snap)
        max_rows = max(max_rows, len(rows))
        unseen = []
        for r in rows:
            key = _row_key(r[0], r[3], r[4])
            if key in tried:
                continue
            if _ledger_seen(uid, key, nick=r[0], data=ledger):
                known_keys.add(key)
                continue
            unseen.append((r, key))

        if not unseen:
            if scrolls >= max_scrolls:
                break
            before = tuple(_row_key(r[0], r[3], r[4]) for r in rows)
            try:
                # 鎵嬫寚涓婃粦 = 鐪嬪垪琛ㄦ洿闈犱笅鐨勪汉銆傚姩浣滃悗寮哄埗閲嶅彇锛屼笉鑳藉鐢ㄦ棫甯с€?
                actor.hand.swipe(450, 1320, 450, 620, duration=0.35, settle=0.8)
            except Exception as e:
                log.warning("濂囬亣閾冨垪琛ㄦ粴鍔ㄥ紓甯? %r", e)
                break
            s2 = actor.snap(force=True)
            if not is_bell_list(s2):
                break
            after = tuple(_row_key(r[0], r[3], r[4]) for r in bell_list_rows(s2))
            scrolls += 1
            if before and before == after:
                log.info("濂囬亣閾冨垪琛ㄥ凡鍒板簳锛堟粴鍔?%d 娆℃棤鍙樺寲锛?, scrolls)
                break
            continue

        (nick, cx, cy, tag, ts), key = unseen[0]
        tried.add(key)
        attempted += 1
        log.info("馃敂 绋嶅悗鍐嶈亰锛?r锛?s %s锛夆啋 鐐硅繘浼氳瘽", nick, tag, ts)
        actor.hand.tap_xy(450, cy, settle=2.5)
        s2 = actor.snap(force=True)
        pg = detect(s2)
        if pg != "chat":
            log.warning("鐐?%r 鍚庢病杩涗細璇濓紙page=%s锛夆啋 璺宠繃", nick, pg)
            _mark(key, "failed", nick, tag, ts, time.time() + BELL_FAIL_RETRY_S)
            skipped += 1
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue

        try:
            said, bubbles = M.said_already(dev, s2)
        except Exception as e:
            log.warning("绋嶅悗鍐嶈亰宸叉湁娑堟伅妫€鏌ュけ璐ワ紙鎸夋湭鍙戝鐞嗭級: %r", e)
            said, bubbles = False, []
        if said:
            log.info("馃敂 绋嶅悗鍐嶈亰 %r 宸叉湁鎴戠殑娑堟伅锛堟皵娉?%d 鏉★級鈫?涓嶉噸澶嶅彂", nick, len(bubbles))
            _mark(key, "already", nick, tag, ts)
            skipped += 1
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue

        if dry_run:
            log.info("[dry] 宸茶繘 %r 浼氳瘽锛屼笉鍙戦€?, nick)
            actor.hand.back(settle=1.2)
            done += 1
            continue

        prof = None
        try:
            prof, pok = M.visit_profile(actor)
            if pok and prof:
                log.info("馃敂 绋嶅悗鍐嶈亰涓婚〉 %r: %s", nick, prof.get("nick"))
        except Exception as e:
            log.warning("绋嶅悗鍐嶈亰涓婚〉寮傚父锛堢户缁彂閫侊級: %r", e)
        block = profile_block_reason(prof)
        if block:
            log.info("馃敂 璺宠繃绋嶅悗鍐嶈亰 %r锛氫富椤垫槑纭啓銆?s銆?, nick, block)
            _mark(key, "blocked", nick, tag, ts)
            skipped += 1
            try:
                actor.hand.back(settle=1.2)
            except Exception:
                pass
            continue

        text = M.pick_opener()
        # 鏂颁細璇濆紑鍦虹櫧鏃?sid 鈫?璧?match.send 鐨?sid="" 鍒嗘敮锛岃繃闂镐絾涓嶅崰璺熻繘棰濆害
        ok, why = M.send(actor, dev, text)
        if ok:
            log.info("鉁?绋嶅悗鍐嶈亰宸插彂 %r: %r", nick, text)
            _mark(key, "sent", nick, tag, ts)
            _save_profile_after_send(actor, dev, db, prof, text, nick)
        else:
            log.warning("绋嶅悗鍐嶈亰鍙戦€佸け璐?%r: %s", nick, why)
            _mark(key, "failed", nick, tag, ts, time.time() + BELL_FAIL_RETRY_S)
            skipped += 1
        if ok:
            done += 1
        try:
            actor.hand.back(settle=1.2)
        except Exception:
            pass
    return done, "绋嶅悗鍐嶈亰宸插彂 %d 浜?/ 璺宠繃 %d / 妫€鏌?%d / 宸插彂杩?%d / 鍗曞睆鏈€澶?%d / 婊氬姩 %d" % (
        done, skipped, attempted, len(known_keys), max_rows, scrolls)
