# -*- coding: utf-8 -*-
"""鏄熺悆鐏甸瓊鍖归厤锛氳璧勬枡 -> 鍑哄紑鍦虹櫧 -> 鍙戦€?-> 鍖归厤涓嬩竴涓?/ 鍥炴槦鐞冮噸鏂板尮閰嶃€?

纭鍒欙紙鐢ㄦ埛 2026-11-02 瀹氾級锛?
  1. **姣忔鍖归厤鍚庡繀椤诲厛鎶婂紑鍦虹櫧鍙戝嚭鍘伙紝鍐嶇偣銆屽尮閰嶄笅涓€涓€?*锛屽惁鍒欒繖涓€澶╃殑
     鍖归厤娆℃暟灏辩櫧璐逛簡銆?
  2. 鍙戝畬鍚庣偣浼氳瘽椤靛乏涓婅銆屽尮閰嶄笅涓€涓€嶏紱娌℃湁鎸夐挳鎴栨病鎹㈡垚鏂板崱灏卞仠鎵嬶紝涓嶉噸澶嶇偣銆?
  3. 寮€鍦虹櫧鐢?*閫氱敤寮€鍦虹櫧**锛堢敤鎴?2026-11-02 瀹氾級锛屼笉鐢ㄥ紩鎿庣幇鐢熸垚銆?

涓轰粈涔堜笉鍐嶇敤鏃у紩鎿庣敓鎴愬尮閰嶅紑鍦虹櫧锛坋ngine_gen=True 浠嶄繚鐣欙級锛?
  瀹炴祴 `opening_line(kind="match")` 鍦ㄦ病鏈夊鏂硅祫鏂欐椂浼氭妸鎴戣嚜宸辩殑淇℃伅
  锛堟睙鍗?/ 缍︽睙涓夋睙 / 寮€缃戝簵鍗栨暟鐮侊級褰撴垚濂圭殑缂栧嚭鍘伙紝4 鏉″€欓€夊叏搴燂細
    銆岃繖涓夋睙鍋跺皵涔熶細鎯宠捣浣犮€傘€嶃€岀湅浣犲湪涓夋睙鍗栨暟鐮佹尯宸х殑銆傘€?
  鍖归厤娆℃暟鎸夊ぉ闄愰噺锛屽畞鍙彂涓€鍙ョǔ鐨勯€氱敤鍙ワ紝涔熶笉鑳芥氮璐逛竴娆″尮閰嶃€?
"""
import re
import time

from core.log import get_logger
from eyes.page import detect

log = get_logger("brain.match")

NEXT_TEXT = "鍖归厤涓嬩竴涓?      # 浼氳瘽椤靛乏涓婅锛涘疄娴?res=tv_rem
MATCH_ENTRY_TEXTS = ("鐏甸瓊鍖归厤", "寮€濮嬪尮閰?, "绔嬪嵆瀵绘壘鎳備綘鐨勪汉")
REMAIN_RE = re.compile(r"浠婃棩鍓╀綑\s*(\d+)\s*娆?)
LIMIT = 20                    # 涓庢棫寮曟搸 opening_line 榛樿涓€鑷?
# 馃敶 2026-11-08锛坃report/14 瀹炴祴锛歮atch 寮€鍦虹櫧闂彞鐜?31.3%锛?
#   鐩爣绾匡細纭棶鍙?鈮?2%锛堝榻愬洖澶嶄晶 12.5% 鐨勬按骞筹紝涓嶅啀鍋氥€岄棶鍙ヤ紭鍏堛€嶏級銆?
OPEN_ASK_RATE = 0.12

# 鍖归厤鍗＄墖/浼氳瘽棰橀噷鐨勫浐瀹氭枃妗堬紝鎶芥樀绉版椂蹇呴』鎺掗櫎
UI_TEXTS = {
    "澶村儚", "鏌ョ湅涓婚〉", "鍖归厤搴?, "鍏虫敞", "鑱婂ぉ璁剧疆", "鍙戦€?, "璇煶", "琛ㄦ儏", "鏇村",
    "鏃╀笂濂?, "浜ゆ崲绛旀", "妗岀悆", "绀肩墿", "涓€璧峰惉", "AI鍔╂墜", "鏂囨槑鑱婂ぉ锛屽弸鍠勪氦鍙媬",
    "鍏虫敞鍚庡彲閭€璇烽€氳瘽", "鎵嬫満淇″彿婊℃牸銆?, "WLAN 淇″彿婊℃牸銆?,
}

# 銆屼綘涔熷湪鈥﹀悧銆嶈繖绫绘妸鑷繁鐨勪俊鎭鍒板ス韬笂锛堟棫寮曟搸 _OPEN_RULES 绗?2 鏉℃湰灏辩姝紝
# 浣嗗疄娴嬩粛浼氭紡鍑烘潵锛岃繖閲屼綔涓虹‖鎷︼級
BAD_RE = (
    re.compile(r"浣犱篃[鍦ㄦ槸鍋氭悶]"),
    re.compile(r"浣犱篃鏄?),
    re.compile(r"鍜变咯閮?),
    re.compile(r"鎴戜滑閮?),
    re.compile(r"^鐪嬪埌浣?),
    re.compile(r"^鍚"),
)

# 鐤戦棶鏍囪锛氬紑鍦虹櫧鏈€濂芥槸鑳借濂规帴璇濈殑闂彞
# 鈿狅笍 淇濈暀鍘熷悕缁欐棫璋冪敤鏂癸紱璇箟宸茬粡鍙嶈浆 鈥斺€?鐜板湪闂彞鏄?*鍑忓垎椤?*锛?
#    瑙?ASK_HARD 涓?score() 鐨勬敞閲婏紙2026-11-08 闄嶉棶鍙ョ巼锛夈€?
ASK_RE = re.compile(r"[锛?]|鍚梶鍛涓峾鍟浠€涔坾鎬庝箞|鍜媩鍑爘鍝獆澶氬皯|鏈夋病鏈?)

# 馃敶 2026-11-08锛堜緷鎹?_report/14 瀹炴祴锛歮atch 寮€鍦虹櫧闂彞鐜?31.3%锛岀洰鏍?<12%锛?
#
#   鏃ч€昏緫鏄€岄棶鍙ヤ紭鍏堛€嶏細`score()` 閲?`if ASK_RE.search(text): s += 3`锛?
#   涓?`opening()` 涓€鏃︽嬁鍒般€屽悎鏍间笖鏄棶鍙ャ€嶅氨 `return` 鎻愬墠鏀跺伐銆?
#   缁撴灉鍏ㄦ槸鏌ユ埛鍙ｏ細`浣犳槸寮€缃戝簵鐨勫悧锛焋 `浣犱篃浣忛噸搴嗗悧锛焋 `浣犲湪閲嶅簡鎵撴嫾鍚梎銆?
#   瀹¤瀹炴祴杩欎簺鍙ュ瓙鐨勯棶鍙ョ巼鏄洖澶嶄晶锛?2.5%锛夌殑 2.5 鍊嶃€?
#
#   涓轰粈涔堥棶鍙ヤ笉鏄ソ浜嬶紙鏁版嵁锛夛細鎶ュ憡-11 鐨勪繚鎸佺儹搴?offer鍨?37.5% / probe鍨?25.9%锛?
#   鑰?match 寮€鍦虹櫧杩欎簺闂彞鍏ㄦ槸 **probe 鍨嬶紙瑕佸ス鎻愪緵淇℃伅锛?*锛?
#   鍦ㄩ檶鐢熷満鏅瓑浜庣涓€娆¤璇濆氨鏌ユ埛鍙?鈥斺€?鍙嶉棶鍘嬪姏澶с€佸洖澶嶇巼浣庛€?
#
#   鏂扮瓥鐣ワ細**闄堣堪鍙ヤ紭鍏?*銆傞檲杩板彞鑷甫涓€涓彲鎺ョ殑璇濆ご锛屽ス鎰挎剰鎺ュ氨鎺ワ紝
#   涓嶆効鎺ヤ篃娌″帇鍔涖€傚彧淇濈暀灏戦噺銆岀粰寰楄捣涓滆タ銆嶇殑 offer 鍨嬮棶鍙ワ紙瑕佷笉瑕?鎴戣浣犺繖绉嶏級銆?
#   `ASK_HARD` 鎵嶆槸銆岀‖闂彞銆嶅垽鎹紙鐪熸鐨勭枒闂彞锛夛紝姣?ASK_RE 绐勶細
#   ASK_RE 浼氭妸銆屼笉銆嶃€屽嚑銆嶃€屽摢銆嶈繖绉嶅瓧闈篃褰撻棶鍙ワ紝鐢ㄦ潵鍘嬪垎澶矖鏆淬€?
#   鈿狅笍 2026-11-08 浜屾淇锛氬垵鐗堟紡浜嗐€屽共鍟?鍜嬫牱/鍦ㄥ摢/澶氬皯銆嶈繖绫?*鏃犻棶鍙风枒闂彞**
#   锛坄鍖归厤鍒颁綘浜嗭紝骞虫椂杩欎釜鐐归兘鍦ㄥ共鍟 琚鍒ゆ垚闄堣堪鍙ワ紝杩樻嬁浜?+3锛夈€?
#   鐜板湪鎶婄枒闂瘝琛ュ叏锛屼絾**鍙鍑虹幇鍦ㄥ悗鍗婂彞/鍙ュ熬鐨?*锛岄伩鍏嶃€屼笉鐭ヤ笉瑙夈€嶈繖绫昏浼ゃ€?
ASK_HARD = re.compile(
    r"[锛?]\s*$"
    r"|(?:鍚梶鍛涔坾涓峾娌?\s*$"
    r"|(?:浠€涔坾鍟鎬庝箞|鍜媩鍝獆涓轰粈涔坾涓哄暐|澶氬皯|鍑燵鐐逛釜宀乚|澶氫箙|骞蹭粈涔坾骞插暐)"
    r"(?:鍛鍟妡鍛€|鍢泑浜??\s*$"
    r"|(?:鍦▅鍋殀骞瞸鏄瘄鏈墊瑕亅鎯硘浼殀鑳絴鐖眧鍠滄|閫墊鐪媩鍚億鐜﹟鍚?(?:浠€涔坾鍟鍝獆鍑?"
)
# 浣庡帇鍔涢棶鍙ワ細闂ス**姝ゅ埢鐘舵€?*锛堜笉娑夊強韬唤/宸ヤ綔/浣忓潃/骞撮緞/浣滄伅瑙勫緥锛夛紝姣旀煡鎴峰彛杞讳竴妗?
# 鈿狅笍 2026-11-08 浜屾淇锛氬垵鐗堝惈銆岃繖涓偣銆嶏紝鎶?`鍖归厤鍒颁綘浜嗭紝骞虫椂杩欎釜鐐归兘鍦ㄥ共鍟
#    涔熸斁杩涗簡杞荤綒妗ｏ紙閭ｅ垎鏄庢槸鍦ㄧ洏闂綔鎭寰?= 鏌ユ埛鍙ｏ級銆傚凡鏀剁獎鍒般€屾鍒荤姸鎬併€嶃€?
SOFT_ASK_RE = re.compile(r"鍒氬繖瀹寍闂茬潃鍛杩欎細鍎?*杩樻槸|鍦ㄥ繖鍟杩藉暐鍓?)
# offer 鍨嬮棶鍙ョ櫧鍚嶅崟锛氶棶鐨勬槸銆屾垜缁欏緱璧蜂粈涔堛€嶏紝涓嶆槸銆屼綘韬笂鏈変粈涔堜俊鎭€?
OFFER_RE = re.compile(r"瑕佷笉瑕佹垜|鎴戝府浣爘鎴戠粰浣爘鎴戦櫔浣爘鎴戣浣爘鎴戝甫浣犲幓|澶熶笉澶焲濂戒笉濂?)

# 杩欎簺璇嶆槸缁欐垜鐪嬬殑锛屼笉璁稿嚭鐜板湪鍙ュ瓙閲岋紙鏃у紩鎿?_OPEN_RULES 绗?7 鏉★級
META_WORDS = ("寮曞姏绛?, "鍏卞悓鐐?, "璧勬枡", "鏍囩", "鍖归厤搴?, "鏄熺悆", "绀间华鍒?, "鏄熷骇")

# 馃敶 鎴戣嚜宸辩殑涓撳睘淇℃伅锛堝彇鑷?soul_rules.PERSONA锛氭睙鍗?缍︽睙涓夋睙/寮€缃戝簵鍗栨暟鐮侊級銆?
#   瀹炴祴鏃у紩鎿庝細鎶娿€屾垜銆嶇殑淇℃伅褰撴垚銆屽ス銆嶇殑璧勬枡缂栧嚭鍘伙細
#     璧勬枡閲屽彧鏈夊紩鍔涚銆屽彧鎯虫壘涓汉鑱婅亰澶┿€嶏紝鍗寸敓鎴愩€岃繖涓夋睙鍋跺皵涔熶細鎯宠捣浣犮€傘€?
#     銆岀湅浣犲湪涓夋睙鍗栨暟鐮佹尯宸х殑銆傘€嶁€斺€斿ス鏍规湰涓嶇煡閬撲笁姹熸槸浠€涔堛€?
#   瑙勫垯锛氳繖浜涜瘝**鍙湁鍦ㄥス璧勬枡閲屽師鏍峰嚭鐜拌繃**鏃舵墠鍏佽浣跨敤锛堟瘮濡傚叡鍚岀偣鍐欎簡閲嶅簡锛夈€?
MY_WORDS = ("姹熷崕", "涓夋睙", "缍︽睙", "閲嶅簡", "缃戝簵", "闂查奔", "鎶栧簵", "鏁扮爜",
            "cpu", "鍐呭瓨", "ssd", "鏄剧ず鍣?, "蹇€?, "杞矾鐢?, "閲嶈绯荤粺", "鐢佃剳閰嶄欢")


def my_words():
    """寮€鍦虹櫧绂佺敤璇嶏細浠庝汉璁剧殑 ban 瀛楁鍙栵紝鍗曚竴鏉ユ簮銆?

    涓や釜璐﹀彿鍏辩敤鍚屼竴浠戒汉璁撅紙鐢ㄦ埛 2026-11-05 鍙ｅ緞锛夛紝涓嶅啀鎸夎处鍙峰垏韬唤锛?
    鍘熸潵纭紪鐮佸湪 match.py锛屾敼浜鸿鏃跺鏄撴紡鏀?鈥斺€?鐜板湪缁熶竴璇?persona.IDENT["ban"]銆?
    MY_WORDS 淇濈暀涓哄悓鍐呭鐨勫厹搴曞父閲忥紙浜鸿妯″潡鍙栦笉鍒版椂鐢級銆?
    """
    try:
        from brain.engine.persona import ident
        w = ident().get("ban")
        if w:
            return tuple(w)
    except Exception:
        pass
    return MY_WORDS

# 鍏ㄥ簾鏃剁殑瀹夊叏鍏滃簳锛堜笉鍚换浣曞叿浣撲俊鎭紝涓嶄細宕╋級
# 馃敶 2026-11-08锛坃report/14锛歮atch 寮€鍦虹櫧闂彞鐜?31.3% 鈫?鐩爣 <12%锛夛細
#   鏃?3 鏉″叏鏄煡鎴峰彛闂彞锛堛€屼綘杩欎細鍎垮湪蹇欏悧銆嶃€屽钩鏃惰繖涓偣閮藉湪骞插暐銆嶏級锛?
#   鑰屼笖瀹冧滑鏄?*鍏滃簳**鈥斺€斾竴鏃︾敤涓婂氨鏄€屽洓鏉″€欓€夊叏搴熴€嶏紝姝ゆ椂鏇撮渶瑕佷竴鍙ョǔ鐨?
#   闄堣堪鍙ユ妸鍦洪潰鎾戜綇锛岃€屼笉鏄啀鎶涗竴涓ス涓嶄竴瀹氳鎺ョ殑闂銆?
#   鏂?3 鏉″叏閮ㄦ敼涓?*闄堣堪鍨?+ 鑷甫璇濆ご**锛岄浂闂彿锛屼笖涓嶆煡鎴峰彛銆?
FALLBACK = (
    "鍒氬尮閰嶅埌锛屽厛杩囨潵鎵撲釜鎷涘懠",
    "鍒氬埛鍒颁綘锛屾垜杩欒竟姝ｉ棽鐫€",
    "鍒氬尮閰嶄笂锛屾垜杩欎細鍎垮垰蹇欏畬鎵嬪ご鐨勪簨",
)

# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲 閫氱敤寮€鍦虹櫧搴擄紙鐢ㄦ埛 2026-11-02 瀹氾細鍖归厤鍦烘櫙鐩存帴鐢ㄩ€氱敤鍙ワ級鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
# 渚濇嵁缃戜笂閫氳鐨勩€岄€氱敤瀹夊叏寮€鍦虹櫧銆嶅師鍒欙細涓嶆煡鎴峰彛锛堜笉闂勾榫?宸ヤ綔/浣忓潃/鐓х墖锛夈€?
# 浣庡帇鍔涖€佺暀涓€涓兘鎺ョ殑璇濆ご銆佷笉澶搁暱鐩搞€佷笉涓婃潵鍊掕嫤姘淬€?
# 涓轰粈涔堜笉鐢ㄥ紩鎿庣幇鐢熸垚锛氬疄娴?`opening_line(kind="match")` 鍦ㄦ病鏈夊鏂硅祫鏂欐椂锛?
# 浼氭妸鎴戣嚜宸辩殑淇℃伅锛堟睙鍗?涓夋睙/鍗栨暟鐮侊級褰撴垚濂圭殑缂栧嚭鍘伙紝4 鏉″叏搴燂紱
# 鑰屽尮閰嶆鏁版槸鎸夊ぉ闄愰噺鐨勶紝瀹佸彲鍙戜竴鍙ョǔ鐨勯€氱敤鍙ワ紝涔熶笉鑳芥氮璐逛竴娆″尮閰嶃€?
#
# 馃敶 2026-11-08锛坃report/14锛歮atch 寮€鍦虹櫧闂彞鐜?31.3%锛屾槸鍥炲渚?12.5% 鐨?2.5 鍊嶏級
#   搴撶粨鏋勯噸鎺掞細**闄堣堪鍙ユ墦澶?*锛岄棶鍙ュ彧鐣欏皯閲忋€岀粰寰楄捣涓滆タ銆嶇殑 offer 鍨嬨€?
#   璁板綍鐢紙48h 瀹炴祴 67 鏉?match 寮€鍦虹櫧锛夛細
#     路 鏌ユ埛鍙ｉ棶鍙ワ細`浣犱篃浣忛噸搴嗗悧锛焋 `浣犲湪閲嶅簡鎵撴嫾鍚梎 `浣犳槸鍋氫笂鐝棌鐨勫悧锛焋
#       `澹版帶鏄暐鎰忔€濓紵` `瑙傝嚜鍦ㄦ槸鍟ユ剰鎬濆晩锛焋 `鑸炶烦寰楀ソ鐪嬪悧` `浣犺绯荤粺鍚梎
#     路 杩欎簺鏄?**probe 鍨?*锛堣濂规彁渚涗俊鎭級锛岄檶鐢熷満鏅涓€娆¤璇濆氨鏌ユ埛鍙ｃ€?
#   闄堣堪鍙ョ殑濂藉锛氳嚜甯﹁瘽澶淬€侀浂鍥炵瓟鍘嬪姏锛屾効鎰忔帴灏辨帴锛屼笉鎺ヤ篃涓嶅按灏€?
OPENERS = (
    # A 闄堣堪寮忕牬鍐帮紙**涓诲姏锛屾棤闂彿**锛?
    "鍒氬尮閰嶅埌锛岃繃鏉ユ墦涓嫑鍛?,
    "鍒氱偣瀹屽尮閰嶅氨纰颁笂浣犱簡锛岀紭鍒嗗搱",
    "绐佺劧璺冲嚭鏉ヤ竴涓垜锛屾儕涓嶆儕鍠?,
    "鎴戝厛寮€鍙ｄ簡锛屼綘鍒珜鎴戠儲鍝?,
    "鎴戝垰闂茬潃娌′簨锛岀涓婁竴涓綘",
    "鐚滀綘鏄偅绉嶈瘽涓嶅浣嗘尯鏈夋剰鎬濈殑浜?,
    "杩欎細鍎挎墜澶存病浜嬶紝姝ｅソ纰颁笂浣?,
    "鍒氬埛鍒颁綘锛屾垜杩欎細鍎挎濂介棽鐫€",
    "鎴戣繖杈瑰垰蹇欏畬锛岄『鎵嬬偣浜嗕笅鍖归厤",
    "鎴戝钩鏃惰瘽涓嶇畻澶氾紝浣嗕笉鎬曞喎鍦?,
    # 鈿狅笍 浠ヤ笅涓ゆ潯琚?check() 鎷﹁繃锛屽凡鏇挎崲锛?
    #    "鍜变咯杩欏尮閰嶅害锛屽厛鑱婁袱鍙ヨ瘯璇曟按"   鈫?鍚厓璇嶃€屽尮閰嶅害銆?META_WORDS)
    #    "浠婂ぉ閲嶅簡鐨勫ぉ姘旀尯鑸掓湇鐨勨€?        鈫?鍚垜鐨勪笓灞炶瘝銆岄噸搴嗐€?my_words)
    "鍏堥殢渚胯涓ゅ彞锛屽悎涓嶅悎鎷嶈亰浜嗘墠鐭ラ亾",
    # B 闄堣堪寮忔姏璇濆ご锛堟妸淇℃伅缁欏嚭鍘伙紝濂硅嚜宸变細鎺ワ級
    "鎴戝厛璇达紝鎴戜粖澶╄繃寰楄繕琛?,
    "鎴戣繖浼氬効鍒氭场浜嗘澂鑼讹紝鍧愮潃鍙戝憜",
    "鎴戣繖浜鸿瘽涓嶅锛屼絾鎺ュ緱浣忚瘽",
    "鍒氬悆瀹岄キ锛屾鎰佹病浜鸿璇磋瘽",
    "鎴戣繖杈圭獥瀛愬紑鐫€锛岄杩樻尯鍑?,
    # C offer 鍨嬶紙闂殑鏄€屾垜缁欏緱璧蜂粈涔堛€嶏紝涓嶆槸銆屼綘韬笂鏈変粈涔堜俊鎭€嶏級
    "瑕佷笉瑕佽亰鑱婁粖澶╂渶鐑︾殑涓€浠朵簨",
    "瑕佹槸浣犱篃涓嶅洶锛屽挶淇╄涓ゅ彞",
    "鎴戝彲浠ュ厛璁茶鎴戣嚜宸憋紝浣犲惉鐫€灏辫",
    # D 灏戦噺浣庡帇鍔涢棶鍙ワ紙**鍏佽淇濈暀锛屽崰姣旀帶鍒跺湪 1/5 浠ュ唴**锛?
    "浣犺繖浼氬効鏄垰蹇欏畬杩樻槸闂茬潃鍛?,
    "杩欎細鍎垮湪蹇欏暐鍛?,
    "鏈€杩戝湪杩藉暐鍓ф病",
)


def read_card(snap):
    """浠庡尮閰嶅崱鐗囬噷鎶借祫鏂欙紝杩斿洖 dict(nick, tags, common, extra)銆?""
    nodes = [n for n in snap.nodes if n.label]
    texts = [n.label.strip() for n in nodes]
    tags, common, extra = [], [], {}

    for i, t in enumerate(texts):
        if t.startswith("Ta鐨勫紩鍔涚"):
            rest = t.split("锛?, 1)[-1].strip() if "锛? in t else ""
            if not rest and i + 1 < len(texts):
                rest = texts[i + 1]
            tags += [x for x in re.split(r"[銆?锛?;锛沑s]+", rest) if x]
        elif t.startswith("浣犱滑鐨勫叡鍚岀偣"):
            rest = t.split("锛?, 1)[-1].strip() if "锛? in t else ""
            if not rest and i + 1 < len(texts):
                rest = texts[i + 1]
            common += [x for x in re.split(r"[銆?锛?;锛沑s]+", rest) if x]
        elif t.startswith("Ta鐨勬槦搴?):
            extra["鏄熷骇"] = t.split("锛?, 1)[-1].strip()
        elif re.fullmatch(r"\d{1,3}%", t):
            extra["鍖归厤搴?] = t
        elif t.startswith("Ta鐨勭ぜ浠垎"):
            extra["绀间华鍒?] = re.sub(r"^Ta鐨勭ぜ浠垎[锛?]\s*", "", t)

    # 鏄电О锛氬崱鐗囧尯锛?40~560锛夐噷鏈€闈犱笂鐨勪竴琛岀煭鏂囨湰锛屾帓闄ら〉闈㈠浐瀹氭枃妗?
    nick = ""
    for n in sorted([x for x in nodes if 140 < x.center[1] < 560],
                    key=lambda x: (x.center[1], x.center[0])):
        t = n.label.strip()
        if not (1 <= len(t) <= 14):
            continue
        if t in UI_TEXTS or t.startswith("鍏虫敞鍚?) or "鍖归厤" in t:
            continue
        nick = t
        break
    return {"nick": nick, "tags": tags, "common": common, "extra": extra}


def _lcs(a, b):
    """鏈€闀垮叕鍏卞瓙涓查暱搴︼紙a/b 閮藉緢鐭紝DP 瓒冲锛夈€?""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def check(text, tags=None, common=None, limit=LIMIT):
    """搴熷彞鏍￠獙銆傝繑鍥?(ok, reason)銆俹k=False 蹇呴』閲嶅啓銆?""
    t = (text or "").strip()
    if not t:
        return False, "绌?
    if len(t) > limit:
        return False, "瓒呴暱 %d 瀛? % len(t)
    if len(t) < 3:
        return False, "澶煭"
    for r in BAD_RE:
        if r.search(t):
            return False, "濂楄瘽/缂栭€? %s" % r.pattern
    for w in META_WORDS:
        if w in t:
            return False, "鍑虹幇鍏冭瘝 %s" % w
    # 澶嶈堪锛氫笌寮曞姏绛?鍏卞悓鐐规湁 >=4 瀛楄繛缁噸鍚堬紝绛変簬鎶婂ス鐨勬爣绛惧康鍥炲幓
    for src in list(tags or []) + list(common or []):
        s = (src or "").strip()
        if len(s) >= 4 and _lcs(t, s) >= 4:
            return False, "澶嶈堪璧勬枡 %r" % s
    # 鎶婃垜鑷繁鐨勪俊鎭綋鎴愬ス鐨勶紙濂硅祫鏂欓噷娌″嚭鐜拌繃鐨勬垜鐨勪笓灞炶瘝锛屼竴寰嬩笉璁告彁锛?
    pool = " ".join([str(x) for x in (list(tags or []) + list(common or []))]).lower()
    low = t.lower()
    for w in my_words():
        if w in low and w not in pool:
            return False, "濂楁垜鐨勪俊鎭?%r" % w
    # 鎷彿琛ㄦ儏澶暱锛堟棫寮曟搸宸插墺锛岃繖閲屽厹搴曪級
    if re.search(r"\[[^\]]{3,}\]", t):
        return False, "琛ㄦ儏杩囬暱"
    return True, ""


def score(text, tags=None, common=None):
    """瓒婂儚銆岃兘鎺ヨ瘽鐨勫紑鍦恒€嶅垎瓒婇珮銆?

    馃敶 2026-11-08锛坃report/14 瀹炴祴淇锛夛細
      鏀瑰墠 鈥斺€?`if ASK_RE.search(text): s += 3`锛?*闂彞鍔犲垎**锛?
      浜庢槸閫夊嚭鏉ョ殑寮€鍦虹櫧鍏ㄦ槸鏌ユ埛鍙ｏ紙闂彞鐜囧疄娴?31.3%锛夈€?
      鏀瑰悗 鈥斺€?**闄堣堪鍙ヤ紭鍏?*锛?
        路 纭棶鍙ワ紙鐪熺枒闂彞锛?     鈭?
        路 offer 鍨嬮棶鍙ワ紙鎴戣浣犫€︼級  +1锛堥棶鐨勬槸鎴戠粰寰楄捣鐨勪笢瑗匡紝鍙互鐣欙級
        路 闄堣堪鍙?+ 鑷甫璇濆ご        +2
        路 缁撳熬鏄彞鍙?鎰熷徆鐨勭函闄堣堪  +1锛堜笉鍐嶆槸 鈭?锛岄檲杩板彞鐜板湪灏辫琚€変笂锛?
      渚濇嵁锛氭姤鍛?11 淇濇寔鐑害 offer 37.5% > probe 25.9% > 闄堣堪 7.3%锛?
      match 鏃у簱閲岀殑闂彞鍏ㄩ儴钀藉湪 **probe锛堣濂规彁渚涗俊鎭級** 閭ｄ竴妗ｏ紝
      鏄笁绉嶉噷鏈€宸殑涓€绫伙紝鑰屾棫浠ｇ爜鍋忓亸缁?probe 鍔犲垎銆?
    """
    t = (text or "").strip()
    s = 0
    hard_ask = bool(ASK_HARD.search(t)) or t.endswith(("锛?, "?"))
    if hard_ask:
        if OFFER_RE.search(t):
            s += 1                     # offer 鍨嬶細缁欏緱璧蜂笢瑗匡紝鍏佽闂?
        elif SOFT_ASK_RE.search(t) and not re.search(r"浣??:鏄瘄鍋殀浣弢鍦?.{0,6}(?:鍚梶鍝獆浠€涔坾鍟?", t):
            s -= 1                     # 浣庡帇鍔涢棶鍙ワ紙闂ス姝ゅ埢鐘舵€侊級锛氳交缃氾紝鍙繚鐣?
        else:
            s -= 3                     # 鏌ユ埛鍙ｉ棶鍙ワ細閲嶇綒
    else:
        s += 2                         # 闄堣堪鍙ワ細鏈瓥鐣ョ殑涓诲姏
        if t.endswith(("銆?, "锛?, "!")):
            s += 1
    n = len(t)
    if 6 <= n <= 16:
        s += 1
    elif n > LIMIT:
        s -= 5
    # 澶钩銆佹病鏈夊叿浣撶敾闈㈢殑娉涘彞闄嶆潈锛堛€岃繃鏉ユ墦涓嫑鍛笺€嶈繖绫诲繀椤绘湁鍒殑鍒嗘拺浣忥級
    if not re.search(r"[浣犳垜浠栧ス鍜盷|浠婂ぉ|杩欎細鍎縷鍒?, t):
        s -= 1
    return s


def _ask_rate_ok(pool, limit=0.12):
    """璇婃柇鐢細杩欎竴姹犲彞瀛愮殑纭棶鍙ユ瘮渚嬫槸涓嶆槸鍘嬪埌浜嗙洰鏍囩嚎浠ヤ笅銆?""
    if not pool:
        return True
    n = sum(1 for t in pool if ASK_HARD.search(t) or t.endswith(("锛?, "?")))
    return (float(n) / len(pool)) <= limit


def _ask_ratio_used(used):
    """鏈€杩戣褰曢噷纭棶鍙ュ崰澶氬皯锛堢敤浜庨厤棰濆垽瀹氾級銆?""
    tail = list(used or [])[-10:]
    if not tail:
        return 0.0
    n = sum(1 for t in tail if ASK_HARD.search(t or "") or (t or "").endswith(("锛?, "?")))
    return float(n) / len(tail)


def _should_ask_now(used):
    """杩欎竴娆¤涓嶈鍏佽鐢ㄩ棶鍙ュ紑鍦猴紙涓ユ牸闄愰噺锛夈€?

    瑙勫垯锛氭渶杩?10 鏉″紑鍦虹櫧閲岀殑闂彞姣斾緥 < OPEN_ASK_RATE(12%) 鎵嶅厑璁告彃涓€鏉°€?
    杩欐牱闂彞鐜囧湪缁撴瀯涓婅閽夊湪 12% 浠ヤ笅锛岃€屼笉鏄潬搴撻噷鏁伴噺姣斾緥"纰拌繍姘?銆?
    """
    import random
    if _ask_ratio_used(used) >= OPEN_ASK_RATE:
        return False
    return random.random() < OPEN_ASK_RATE


def pick_opener(avoid_recent=12):
    """浠庨€氱敤寮€鍦虹櫧搴撴寫涓€鏉★紝閬垮紑鏈€杩戠敤杩囩殑銆?

    馃敶 2026-11-08锛坃report/14锛歮atch 寮€鍦虹櫧闂彞鐜?31.3% 鈫?鐩爣 <12%锛夛細
      鏀瑰墠鏄?*绾殢鏈?* `random.choice(pool)` 鈥斺€?搴撻噷闂彞鍗犲ぇ澶达紝
      鎶藉嚭鏉ヨ嚜鐒跺氨鏄煡鎴峰彛銆傜幇鍦ㄦ敼鎴?*鍏堝垎姹犮€佸啀鍦ㄩ檲杩版睜閲岄殢鏈?*锛?
        路 闄堣堪姹?= 闈炵‖闂彞  鈫?榛樿浠庤繖閲屾娊锛堣繖灏辨槸 88% 浠ヤ笂鐨勫嚭璇濓級
        路 闂彞姹?= 纭棶鍙?   鈫?鍙湁闄堣堪姹犺"鏈€杩戠敤杩?鎺忕┖鏃舵墠鍥炶惤锛?
                                骞剁敤 _OPEN_ASK_QUOTA 鎺у埗鍗犳瘮
      淇濈暀闅忔満鎬э紙閬垮厤姣忓ぉ鍚屼竴鍙ワ級锛屼絾**缁撴瀯涓?*淇濊瘉闂彞涓嶅啀鏄富鍔涖€?
    """
    import json
    import random

    used = []
    try:
        used = json.loads(_head_file().read_text("utf-8"))
    except Exception:
        used = []

    def _is_ask(x):
        return bool(ASK_HARD.search(x)) or x.endswith(("锛?, "?"))

    def _fresh(pool, n):
        return [t for t in pool if t not in used[-n:]]

    stmt_pool = [t for t in OPENERS if not _is_ask(t)]
    ask_pool = [t for t in OPENERS if _is_ask(t)]

    # 涓诲姏锛氶檲杩版睜閲屾寫娌＄敤杩囩殑
    pool = _fresh(stmt_pool, avoid_recent)
    if not pool:                       # 闄堣堪鍙ュ叏鐢ㄨ繃浜?-> 鍙伩寮€鏈€杩?5 鏉?
        pool = _fresh(stmt_pool, 5) or stmt_pool
    # 浜ゅ弶锛氭瘡 OPEN_ASK_EVERY 娆″厑璁告彃涓€鏉￠棶鍙ワ紙璁╁簱涓嶅憜鏉匡紝浣嗕弗鏍奸檺閲忥級
    if ask_pool and _should_ask_now(used):
        ap = _fresh(ask_pool, avoid_recent) or ask_pool
        if ap:
            pool = ap

    t = random.choice(pool) if pool else (FALLBACK[0])
    try:
        used = (used + [t])[-40:]
        _head_file().write_text(json.dumps(used, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("璁板紑鍦虹櫧澶辫触: %r", e)
    return t


def opening(b, card, limit=LIMIT, tries=4, engine_gen=False):
    """鍑哄紑鍦虹櫧銆傝繑鍥?(text, tries_log)銆?

    榛樿锛坋ngine_gen=False锛岀敤鎴?2026-11-02 鍙ｅ緞锛夌敤**閫氱敤寮€鍦虹櫧搴?*锛?
    鍖归厤娆℃暟鎸夊ぉ闄愰噺锛岄€氱敤鍙ョǔ銆? 寤惰繜銆佷笉浼氱紪閫狅紝姣旂瓑寮曟搸 6s 鏇村垝绠椼€?
    engine_gen=True 鏃舵墠璧版棫寮曟搸涓€у寲鐢熸垚锛堝甫涓夐亾搴熷彞闂?+ 鍏滃簳锛夈€?
    """
    if not engine_gen:
        t = pick_opener()
        return t, [(t, True, "閫氱敤搴?, 3)]

    tags, common = card.get("tags") or [], card.get("common") or []
    nick = card.get("nick") or ""
    cands = []
    for i in range(tries):
        try:
            t, _ms = b.opening_line(sid="", nick=nick, hist=[], tags=tags,
                                    common=common, kind="match", limit=limit)
        except Exception as e:
            log.warning("opening_line 绗?d娆″紓甯? %r", i + 1, e)
            continue
        t = (t or "").strip()
        ok, why = check(t, tags, common, limit)
        sc = score(t, tags, common) if ok else -99
        cands.append((t, ok, why, sc))
        log.info("鍊欓€?d %r ok=%s %s score=%d", i + 1, t[:26], ok, why, sc)
        # 馃敶 2026-11-08锛坃report/14 淇锛夛細杩欓噷鍘熸潵鏄?
        #     `if ok and ASK_RE.search(t): return t`  鈫?**闂彞涓€鍑虹幇灏辨彁鍓嶆敹宸?*锛?
        #   杩欐鏄煡鎴峰彛寮€鍦虹櫧鐨勭洿鎺ユ潵婧愶紙瀹炴祴 `浣犳槸寮€缃戝簵鐨勫悧锛焋 灏辨槸杩欎箞鍑哄幓鐨勶級銆?
        #   鐜板湪鍙嶈繃鏉ワ細**鎷垮埌鍚堟牸闄堣堪鍙ュ氨鎻愬墠鏀跺伐**锛堥檲杩板彞鏄湰绛栫暐鐨勪富鍔涳級锛?
        #   闂彞鍙湪娌℃湁闄堣堪鍙ユ椂闈?score 鍙備笌姣旇緝銆?
        if ok and not ASK_HARD.search(t) and not t.endswith(("锛?, "?")) and sc >= 3:
            return t, cands            # 鍚堟牸闄堣堪鍙ヤ笖鍒嗘暟澶?鈫?鐩存帴鐢?
    good = [c for c in cands if c[1]]
    if good:
        good.sort(key=lambda c: -c[3])
        return good[0][0], cands
    return _fallback(), cands


# ---------------- 鎵ц ----------------
def _head_file():
    from core.paths import STATE
    return STATE / "match_heads.json"


def _fallback():
    """鍏ㄥ簾鍏滃簳锛氭寫涓€鏉℃渶杩戞病鐢ㄨ繃鐨勯€氱敤寮€鍦恒€?""
    import json
    used = []
    try:
        used = json.loads(_head_file().read_text("utf-8"))
    except Exception:
        used = []
    pick = None
    for t in FALLBACK:
        if t not in used:
            pick = t
            break
    pick = pick or FALLBACK[0]
    try:
        used = (used + [pick])[-6:]
        _head_file().write_text(json.dumps(used, ensure_ascii=False), "utf-8")
    except Exception as e:
        log.warning("璁板厹搴曞彞澶辫触: %r", e)
    log.warning("鍥涙潯鍊欓€夊叏搴燂紝鏀圭敤鍏滃簳鍙?%r", pick)
    return pick


def _local_opener(card):
    """鏈湴妯″瀷鐢熸垚寮€鍦虹櫧锛堢敤鎴?2026-11-04 瀹氾細搴熷純鍥哄畾姹犲瓙锛屾敼鏈湴妯″瀷鐢熸垚锛夈€?

    寮曟搸涓嶅彲鐢?/ 鐢熸垚鍏ㄥ簾鏃舵墠閫€鍥?_fallback 鍏滃簳锛? 鏉″畨鍏ㄥ彞锛夈€?
    opening(engine_gen=True) 鍐呴儴宸插甫涓夐亾搴熷彞闂革紙check锛夆€斺€斿巻鍙查棶棰樸€屾妸鎴戠殑淇℃伅
    锛堟睙鍗?涓夋睙/鍗栨暟鐮侊級褰撴垚濂圭殑缂栧嚭鍘汇€嶄細琚?MY_WORDS 闂告嫤鎺夛紝涓嶄細婕忓嚭鍘汇€?

    馃敶 2026-11-08锛坃report/14锛氬疄娴?67 鏉?match 寮€鍦虹櫧閲岄棶鍙ョ巼 31.3%锛夛細
      妯″瀷鍑犱箮姣忔閮戒紭鍏堝悙闂彞锛坄浣犳槸寮€缃戝簵鐨勫悧锛焋 `浣犱篃浣忛噸搴嗗悧锛焋 `瑙傝嚜鍦ㄦ槸鍟ユ剰鎬濆晩锛焋锛夛紝
      鑰?`check()` 鍙嫤銆岀紪閫?濂椾俊鎭?澶嶈堪璧勬枡銆嶏紝**涓嶆嫤闂彞** 鈫?鍏ㄩ儴鏀捐銆?
      杩欓噷鍔犳渶鍚庝竴閬?*闂彞閰嶉闂?*锛?
        路 妯″瀷鍑虹殑鏄‖闂彞锛屼笖鏈€杩?10 鏉￠噷闂彞宸插埌 OPEN_ASK_RATE 鈫?涓㈠純锛屾敼璧?
          `pick_opener()` 鐨勯檲杩版睜锛堢粨鏋勪笂淇濊瘉闂彞涓嶈秴鏍囷級
        路 offer 鍨嬮棶鍙ワ紙銆岃涓嶈鑱婅亰鈥︺€嶏級涓嶅彈闄愶細瀹冮棶鐨勬槸鎴戠粰寰楄捣鐨勪笢瑗?
      杩欐槸**鏈枃浠跺唴**鐨勭瓥鐣ヤ慨姝ｏ紝涓嶅姩 brain/engine/opener.py锛堝埆浜虹殑鍐欏煙锛夈€?
    """
    try:
        from brain import reply as _R
        b = _R.engine()
        if b is not None and hasattr(b, "opening_line"):
            t, _ = opening(b, card, engine_gen=True)
            t = (t or "").strip()
            if t:
                is_ask = bool(ASK_HARD.search(t)) or t.endswith(("锛?, "?"))
                if is_ask and not OFFER_RE.search(t):
                    try:
                        import json
                        used = json.loads(_head_file().read_text("utf-8"))
                    except Exception:
                        used = []
                    if _ask_ratio_used(used) >= OPEN_ASK_RATE:
                        log.info("寮€鍦虹櫧闂彞閰嶉宸叉弧 鈫?寮冪敤妯″瀷闂彞 %r锛屾敼鐢ㄩ檲杩板簱", t[:24])
                        return pick_opener()
                return t
    except Exception as e:
        log.warning("鏈湴寮€鍦虹櫧鐢熸垚寮傚父锛岄€€鍥炲厹搴? %r", e)
    return _fallback()


def send(actor, dev, text, sid=""):
    """鐏屽瓧 -> 鍙戦€?-> 鏍￠獙杈撳叆妗嗐€傝繑鍥?(ok, 璇存槑)銆?""
    from hands.input import Input

    # 馃敶 2026-11-03 淇锛氬尮閰嶅紑鍦虹櫧鍘熸潵鍙?note_sent() 涓嶆鏌ヤ笂闄愶紝
    #    涓庡敜閱掍竴璧锋瀯鎴?闄愭祦鐩插尯"锛堝皬鏃朵笂闄愬杩欎袱鏉￠摼璺棤鏁堬級銆?
    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            return False, "鏈皬鏃跺彂閫佸凡杈句笂闄?
    except Exception:
        pass

    # 璺熻繘闃舵鍙戦€侀椄锛歴id 涓虹┖锛堝閬囬搩 / 鍖归厤 / 鏂版嫑鍛肩瓑鏂颁細璇濆紑鍦虹櫧锛?
    # 杩囬椄鏀捐锛屼絾涓嶅崰 2/6 鏉¤窡杩涢搴︼紱灏嗘潵璋冪敤鏂规嬁鍒?sid 浼犺繘鏉ュ嵆鑷姩鍙楃害鏉熴€?
    try:
        from brain import sendgate as SG
        _d = SG.allow(sid, 1)
        if not _d.ok:
            log.info("璺熻繘闃舵鎷︽埅 sid=%s state=%s锛?s锛?, sid, _d.state, _d.reason)
            return False, "璺熻繘闃舵鎷︽埅(%s)" % _d.state
    except Exception:
        pass

    # 鍙戦€佸墠鍏堝０鏄庯細杩欎竴娈靛簱鍐欏叆閮芥槸鎴戣嚜宸辩殑
    try:
        from data import watch as _W
        _W.mark_self_write(20.0)
    except Exception:
        pass

    inp = Input(dev)
    ok, got = inp.type_and_verify(text, actor)
    if not ok:
        inp.clear()
        return False, "鐏屽瓧澶辫触(瀹為檯 %r)" % (got,)
    if not inp.tap_send(actor, settle=1.6):
        inp.clear()
        return False, "鎵句笉鍒板彂閫佹寜閽?
    # 馃敶 2026-11-12锛團-01锛夛細sent_ok 鏄笁鎬侊紙ok/unknown/residual锛岃 hands/input.py锛夈€?
    #   鍙湁 residual锛堣緭鍏ユ杩樻湁瀛?= 鏄庣‘娌″彂锛夋墠绠楀け璐ワ紱unknown锛堣浆鍦哄抚璇讳笉鍒?
    #   杈撳叆妗嗭紝澶ф鐜囧凡鍙戯級鎸夊凡鍙戣璐︼紝閬垮厤銆屽疄闄呭凡鍙戝嵈琚垽澶辫触銆嶇儳鍖归厤娆℃暟銆?
    _ok = inp.sent_ok(actor, text, timeout=6)
    _why = getattr(inp, "last_reason", "") or ""
    if (not _ok) and _why == "residual":
        return False, "鍙戦€佸悗杈撳叆妗嗘湭娓呯┖(娈嬬暀)"
    # ok 鎴?unknown锛堝ぇ姒傜巼宸插彂锛夆啋 鎸夊凡鍙戣璐?
    # 寮€鍦虹櫧涔熸槸鑷繁鍐欑殑搴撳彉鍖栵紝蹇呴』鎶戝埗锛堝惁鍒欏尮閰嶅垰鍙戝畬灏辫鑷繁鐨勫啓鍏ユ墦鏂級
    try:
        from data import watch as _W
        _W.mark_self_write(6.0)
    except Exception:
        pass
    try:
        from brain import ratelimit as _RL
        _RL.note_sent()
    except Exception:
        pass
    if sid:
        try:
            from brain import sendgate as SG
            SG.note_sent(sid, 1)
        except Exception:
            pass
    return True, "宸插彂閫?


def _has_chat_input(snap):
    """褰撳墠灞忔槸涓嶆槸浼氳瘽椤碉紙銆屽彂閫併€嶆垨銆岄暱鎸夎璇濄€嶅嚭鐜帮級銆?

    馃敶 2026-11-12锛圚Y-09锛夛細`next_one` 鎹汉纭鍘熸潵鍙 `detect()=="chat"` 鎴?
      `has_card(s)`銆傚疄娴嬪尮閰嶅崱鍒氭崲瀹屻€佽祫鏂欏崱杩樻病娓叉煋鍑烘潵鐨勯偅涓€鐬紝
      detect 鍙兘涓嶆槸 chat銆乭as_card 涔熶负 False 鈫?琚鍒ゃ€岃繕娌℃崲銆嶁啋 绛夋弧 3 杞€?
      鍔犮€屽彂閫?闀挎寜璇磋瘽銆嶇洿鎺ュ厹搴曪細鍙浼氳瘽杈撳叆妗嗗湪锛屽氨鏄凡鎹汉銆?
    """
    try:
        txt = " ".join(snap.texts())
        return ("鍙戦€? in txt) or ("闀挎寜璇磋瘽" in txt)
    except Exception:
        return False


def _clickable_text(snap, texts):
    """鎸夋枃妗堥『搴忔壘鍙偣鍑荤洰鏍囷紱鍙繑鍥?clickable 鑺傜偣銆?""
    for text in texts:
        n = snap.hit(text=text)
        if n is not None and n.clickable:
            return n
    return None


def match_entry(snap):
    """杩斿洖鏄熺悆椤电殑鐏甸瓊鍖归厤鍗＄墖鍜岃鍗＄墖浠婃棩鍓╀綑娆℃暟銆?

    鏂扮増鏄熺悆椤垫病鏈夈€屽紑濮嬪尮閰嶃€嶆寜閽紝鑰屾槸鍦?`ratioContainer` 鍗＄墖閲屾樉绀?
    銆岀伒榄傚尮閰?/ 浠婃棩鍓╀綑 N 娆°€嶃€傝闊冲尮閰嶅崱鐗囦篃鏈変竴涓€屼粖鏃ュ墿浣?M 娆°€嶏紝
    鎵€浠ヤ笉鑳界畝鍗曞彇椤甸潰涓婄涓€涓墿浣欐鏁帮紱蹇呴』缁戝畾鍒扮伒榄傚尮閰嶅崱鐗囪嚜宸辩殑 bounds銆?
    """
    entry = _clickable_text(snap, MATCH_ENTRY_TEXTS)
    if entry is None:
        return None, None
    left, top, right, bottom = entry.bounds
    remain = None
    labels = []
    for n in snap.nodes:
        if not n.visible or "浠婃棩鍓╀綑" not in (n.label or ""):
            continue
        x, y = n.center
        if left <= x <= right and top <= y <= bottom:
            m = REMAIN_RE.search(n.label)
            if m:
                labels.append(int(m.group(1)))
    if labels:
        remain = labels[0]
    return entry, remain


def next_button(snap):
    """鎵句細璇濋〉宸︿笂瑙掋€屽尮閰嶄笅涓€涓€嶏紝鍏煎鏃х増浠呮湁璧勬簮 id 鐨勮妭鐐广€?""
    n = snap.hit(text=NEXT_TEXT)
    if n is not None:
        return n
    for x in snap.nodes:
        if (x.visible and x.clickable and "tv_rem" in (x.res_id or "")
                and x.center[0] < 260 and x.center[1] < 200):
            return x
    return None


def wait_match_card(actor, timeout=12.0):
    """绛夊尮閰嶉〉浠庤浆鍦哄抚绋冲畾鎴?`chat + 鍖归厤鍗锛屾湡闂翠笉鐐瑰嚮銆?""
    deadline = time.time() + max(1.0, float(timeout))
    last = None
    while time.time() < deadline:
        last = actor.snap(force=True)
        pg = detect(last)
        if pg == "chat" and has_card(last):
            return last, "chat"
        time.sleep(0.8)
    return last or actor.snap(force=True), detect(last) if last is not None else "unknown"


def next_one(actor, max_wait=8.0):
    """鐐逛竴娆″乏涓婅銆屽尮閰嶄笅涓€涓€嶏紝鍙帴鍙楅〉闈笂鍑虹幇鐨勬柊鍖归厤鍗°€?

    2026-11-14 鐢ㄦ埛鍙ｅ緞锛氬尮閰嶅埌浜?鈫?鐐逛釜浜轰富椤靛缓妗?鈫?鍙戝紑鍦虹櫧 鈫?鐐瑰乏涓婅
    銆屽尮閰嶄笅涓€涓€嶃€備笉鑳介€€鍥炴槦鐞冮〉鍐嶇偣銆岀伒榄傚尮閰嶃€嶏紝閭ｄ細涓㈠け褰撳墠鍖归厤娴佸苟
    澶氱儳娆℃暟銆傝繖閲屼篃涓嶉噸璇曠偣鍑伙細鐐瑰嚮鍚庤嫢瓒呮椂锛岃皟鐢ㄦ柟蹇呴』鍋滄墜锛屽厛鏌ヨ澶?
    缃戠粶锛岄伩鍏嶅洜鍚屼竴涓參璇锋眰杩炵偣鑰岄噸澶嶆秷鑰椼€?
    """
    snap = actor.snap(force=True)
    if quota_out(snap):
        return snap, "no_quota", "no_quota"
    n = next_button(snap)
    if n is None:
        return snap, detect(snap), "no_button"
    before = snap.signature()
    actor.hand.tap_node(n, settle=1.0)

    deadline = time.time() + max(2.0, float(max_wait))
    last = None
    while time.time() < deadline:
        s = actor.snap(force=True)
        last = s
        pg = detect(s)
        if quota_out(s):
            _dismiss_quota(actor, s)
            return s, "no_quota", "no_quota"
        # 蹇呴』鍚屾椂婊¤冻锛氭柊鎸囩汗 + 浠嶆槸浼氳瘽椤?+ 鍑虹幇鍖归厤鍗°€?
        # 涓嶈兘鍙杈撳叆妗嗭紝鍚﹀垯鏅€氭棫浼氳瘽涔熶細琚褰撴垚涓嬩竴寮犲尮閰嶅崱銆?
        if s.signature() != before and (pg == "chat" or _has_chat_input(s)) and has_card(s):
            log.info("鍖归厤涓嬩竴涓垚鍔燂細宸茬‘璁ゆ柊鍗?(sig %s -> %s)", before, s.signature())
            return s, "chat", "next"
        time.sleep(0.8)
    log.warning("鍖归厤涓嬩竴涓悗鏈瓑鍒版柊鍗★紙page=%s sig=%s锛?,
                detect(last) if last is not None else "?", last.signature() if last else "?")
    return last or actor.snap(force=True), detect(last) if last is not None else "unknown", "timeout"


# 鍖归厤棰濆害鐢ㄥ畬鐨勬彁绀猴紙瀹炴祴寮瑰眰鍘熸枃锛氥€屼粖鏃ュ厤璐瑰尮閰嶆満浼氬凡鐢ㄥ畬 (50/50)銆嶏級
QUOTA_HINT = "鍖归厤鏈轰細宸茬敤瀹?


def _dismiss_quota(actor, s):
    """鍙偣寮瑰眰鑷繁鐨勫叧闂帶浠讹紝涓嶆寜绯荤粺杩斿洖閿€傝繑鍥炴槸鍚﹀凡鍏虫帀銆?""
    s2 = s
    n = None
    for label in ("鍏抽棴", "鐭ラ亾浜?, "鎴戠煡閬撲簡", "鍙栨秷"):
        n = s2.hit(text=label)
        if n is not None:
            break
    if n is not None:
        try:
            actor.hand.tap_node(n, settle=1.2)
            if not quota_out(actor.snap(force=True)):
                return True
        except Exception:
            pass
    log.warning("棰濆害寮瑰眰鎵句笉鍒板彲鐐圭殑鍏抽棴鎺т欢 鈫?涓嶆寜绯荤粺杩斿洖锛屼氦缁欎笂灞傞€€閬?)
    return False


def quota_out(snap):
    """褰撳墠鏄笉鏄脊鐫€銆屼粖鏃ュ厤璐瑰尮閰嶆満浼氬凡鐢ㄥ畬銆嶇殑閬僵銆?

    馃敶 2026-11-02 瀹炴祴锛氶搴?50/50 鐢ㄥ畬鍚庯紝鐐广€屽紑濮嬪尮閰嶃€嶅彧浼氫粠搴曢儴鍗囪捣杩欎釜
       鍗婂睆寮瑰眰锛堝崠娆℃暟鍗?+ 鍋氫换鍔★級锛?*椤甸潰姘歌繙杩涗笉鍒颁細璇濋〉**銆傚師鏉ョ殑瀹炵幇
       涓€璺瓑鍒?25~50 绉掕秴鏃讹紝姣忔鐧界儳鍗婂垎閽燂紙鐢ㄦ埛鐪嬪埌鐨勩€屽尮閰嶇┖鐑с€嶏級銆?
    """
    try:
        return QUOTA_HINT in " ".join(snap.texts())
    except Exception:
        return False


def start_match(actor, max_wait=25):
    """浠庢槦鐞冮〉鐐逛竴娆＄伒榄傚尮閰嶅崱鐗囷紝绛夊埌鏂板尮閰嶄細璇濋〉銆?

    鏂扮増鍗＄墖鏂囨鏄€岀伒榄傚尮閰?/ 浠婃棩鍓╀綑 N 娆°€嶏紝涓嶆槸鏃х増銆屽紑濮嬪尮閰嶃€嶃€?
    璇诲彇鍓╀綑娆℃暟鏃跺彧鐪嬬伒榄傚尮閰嶅崱鐗囪嚜韬?bounds锛屼笉鑳借鏃佽竟璇煶鍖归厤鐨?3 娆℃贩娣嗐€?
    鐐瑰嚮澶辫触鎴栬秴鏃跺彧杩斿洖澶辫触锛屼笉鍦ㄦ湰鍑芥暟閲屼簩娆＄偣鍑汇€?
    """
    from brain import nav

    nav.ensure_app(actor.dev)
    snap, pg = nav.to_tab(actor, "鏄熺悆")
    if pg != "planet":
        return snap, pg                      # 鍥炰笉鍒版槦鐞冮〉锛岀敱涓婂眰璁板け璐?

    if quota_out(snap):
        _dismiss_quota(actor, snap)
        return snap, "no_quota"
    n, remain = match_entry(snap)
    if n is None:
        return snap, "no_start"
    if remain == 0:
        log.warning("浠婃棩鐏甸瓊鍖归厤棰濆害宸茬敤瀹岋紙鍗＄墖鏄剧ず 0 娆★級鈫?涓嶅啀鐐瑰嚮")
        return snap, "no_quota"
    log.info("鐐圭伒榄傚尮閰?%s锛屼粖鏃ュ墿浣?%s", n.bounds, remain if remain is not None else "鏈煡")

    before = snap.signature()
    actor.hand.tap_node(n, settle=2.0)

    # 鐐逛竴娆″悗鍙瓑寰咃紝涓嶅洜鎱㈣姹傞噸澶嶇偣鍑汇€傚尮閰嶅姩鐢婚€氬父 3~5s锛涙參璁惧/鏈嶅姟绔?
    # 鍙兘鍒?20~30s銆傝秴鏃跺嵆鍋滄墜锛岄伩鍏嶅悓涓€涓尮閰嶇儳涓ゆ銆?
    t0 = time.time()
    while time.time() - t0 < max_wait:
        s = actor.snap(force=True)
        if quota_out(s):
            log.warning("浠婃棩鍖归厤棰濆害宸茬敤瀹?鈫?鍏虫帀寮瑰眰锛屼粖澶╀笉鍐嶅尮閰?)
            _dismiss_quota(actor, s)
            return s, "no_quota"
        pg2 = detect(s)
        if s.signature() != before and (pg2 == "chat" or _has_chat_input(s)) and has_card(s):
            log.info("宸茶繘鍏ユ柊鍖归厤浼氳瘽 (sig %s -> %s)", before, s.signature())
            return s, "chat"
        time.sleep(0.8)
    s = actor.snap(force=True)
    log.warning("鐐圭伒榄傚尮閰嶅悗鏈繘鍏ユ柊鍖归厤浼氳瘽锛坧age=%s sig=%s锛?,
                detect(s), s.signature())
    return s, "timeout"


def run_once(actor, dev, db, dry_run=False, preempt=None):
    """澶勭悊**褰撳墠**鍖归厤浼氳瘽锛氬缓妗?-> 鍙戦€氱敤寮€鍦虹櫧 -> 瀛樻棫妗堟儏鍖呫€?

    daemon 姣忚疆璋冨畠涓€娆★紝鍐嶈皟 advance() 鍓嶈繘銆傝繑鍥?dict锛?
        {ok, sent, text, prof, sid, err}
    閾佸緥锛氭病鍙戞垚鍔熶笉鐐广€屽尮閰嶄笅涓€涓€嶏紙浼氱櫧璐逛竴娆″尮閰嶆鏁帮級銆?
    """
    from brain import casepack as CP

    out = {"ok": False, "sent": False, "text": "", "prof": None, "sid": None,
           "err": "", "preempted": "", "skip_said": False}

    # 馃敶 浠庤繖涓€鍒昏捣鎴戦€犳垚鐨勫簱鍙樺寲閮戒笉绠椼€屾柊娑堟伅銆嶏紙杩涗細璇?鍙戝紑鍦虹櫧閮戒細鍐欏簱锛夛紝
    #    鍚﹀垯涓嬮潰 preempt 妫€鏌ュ繀鐒跺懡涓紝鍖归厤姘歌繙鍙戝畬涓€鍙ュ氨閫€銆?
    try:
        from data import watch as _W
        _W.mark_self_write(40.0)
    except Exception:
        pass

    snap = actor.snap(force=True)
    if detect(snap) != "chat":
        out["err"] = "涓嶅湪浼氳瘽椤?%s)" % detect(snap)
        return out

    card = read_card(snap)
    said, bs = said_already(dev, snap)
    if said:
        log.info("璇ヤ細璇濆凡璇磋繃璇濓紙姘旀场 %d 鏉★級锛岃烦杩囧彂閫?, len(bs))
        out["ok"] = True
        out["err"] = "宸茶杩囪瘽"
        # 馃敶 2026-11-03 淇 P1锛氭姠鍗犵暀浼氳瘽鍚庝簩娆¤繘鍏ワ紝闇€鍓嶈繘涓嶉噸鍙?
        #    锛坉aemon 鎹璋?advance锛岃€屼笉鏄妸銆屽凡璇磋繃璇濄€嶅綋澶辫触鍗℃锛夈€?
        out["skip_said"] = True
        return out

    # 鈶?杩涘鏂逛富椤靛缓妗?
    prof = None
    try:
        prof, pok = visit_profile(actor)
        if pok:
            out["prof"] = prof
            log.info("涓婚〉寤烘。 %s", prof)
    except Exception as e:
        log.warning("涓婚〉寤烘。寮傚父锛堢户缁彂寮€鍦虹櫧锛? %r", e)

    # 鈶?鍙戝紑鍦虹櫧锛堢敤鎴?2026-11-04 瀹氾細鏈湴妯″瀷鐢熸垚锛屽簾寮冨浐瀹氭睜瀛愶級
    text = _local_opener(card)
    out["text"] = text
    log.info("寮€鍦虹櫧 %r", text)
    if dry_run:
        out["ok"] = True
        return out

    ok, why = send(actor, dev, text)
    if not ok:
        out["err"] = why
        log.warning("鍙戦€佸け璐? %s", why)
        return out
    out["sent"] = True
    out["ok"] = True

    # 鈶?钀芥棫妗堟儏鍖?L4
    if prof:
        try:
            sid = CP.find_sid(db, text, device=dev)
            if sid:
                CP.save_profile(sid, prof, tags=card["tags"], common=card["common"])
                out["sid"] = sid
                log.info("妗堟儏鍖呭凡鍐?sid=%s", sid)
                # 馃 鏂板尮閰嶇殑浜猴細绔嬪埢璁╂湰鍦版ā鍨嬪嚭鐢诲儚/鏂规锛堢敤鎴?2026-11-02锛?
                #    杩欐牱濂圭涓€娆″洖璇濇椂锛屽嚭璇濆眰宸茬粡鏈夈€屽ス鏄粈涔堜汉銆嶅彲鐢紝
                #    涓嶇敤绛夊ス鑱婂崄鍙ユ墠寮€濮嬪缓妯°€?
                try:
                    from brain import reply as _R
                    _R.warm_local(sid, db, her_msg="", nick=prof.get("nick") or "")
                except Exception as _e:
                    log.debug("鏈湴鍒嗘瀽鎶曢€掑紓甯革紙涓嶅奖鍝嶅紑鍦虹櫧锛? %r", _e)
            else:
                log.warning("鍙嶆煡涓嶅埌 sid锛岃烦杩囧缓妗ｏ紙瀹佸彲涓嶅啓锛屼笉鍙啓閿欎汉锛?)
        except Exception as e:
            log.warning("鍐欐鎯呭寘寮傚父: %r", e)

    # 鈶?馃敶 鎶㈠崰妫€鏌ワ紙鐢ㄦ埛 2026-11-02锛夛細銆屽尮閰嶄腑鏈夋柊娑堟伅涔熻閫€鍑烘潵锛?
    #    浣嗘槸閫€鍑轰箣鍓嶄竴瀹氳鎶婂紑鍦虹櫧鍙戜簡鏉ャ€嶁€斺€旀墍浠ユ鏌ョ偣鏀惧湪**鍙戝畬涔嬪悗**銆?
    #    鍛戒腑灏变笉 advance锛屾妸杩欎釜浼氳瘽鐣欑潃锛堜笅娆?run_once 浼氬垽"宸茶杩囪瘽"鍐嶅墠杩涳級锛?
    #    杩欐牱鏃笉娴垂鍖归厤娆℃暟锛屽張鑳界珛鍒诲洖鍘诲鐞嗘柊娑堟伅/閾冦€?
    if preempt is not None:
        try:
            why = preempt()
            if why:
                log.info("鈿?寮€鍦虹櫧宸插彂锛屼絾妫€娴嬪埌 %s 鈫?涓嶅墠杩涳紝绔嬪埢鍥炲幓澶勭悊", why)
                out["preempted"] = why
        except Exception as e:
            log.warning("鎶㈠崰妫€鏌ュ紓甯革紙鎸変笉鎶㈠崰澶勭悊锛? %r", e)
    return out


def advance(actor):
    """鍦ㄥ紑鍦虹櫧纭鍙戝嚭鍚庯紝鐐逛細璇濋〉宸︿笂瑙掋€屽尮閰嶄笅涓€涓€嶃€?

    2026-11-14 鐢ㄦ埛纭鐨勬柊鐗堟祦绋嬶細
      鍖归厤鍒颁汉 鈫?鐐逛釜浜轰富椤靛缓妗?鈫?鍙戝紑鍦虹櫧 鈫?鐐瑰乏涓婅銆屽尮閰嶄笅涓€涓€嶃€?
    杩欓噷蹇呴』鐩存帴鍒囧埌涓嬩竴寮犲崱锛屼笉鑳藉洖鏄熺悆椤甸噸鏂板尮閰嶏紱杩斿洖 how锛?
      next     宸茬‘璁ゆ柊鍖归厤鍗?
      no_quota 宸茬敤瀹?
      no_button/timeout 鍋滄墜锛堜笉閲嶅鐐瑰嚮锛?
    """
    snap, pg, how = next_one(actor)
    if how == "next":
        return snap, pg, "next"
    if how == "no_quota":
        return snap, pg, "no_quota"
    log.warning("鍖归厤涓嬩竴涓湭鎴愬姛锛?s锛坧age=%s锛?, how, pg)
    return snap, pg, "fail"


def visit_profile(actor, settle=2.5):
    """杩涘鏂逛釜浜轰富椤垫姄璧勬枡锛屽啀杩斿洖浼氳瘽椤点€傝繑鍥?(prof, ok)銆?

    鐢ㄦ埛 2026-11-02锛?*鍖归厤鍒颁汉瑕佸厛寤哄鏂逛富椤垫。妗?*锛堝瓨杩涙棫妗堟儏鍖?L4锛夛紝
    鍚庣画鍥炲/鐢诲儚鎵嶆湁渚濇嵁锛堝凡濠?鑱屽満鎵撳伐浜鸿繖绫绘爣绛剧洿鎺ュ喅瀹氳瘽鏈竟鐣岋級銆?

    鍏ュ彛锛氫細璇濋〉鍙充笂銆屾煡鐪嬩富椤点€?725,219,900,288)锛屾垨瀵规柟澶村儚 userAvatar銆?
    """
    from eyes import profile as P

    def ui_back(s):
        """鍙湪涓婚〉宸︿笂瑙掔偣 App 鑷繁鐨勮繑鍥炴帶浠讹紝绂佹鐢ㄧ郴缁熻繑鍥為敭銆?""
        cands = []
        for x in s.nodes:
            if not x.visible or not x.clickable or x.center[1] > 220:
                continue
            label = (x.label or "").strip()
            if ("杩斿洖" in label or "back" in (x.res_id or "").lower()
                    or "item_left_back" in (x.res_id or "")):
                cands.append(x)
        if not cands:
            return None
        cands.sort(key=lambda x: (x.center[1], x.center[0]))
        return cands[0]

    snap = actor.snap()
    n = snap.hit(text="鏌ョ湅涓婚〉")

    if n is None:
        # 鈶?瀵规柟澶村儚銆傪煍?2026-11-10锛堟紨绀哄疄寮癸級锛歋oul 6.41.0 澶村儚 res-id 鏄?
        #    `chat_avatar`锛坄userAvatar` 宸蹭笉瀛樺湪锛夆啋 鍘熸潯浠舵案杩滆惤绌?鈫?鎺夋樀绉板厹搴?
        #    鐐归敊銆屽姞閫熴€嶃€傚彟鍔犲乏鍗婂睆杩囨护锛堝鏂瑰ご鍍?x鈮?0~128锛屾垜鏂瑰ご鍍忓湪鍙充晶锛夈€?
        av = [x for x in snap.nodes
              if x.clickable and x.center[0] < 450
              and ("userAvatar" in (x.res_id or "") or "chat_avatar" in (x.res_id or "")
                   or (x.desc or "") == "澶村儚")]
        if av:
            av.sort(key=lambda x: x.center[0])
            n = av[0]
            log.info("鐢ㄥご鍍忚妭鐐?%s 杩涗富椤?, n.bounds)

    if n is None:
        # 鈶?浼氳瘽椤甸《閮ㄧ殑瀵规柟鏄电О锛堝疄娴?y鈮?05銆亁鈮?50锛夆€斺€旀櫘閫氫細璇濋〉娌℃湁銆屾煡鐪嬩富椤点€嶏紝
        #    浣嗙偣鏄电О鑳借繘涓婚〉锛涜繖涓€姝ヨ銆岃亰澶╂椂琛ュ缓妗ｆ銆嶇湡姝ｅ彲琛屻€?
        skip = ("杩斿洖", "鍏虫敞", "鑱婂ぉ璁剧疆", "鏇村", "鎼滅储", "閫氳褰?,
                "8灏忔椂鍓?, "鍒氬垰鍦ㄧ嚎", "鍦ㄧ嚎",
                # 馃敶 2026-11-10锛堟紨绀哄疄寮圭偣閿欍€屽姞閫熴€嶏級锛氶《鏍忓姛鑳芥寜閽叏閮ㄦ帓闄?
                "鍔犻€?, "鍏虫敞鍚庡彲閭€璇烽€氳瘽", "閫氳瘽", "绀肩墿", "妗岀悆", "涓€璧峰惉")
        cands = [x for x in snap.nodes
                 if x.label and x.clickable and x.center[1] < 170
                 and 150 < x.center[0] < 800
                 and x.label.strip() not in skip
                 and 1 <= len(x.label.strip()) <= 16
                 and "TextView" in (x.cls or "")        # 馃敶 鍙鏂囨湰鑺傜偣锛屽埆鐐瑰埌瀹瑰櫒
                 and ":" not in x.label and "锛? not in x.label]  # 鏃堕棿/鍓爣棰樻帓闄?
        if cands:
            # 馃敶 鍘熸潵鍙?cands[0]锛堟枃妗ｉ『搴忥紝鍙兘鏄《鏍忔煇涓鍣級锛涙敼鎴愪粠涓婂埌涓嬨€佷粠宸﹀埌鍙?
            cands.sort(key=lambda x: (x.center[1], x.center[0]))
            n = cands[0]
            log.info("鐢ㄩ《閮ㄦ樀绉?%r 杩涗富椤?, n.label)

    if n is None:
        log.info("浼氳瘽椤垫病鏈夎繘涓婚〉鐨勫叆鍙ｏ紙鏅€氫細璇濓級锛岃烦杩囧缓妗?)
        return None, False

    log.info("杩涘鏂逛富椤?%s", n.bounds)
    actor.hand.tap_node(n, settle=settle)
    s = actor.snap(force=True)

    txt = "\n".join(s.texts())
    if not any(k in txt for k in ("鐏甸瓊鐢诲儚", "Ta鐨勫睍鍝侀", "IP灞炲湴", "琚叧娉?)):
        log.warning("鐐逛簡鏌ョ湅涓婚〉浣嗘病杩涗富椤碉紙page=%s锛?, detect(s))
        if detect(s) != "chat":
            b = ui_back(s)
            if b is not None:
                actor.hand.tap_node(b, settle=1.2)
        return None, False

    prof = P.read(s)
    log.info("涓婚〉璧勬枡: %s", P.summary(prof))

    # 鐢ㄦ埛纭鍒欙細鍖归厤閾捐矾涓嶇敤绯荤粺杩斿洖閿€傜偣涓婚〉宸︿笂瑙?App 杩斿洖鎺т欢锛?
    # 鏈壘鍒板氨鍋滄墜锛岀粷涓嶆妸鍖归厤浼氳瘽韪㈠洖鏄熺悆椤点€?
    b = ui_back(s)
    if b is None:
        log.warning("涓婚〉鎵句笉鍒伴〉闈㈣繑鍥炴帶浠讹紱涓嶆寜绯荤粺杩斿洖锛屼繚鐣欑幇鍦?)
        return prof, False
    log.info("鐐逛富椤佃繑鍥炴帶浠?%s", b.bounds)
    actor.hand.tap_node(b, settle=1.5)
    s2, pg = actor.wait_page(("chat",), timeout=6.0)
    if pg != "chat":
        log.warning("浠庝富椤佃繑鍥炲悗椤甸潰=%s锛涙湰杞笉鍙戦€併€佷笉鐐瑰尮閰嶄笅涓€涓?, pg)
        return prof, False
    return prof, True


def has_card(snap):
    """褰撳墠浼氳瘽椤垫槸涓嶆槸銆屽垰鍖归厤銆佽繕娌¤璇濄€嶇殑璧勬枡鍗°€?

    瀹炴祴鍖归厤鍗′笂涓€瀹氫細鏈夈€屽尮閰嶅害銆? 鐧惧垎姣旓紱寮曞姏绛?鏄熷骇涓嶄竴瀹氭樉绀猴紙鏈変汉鍦ㄦ槦鐞?
    閲屾病濉級锛屾墍浠ヤ笉鑳藉彧闈犻偅涓ら」銆?
    """
    txt = "\n".join(snap.texts())
    if "鍖归厤搴? in txt:
        return True
    if "Ta鐨勫紩鍔涚" in txt or "Ta鐨勬槦搴? in txt:
        return True
    return False


CARD_AREA_BOTTOM = 640   # 鍖归厤璧勬枡鍗★紙鍚叴瓒ｆ爣绛句簯锛夊崰鎹殑绾靛悜鍖哄煙锛屽疄娴嬪簳閮?~600

# 馃敶馃敶 2026-11-08 11:3x锛圥0路鐢ㄦ埛锛氥€岃繘鍏ュ璇濋〉閭ｄ箞涔呬簡 寮€鍦虹櫧杩樺彂涓嶅嚭鍘汇€嶏級
#
#   銆愬疄娴嬫牴鍥犮€戠敓浜ф棩蹇楅噷杩炵画 6+ 娆″嚭鐜帮細
#       銆岃浼氳瘽宸茶杩囪瘽锛堟皵娉?3 鏉★級锛岃烦杩囧彂閫併€?
#       銆岃鍖归厤浼氳瘽宸茶杩囪瘽 鈫?鍓嶈繘鍒颁笅涓€涓汉锛堜笉閲嶅彂锛夈€?
#   鑰岄偅涓€灞?*鏄庢槑鏄叏鏂板尮閰嶅崱**锛堟爲閲屾湁銆屽尮閰嶅害 96%銆嶃€屾煡鐪嬩富椤点€嶃€岀伒鎰熷洖澶嶅彲鎻愬崌鍥炲鐜囧摝銆嶏紝
#   涓€鏉℃秷鎭兘娌℃湁锛夈€備簬鏄瘡涓€寮犳柊鍗￠兘琚垽銆屽凡璇磋繃璇濄€嶁啋 寮€鍦虹櫧涓€娆￠兘涓嶅彂 鈫?鍖归厤棰濆害鐧界儳銆?
#
#   涓轰粈涔?OCR 浼氬垽鎴愩€屾垜鍙戣繃銆嶏細鍏ㄦ柊鍗′笅闈㈡湁涓€鏁村潡 **鐏垫劅鍥炲寤鸿**锛圫oul 缁欑殑蹇嵎鍙ワ級锛?
#   瀹炴祴 11:32 鐨?OCR锛?
#       (76,1216) '浣犲ソ锛忓彲浠ヨ璇嗗悧'   (79,1275) '鉁ㄥ甫涓洰鐨勶紝鐩寸悆鐮村啺鍚?
#       (76,1358) '鍡紝浣犲ソ锛忓湪骞插槢鍛€锛?  (102,1141) '鐏垫劅鍥炲鍙彁鍗囧洖澶嶇巼鍝?
#   杩欎簺**涓嶅湪 a11y 鏍戦噷**锛坕ntree=False锛夛紝鎵€浠ャ€屾爲閲屾湁 鈫?鍓旈櫎銆嶈繖涓€鎷涘瀹冧滑鏃犳晥锛?
#   鑰岃祫鏂欏崱鍖哄煙杩囨护鍙尅浜?y<640锛屽畠浠叏鍦?y=1100~1400 鈬?婕忚繘鏉ャ€?
#   鍙鍏朵腑浠绘剰涓€鏉＄殑 OCR 妗嗗彸杈圭晫 >= 700锛堝疄娴?'娲惧澶у巺>'/'鐙间汉榄呭奖' 杩欑被鍙充晶鍏冪礌
#   鍜岄暱鍙ュ缓璁彞閮戒細锛夛紝side_of() 灏卞垽鎴?me 鈬?said_already=True銆?
#
#   銆愪慨娉暵蜂袱灞傦紝閮芥槸纭垽鎹笉鏄皟闃堝€笺€?
#     鈶?**鏍戞爣璁颁紭鍏?*锛氬叏鏂板崱涓€瀹氭湁銆岀伒鎰熷洖澶嶅彲鎻愬崌鍥炲鐜囧摝銆嶏紝
#        鑰屽彂杩囪瘽涔嬪悗杩欎釜鏍囪浼氬彉鎴愩€屽唴瀹圭敱AI鐢熸垚锛屼粎渚涘弬鑰冦€嶏紙11:26 鍙戝畬鍚庡疄娴嬶級銆?
#        鈬?瑙佸埌鍓嶈€呭氨 100% 璇存槑銆屼竴鍙ラ兘娌″彂杩囥€嶏紝鐩存帴杩斿洖 False锛岃繛 OCR 閮戒笉鐢ㄨ窇锛堢渷 2s锛夈€?
#     鈶?鏈夊崱鏃讹紝鎶娿€岀伒鎰熷洖澶?寤鸿鍙ャ€嶆墍鍦ㄧ殑 y>=1100 鏁存鎺掗櫎鍑烘皵娉″垽瀹氥€?
#        鐪熸鐨勬秷鎭皵娉″湪鍗′笂鍑虹幇鍦?y鈮?80~900锛堝疄娴嬫垜鍙戠殑閭ｅ彞鍦?714锛夈€?
CARD_FRESH_MARK = "鐏垫劅鍥炲鍙彁鍗囧洖澶嶇巼鍝?
CARD_REPLY_MARK = "鍐呭鐢盇I鐢熸垚"
SUGGEST_Y_TOP = 1100     # 鍗′笂銆岀伒鎰熷洖澶嶃€嶅缓璁尯涓婄晫锛堝疄娴?1123~1400锛?


def said_already(dev, snap=None):
    """褰撳墠浼氳瘽閲屾垜鏄惁宸茬粡鍙戣繃娑堟伅銆傝繑鍥?(bool, bubbles)銆?

    Soul 鐨勬皵娉′笉鍦?a11y 鏍戦噷锛屽彧鑳芥埅鍥?OCR 鐪嬪乏鍙筹紙x2>=700 = 鎴戯級銆?
    浣嗗尮閰嶈祫鏂欏崱涓婄殑鏂囧瓧浼氭贩杩?OCR锛屽疄娴嬩袱绫昏鍒わ細
      鈶?銆?5%銆嶃€屾煡鐪嬩富椤点€嶈繖绫诲彸渚у厓绱?-> 琚綋鎴愭垜鏂规皵娉?
      鈶?鍏磋叮鏍囩浜戙€岀編椋熼煶涔愯拷鍓ч槄璇汇€嶃€岋級锛堣澶存枃鍖栥€嶈鍚堝苟璇嗗埆鎴愪竴琛屻€?
         钀藉埌鍙充晶 x=447..811 -> 涔熻褰撴垚鎴戞柟姘旀场
    涓や釜骞插噣鍒ゆ嵁锛?
      鈶?鍗＄墖鏂囧瓧鍏ㄩ兘鍦?UI 鏍戦噷锛岀湡姝ｇ殑娑堟伅姘旀场涓嶅湪鏍戦噷 -> 鎸夋枃鏈墧闄?
      鈶?璧勬枡鍗″尯鍩燂紙y < CARD_AREA_BOTTOM锛夐噷鐨勪笢瑗夸竴寰嬩笉鏄秷鎭?-> 鎸夊尯鍩熷墧闄?
    """
    from eyes import chat as C

    if snap is None:
        from eyes.uitree import Screen
        snap = Screen(dev).get(force=True)
    tree = set(t.strip() for t in snap.texts() if t and t.strip())
    card = has_card(snap)

    # 鈶?鍏ㄦ柊鍖归厤鍗★細鏍戦噷鏈夈€岀伒鎰熷洖澶嶅彲鎻愬崌鍥炲鐜囧摝銆嶁噿 涓€鍙ラ兘娌″彂杩囷紙瑙佷笂鏂归暱娉ㄩ噴锛?
    if card and CARD_FRESH_MARK in tree:
        return False, []

    png = dev.screencap()
    bs = C.bubbles(png)
    real = []
    for b in bs:
        t, side, it = b
        if t.strip() in tree:
            continue
        if card and it.cy < CARD_AREA_BOTTOM:
            continue
        # 鈶?鍗′笂鐨勩€岀伒鎰熷洖澶嶃€嶅缓璁尯锛坹>=1100锛変笉鏄秷鎭紝涓€寰嬫帓闄?
        if card and it.cy >= SUGGEST_Y_TOP:
            continue
        real.append(b)
    return any(side == "me" for _t, side, _it in real), real
