# -*- coding: utf-8 -*-
"""宸茶鏈洖闃熷垪锛氭湁娑堟伅銆佷絾娌＄孩鐐圭殑浼氳瘽涔熻鍥炪€?

鐢ㄦ埛 2026-11-02锛氥€岀孩鐐规竻瀹屼簡涔嬪悗 瑕佺‘璁や竴涓嬪凡璇绘湭鍥炵殑涔熻澶勭悊銆?
       銆岃繘鍏ュ璇濇浜嗕箣鍚?濡傛灉鏈€鍚庝竴鏉℃秷鎭槸瀵规柟鍙戞潵鐨?閭ｄ箞涓€瀹氳鍋氬洖澶嶃€?

涓轰粈涔堝崟鐙竴涓ā鍧楋細
  娓呯孩鐐癸紙brain.clear锛夊彧鑳藉鐞?*鍒楄〃閲屾湁绾㈢偣**鐨勪細璇濄€?
  浣嗐€岃繘鍘荤湅杩囦竴鐪煎氨閫€鍑恒€嶄細鎶婄孩鐐规竻鎺夛紝娑堟伅鍗磋繕娌″洖 鈥斺€?杩欑被浼氳瘽璇箟涓婁粛鏄緟鍥烇紝
  鍙槸娌℃湁绾㈢偣鍙偣锛屽繀椤婚潬 **鎼滅储 lastMsgText** 瀹氫綅锛坆rain.search锛夈€?
"""
import json
import os
import re
import threading
import time
from collections import Counter

from brain import casepack as CP
from brain import reply as R
from brain import pending_policy as PP
from brain import voice as V
from brain import search as S
from core.log import get_logger
from core import metrics as MET
from core.paths import LOGS, STATE
from data import pending_ledger as PL
from hands.input import Input

log = get_logger("brain.pendingq")

MAX_N = 5
# 銆屾柊娑堟伅銆嶇獥鍙ｏ細杩欎箞涔呬互鍐呭ス鍙戞潵鐨勶紝鍜屾柊绉帇**浜ら敊**鍑洪槦锛堣 candidates 鏈熬锛夈€?
#   鐢ㄦ埛 2026-11-03锛氥€屾湁绾㈢偣灏变竴瀹氭湁鏂版秷鎭繘鏉ャ€嶁€斺€?鏂版秷鎭笉鑳借鍑犲崄涓Н鍘嬫尋浣忋€?
FRESH_H = float(os.environ.get("SOUL_FRESH_H", "6") or 6)
# 涓€娆℃壂鎻忓彇澶氬皯涓€欓€夛紙鐢ㄤ簬鍒ゆ柇绉帇瑙勬ā + 鎺掑簭锛夈€?
#   馃敶 2026-11-03锛氬師鏉ュ啓姝?12 鈫?backlog 姘歌繙鏄剧ず 12锛岃€屽疄闄呯Н鍘?54 涓紝
#     闄嶇骇闃堝€?鍚炲悙鍏ㄦ寜閿欑殑鏁扮畻锛岄槦鍒楁湯灏剧殑鑰佷細璇濇案杩滆繘涓嶄簡瑙嗛噹銆?
CAND_SCAN = int(os.environ.get("SOUL_CAND_SCAN", "60") or 60)
# 馃敶 2026-11-04锛圥0 澶勭悊鐜妭锛夛細find_row 棣栧睆涔嬪鏈€澶氬啀寰€涓嬬炕鍑犲睆銆?
#   瀹炴祴棣栧睆鍙湁 8~10 琛岋紝鍊欓€?60 涓?鈫?棣栧睆鍛戒腑鐜囦粎 **14%**锛?6% 琚揩璧版悳绱?
#   锛?1~15s/娆°€佷笖 Soul 涓嶇储寮曞嚑澶╁墠鐨勬秷鎭?鈫?甯?notfound锛夈€傜炕 3 灞忔妸鍛戒腑鐜囨姮涓婃潵銆?
# 馃敶 2026-11-10 23:45锛堥€熷害锛夛細3 -> 5銆傜炕涓€灞?~4s锛屼竴娆℃悳绱?~32s 鈥斺€?
#   缈诲睆姣旀悳绱究瀹?8 鍊嶄笖涓嶄細瑙﹀彂 clear_text/鍒囧悗鍙伴闄┿€傚疄娴?22h 鐨勪細璇?
#   缈?3 灞忚惤绌恒€佽浆鎼滅储鍙堣秴鏃讹紱澶氱炕 2 灞忥紙+8s锛夎繙姣旀悳涓€娆★紙32s锛夊垝绠椼€?
FIND_PAGES = int(os.environ.get("SOUL_FIND_PAGES", "5") or 5)
SKIP_UID_PREFIX = ("2042683",)     # 瀹樻柟钀ラ攢鍙锋锛堝疄娴?2042683xx 鍏ㄦ槸绉垎/绀肩墿鎺ㄩ€侊級
LOOKBACK_DAYS = 7
SCAN_SESSIONS = 300
# 馃敶 2026-11-08 03:30锛圥0 姝婚攣淇锛?*闃堝€兼寜瀹炴祴鏁版嵁淇锛?2h 鈫?24h**锛?
#
#   瓒呰繃杩欎釜灏忔椂鏁版病娲昏穬鐨勪細璇濓紝涓嶅啀娴垂銆岀炕 3 灞?+ 鎼滅储銆嶅幓瀹氫綅銆?
#
#   銆?2h 鏄敊鐨勶紝瀹炴祴鎷愮偣鍦?12h銆慴acklog-profiler 鍏ㄩ噺閰嶅 2383 涓牱鏈?
#   锛坆rain.pendingq.log 11-02鈫?1-08锛夊緱鍑猴細
#     鍒楄〃鍛戒腑鐜囷細 0鈥?h 43.9% 鈫?3鈥?h 3.0% 鈫?**12鈥?8h 0.0%** 鈫?24h 鍚?鈮?
#     鍥炴垚鍔熺巼锛?  0鈥?h 55.8% 鈫?6鈥?2h 7.7% 鈫?**60鈥?2h 绮剧‘ 0.0%锛?55/155 鍏ㄨ触锛?*
#
#   闃熷垪/浜у嚭瀵圭収锛堝綋鍓嶅疄鐩?63 浜猴級锛?
#     age<24h  鈫?闃熷垪 11锛岄鏈熷洖鍑?~6 鏉?杞?  鈫?鏈€浼?
#     age<36h  鈫?闃熷垪 17锛寏6.5
#     age<72h锛堝師璁惧畾锛夆啋 闃熷垪 33锛寏6.7        鈫?澶?22 涓櫧鐑э紝鍙璧?0.7 鏉★紝鑰楁椂脳3
#     鍏ㄩ噺 63  鈫?棰勬湡浠?3.1 鏉?
#
#   鎵€浠ュ彇 24h锛堢浉姣?18h 鐨勭湡瀹炴嫄鐐圭暀 6h 瀹夊叏杈归檯锛夈€?
#   娉ㄦ剰锛?*涓嶆槸涓嶅洖浜?* 鈥斺€?濂逛滑浠嶅湪搴撻噷锛岀瓑鍝ぉ鍐嶅彂鏂版秷鎭紙ts 鍙樻柊锛夎嚜鐒跺洖鍒伴槦鍒椼€?
#
# 馃敶馃敶 2026-11-08 12:4x锛?4h 浠嶅お鏉撅紝闄嶅埌 12h锛圥0-1锛宊team/search_diag.md 搂2.1锛夈€?
#   瀹炴祴鎸夊勾榫勫垎娈电殑鍥炲嚭鐜囷細0-1h 49.2% / 3-6h 0.0% / 6-12h 10.7% / 12-24h 0.0% / 24h+ ~0%銆?
#   12-24h 娈靛洖鍑虹巼 0.0%锛屽嵈鍗犱簡鍊欓€夌殑鐩稿綋姣斾緥锛岀炕灞?21.2s/娆″叏閮ㄧ櫧鐑с€?
#   闄嶉椄鍚?44h 绐楀彛棰勮鐪?~229 鍒嗛挓瀹氫綅鏃堕棿锛屾妸棰勭畻璁╃粰 0-1h 鐨勬柊椴滃€欓€夈€?
#
# 馃敶馃敶馃敶 2026-11-08 12:46锛?*鑷垜鎷烽棶鍚庡洖閫€锛屼笂闈㈣繖鏉℃敼鍔ㄦ槸閿欑殑**锛?
#
#   鎴戞敼瀹?12h 鍚庣珛鍒诲疄娴嬶紝缁撴灉鏄伨闅撅細
#     路 candidates(40) 浠?12 涓帀鍒?**1 涓?*
#     路 鏃ュ織杩炵画鍑虹幇銆岃繃鏈熸窐姹?11 涓?鈫?闃熷垪鍓?1 涓€嶃€岄槦鍒楀墿 0 涓€?
#     路 绾㈢偣闂歌杩€屾斁琛屽尮閰嶏紙candidates 涓虹┖锛夈€嶏紝宸茶鏈洖褰诲簳绌鸿浆
#
#   涓轰粈涔堥敊锛氶偅涓€?2-24h 鍥炲嚭鐜?0.0%銆嶆槸**鍘嗗彶缁熻**锛岃€岃繖娈靛巻鍙查噷
#   `open_search()` 涓€鐩存槸鍧忕殑锛堟悳绱㈡鏂囨鏄€屾悳绱㈠娉ㄣ€佹樀绉版垨鑰呰亰澶╄褰曘€嶏紝
#   鏃т唬鐮佸彧璁ゃ€屾悳绱€嶄袱涓瓧 鈫?蹇呯劧澶辫触锛夈€?*鍥炲嚭鐜?0% 鏄悳绱㈠潖鎺夌殑缁撴灉锛?
#   涓嶆槸銆岃€佷細璇濅笉鍊煎緱鍥炪€嶇殑璇佹嵁**銆傛嬁涓€涓湁 bug 鏃舵湡鐨勭粺璁″幓瀹氶槇鍊硷紝
#   绛変簬鎶?bug 褰撴垚浜嗚瘉鎹?鈥斺€?杩欐槸鍏稿瀷鐨勩€岀敤鐩稿叧鎬у啋鍏呭洜鏋溿€嶃€?
#
#   鑰屼笖鏂瑰悜涓婃洿绯燂細鎴戝垰鎶婃悳绱慨濂斤紝鑰佷細璇濈幇鍦?*鏈夊彲鑳?*鍥炲緱鍑哄幓浜嗭紝
#   姝ゆ椂鏀剁揣闂搁棬姝ｅソ鎶婂垰淇ソ鐨勮兘鍔涘叧鎺夈€?
#
#   鈬?鍥炲埌 24h銆傜湡瑕佹敹绱э紝蹇呴』绛夋悳绱慨澶嶅悗鐨?*鏂?*鏁版嵁锛堣嚦灏戣窇婊′竴澶╋級鍐嶅畾锛?
#     鑰屼笖搴旇鐢ㄣ€屾悳绱㈡垚鍔熺巼銆嶈€屼笉鏄€屽洖鍑虹巼銆嶄綔渚濇嵁銆?
# 馃敶 2026-11-10 搂104锛堢敤鎴峰畾绋匡級锛氫笌 RESTART_H **蹇呴』瀵硅皟**锛屽崟鏀逛换涓€鏉￠兘鐣欏潙銆?
#   鍘?24h 娣樻卑浼氭妸 24~72h 鐨勫緟鍥炲叏閮ㄨ涪鍑猴紝瀵艰嚧銆?24h 閲嶆柊寮€鍦恒€嶆案杩滆Е鍙戜笉浜嗭紱
#   鏀规垚 72h 鍚庯紝24~72h 鐨勪汉浜ょ粰閲嶆柊寮€鍦?璺熻繘闃舵锛?72h 鎵嶇敱鐘舵€佹満褰掓。銆?
STALE_GIVEUP_H = float(os.environ.get("SOUL_STALE_GIVEUP_H", "72") or 72)

# 馃敶 2026-11-03锛堢敤鎴峰畾 **B 鏂规**锛夛細濂逛笂涓€鏉″凡瓒呰繃 RESTART_H 灏忔椂 鈫?涓嶅啀銆屾帴璇濄€嶏紝
#   鏀广€岄噸鏂板紑鍦恒€嶏紙鎹㈢敱澶淬€佷笉鎻愭棫璇濋銆佷笉閬撴瓑锛夈€?
#   瀹炵洏锛?6:30 鍓満涓や釜搴擄級锛?72h 寰呭洖 29 涓紝鏈€鑰?570h 鈮?23.8 澶╋紱
#   鍏朵腑 11 涓ス鍙洖浜嗐€屽棷 / 浣犲ソ / 鍝堝搱 / [鍛哴 / [鐙楀瓙]銆嶁€斺€?
#   闅斾簩鍗佸ぉ鍘荤瓟涓€涓€屽棷銆嶆棦娌″唴瀹癸紝涔熶竴瀹氶湶棣咃紙濂规棭蹇樹簡鑷繁璇磋繃锛夈€?
#   0 = 鍏抽棴锛堝叏閮ㄦ寜姝ｅ父鎺ヨ瘽锛夈€?
# 馃敶 2026-11-10 搂104锛?2 鈫?24锛堢敤鎴枫€岃秴杩?24h 鐨勭Н鍘嬮噸鏂板紑鍦恒€嶏級銆?
#   鍒ゆ嵁涓嶅啀鍙湅 age锛歨andle_pending 鏀圭敤 verdict 鐘舵€佹満锛坅ge>=24h 涓旀湰鍥炲悎 0 鏉★級銆?
RESTART_H = float(os.environ.get("SOUL_RESTART_H", "24") or 24)
# 姣忚疆鏈€澶氬鐞嗗嚑涓€岄噸鏂板紑鍦恒€嶏細29 涓竴娆℃€у彂鍑哄幓鍍忕兢鍙戯紝
#   鑰屼笖鑰佷細璇濅細鍗犳帀鏈疆鐨勫彂閫佸悕棰濄€傚師鏉?1 涓?杞紝閰?2 鏉?杞殑棰濆害锛?
#   17 涓?>72h 鐨勪細璇濊 17 杞紙绾?1 灏忔椂锛夋墠杞埌涓€閬?鈥斺€?鐜板湪 2 涓?杞€?
RESTART_PER_ROUND = int(os.environ.get("SOUL_RESTART_PER_ROUND", "2") or 2)
# 绯荤粺绫讳細璇濇枃鏈紙涓嶆槸鐪熶汉璇寸殑璇濓紝鍥炰簡绛変簬瀵规満鍣ㄨ璇濓級
SYS_TEXTS = ("[浜掑姩娑堟伅]", "[浜掑姩鎻愰啋]", "[绯荤粺娑堟伅]", "[瀹樻柟娑堟伅]")

# 馃敶 澶辫触鍙拌处锛堢敤鎴?2026-11-02锛氥€岄兘鍑虹幇鏈壘鍒扮浉鍏崇粨鏋滀簡 涓轰粈涔堣繕鏈夋棤闄愭鐨勯噸璇曘€嶏級
#   鎼滀笉鍒扮殑浼氳瘽濡傛灉姣忚疆閮介噸璇曪紝姣忔鐧界儳 11s锛堟悳绱㈡帴鍙ｆ湰韬 11s 鎵嶈繑鍥?鏈壘鍒?锛夈€?
#   瑙勫垯锛氬悓涓€ sid + 鍚屼竴鍙ユ湯鏉★紝澶辫触鍚庡喎鍗?SKIP_HOURS 灏忔椂锛?
#         濂逛竴鍙戞柊娑堟伅锛堟湯鏉℃枃鏈彉浜嗭級灏辫嚜鍔ㄩ噸鏂拌瘯 鈥斺€?鍒妸娲讳汉姘镐箙鎷夐粦銆?
SKIP_HOURS = 3

# 馃敶 2026-11-09 R3锛堢敤鎴锋媿鏉匡細銆屾悳绱笉鍒板氨涓嶆悳浜嗗晩 绛夐棽涓嬫潵鐨勬椂鍊欐悳銆嶏級
#   鏃у疄鐜?notfound 涓€娆＄綒 3 灏忔椂 鈬?鐩存帴琛ㄧ幇鎴愩€屾秷鎭繘鏉ュ緢涔呮病浜哄洖銆?
#   锛堝疄娴?21:08 浠嶆湁浼氳瘽銆屽師鍥?notfound锛屽墿 89 鍒嗛挓銆嶏紝绛変簬鎶婂ス鍐诲埌涓嬩竴鍦哄璇濓級銆?
#   鏂板彛寰勶細鏈疆鎼滀笉鍒?= 鏈疆涓嶆悳锛? 鍒嗛挓鍚庯紙鈮?闂蹭笅鏉ユ椂锛夎嚜鐒堕噸璇曪紝涓嶅喕缁撱€?
#   闃茬櫧鐑э細鍚?sid 30 鍒嗛挓鍐?notfound 鈮? 娆?鈫?鍗囩骇 30 鍒嗛挓锛岄伩鍏嶅弽澶嶆挒澧欍€?
#   鍏ㄩ儴鍙敤鐜鍙橀噺鍥炶皟锛涜 SOUL_NOTFOUND_COOL_MIN=180 鍗冲洖鍒版棫琛屼负銆?
NOTFOUND_COOL_H = float(os.environ.get("SOUL_NOTFOUND_COOL_MIN", "5") or 5) / 60.0
NOTFOUND_STORM_N = int(os.environ.get("SOUL_NOTFOUND_STORM_N", "3") or 3)
NOTFOUND_STORM_H = float(os.environ.get("SOUL_NOTFOUND_STORM_MIN", "30") or 30) / 60.0
# R5锛氬ス鏈€鍚庝竴鏉¤秴杩囪繖涔堝鍒嗛挓娌℃帴涓?鈫?鏍囩孩锛堝彧璁版棩蹇楋紝涓嶆彃鎵嬫搷浣滐級
SLA_WARN_MIN = float(os.environ.get("SOUL_SLA_WARN_MIN", "5") or 5)
SLA_WARN_REPEAT_S = float(
    os.environ.get("SOUL_SLA_WARN_REPEAT_MIN", "30") or 30
) * 60.0
# 馃敶 2026-11-04锛圥1锛夛細12h 鈫?3h銆傚師鏉ョ殑 12h 鏄湪銆屽彧鑳介潬鎼滅储瀹氫綅銆嶇殑鍓嶆彁涓嬪畾鐨勶紝
#   鑰岀幇鍦?find_row 浼氱炕 3 灞忥紝寰堝 notfound 鐨勪細璇濅笅涓€杞氨鑳藉湪鍒楄〃閲岀偣杩涘幓锛?
#   12h 鍐峰嵈鍙嶈€岃瀹冧滑鐧界瓑鍗婂ぉ锛堝疄娴嬬敓鏁?29 鏉°€佷腑浣嶅墿 11.1h锛夈€?
#   鍐峰嵈浠嶆寜 (sid + 鏈潯鏂囨湰) 姣斿 鈥斺€?濂逛竴璇存柊璇濆氨鑷姩澶辨晥锛屼笉浼氳浼ゃ€?
# 馃敶 瓒呮椂锛堟帴鍙ｆ參/璁惧鍗★級**涓嶆槸**鎼滀笉鍒帮細鍙綒 10 鍒嗛挓灏遍噸璇曘€?
#   2026-11-02 鐜扮綉浜嬫晠锛氭悳绱?15s 绐楀彛澶揣 鈫?瓒呮椂琚綋鎴?notfound 鈫?鍚屼竴浜哄喎鍗?12 灏忔椂娌′汉鍥炪€?
TIMEOUT_RETRY_H = 0.17
# 馃敶 2026-11-10锛氭悳涓嶅埌浠讳綍鍙潬绾跨储锛堟樀绉般€佺嫭涓€鏃犱簩鍐呭閮芥病鏈夛級鏃剁殑鍐峰嵈銆?
#   鐢ㄦ埛鍙ｅ緞銆岃繕鏄笉琛屽氨鏀惧純鎴栬€呰烦杩囥€嶁€斺€斾絾鍙拌处 key 鍚ス鏈潯鏂囨湰锛?
#   濂逛竴鍙戞柊娑堟伅灏变細鑷姩閲嶆柊缁欐満浼氾紝鎵€浠ヨ繖閲屽彧鎸°€屽悓涓€鍙ュ弽澶嶆挒澧欍€嶃€?
NO_CUE_H = float(os.environ.get("SOUL_NOCUE_COOL_MIN", "30") or 30) / 60.0
ENTER_RETRY_H = 0.5
# 馃敶 2026-11-04锛圓鎵规彁閫燂級锛氱煭娑堟伅/绾〃鎯?find_row 钀界┖鍚庝笉鎼滅储锛岀煭鍐峰嵈锛?0鍒嗛挓锛?
#   濂瑰啀鍙戞柊娑堟伅锛堟柊绾㈢偣锛変笅涓€杞?find_row 灏辫兘鍛戒腑锛屼笉浼氭案涔呭け鑱斻€?
SHORT_RETRY_H = 0.5
# 馃敶 2026-11-04锛堝繀鍥為棴鐜級锛氳韩浠芥牎楠岃繛缁け璐ヨ**鐔旀柇**銆?
#   瀹炴祴銆岄偅涓嶇煡閬撱€嶃€孾鐙楀瓙]銆嶄袱浼氳瘽鍚勫け璐?8 娆★細鎼滅储鍑?2~3 鏉＄粨鏋滀絾姘歌繙鐐圭涓€鏉?
#   鈫?杩涢敊浼氳瘽 鈫?鏍￠獙澶辫触 鈫?2 鍒嗛挓鍚庨噸璇曡繕鏄涓€鏉?鈫?鏃犻檺绌鸿浆锛堟瘡杞櫧鐑?15~20s锛?
#   鑰屼笖杩欎簺浜?*姘歌繙鍥炰笉浜?*锛夈€傜幇鍦ㄦ寜澶辫触娆℃暟渚濇鐐圭 2銆? 鏉＄粨鏋滐紝
#   鍏ㄩ儴璇曡繃锛圛DFAIL_MAX_TRIES锛夊氨闀垮喎鍗?IDFAIL_GIVEUP_H 灏忔椂锛岀瓑濂瑰彂鏂版秷鎭啀璇?
#   锛堟湯鏉℃枃鏈彉浜?鈫?should_skip 鑷姩澶辨晥 鈫?閲嶆柊缁欐満浼氾級銆?
IDFAIL_MAX_TRIES = 4
IDFAIL_GIVEUP_H = 2.0
SKIP_FILE = PL.SKIP_FILE

# 馃敶 2026-11-08锛圥0銆岀瀻鎿嶄綔銆嶆牴鍥犱慨澶?路 璁惧绾ф晠闅滅啍鏂級锛?
#   鏀瑰墠锛氫富寰幆閲?`if pg != "chatlist": break` 鈥斺€?鍥炰笉鍒板垪琛ㄥ氨**浣滃簾鏁磋疆**銆?
#   鏃ュ織瀹炶瘉锛坉aemon.out 11-08 00:19鈥?0:30锛夛細杩炵画 14 涓€欓€夈€佸洖 0 鏉°€?
#   鏁磋疆 533.8s 鍏ㄥ簾锛宍宸茶鏈洖 425s 涓€鏉￠兘娌″洖鎴?鈫?鏀跺伐锛堝紓甯革級`銆?
#   鍚屾 brain.nav.log 23 鏉″叏閮ㄦ槸 `[nav] unknown 绗?1 娆?鈫?back` 鈥斺€?nav 鐨勬仮澶?
#   闃舵浠庢病鐖笂鍘伙紙鍏ㄩ噺 `unknown 绗?1/2/3 娆 = 123/1/1銆乣寮哄埗鍥為椤礰=1銆乣閲嶅惎 App`=0锛夈€?
#
#   涓轰粈涔堜笉鏄€岄€愪釜鎺掗槦 + 2min 鍐峰嵈銆嶏紙鎴戜笂涓€鐗堟彁妗堬紝宸茶鍚﹀喅锛夛細
#     `not_chatlist` 鏄?*浜烘棤鍏?*鐨勬晠闅?鈥斺€?鍚屼竴娆¤澶囨晠闅滀細璁╂墍鏈夊€欓€夌瓑姒傜巼澶辫触銆?
#     缁欏崟涓?sid 璁板喎鍗?= 鍋囪銆岃繖涓汉鏈夐棶棰樸€嶏紝鍓嶆彁灏辨槸閿欑殑锛涘喎鍗村埌鏈熷悗璁惧鑻ヤ粛鏈仮澶嶏紝
#     杩?14 涓汉浼?*鍐嶆帓闃熸挒涓€娆″**锛?4脳20s=280s 鍏ㄥ簾锛岃繕鐧借 14 鏉″喎鍗达級銆?
#   鐜板湪锛氬け璐ュ厛 continue锛堝彧璺宠繃杩欎釜浜猴級锛?*杩炵画 3 娆?*鎵嶅垽璁惧绾ф晠闅溿€佹暣杞敹宸ワ紝
#     绔嬪埢浜ょ粰 watchdog / 涓嬩竴杞紝璁惧鎭㈠鍚庝竴娆″叏濂姐€傛垚鍔熷洖涓€娆＄珛鍒绘竻闆躲€?
#   杩炵画 3 娆℃墠鍒ゆ槸涓轰簡鎺掗櫎鍗曟鍋跺彂锛堝疄娴?dump p50=1.50s / max=4.73s锛屽崟娆¤浆鍦哄緢甯歌锛夈€?
_NOT_CHATLIST_STREAK = [0]
NOT_CHATLIST_MAX = 3

# 馃敶 2026-11-08锛堢敤鎴凤細銆屼竴瀹氳姝ｅ父璇嗗埆瀵规柟璇煶鍐呭鐒跺悗鍐嶅洖澶嶃€嶏級锛?
#   鏈疆鍊欓€夐噷**鍝簺 sid 鐨勬湯鏉℃槸璇煶**銆?
#   鐢ㄩ€旓細璇煶杞啓鍑烘潵鐨勬枃瀛楀彧鍦ㄦ垜浠唴瀛橀噷锛孲oul 鍒楄〃棰勮鏄剧ず鐨勬槸銆孾璇煶]銆嶏紝
#   鎷胯浆鍐欐枃瀛楀幓鎼滅储蹇呯劧銆屾湭鎵惧埌鐩稿叧缁撴灉銆嶏紝鐧界瓑 11~30s銆?
#   鎵€浠ヨ繖浜?sid 璧?kw_of(..., skip_text=True)锛岀洿鎺ョ敤濂逛箣鍓嶇殑鍘嗗彶闀垮彞褰撳叧閿瘝銆?
#   姣忚疆寮€澶存竻绌猴紙鍙湇鍔℃湰杞級锛屼笉钀界洏銆?
_VOICE_SIDS = set()
# 鍚屼竴娈佃闊冲彧杞啓涓€娆★紱澶辫触缂撳瓨 30 鍒嗛挓鍚庢墠閲嶈瘯锛岄伩鍏?3 涓潖璇煶姣忚疆鍒?800+ 娆°€?
VOICE_FAIL_TTL_S = float(os.environ.get("SOUL_VOICE_FAIL_TTL_S", "1800") or 1800)
VOICE_OK_TTL_S = 24 * 3600
_VOICE_CACHE = {}


def _voice_cache_key(sid, msg, db=None):
    msg = V.resolve_msg(msg, db=db, sid=sid)
    try:
        duration = int(V.duration(msg))
    except Exception:
        duration = 0
    return (
        str(sid),
        int(getattr(msg, "ts", 0) or 0),
        duration,
        str(getattr(msg, "url", "") or ""),
    )


def _voice_text_cached(sid, msg, db=None):
    """杩斿洖 (鏂囨湰, 鏉ユ簮, 鏄惁鏂板け璐?銆傚け璐ョ粨鏋滅煭鏈熺紦瀛橈紝閬垮厤閲嶅 ASR銆?""
    msg = V.resolve_msg(msg, db=db, sid=sid)
    key = _voice_cache_key(sid, msg, db=db)
    now = time.time()
    rec = _VOICE_CACHE.get(key)
    if rec:
        age = now - rec["at"]
        if rec["ok"] and age < VOICE_OK_TTL_S:
            return rec["text"], "cache", False
        if not rec["ok"] and age < VOICE_FAIL_TTL_S:
            return None, "cached_fail", False
    try:
        text, how = V.voice_text(msg, db=db, sid=sid)
    except Exception as e:
        text, how = None, repr(e)
    if text:
        _VOICE_CACHE[key] = {"at": now, "ok": True, "text": text, "how": how}
        return text, how, False
    _VOICE_CACHE[key] = {"at": now, "ok": False, "text": None, "how": how}
    if len(_VOICE_CACHE) > 500:
        for k, v in list(_VOICE_CACHE.items()):
            if now - float(v.get("at") or 0) > VOICE_OK_TTL_S:
                _VOICE_CACHE.pop(k, None)
    return None, how, True

# 馃敶 2026-11-03锛圥0 閲嶅鍙戦€侊紝瀹炴祴锛歶id=*** 鍦?09:31~09:35 琚繛鍥?5 娆★級
#   鏍瑰洜锛氬€欓€夊彧鐪嬪簱閲屻€屾湯鏉℃槸濂广€嶁€斺€?鑰屽簱鏄?pull 缂撳瓨锛屾垜鍙戝嚭鍘荤殑璇濊绛変笅涓€娆?
#   pull 鎵嶄細鍑虹幇銆備簬鏄竴娈垫椂闂寸獥閲屾瘡杞兘鍒ゅ畾銆岃繕娌″洖銆嶏紝閲嶅鐏屽瓧銆?
#   鈬?鏈湴璁颁竴浠姐€屽垰鍥炶繃璋併€嶇殑鍙拌处锛堣惤鐩橈紝閲嶅惎涓嶄涪锛夛紝REPLIED_GAP 绉掑唴涓嶅啀纰般€?
REPLIED_GAP = 300
REPLIED_FILE = PL.REPLIED_FILE
# 韬唤鏍￠獙澶辫触璁℃暟锛?*钀界洏**锛岄噸鍚笉娓呴浂锛夛細{"sid|鏈潯鍓?0瀛?: {"n": n, "t": ts}}銆?
# 馃敶 2026-11-03 瀹炴祴鏁欒锛氬師鏉ユ槸鍐呭瓨 dict锛岃€屽綋澶╀负閮ㄧ讲鏀逛簡鍗佸嚑娆′唬鐮併€侀噸鍚崄鍑犳锛?
#    姣忔娓呴浂 -> 璁℃暟姘歌繙鍋滃湪銆岀 1 娆°€?> 銆岀 2 娆￠檷绾у彂瀹夊叏鍙ャ€嶇殑鍒嗘敮涓€娆￠兘璧颁笉鍒帮紝
#    uid=*** 鐨勩€岀畻銆嶅崱浜?10 灏忔椂浠ヤ笂锛?5:41 / 15:49 涓ゆ id_mismatch 閮界畻绗?1 娆★級銆?
IDFAIL_FILE = STATE / "idfail.json"
_IDFAIL = {}


def _load_replied():
    """璇诲彴璐?{sid: {"text": 鎴戝洖鐨勯偅涓€鍙? "ts": 鍥炲鏃跺埢}}锛涘吋瀹规棫鐨?{uid: ts}銆?""
    return PL.load_replied()


def _mark_replied(uid, sid=None, text=None):
    """璁般€?*杩欎竴鍙?*鎴戝凡缁忓洖杩囦簡銆嶏紙涓嶆槸銆岃繖涓汉鏈€杩戝洖杩囥€嶏級銆?

    馃敶 2026-11-04锛圥0 閲嶅楠氭壈锛屽疄娴?uid=*** 08:40:45 / 08:47:28 琚洖涓ゆ锛夛細
      鏃у彴璐︽槸 {uid: ts} + REPLIED_GAP=300s 鏃堕棿绐?鈥斺€?濂规病鍐嶈鏂拌瘽鏃讹紝5 鍒嗛挓鍚?
      銆屾湯鏉℃槸濂广€嶅張閲嶆柊鎴愮珛锛屼簬鏄悓涓€涓汉琚弽澶嶅紑鍦猴紝鍦ㄧ湡浜虹溂閲屽氨鏄釜鏈哄櫒浜恒€?
      鐜板湪璁?{sid: {"text": 鎴戝洖鐨勫摢涓€鍙? "ts": 鏃跺埢}}锛?
        路 鏈潯杩樻槸鍚屼竴鍙?鈫?涓嶈杩囧涔呴兘涓嶅啀鍥烇紙杩欏彞宸茬粡鍥炶繃锛?
        路 濂瑰彂浜嗘柊璇濓紙text 鍙橈級鎴栨柊璇濇椂闂存櫄浜庢垜鍥炲鏃跺埢 鈫?绔嬪埢鏀捐
    """
    PL.mark_replied(uid, sid=sid, text=text)


def _recently_replied(uid, sid=None, text=None, her_ts_ms=0):
    """杩欏彞鏄笉鏄凡缁忓洖杩囦簡銆傝 _mark_replied 鐨勮鏄庛€?""
    return PL.recently_replied(uid, sid=sid, text=text, her_ts_ms=her_ts_ms)


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲 韬唤鏍￠獙澶辫触璁℃暟锛堣惤鐩橈紝閲嶅惎涓嶆竻闆讹級 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲
def _idfail_key(sid, txt):
    return "%s|%s" % (sid, (txt or "")[:40])


def _load_idfail():
    """璇诲け璐ヨ鏁帮紱鍙繚鐣?24h 鍐呯殑锛堣繃鏈熻嚜鍔ㄥ繕锛屽埆鎶婃椿浜烘案涔呴檷绾э級銆?""
    try:
        d = json.loads(IDFAIL_FILE.read_text(encoding="utf-8"))
        now = time.time()
        out = {}
        for k, v in d.items():
            try:
                item = v if isinstance(v, dict) else {"n": int(v), "t": now}
                t = float(item.get("t", now))
                if now - t < 86400:
                    out[str(k)] = {"n": int(item.get("n", 0)), "t": t}
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_idfail():
    try:
        IDFAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 馃敶 2026-11-12 澶滅彮淇锛圖6锛夛細鍘熷瓙鍐欙紙tmp + os.replace锛夛紝涓?reply_state._save
        #   鍚屾銆傛敼鍓?write_text 鐩存帴瑕嗙洊锛岃繘绋嬪穿婧冪暀鍗婃埅 JSON 鈫?鍙拌处鍏ㄤ涪銆?
        _tmp = IDFAIL_FILE.with_name(IDFAIL_FILE.name + ".tmp")
        _tmp.write_text(json.dumps(_IDFAIL, ensure_ascii=False), encoding="utf-8")
        os.replace(str(_tmp), str(IDFAIL_FILE))
    except Exception as e:
        log.debug("瀛?idfail 澶辫触: %r", e)


def _idfail_bump(sid, txt):
    """澶辫触娆℃暟 +1锛堣惤鐩橈級锛岃繑鍥炴湰娆℃槸绗嚑娆°€?""
    k = _idfail_key(sid, txt)
    n = int((_IDFAIL.get(k) or {}).get("n", 0)) + 1
    _IDFAIL[k] = {"n": n, "t": time.time()}
    _save_idfail()
    return n


def _idfail_clear(sid, txt):
    if _IDFAIL.pop(_idfail_key(sid, txt), None) is not None:
        _save_idfail()


_IDFAIL = _load_idfail()



def _l2_last_is_me(sid, her_ts_ms=None):
    """L2 鏈€鍚庝竴琛屾槸涓嶆槸銆屾垜銆嶈鐨勶紝涓旀椂闂翠笉鏃╀簬濂规渶鏂颁竴鏉℃秷鎭€?

    2026-11-03 涓轰粈涔堝姞杩欓亾鍒ゆ嵁锛氬簱鏄?pull 缂撳瓨锛圧EFRESH_S=300锛夛紝
    鎴戝彂鍑哄幓鐨勬秷鎭绛変笅涓€娆?pull 鎵嶅嚭鐜?鈥斺€?瀹炴祴 09:30 鍙戝畬銆?9:31 搴撻噷杩樼湅涓嶅埌锛?
    浜庢槸 pendingq 杩炲洖 5 鏉°€傝€?L2 鏄?*鍙戦€佹垚鍔熷悗绔嬪埢鍐?*鐨勶紝姣斿簱瀹炴椂銆?

    馃敶 2026-11-03 淇 P1锛氬師鏉ュ彧鐪?L2 鏈鏄笉鏄€屾垜:銆嶏紝涓嶆瘮瀵规椂闂?鈥斺€?
    flow 鏇惧洖杩囧ス锛圠2 鏈=鎴戯級锛屽ス鍚庢潵鍙堟柊鍙戞秷鎭笖宸茶锛宒b 鏈潯宸叉槸濂癸紝
    杩欓噷浠嶅垽銆屽凡鍥炪€嶁啋 姘镐箙婕忓洖銆傜幇鍦細L2 鏈鏄垜 涓?璇ヨ鏃堕棿 >= 濂规渶鏂版秷鎭椂闂?
    鎵嶇畻宸插洖锛涘惁鍒欙紙濂瑰張鏈夋柊璇濓級鍒ゆ湭鍥炪€?
    her_ts_ms = 濂规渶鏂版秷鎭殑 localTime锛堟绉掞級锛汵one 鏃堕€€鍥炲彧鐪嬫湯琛岃鑹层€?
    """
    try:
        from brain.pack import store as _PK
        t = _PK.read_turns(sid) or ""
        last_ln = None
        for ln in reversed(t.splitlines()):
            ln = ln.strip()
            if ln.startswith("- "):
                last_ln = ln
                break
        if not last_ln:
            return False
        if " 鎴? " not in last_ln:
            return False          # 鏈鏄ス 鈫?鏈洖
        if her_ts_ms:
            # 馃敶馃敶 2026-11-12锛圖S-01锛氬垎閽熷瓧绗︿覆姣旇緝 鈫?姣绮剧‘锛?
            #   鍘熷疄鐜版妸 her_ts_ms 鎶樻垚 "%m-%d %H:%M" **瀛楃涓?*鍐嶅拰 L2 鏈姣旓紝
            #   鍙湁鍒嗛挓绮惧害銆?*鍚屼竴鍒嗛挓**鍐呭ス鍦ㄦ垜鍙戝畬涔嬪悗鍙堣ˉ涓€鍙ユ椂锛屽瓧绗︿覆鐩哥瓑
            #   璧颁笉鍒?`>` 鍒嗘敮 鈫?璇垽銆屽凡鍥炪€嶁啋 婕忓洖锛堟渶宸け璐ユā寮忥級銆?
            #   淇硶锛氭妸 her_ts_ms 鎶樻垚銆屽垎閽熸《銆嶏紙姣/60000锛変笌 L2 琛屽仛**鏁板€?*
            #   姣旇緝锛堟绉掔簿纭埌鍒嗛挓妗讹級锛屾秷闄ゅ瓧绗︿覆姣旇緝鐨勮竟鐣屾涔夈€?
            #   鍚屽垎閽熻涓?*涓嶅彲鍒ゅ畾** 鈫?鎸変繚瀹堝垽銆屾湭鍥炪€嶏紙濂规湁鏂拌瘽鐨勭枒鐐逛紭鍏堬細
            #   婕忓洖姣旈噸澶嶅洖鏇寸碂锛涢噸澶嶅洖杩樻湁 replied.json/_recently_replied 鍏滃簳锛夈€?
            try:
                her_min = int(float(her_ts_ms) / 60000.0)
                _y = time.localtime(float(her_ts_ms) / 1000.0).tm_year
            except Exception:
                her_min = None
                _y = time.localtime().tm_year
            m = re.match(r"^- (\d{2}-\d{2} \d{2}:\d{2}) ", last_ln)
            if m and her_min is not None:
                try:
                    l2_min = int(time.mktime(time.strptime(
                        "%d-%s" % (_y, m.group(1)), "%Y-%m-%d %H:%M")) / 60.0)
                except Exception:
                    l2_min = None
                if l2_min is not None:
                    if her_min > l2_min:
                        return False        # 濂规洿鏂?鈫?鏈洖
                    if her_min == l2_min:
                        return False        # 鍚屽垎閽熶笉鍙垽瀹?鈫?淇濆畧鏈洖
                    # her_min < l2_min 鈫?L2 鍦ㄥス涔嬪悗 鈫?宸插洖
                    return True
        return True
    except Exception:
        pass
    return False


def _my_last_ts_ms(db, sid):
    """鎴戞柟鍦ㄨ浼氳瘽鐨勬渶鍚庝竴鏉℃秷鎭椂闂达紙姣锛夈€傚彇涓嶅埌杩斿洖 0锛?鏈煡锛夈€?

    馃敶馃敶 2026-11-12锛圖S-05锛歴tate_of 鏈紶 my_last_ts_ms锛?
       verdict.state_of 鐨勩€屾垜鏂规湯鏉℃櫄浜庡ス鏈潯 鈫?AWAITING銆嶅垎鏀緷璧?
       my_last_ts_ms锛屼絾 candidates() 閲屼袱澶?state_of 閮芥病浼?鈫?鎭?0 鈫?AWAITING
       姘镐笉瑙﹀彂锛屽凡鍥炶繃/绛夊ス鍥炵殑浼氳瘽琚垽閿欑姸鎬併€?
       淇硶锛氭娊涓€涓渶灏忚鍙栧嚱鏁帮紝鎸?sender==uid 鎵?chatmsg 閲屾垜鏂规湯鏉°€?
       澶辫触杩斿洖 0锛屼笌 state_of 鐨?0 璇箟涓€鑷达紝涓嶄細璇激銆?
    """
    try:
        if db is None or not sid:
            return 0
        uid = getattr(db, "uid", "") or ""
        if not uid:
            return 0
        last_my = 0
        for m in db.messages(str(sid), limit=60):
            if str(getattr(m, "sender", "") or "") == str(uid):
                last_my = max(last_my, int(getattr(m, "ts", 0) or 0))
        return last_my
    except Exception:
        return 0


# 馃敶 2026-11-04锛堢敤鎴峰彛寰勶級锛氳繘浼氳瘽鍚庢牳瀵硅韩浠斤紝鏈€纭殑璇佹嵁鏄?**sid**銆?
#   App 杩涗細璇濅細鎶婅 session 鐨?unReadCount 缃?0 鈬?銆岃繘涔嬪墠 / 杩涗箣鍚庛€嶅悇鏌ヤ竴娆?
#   鏈闆嗗悎锛屽樊闆嗗氨鏄垰杩涘幓鐨勪細璇濄€傝繖閲屽瓨銆岃繘涔嬪墠銆嶇殑蹇収锛圢one = 娌℃嬁鍒拌瘉鎹級銆?
_UNREAD_BEFORE = {"set": None}

# 璁惧瀛樻椿鏍￠獙鐨勭紦瀛橈紙瑙?_device_live_uids锛?
_LIVE_CACHE = {"v": None, "ts": 0.0}
# 馃敶馃敶 2026-11-12锛圖S-06锛夛細TTL 涓?data.imdb.DEVICE_LIVE_TTL_S 缁熶竴锛堥粯璁?120s锛夈€?
#   鍘熸潵鍐欐 120锛涙敼涓哄紩鐢?imdb 鐨勫叡浜父閲忥紝涓よ竟鍙ｅ緞姘镐笉澶辫仈銆?
try:
    from data import imdb as _IM_TTL
    _LIVE_TTL_S = float(os.environ.get("SOUL_LIVE_TTL_S", str(_IM_TTL.DEVICE_LIVE_TTL_S))
                        or _IM_TTL.DEVICE_LIVE_TTL_S)
except Exception:
    _LIVE_TTL_S = float(os.environ.get("SOUL_LIVE_TTL_S", "120") or 120)
_DEV_REF = {"dev": None}
_UNREAD_CACHE = {"ts": 0.0, "sids": set()}
_CANDIDATE_CACHE = {"key": None, "at": 0.0, "value": []}
CANDIDATE_CACHE_S = float(os.environ.get("SOUL_CANDIDATE_CACHE_S", "8") or 8)


def _device_unread_sids(db):
    """璁惧搴?unReadCount>0 鐨?sid 闆嗗悎锛?0s TTL 缂撳瓨锛夈€?

    馃敶 2026-11-09 P0锛歮sg_probe 鐩存煡璁惧搴撶湅鍒?10 鏉＄Н鍘嬫湭璇伙紝
       浣?candidates() 鍙湅鏈湴闀滃儚 + replied.json + turns.md(L2) + pending_skip.json锛?
       鍥涘鏈湴鐘舵€侀兘浼氭粸鍚庯紝鎶婄湡绾㈢偣鍒ゆ垚銆屽凡鍥?鍐峰嵈涓€嶁啋 杩炵画 29 杞浂鍥炲銆?
       璁惧搴撴湭璇绘槸銆屽ス鍙戜簡涓斾粠鏈繘浼氳瘽璇昏繃銆嶇殑寮虹湡鍊硷紝鐢ㄥ畠鍏滃簳鏀捐銆?
       涓€杞唴 candidates() 浼氳璋?6+ 娆★紝鏁呭姞 60s 缂撳瓨閬垮厤閲嶅 adb銆?
    """
    now = time.time()
    if now - _UNREAD_CACHE["ts"] < 60.0:
        return _UNREAD_CACHE["sids"]
    out = set()
    try:
        from data import imdb as _IM
        dev = getattr(db, "dev", None) or _DEV_REF.get("dev")
        if dev is not None:
            m = _IM.device_unread_map(dev, timeout=6, uid=getattr(db, "uid", None))
            if m:
                out = {str(k) for k, v in m.items() if v}
    except Exception as e:
        log.debug("璁惧鏈闆嗗悎鍙栦笉鍒帮紙闄嶇骇涓轰笉纭斁琛岋級: %r", e)
    _UNREAD_CACHE.update(ts=now, sids=out)
    return out


def invalidate_live_cache():
    """馃敶 2026-11-09 P0锛氬簱鍙樺寲鏃舵竻鎺夈€岃澶囧瓨娲?uid銆嶇紦瀛樸€?

    鍜?invalidate_unread_cache 鍚岀悊锛歚_device_live_uids` 鏈?120s TTL锛?
    搴撳垰鍚屾杩涙柊浼氳瘽鏃讹紝缂撳瓨閲屽彲鑳借繕娌℃湁杩欎釜浜?鈫?琚綋鎴愩€孉pp 閲屽凡涓嶅瓨鍦ㄣ€?
    绉诲嚭鍊欓€夛紙瀹炴祴涓€娆＄Щ鍑?180 涓級銆傛柊娑堟伅鍒拌揪鏃舵竻鎺夛紝閫煎畠閲嶆柊鎵澶囧簱銆?
    """
    _LIVE_CACHE.update(v=None, ts=0.0)
    _CANDIDATE_CACHE.update(key=None, at=0.0, value=[])
    log.info("璁惧瀛樻椿缂撳瓨宸叉竻闄わ紙搴撳彉鍖栦俊鍙疯Е鍙戯級")


def invalidate_unread_cache():
    """馃敶 2026-11-09 P0 淇锛氬簱鍙樺寲鏃舵竻鎺夎澶囨湭璇荤紦瀛樸€?

    鏁呴殰閾捐矾锛?8:42 鏂版秷鎭湭澶勭悊锛夛細
      18:42:20 cycle() 妫€娴嬪埌 DBW.urgent() 鈫?open_account(force=True) 鍚屾鏈€鏂板簱
      鈫?浣?_device_unread_sids() 鐨?60s TTL 缂撳瓨杩樺仠鐣欏湪 60s 鍓嶇殑蹇収
      鈫?鏂版秷鎭?sid 涓嶅湪缂撳瓨闆嗗悎閲?鈫?璁惧鏈銆岀‖鏀捐銆嶅け鏁?
      鈫?鏂版秷鎭 _recently_replied / _l2_last_is_me / should_skip 鎺愭帀
      鈫?candidates() 杩斿洖绌?鈫?cycle() 涓€璺蛋鍒扮┖闂诧紝鏂版秷鎭案涔呮悂缃?

    淇硶锛歞aemon.cycle() 鍦?_dirty=True 鏃惰皟鏈嚱鏁版竻缂撳瓨锛?
    璁╃揣鎺ョ潃鐨?candidates() 閲嶆柊鏌ヨ澶囧簱鎷垮埌鏈€鏂扮殑鏈闆嗗悎銆?
    """
    _UNREAD_CACHE.update(ts=0.0, sids=set())
    _CANDIDATE_CACHE.update(key=None, at=0.0, value=[])
    log.info("璁惧鏈缂撳瓨宸叉竻闄わ紙搴撳彉鍖栦俊鍙疯Е鍙戯級")


# 馃敶 2026-11-09锛氫竴杞?cycle 閲屻€岃澶囧瓨娲绘牎楠屻€嶄細琚涓瓙娴佺▼鍚勮皟涓€娆★紝
#    uids 宸叉湁 120s 缂撳瓨銆佷笉浼氶噸澶嶆壂璁惧锛屼絾鏃х殑 INFO 姣忔閮芥墦 鈫?
#    瀹炴祴鍚屼竴绉掑埛 3~4 琛屻€?05 涓€﹀墿 95 涓€嶆妸鐪熸棩蹇楁饭浜嗐€?
#    鐩稿悓缁撹鍦?TTL 鍐呭彧 INFO 涓€娆★紝鍏朵綑闄?DEBUG锛堣鏌ラ殢鏃惰兘寮€锛夈€?
_LIVE_LOG = {"sig": None, "ts": 0.0}
_CAND_SCAN_LOG = {"sig": None, "ts": 0.0}


def _device_live_uids(db):
    """褰撳墠璐﹀彿璁惧搴撻噷杩樺瓨鍦ㄧ殑 toUserId 闆嗗悎銆傚彇涓嶅埌杩斿洖 None锛堣皟鐢ㄦ柟闄嶇骇涓嶈繃婊わ級銆?

    瑙?`data/imdb.device_live_uids` 鐨勬敞閲婏紙P0锛氭湰鍦伴暅鍍忛噷鐨勩€屾浜恒€嶏級銆?
    杩欓噷鍙仛涓€灞傜紦瀛?+ 寮傚父鍏滃簳锛岀湡姝ｇ殑鏌ヨ鍜岃处鍙烽殧绂诲湪閭ｉ噷瀹炵幇銆?

    馃敶馃敶 2026-11-12锛圖S-08 绌洪泦鍒ゆ柇锛夛細`device_live_uids` 宸茬‘璁?*淇濇寔 None 涓嶈繃婊?*
    锛堟煡璇㈡垚鍔熶絾 0 浼氳瘽涓庢煡璇㈠け璐ュ湪 `_dev_sql` 灞傛棤娉曞尯鍒嗭紝杩斿洖绌?set 浼氬湪
    adb 鎶栧姩鏃惰浼ゅ叏閮ㄥ€欓€?鈫?婕忓洖锛夈€傚洜姝よ繖閲?`if uids:` 缂撳瓨闈炵┖闆嗗悎鍗冲彲锛?
    None / 绌洪泦閮戒笉缂撳瓨锛堜笅娆￠噸鏌ワ級锛屼繚鎸併€岄檷绾т笉杩囨护銆嶇殑鏃ц涓恒€?
    """
    now = time.time()
    cache = _LIVE_CACHE.get("v")
    if cache and (now - _LIVE_CACHE.get("ts", 0)) < _LIVE_TTL_S:
        return cache
    dev = getattr(db, "dev", None) or _DEV_REF.get("dev")
    if dev is None:
        log.debug("_device_live_uids: 娌℃湁 device 寮曠敤锛岃烦杩囧瓨娲绘牎楠?)
        return None
    from data import imdb as _IM
    uids = _IM.device_live_uids(dev, db.uid)
    if uids:
        _LIVE_CACHE["v"] = uids
        _LIVE_CACHE["ts"] = now
    return uids


def mark_before_enter(actor):
    """鐐瑰嚮浼氳瘽琛?鎼滅储缁撴灉**涔嬪墠**璋冧竴娆★紝璁颁笅鏈闆嗗悎蹇収銆?""
    try:
        from data import imdb as _IM
        _UNREAD_BEFORE["set"] = _IM.device_unread_map(actor.dev)
    except Exception:
        _UNREAD_BEFORE["set"] = None


def _sid_by_unread_clear(actor, sid, tries=3, wait=0.7):
    """鏈娓呴浂宸垎鍒よ韩浠斤細True/False=None锛堟棤璇佹嵁锛屼氦缁欐枃鏈牎楠岋級銆?""
    before = _UNREAD_BEFORE.get("set")
    if not before:
        return None
    try:
        from data import imdb as _IM
    except Exception:
        return None
    cleared = set()
    for i in range(max(1, tries)):
        try:
            after = _IM.device_unread_map(actor.dev)
        except Exception:
            return None
        if after is None:
            return None
        cleared = set(before) - set(after)
        if cleared:
            break
        time.sleep(wait)          # 钀藉簱鏈夊嚑鍗佹绉掑欢杩燂紝绛変竴灏忎細鍐嶇湅
    if not cleared:
        return None               # 濂硅繖鏉℃湰鏉ュ氨娌℃湁鏈锛堝凡璇绘湭鍥烇級鈫?鏃犺瘉鎹?
    # 馃敶 2026-11-08锛圥0 淇€岃韩浠芥牎楠屽け璐?261 娆°€嶉噷鐨勫亣鍚﹀喅锛夛細
    #   瀹炴祴 daemon.out 鍏ㄩ噺 57 娆?`韬唤鏍￠獙澶辫触锛堣繘鐨勬槸鍒殑浼氳瘽锛氭竻闆?[...]锛屾湡鏈?SID锛塦锛?
    #   鍏朵腑 **48 娆★紙84%锛夌殑銆屾竻闆堕泦鍚堛€嶆槸鍚屼竴涓鐢ㄦ寚绾?*锛岃法 38 鍒嗛挓瑕嗙洊 23 涓笉鍚岀洰鏍囦汉锛?
    #     11-07 00:09:01 ... 娓呴浂 ['96691646131306455','96691646215313007','96691646187185972'] 鈫?鏈熸湜 9669164692166884
    #     11-07 00:47:30 ... 鍚屼竴涓泦鍚?                                                     鈫?鏈熸湜 96691646451226869
    #   涓€涓泦鍚堝湪 23 涓笉鍚岀洰鏍囦汉涓婇噸澶嶅嚭鐜帮紝**涓嶅彲鑳芥槸杩?23 娆￠兘杩涗簡鍚屼竴涓埆浜虹殑浼氳瘽**銆?
    #   鐪熷洜锛歘UNREAD_BEFORE 鏄ā鍧楃骇鍙彉鍏ㄥ眬锛堣鏈枃浠?_UNREAD_BEFORE 瀹氫箟锛夛紝
    #   鑰?actor.snap() 涓€娆?1.5~4.7s锛岃繖涓獥鍙ｉ噷涓婁竴杞殑杩涗細璇濆姩浣滃凡鎶婂揩鐓ф敼鎺?鈥斺€?
    #   绠楀嚭鏉ョ殑 cleared 鍜屾湰娆＄偣鍑绘棤鍏筹紝灞炰簬**蹇収姹℃煋**锛屼笉鏄€岃繘閿欎汉銆嶃€?
    #   澶勭悊锛氫竴娆℃竻闆?>3 涓細璇濇槑鏄句笉鍍忋€岃繘浜嗕竴涓細璇濄€嶁啋 褰撲綔鏃犺瘉鎹紙杩斿洖 None锛夛紝
    #   浜ょ粰鍚庨潰鐨勬樀绉?/ session 鎽樿 / 姘旀场鍙嶆煡缁х画鏍￠獙锛屼笉瑕佸湪杩欎竴灞傜洿鎺?fail-closed 璇潃銆?
    if len(cleared) > 3:
        log.info("鏈宸垎涓嶅彲淇★紙涓€娆℃竻闆?%d 涓細璇濓紝鐤戜技蹇収琚笂涓€杞薄鏌擄級鈫?浜ゆ枃鏈牎楠?,
                 len(cleared))
        return None
    if str(sid) in cleared:
        log.info("韬唤鏍￠獙閫氳繃锛堟湭璇绘竻闆跺樊鍒?= 绮剧‘ sid %s锛?, sid)
        return True
    log.warning("韬唤鏍￠獙澶辫触锛堣繘鐨勬槸鍒殑浼氳瘽锛氭竻闆?%r锛屾湡鏈?%s锛?, list(cleared)[:3], sid)
    return False


def _norm_nick(s):
    """鏄电О褰掍竴鍖栵細鍘荤┖鐧?鈥?鏍囩偣锛屼究浜庡墠缂€姣斿锛堟爣棰樺父琚埅鏂垚銆岀嚂澶┾€︺€嶏級銆?""
    import re as _re
    t = (s or "").strip()
    t = _re.sub(r"[\s\u3000鈥.,锛屻€?锛?锛焴锝瀄-鈥擾]+$", "", t)
    return t


def _nick_matches(actor, nick):
    """瀵硅瘽椤垫爣棰樻樀绉版槸鍚︿笌鍒楄〃琛屾樀绉颁竴鑷淬€俆rue / None锛堟棤璇佹嵁锛夈€?""
    nk = _norm_nick(nick)
    if not nk:
        return None
    try:
        from eyes import chat as _C
        snap = actor.snap(force=True)
        title = _C.title_of(snap)
    except Exception as e:
        log.debug("璇诲璇濋〉鏍囬澶辫触: %r", e)
        return None
    t = _norm_nick(title)
    if not t:
        return None
    # 鏍囬鍙兘琚埅鏂紙銆岀嚂澶┾€︺€嶏級鈫?鍙屽悜鍓嶇紑姣斿
    if t == nk or (len(t) >= 2 and nk.startswith(t)) or (len(nk) >= 2 and t.startswith(nk)):
        log.info("韬唤鏍￠獙閫氳繃锛堝璇濋〉鏄电О涓€鑷达細%r锛?, title)
        return True
    return None          # 涓嶄竴鑷翠笉鍋氬惁鍐筹細鏄电О鍙兘琚娉ㄦ敼鍐欙紝鍚﹀喅浼氬彉鎴愭紡鍥?


def _session_matches(actor, db, sid, nick=None):
    """杩涘叆 chat 鍚庢牎楠屽綋鍓嶄細璇濇槸鍚︾湡鐨勬槸鍊欓€?sid銆?

    馃敶 2026-11-03 淇 P1锛堥槻閿欏彂/涓插彴锛夛細鍒楄〃 `find_row` 鎸夋枃鏈墖娈靛懡涓琛屻€?
    鎼滅储 `enter_first` 鍙偣绗竴鏉＄粨鏋滐紝閮戒笉鏍￠獙缁撴灉鎵€灞?sid/uid 鈥斺€?鍙兘杩涢敊浼氳瘽锛?
    鎶婄敳鐨勫巻鍙插嚭璇濆彂缁欎箼锛岃繕璇鐢插凡鍥炪€傝繖閲岃褰撳墠浼氳瘽鐨勩€屽鏂规皵娉°€嶆枃鏈紝
    鍙嶆煡搴撶‘璁や細璇濊韩浠斤細
      鍛戒腑鏁版渶楂樼殑浼氳瘽 == 鍊欓€?sid 涓旀槑鏄惧敮涓€ 鈫?涓€鑷达紙True锛夛紱
      璇讳笉鍒版皵娉?/ 鍙嶆煡涓嶅埌 / 涓嶅敮涓€ / 涓嶄竴鑷?鈫?鏃犳硶纭锛團alse锛夈€?
    fail-closed锛氬彂閿欎汉 = 楂樺嵄涓嶅彲閫嗭紝瀹佸彲涓嶅彂锛堣鍙拌处鐭喎鍗翠笅杞噸璇曪級锛屼笉鍙彂閿欍€?
    """
    # 馃敶 2026-11-04锛氱涓€椤轰綅 = 鏈娓呴浂宸垎锛堢簿纭?sid锛屼笉渚濊禆鏂囨湰锛夈€?
    #   杩涢敊浜烘椂瀹冧細鐩存帴缁欏嚭 False锛涘ス杩欐潯鏈潵灏辨病鏈鏃惰繑鍥?None 璧版枃鏈厹搴曘€?
    _u = _sid_by_unread_clear(actor, sid)
    if _u is not None:
        return _u
    # 绗簩椤轰綅锛氬璇濋〉鏍囬鏄电О锛堝ス杩欐潯鏈潵灏辨病鏈鏃剁殑寮鸿瘉鎹級
    if nick:
        _n = _nick_matches(actor, nick)
        if _n is not None:
            return _n
    from eyes import chat as C
    try:
        png = actor.dev.screencap()
        bs = C.bubbles(png)
    except Exception:
        return False
    # 馃敶 2026-11-03锛氫笉鍙彇銆屽ス銆嶇殑姘旀场 鈥斺€?鐭秷鎭紙"绠?/"娌℃湁鍟?锛夊湪搴撻噷鎾炶溅锛?
    #    鍙潬濂归偅鍙ュ弽鏌ュ繀鐒朵笉鍞竴銆傛妸銆屾垜銆嶇殑姘旀场涔熺畻杩涙潵锛屽懡涓暟鏇存湁鍖哄垎搴︺€?
    texts = [t for t, side, it in bs if side in ("her", "me") and len(t) >= 2]
    if not texts:
        return False
    # 馃敶 2026-11-04锛堝繀鍥為棴鐜級锛氬厛鐢ㄣ€宻ession 鎽樿銆嶈繖鏉″己璇佹嵁鐩存帴鏀捐銆?
    #    鎽樿 = 鍒楄〃棰勮 = 灞忓箷涓婃渶鍚庝竴鍙ヨ瘽锛屽拰绔欒繘鏉ョ湅鐨勫繀鐒舵槸鍚屼竴涓細璇濓紱
    #    鑰屽師鏉ョ殑 chatmsg 鍙嶆煡鍦ㄣ€屽叆鍚戜笉钀藉簱銆嶇殑璐﹀彿涓婂繀鐒跺け璐?鈫?fail-closed
    #    姘歌繙涓嶅彂锛堝疄娴嬨€孾鐙楀瓙]銆嶃€岄偅涓嶇煡閬撱€嶅悇澶辫触 10 娆°€佹渶缁堥暱鍐峰嵈 2h锛夈€?
    try:
        if db.digest_matches(sid, texts, min_len=2):
            log.info("韬唤鏍￠獙閫氳繃锛坰ession 鎽樿涓€鑷达級sid=%s", sid)
            return True
    except Exception as e:
        log.debug("鎽樿鏍￠獙寮傚父: %r", e)
    try:
        hits = db.sessions_for_texts(texts, min_len=2)
    except Exception:
        return False
    if not hits:
        return False
    top_sid, top_n = hits[0]
    if str(top_sid) != str(sid):
        return False
    if len(hits) > 1 and hits[1][1] >= top_n:
        return False          # 鍛戒腑鏁板苟鍒?鈫?涓嶅敮涓€
    return True


def _load_skip():
    return PL.load_skip()


def _save_skip(d):
    PL.save_skip(d)


_LAST_SKIP = {}


def should_skip(sid, txt, hours=SKIP_HOURS):
    """杩欎釜浼氳瘽鐨勮繖鍙ヨ瘽鏄笉鏄垰澶辫触杩囷紙鍐峰嵈涓級銆?""
    return PL.should_skip(sid, txt, default_hours=hours, last_out=_LAST_SKIP)


def mark_skip(sid, txt, reason="notfound", hours=None):
    h = SKIP_HOURS if hours is None else hours
    PL.mark_skip(sid, txt, reason=reason, hours=h)
    log.info("璁板叆澶辫触鍙拌处 sid=%s锛?s锛夛紝%.2f 灏忔椂鍐呬笉鍐嶈瘯", sid, reason, h)


def _nf_hits(sid):
    """30 鍒嗛挓鍐呰 sid 绱 notfound 娆℃暟锛堣繘绋嬪唴璁℃暟锛岄噸鍚嵆娓咃級銆?""
    now = time.time()
    arr = [t for t in _NF_HITS.get(str(sid), []) if now - t < 1800]
    arr.append(now)
    _NF_HITS[str(sid)] = arr
    if len(_NF_HITS) > 500:                      # 闃叉甯搁┗杩涚▼鏃犻檺澧為暱
        for k in [k for k, v in _NF_HITS.items() if not v or now - v[-1] > 3600]:
            _NF_HITS.pop(k, None)
    return len(arr)


_NF_HITS = {}
_SLA_WARNED = {}


def _sla_warn(sid, to_uid, her_ts_ms, why):
    """R5锛氬ス鏈€鍚庝竴鏉¤秴杩?SLA_WARN_MIN 鍒嗛挓杩樻病琚帴涓?鈫?鏍囩孩涓€琛岋紙涓嶆彃鎵嬫搷浣滐級銆?

    鍚屼竴 sid 榛樿 30 鍒嗛挓鍐呭彧鎶ヤ竴娆★紝閬垮厤鍙嶅鍒峰睆銆?
    """
    try:
        age_min = (time.time() - float(her_ts_ms or 0) / 1000.0) / 60.0
    except Exception:
        return
    if age_min < SLA_WARN_MIN:
        return
    now = time.time()
    if now - _SLA_WARNED.get(str(sid), 0) < SLA_WARN_REPEAT_S:
        return
    _SLA_WARNED[str(sid)] = now
    log.warning("鈴?瓒?%.0f 鍒嗛挓鏈洖 uid=%s sid=%s锛?s锛夆啋 鏍囩孩锛岀暀闃熷垪鎸夌瓑寰呮椂闀块噸鎺?,
                age_min, to_uid, sid, why)


def cooldown_waiting(max_min=30.0):
    """杩樻湁銆屽喎鍗翠腑浣嗘病鍒?24h 娣樻卑銆嶇殑浼氳瘽鍦ㄧ瓑浜哄洖鍚楋紵

    馃敶 2026-11-09 R8锛堢敤鎴锋媿鏉裤€屽綋鍓嶈处鍙锋病姒ㄥ共涓嶅垏鍙枫€嶏級
        鍒囧彿鍓嶆彁鈶犮€岀湡寰呭洖 = 0銆嶅師鏉ョ洿鎺ョ敤 candidates()==0 鍒わ紝鑰?candidates()
        浼氭护鎺夊喎鍗翠腑鐨勪汉 鈬?21:21 瀹炴祴銆屽緟鍥?4 浜哄叏鏄喎鍗翠腑/宸插洖銆嶈鍒ゆ垚
        銆屾棤浜哄彲鑱娿€嶁啋 30 绉掑悗鍒囧彿锛屾妸 4 涓彲鑳借繕鍦ㄧ瓑鐨勪汉涓㈢粰鍙︿竴璐﹀彿 8 灏忔椂銆?
        杩欎釜鍑芥暟鍙敤浜庛€屽垏鍙峰墠澶氱瓑涓€鍙ｆ皵銆嶏紝涓嶅奖鍝嶅尮閰嶉椄闂紙閬垮厤 11-08 鐨勯タ姝诲洖娼級銆?

    杩斿洖 (n, 鏈€鏃╄繕鍓╁灏戝垎閽?锛沶=0 琛ㄧず纭疄娌′汉銆?
    """
    try:
        d = _load_skip()
    except Exception:
        return (0, 0.0)
    now = time.time()
    left = []
    for sid, rec in (d or {}).items():
        if not isinstance(rec, dict):
            continue
        if (rec.get("reason") or "") not in ("notfound", "notfound_fresh",
                                             "notfound_storm", "slow", "timeout"):
            continue
        ts = float(rec.get("ts") or 0)
        if now - ts > 86400:                    # 瓒呰繃 24h 鐨勯檲鏃у彴璐︿笉绠?
            continue
        h = float(rec.get("hours") or 0)
        rem = h * 60 - (now - ts) / 60.0
        if rem > 0:
            left.append(rem)
    if not left:
        return (0, 0.0)
    return (len(left), max(left))


def _burst_n(db, sid, uid):
    """濂?*鏈€鏂拌繛鍙?*鐨勬潯鏁帮紙鐢ㄤ簬鎺掑簭浼樺厛绾э細澶氭潯 > 鍗曟潯锛夈€?

    澶嶇敤 flow.her_burst 鐨勮涔夛紙浠庢渶鍚庝竴鏉″線鍓嶃€侀亣鍒版垜鍙戠殑灏卞仠銆佽烦杩囩郴缁熸彁绀猴級锛?
    鍙彇鏉℃暟銆備换浣曞紓甯搁兘杩斿洖 1锛堝綋浣滃崟鏉★紝缁濅笉鍥犱负绠楁潯鏁板け璐ヤ涪鎺夊€欓€夛級銆?
    """
    try:
        from brain import flow
        return max(1, len(flow.her_burst(db, sid, uid) or []))
    except Exception:
        return 1


def candidates(db, limit=MAX_N, days=LOOKBACK_DAYS):
    """寰呭洖鍊欓€夛細**鏈€鍚庝竴鏉℃槸瀵规柟鍙戠殑**浼氳瘽锛堜笉绠″凡璇绘湭璇伙級銆?

    馃敶 涓轰粈涔堜笉鐢?`db.pending()`锛?026-11-02 瀹炴祴鏁欒锛夛細
      瀹冧緷璧?`session.unReadCount > 0`锛岃€屻€岃繘鍘荤湅涓€鐪煎氨閫€鍑恒€嶄細鎶婃湭璇绘暟娓呴浂銆?
      绾㈢偣涔熸秷澶?鈥斺€?閭ｇ被姝ｅソ灏辨槸鐢ㄦ埛瑕佺殑銆屽凡璇绘湭鍥炪€嶃€傜敤 pending() 鏌ュ彧鍓?1 涓紝
      鏀规垚鐪?chatmsg 鏈€鍚庝竴鏉＄殑 sender 鍚庢仮澶嶅埌姝ｅ父鏁伴噺銆?

    杩斿洖 [(sessionId, to_uid, 鏈潯鏂囨湰, 鏈潯姣鏃堕棿)]锛屾寜濂规湯鏉℃椂闂?*鍗囧簭**锛堟渶鑰佷紭鍏堬級銆?
    """
    cutoff = (time.time() - days * 86400) * 1000
    scan_stats = Counter()
    # 馃敶 2026-11-10 搂104 C4锛氬綊妗ｉ泦鍚堜竴娆℃€у彇锛堝惊鐜噷閫愪釜璇诲彴璐︿細鐧界儳纾佺洏锛夈€?
    _archived = set()
    try:
        from brain import sendgate as _SG0
        _archived = set(str(x) for x in _SG0.archived_sids())
    except Exception as _e0:
        log.debug("褰掓。闆嗗悎鍙栦笉鍒帮紙鏈疆涓嶆帓闄わ級: %r", _e0)
    # 馃敶 2026-11-09 P0锛氬厛鍙栬澶囧簱鐪熷疄鏈闆嗗悎锛?0s 缂撳瓨锛夛紝渚涗笅闈㈢‖鏀捐浣跨敤銆?
    _unread_sids = _device_unread_sids(db)
    # Repeated calls inside one cycle used to rescan hundreds of sessions and
    # re-log the same cooldowns. Cache only the final decision for a few seconds;
    # every source state that can change a decision participates in the key.
    try:
        from data import reply_state as _RSc
        _rs_mtime = _RSc.FILE.stat().st_mtime_ns if _RSc.FILE.exists() else 0
    except Exception:
        _rs_mtime = 0
    _cache_key = (
        str(getattr(db, "uid", "") or ""),
        str(getattr(getattr(db, "path", None), "name", "") or ""),
        int(limit or 0),
        int(days or 0),
        tuple(sorted(_archived)),
        tuple(sorted(_unread_sids)),
        SKIP_FILE.stat().st_mtime_ns if SKIP_FILE.exists() else 0,
        REPLIED_FILE.stat().st_mtime_ns if REPLIED_FILE.exists() else 0,
        _rs_mtime,
    )
    _cache_now = time.time()
    if (_CANDIDATE_CACHE.get("key") == _cache_key
            and 0 <= _cache_now - float(_CANDIDATE_CACHE.get("at") or 0) < CANDIDATE_CACHE_S):
        log.debug("鍊欓€夋壂鎻忓懡涓?%.1fs 鐭紦瀛橈紙涓嶉噸澶嶆煡搴?鍒锋棩蹇楋級", CANDIDATE_CACHE_S)
        return list(_CANDIDATE_CACHE.get("value") or [])
    try:
        rows = db.con.execute(
            "SELECT sessionId, toUserId FROM session "
            "WHERE toUserId > 0 AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (cutoff, SCAN_SESSIONS)).fetchall()
    except Exception as e:
        log.warning("鏌ヤ細璇濆け璐? %r", e)
        return []
    scan_stats["source"] = len(rows)

    # 馃敶馃敶馃敶 2026-11-08 12:56锛?*鏈疆鏈€閲嶈鐨勪竴鏉?*锛氭湰鍦伴暅鍍忛噷鐨勩€屾浜恒€嶏級
    #
    #   瀹炴祴锛坃final.py锛岀洿鎺?pull 璁惧搴撳姣旓級锛?
    #     鏈湴闀滃儚 96691646 鈫?session 1524 琛?/ chatmsg 20979 琛?/ 12.2MB
    #     璁惧鐪熷疄 96691646 鈫?session   31 琛?/ chatmsg   141 琛?/ 204KB
    #     uid 浜ら泦锛氳澶?31 涓紝鏈湴 1524 涓紝**鍙湪鏈湴锛堣澶囦笂宸蹭笉瀛樺湪锛? 1495 涓?*
    #   鍙︿竴璐﹀彿鍚岀悊锛氭湰鍦?1298 鈫?璁惧 55銆?
    #
    #   鍚箟锛歋oul **鐪熺殑鎶婅繖涓处鍙风殑鍘嗗彶浼氳瘽娓呯┖浜?*锛岃澶囦笂鍙墿鏈€杩?31 涓€?
    #   鑰屾湰鍦伴暅鍍忔槸銆屽巻鍙插揩鐓с€嶏紙sync 鐨勬埅鏂繚鎶ゆ晠鎰忎繚鐣欏畠锛屼笉瑕嗙洊锛夛紝
    #   閲岄潰 1495 涓細璇濆湪 App 閲?*鏍规湰涓嶅瓨鍦ㄤ簡**銆?
    #
    #   浜庢槸銆屽緟鍥?22 浜恒€嶈繖涓暟瀛楁槸**鍋囩殑**锛氶偅 22 涓汉鍦ㄨ澶囦笂鎵句笉鍒帮紝
    #   缈诲睆缈讳笉鍒般€佹悳绱㈡悳涓嶅埌 鈥斺€?杩欎笉鏄悳绱㈢殑 bug锛屾槸**浜哄凡缁忔病浜?*銆?
    #   瀹炴祴鍊欓€夐噷銆岃澶囦笂杩樻椿鐫€銆? 0 / 1銆傜櫧鐑?40~50s/浜猴紝涓€涓汉閮藉洖涓嶆帀銆?
    #
    #   淇硶锛氬€欓€夊繀椤昏繃涓€閬?*璁惧瀛樻椿鏍￠獙** 鈥斺€?鍙湁銆岃澶囧簱閲屼篃鏈夎繖涓?toUserId銆?
    #   鐨勪汉鎵嶈繘闃熷垪銆傝繖鍚屾椂涔熸槸鐢ㄦ埛鍙嶅寮鸿皟鐨勩€岃处鍙锋暟鎹殧绂汇€嶇殑姝ｉ潰瀹炵幇锛?
    #   鍙敤**褰撳墠璐﹀彿鑷繁鐨勮澶囧簱**鍒ゅ畾锛岀粷涓嶈法搴撱€佺粷涓嶆嬁鍘嗗彶蹇収鍐掑厖鐜扮姸銆?
    #
    #   闄嶇骇锛氳澶囪涓嶅埌锛坅db 鎶栧姩/鏃?root锛夆啋 杩斿洖 None 鈫?**涓嶈繃婊?*锛堜繚鎸佹棫琛屼负锛夈€?
    #   瀹佸彲鎸夋棫琛屼负鐧界儳锛屼篃涓嶈兘鍥犱负涓€娆?adb 澶辫触鎶婃暣杞緟鍥炲叏鎺愭帀銆?
    _live_uids = None
    try:
        _live_uids = _device_live_uids(db)
    except Exception as _e:
        log.warning("璁惧瀛樻椿鏍￠獙鍙栦笉鍒帮紙鏈疆涓嶈繃婊わ紝鎸夋棫琛屼负璧帮級: %r", _e)
    if _live_uids is not None:
        _before = len(rows)
        rows = [(s, u) for (s, u) in rows if str(u) in _live_uids]
        _dead = _before - len(rows)
        if _dead:
            _sig = (_dead, len(rows))
            _now = time.time()
            if _LIVE_LOG.get("sig") != _sig or (_now - _LIVE_LOG.get("ts", 0)) >= _LIVE_TTL_S:
                log.info("璁惧瀛樻椿鏍￠獙锛?d 涓細璇濆湪 App 閲屽凡涓嶅瓨鍦紙Soul 娓呰繃鍘嗗彶锛夆啋 绉诲嚭鍊欓€夛紝鍓?%d 涓?,
                         _dead, len(rows))
                _LIVE_LOG.update(sig=_sig, ts=_now)
            else:
                log.debug("璁惧瀛樻椿鏍￠獙(TTL 鍐呴噸澶?锛氱Щ鍑?%d 涓紝鍓?%d 涓?, _dead, len(rows))

    out = []
    for sid, to_uid in rows:
        if str(to_uid).startswith(SKIP_UID_PREFIX):
            log.debug("璺宠繃瀹樻柟鍙?uid=%s锛圫KIP_UID_PREFIX锛?, to_uid)
            continue
        try:
            # 馃敶 2026-11-04锛氬彇 latest 鈥斺€?鍏ュ悜涓嶈惤 chatmsg 鐨勮处鍙凤紙瀹炴祴 402857053锛?
            #    鍙湁 session 鎽樿閲屾湁濂瑰垰璇寸殑璇濓紝鍙 chatmsg 浼氳鍊欓€夋案杩滃仠鍦ㄥ嚑澶╁墠锛?
            #    杩涜€屾嬁 87h 鍓嶇殑鑰佽瘽鍘绘悳绱?鈫?韬唤鏍￠獙蹇呯劧澶辫触锛堝疄娴嬪悇澶辫触 10 娆★級銆?
            last, _src = db.latest(sid)
        except Exception:
            continue
        if last is None:
            log.debug("鍊欓€夎烦杩?sid=%s锛歭atest() 杩斿洖 None锛坈hatmsg 涓庢憳瑕侀兘绌猴級", sid)
            continue
        # 馃敶 搂104 C4锛氬綊妗?鈮?鎷夐粦銆傚ス鍐嶅彂浜鸿瘽锛坱s 姣斿彴璐︽按浣嶇嚎鏂帮級鈫?鍥炲悎閲嶇疆銆佽В闄ゅ綊妗ｃ€?
        #    蹇呴』鎷垮埌 last 鎵嶈兘姣旀椂闂达紝鎵€浠ユ斁鍦?latest() 涔嬪悗銆佽繃婊ら摼鏈€鍓嶉潰銆?
        #    鑻ユ斁鍦ㄥ惊鐜紑澶寸洿鎺?continue锛屽綊妗ｄ細璇濆皢姘歌繙瑙ｄ笉寮€锛堝疄娴嬫帹婕斿嚭鐨勬礊锛夈€?
        if str(sid) in _archived:
            try:
                from brain import sendgate as _SGa
                from data import reply_state as _RSa
                from eyes import sysmsg as _SMa
                # 馃敶 搂106 浜ゅ弶瀹℃煡瀹炶瘉锛圥0-1锛夛細鍙瘮 ts 浼氭妸銆屾垜鏂瑰垰鍙戠殑璺熻繘銆嶅拰
                #    Soul 鎺ㄧ殑绯荤粺鍗″綋鎴愬ス鐨勪汉璇?鈫?褰掓。澶嶆椿 + 姘翠綅绾胯姹℃煋锛?
                #    age 褰掗浂鍚庢渶澶氬彲鍐嶅彂 6 鏉°€傚繀椤诲悓鏃跺垽 sender 涓?human銆?
                _lt = (last.text or "").strip()
                # 鏂囨湰涓虹┖鏃讹紙璇煶/鍥剧墖鍗犱綅锛夊彧瑕佷笉鏄?msgType 27/35 涔熺畻鐪熶汉锛?
                # 閬垮厤濂圭敤璇煶/鍥剧墖閲嶆柊寮€鍙ｆ椂褰掓。姘歌繙瑙ｄ笉寮€锛圕4锛夈€?
                _human_ok = (_SMa.is_human(_lt, getattr(last, "msg_type", None),
                                           uid=to_uid) if _lt else
                             int(getattr(last, "msg_type", 0) or 0) not in (27, 35))
                _is_new_her = (str(last.sender) != str(db.uid) and _human_ok
                               and int(last.ts or 0) > _RSa.her_ts_of(str(sid)))
                if _is_new_her:
                    _SGa.on_her(str(sid), int(last.ts or 0), human=True)
                    log.info("褰掓。浼氳瘽鏉ヤ簡鏂扮殑浜鸿瘽 sid=%s 鈫?瑙ｉ櫎褰掓。锛岄噸鏂拌鍏ュ緟鍥?, sid)
                else:
                    scan_stats["archived"] += 1
                    log.debug("璺宠繃宸插綊妗ｄ細璇?sid=%s锛圕4锛氫笉鍥炪€佷笉鍞ら啋銆佷笉璁″緟鍥烇級", sid)
                    continue
            except Exception as _e_ar:
                log.debug("褰掓。妫€鏌ュ紓甯革紙鏈疆浠嶈烦杩囷級: %r", _e_ar)
                continue
        if str(last.sender) == str(db.uid):
            # 馃敶馃敶 2026-11-09 P0锛?8:42 鏂版秷鎭湭澶勭悊 路 鐪熸鐨勯攣鑺級
            #
            #   銆愭敼鍓嶃€戣繖閲屾槸涓€鍙?*娌℃湁浠讳綍鏃ュ織**鐨?`continue`銆?
            #   鑰岃繖涓处鍙凤紙402857053锛夌殑鐗规€ф槸銆屽叆鍚戞秷鎭笉钀?chatmsg銆佸彧鏇存柊 session 鎽樿銆嶏紝
            #   `latest()` 鍦ㄣ€屾憳瑕佹椂闂?<= chatmsg 鏃堕棿銆嶆椂鐩存帴杩斿洖 chatmsg 閭ｆ潯
            #   鈬?濂?18:42 鍒氳鐨勮瘽锛岃鍒ゆ垚銆屾渶鍚庝竴鏉℃槸鎴戝彂鐨?鈫?涓嶇敤鍥炪€嶏紝
            #   闈欓粯涓㈠純銆侀浂鏃ュ織銆傚疄娴?18:48 杩炵画澶氳疆 `寰呭洖 1 浜篳 浣?`candidates 涓虹┖`锛?
            #   灏辨槸杩欐潯璺緞鍚冩帀鐨勶紙鍏朵綑杩囨护鍏ㄩ兘鏈夋棩蹇楀彲鏌ワ級銆?
            #
            #   銆愭敼鍚庛€戞湯鏉℃槸鎴?+ 璁惧搴撹杩欎釜浼氳瘽 unReadCount>0
            #   鈬?浠ャ€岃澶囨湭璇汇€嶄负鍑嗭紙瀹冩槸寮虹湡鍊硷紝闀滃儚鍙槸缂撳瓨锛夛紝
            #   鐢?session 鎽樿閲屽ス鐨勮瘽纭斁琛岃繘闃熷垪锛涘彧鏈夋憳瑕佷篃璇佹槑鏄垜璇寸殑鎵嶈烦杩囥€?
            #   杩欐牱 `_recently_replied` 鐨勩€屽ス鏇存柊浜庢垜鐨勫洖澶嶃€嶈涔変粛鐒剁敓鏁堬紝涓嶄細閲嶅鍙戙€?
            if str(sid) in _unread_sids:
                _dig = {}
                try:
                    _dig = db.session_digest(sid) or {}
                except Exception:
                    _dig = {}
                _d_txt = (_dig.get("text") or "").strip()
                _d_ts = int(_dig.get("ts") or 0)
                # 馃敶 2026-11-12 澶滅彮淇锛圖5锛夛細璁惧鏈纭斁琛屽墠鍏堣繃绯荤粺鏂囨湰杩囨护銆?
                #   鏀瑰墠璇ュ垎鏀?out.append + continue 璺宠繃浜嗗悗闈?996-1016 鐨?SYS_TEXTS /
                #   is_human 绯荤粺鏂囨湰杩囨护 鈫?鍙兘鎶婄郴缁熷崱锛堝銆屼簰鐩稿叧娉ㄥ悗鍗冲彲鈥︺€嶏級褰?
                #   銆屽ス鐨勪汉璇濄€嶇‖鍏ラ槦锛圕5/C8 杩濊锛夈€俰s_human 鍒ゅ畾涓庝富寰幆鍚屾銆?
                if _d_txt:
                    try:
                        from eyes import sysmsg as _SM2
                        if not _SM2.is_human(_d_txt, getattr(last, "msg_type", None),
                                             uid=to_uid):
                            scan_stats["system"] += 1
                            log.debug("璁惧鏈纭斁琛屄风郴缁熸枃鏈?sid=%s uid=%s 鎽樿=%r 鈫?璺宠繃锛圕5/C8锛?,
                                      sid, to_uid, _d_txt[:16])
                            continue
                    except Exception:
                        pass
                if _d_txt and _d_ts and not _recently_replied(
                        to_uid, sid=sid, text=_d_txt, her_ts_ms=_d_ts):
                    log.info("璁惧鏈纭斁琛屄烽暅鍍忔粸鍚?uid=%s sid=%s 鎽樿=%r"
                             "锛坈hatmsg 鏈潯鏄垜锛屼絾璁惧璇存湭璇?鈫?鍒ゅ畾鏄ス鏂拌瘽锛?,
                             to_uid, sid, _d_txt[:24])
                    out.append((sid, to_uid, _d_txt, _d_ts,
                                _burst_n(db, sid, db.uid)))
                    continue
                scan_stats["mine_last"] += 1
                log.debug("璺宠繃鏈潯鏄垜 sid=%s uid=%s锛堣澶囪鏈锛屼絾鎽樿涔熻瘉鏄庢槸鎴戣鐨?
                          "鎴栧彇涓嶅埌鎽樿锛?r锛?, sid, to_uid, _d_txt[:20])
            else:
                log.debug("璺宠繃鏈潯鏄垜 sid=%s uid=%s锛堣澶囨湭璇婚泦鍚堥噷娌℃湁 鈫?鐪熉锋棤闇€鍥烇級",
                          sid, to_uid)
            continue
        # 馃敶 2026-11-03锛堟渶鑰佷紭鍏堢殑閰嶅闂革級锛歚session.timestamp` 浼氳銆屾湭璇绘帹閫?/
        #    鎺ㄨ崘浣嶅埛鏂般€嶆洿鏂帮紝涓?chatmsg 閲屽ス**鐪熸**鐨勬湯鏉℃椂闂村樊寰楀緢杩?鈥斺€?
        #    瀹炴祴绗簩涓处鍙烽噷娣疯繘浜?257h锛?0 澶╋級鍓嶇殑浼氳瘽锛宻ession 鏃堕棿鍗磋鍒锋垚杩戝嚑澶┿€?
        #    鏀规垚鏈€鑰佷紭鍏堝悗杩欑被浼氭姠鍒伴槦棣栵紝鎶婄湡姝ｈ鍥炵殑鎸ゅ埌鍚庨潰锛屾墍浠ヨ繖閲屾寜
        #    鐪熷疄鏈潯鏃堕棿鍐嶅崱涓€娆?LOOKBACK_DAYS 绐楀彛锛堣秴鏈熺殑鍥炰簡涔熸€紝濂规棭蹇樹簡锛夈€?
        if int(last.ts or 0) < cutoff:
            scan_stats["too_old"] += 1
            log.debug("璺宠繃瓒呮湡浼氳瘽 sid=%s锛堝ス鏈潯宸?%.1f 澶╁墠锛?,
                      sid, (time.time() * 1000 - int(last.ts or 0)) / 86400000.0)
            continue
        # 闈炴枃鏈被锛堣闊?鍥剧墖/琛ㄦ儏/鍗＄墖锛夊湪**鏈槦鍒楅噷涓€寰嬭烦杩?*锛?
        #   瀹冧滑鐨?text 鎭掍负绌?鈫?鎼滀笉鍒般€佸垪琛ㄩ瑙堜篃璁や笉鍑烘槸璋侊紝
        #   浣?*蹇呯劧甯︾孩鐐?* 鈫?鐢?clear.sweep 鈫?flow.handle_one 澶勭悊锛?
        #   閭ｆ潯閾捐矾宸茬粡鎺ュソ ASR / 鍥剧墖璇濇湳锛坆rain/voice.py銆乫low.MEDIA_REPLIES锛夈€?
        k = V.kind_of(last)
        if k == "tip":
            # 馃敶 2026-11-05锛氫笉鑳介潤榛樿烦杩?鈥斺€?濂硅瀹岃瘽鍚庡彲鑳界揣璺熺郴缁熷崱鐗囷紝
            #   鍘熸潵鐩存帴 continue 浼氳閭ｅ彞璇濇案涔呮病浜烘帴锛堜笖娌℃湁浠讳綍鏃ュ織鍙煡锛夈€?
            #   寰€鍓嶆壘濂规渶鍚庝竴鏉＄湡瀹炴秷鎭紝鎵惧埌浜嗗氨鎹㈠畠缁х画鍒ゃ€?
            from brain import flow as _flow
            _real = _flow.her_last_real(db, sid, db.uid)
            if _real is None:
                continue
            last = _real
            k = V.kind_of(last)
            if k == "tip":
                continue
        if k in ("image", "emoji", "other"):
            scan_stats["nontext"] += 1
            log.debug("闈炴枃鏈秷鎭紙%s锛塻id=%s 璧扮孩鐐硅矾寰勶紝杩欓噷璺宠繃", k, sid)
            continue
        if V.is_voice(last):
            # 馃敶馃敶 2026-11-08 01:45 鐢ㄦ埛鏄庣‘瑕佹眰锛氥€屼竴瀹氳姝ｅ父璇嗗埆瀵规柟璇煶鍐呭鐒跺悗鍐嶅洖澶嶃€嶃€?
            #   鏀瑰墠锛氳闊冲湪杩欓噷 `continue`锛岀悊鐢辨槸銆岀暀缁欑孩鐐硅矾寰勶紙clear.sweep 鈫?flow.handle_one锛夈€嶃€?
            #   浣嗗疄娴嬭繖涓悊鐢辨槸**涓嶆垚绔?*鐨勶細
            #     路 `unread_msg_number` 鍦?dump 閲屽嚭鐜?**0 娆?*锛堜袱甯ц繛缁獙璇侊級锛?
            #       `clear.dots()` 鎭掍负绌?鈫?绾㈢偣璺緞**鏍规湰涓嶄細瑙﹀彂**锛?
            #     路 浜庢槸銆屽ス鍙戣闊炽€? 姘镐箙鏃犱汉鍥炪€傝繖姝ｆ槸鐢ㄦ埛鍙嶅璇淬€岃闊虫病澶勭悊濂姐€嶇殑鐪熷洜銆?
            #   鏀瑰悗锛?*灏卞湴杞啓**锛岃浆鍑烘枃瀛楀氨褰撴垚姝ｅ父鏂囨湰鍊欓€夎繘鍏ラ槦鍒椼€?
            #   瀹炴祴鎴愭湰锛欰pp 鑷甫 word 鍛戒腑鐜囦粎 1/15锛?.7%锛夛紝鍏朵綑璧版湰鍦?whisper锛?
            #   2~10s 璇煶 0.1~12s/鏉★紙妯″瀷宸插姞杞藉悗 0.1s 鍛戒腑缂撳瓨锛屽喎鍚姩绾?5~12s锛夈€?
            #   杞啓澶辫触 鈫?鐢ㄥ崰浣嶄覆鐓ф牱杩涢槦鍒楋紙瀹佸彲鍥炰竴鍙ャ€屾病鍚竻锛屼綘鍐嶈涓€閬嶃€嶏紝
            #   涔熶笉鑳借濂圭殑璇煶姘歌繙鐭虫矇澶ф捣锛夈€?
            vtxt, vhow, _fresh_fail = _voice_text_cached(sid, last, db=db)
            full_voice = V.resolve_msg(last, db=db, sid=sid)
            if vtxt:
                if vhow != "cache":
                    log.info("璇煶宸茶浆鍐?sid=%s锛?ds, %s锛? %r",
                             sid, int(V.duration(full_voice)), vhow, vtxt[:40])
                txt = vtxt
            else:
                if _fresh_fail:
                    log.warning("璇煶杞啓澶辫触 sid=%s锛?ds锛夆啋 鐢ㄥ崰浣嶄覆鐓у父鍥炲锛?
                                "%.0f 鍒嗛挓鍐呬笉閲嶅杞啓",
                                sid, int(V.duration(full_voice)),
                                VOICE_FAIL_TTL_S / 60.0)
                else:
                    log.debug("璇煶杞啓娌跨敤澶辫触缂撳瓨 sid=%s锛?ds锛?,
                              sid, int(V.duration(full_voice)))
                txt = V.PLACEHOLDER
            # 鏍囪杩欎釜 sid 鏄闊筹細鎼滅储鏃跺繀椤昏烦杩囥€岀敤杞啓鏂囧瓧鎼溿€嶏紝
            # 鍥犱负 Soul 鍒楄〃棰勮鏄剧ず鐨勬槸銆孾璇煶]銆嶏紝杞啓鏂囧瓧鎼滀笉鍒帮紙瑙?kw_of锛夈€?
            _VOICE_SIDS.add(str(sid))
        else:
            txt = (last.text or "").strip()

        if not txt:
            scan_stats["empty"] += 1
            log.debug("鍊欓€夎烦杩?sid=%s uid=%s锛氭湯鏉℃棤鏂囨湰锛坘ind=%s锛夛紝涓嶅湪姝ら槦鍒楀鐞?,
                      sid, to_uid, k)
            continue
        # 馃敶 2026-11-10 搂104 C5/C8锛氱郴缁?骞垮憡娑堟伅涓嶅洖銆佷笉璁″緟鍥炪€?
        #    **涓嶆洿鏂?her_ts 姘翠綅绾?*銆佸彧璺宠繃涓嶅喎鍗达紙濂圭揣鎺ョ潃鍙戜汉璇濅粛瑕佹甯稿洖锛夈€?
        #    鏃у垽瀹氬彧璁?4 涓瓧闈㈤噺锛屾紡鎺夈€屼簰鐩稿叧娉ㄥ悗鍗冲彲鈥︺€嶈繖绫荤郴缁熷崱锛堝鐝疄璇佸洖閿欒繃锛夈€?
        _human = txt not in SYS_TEXTS
        try:
            from eyes import sysmsg as _SM
            _human = _SM.is_human(txt, getattr(last, "msg_type", None), uid=to_uid)
        except Exception as _e_sm:
            log.debug("sysmsg 鍒嗙被寮傚父锛堥€€鍥炲瓧闈㈤噺鍒ゅ畾锛? %r", _e_sm)
        if not _human:
            try:
                from brain import sendgate as _SG1
                _SG1.on_her(str(sid), int(last.ts or 0), human=False)
            except Exception:
                pass
            scan_stats["system"] += 1
            log.debug("绯荤粺/骞垮憡娑堟伅锛?s锛塻id=%s 鈫?涓嶅洖涓嶈寰呭洖锛圕5/C8锛?, txt[:20], sid)
            continue
        # C2锛氬ス鏈潯鐪熶汉娑堟伅鎺ㄨ繘姘翠綅绾匡紙鍙湪 ts 鍙樻柊鏃惰惤鐩橈紝浼氭竻鎺夋湰鍥炲悎鍙戦€佽鏁帮級銆?
        try:
            from brain import sendgate as _SG2
            _SG2.on_her(str(sid), int(last.ts or 0), human=True)
        except Exception:
            pass
        # 馃敶 2026-11-03 淇 P1锛氬師鏉?len(txt)<2 鎶娿€屽棷/濂?鍝︺€嶈繖绫讳竴瀛楃函鏂囨湰涔熶涪寮冦€?
        #    涓€瀛楁秷鎭嫢绾㈢偣宸叉竻涓斿綋鏃舵病鍙戝嚭锛屽氨浼氭案涔呮紡鍥炪€佷笖鏃犲彴璐﹀彲鎭㈠銆?
        #    鐜板湪鍙涪绌烘枃鏈紱涓€瀛楁秷鎭繚鐣欎负鍊欓€夛紝鎼滅储鍏抽敭璇嶇敱 kw_of 閫€鍥炲巻鍙查暱鍙ュ厹搴曘€?
        # 馃敶 2026-11-09 P0锛氳澶囧簱 unread>0 = 鐪熺孩鐐癸紝纭斁琛屻€?
        #    鍙拌处(replied.json)銆丩2(turns.md)銆佸喎鍗?pending_skip.json) 閮芥槸鏈湴鐘舵€侊紝
        #    闀滃儚婊炲悗鏃朵細鎶婃柊娑堟伅璇垽鎴愩€屽凡鍥?鍐峰嵈涓€嶏紝瀵艰嚧绾㈢偣鍫嗙潃涓€鏉￠兘涓嶅洖銆?
        #    杩欓噷鐩存帴鍏ラ槦锛屽悗缁畾浣?韬唤鏍￠獙/鍙戦€佷笁鎬佺‘璁や粛鐓у父鎵ц锛屼笉浼氫贡鍙戙€?
        if str(sid) in _unread_sids:
            if should_skip(sid, txt):
                _r = _LAST_SKIP.get(str(sid)) or {}
                _left = PP.cooldown_remaining_minutes(_r)
                scan_stats["cooldown"] += 1
                scan_stats["cooldown:%s" % (_r.get("reason") or "?")] += 1
                log.debug("璁惧鏈纭斁琛屄峰喎鍗存湭鍒?sid=%s锛堝師鍥?%s锛屽墿 %.0f 鍒嗛挓锛夆啋 鏈疆涓嶇‖鏀捐锛岄伩鍏嶅弽澶嶇櫧鐑?,
                          sid, _r.get("reason") or "?", _left)
                _sla_warn(sid, to_uid, last.ts, "鍐峰嵈涓?鍓?.0f鍒? % _left)
                continue
            log.info("璁惧鏈纭斁琛?uid=%s sid=%s锛堣烦杩囧彴璐?L2/鍐峰嵈锛?, to_uid, sid)
            out.append((sid, to_uid, txt, int(last.ts or 0), _burst_n(db, sid, db.uid)))
            continue

        # 馃敶 2026-11-10 搂104锛氱姸鎬佹満鍙栦唬銆岀函鏂囨湰 old==cur / L2 鏈鏄垜銆嶅垽瀹氥€?
        #    11-10 澶滅彮瀹炴祴锛氳繖涓ゅ彞璇垽銆岃鍒ゅ凡鍥炪€?42 娆°€佽烦杩囧凡鍥炰細璇?1549 娆?鈥斺€?
        #    濂瑰啀鍙戜竴鍙ヤ竴妯′竴鏍风殑銆屽搱鍝堝搱銆嶅氨琚綋鎴愬洖杩囷紝姘镐箙婕忓洖銆?
        #    鐜板湪鍙湁 awaiting / following / archived / no_human 鎵嶈烦杩囷紱
        #    濂硅浜嗕汉璇濅笖杩樻湁棰濆害涓€寰嬭繘闃熷垪锛屽叿浣撳彂鍑犳潯鐢?handle_pending 鐨勫彂閫侀椄瑁佸喅銆?
        _vd = None
        try:
            from brain import sendgate as _SG3
            from brain import verdict as _VD
            # 馃敶馃敶 2026-11-12锛圖S-05锛夛細琛ヤ紶 my_last_ts_ms 鈥斺€?鍚﹀垯 verdict 鐨?
            #   銆屾垜鏂规湯鏉℃櫄浜庡ス鏈潯 鈫?AWAITING銆嶅垎鏀亽涓嶈Е鍙戯紙榛樿 0锛夈€?
            _vd = _SG3.state_of(str(sid), her_ts_ms=int(last.ts or 0), has_human=True,
                                my_last_ts_ms=_my_last_ts_ms(db, str(sid)))
            if _vd.state == _VD.ARCHIVED:
                try:
                    from data import reply_state as _RSa
                    _RSa.set_archived(str(sid), True)   # wake.candidates() 涔熻鎺掗櫎
                except Exception:
                    pass
            if _vd.state in (_VD.AWAITING, _VD.FOLLOWING,
                             _VD.ARCHIVED, _VD.NO_HUMAN):
                scan_stats["state:%s" % _vd.state] += 1
                log.debug("鐘舵€佹満璺宠繃 uid=%s sid=%s state=%s锛?s锛?,
                          to_uid, sid, _vd.state, _vd.reason)
                continue
        except Exception as _e_vd:
            log.debug("鐘舵€佹満寮傚父 鈫?閫€鍥炴棫鍙拌处鍒ゅ畾: %r", _e_vd)
            if _recently_replied(to_uid, sid=sid, text=txt, her_ts_ms=last.ts) \
                    or _l2_last_is_me(sid, her_ts_ms=last.ts):
                scan_stats["replied"] += 1
                log.debug("璺宠繃宸插洖浼氳瘽 uid=%s锛堝彴璐? L2 鏈鏄垜涓斾笉鏃╀簬濂规渶鏂版秷鎭級", to_uid)
                _sla_warn(sid, to_uid, last.ts, "琚垽宸插洖")
                continue

        if should_skip(sid, txt):
            _r = _LAST_SKIP.get(str(sid)) or {}
            _left_min = PP.cooldown_remaining_minutes(_r)
            scan_stats["cooldown"] += 1
            scan_stats["cooldown:%s" % (_r.get("reason") or "?")] += 1
            log.debug("璺宠繃鍐峰嵈涓殑浼氳瘽 sid=%s锛堝師鍥?%s锛屽墿 %.0f 鍒嗛挓锛?,
                      sid, _r.get("reason") or "?", max(0.0, _left_min))
            _sla_warn(sid, to_uid, last.ts, "鍐峰嵈涓?鍓?.0f鍒? % max(0.0, _left_min))
            continue
        out.append((sid, to_uid, txt, int(last.ts or 0), _burst_n(db, sid, db.uid)))

    # 馃敶馃敶馃敶 2026-11-09 P0锛堟渶鍚庝竴閬撻椄 路 璁惧鏈瀵硅处锛?
    #
    #   涓婇潰姣忎竴涓繃婊ら兘瀵癸紝浣?*缁勫悎璧锋潵**浼氭妸銆岃澶囨槑璇存湁鏈銆嶇殑浼氳瘽婕忔帀锛?
    #     路 闀滃儚婊炲悗 鈫?latest() 杩斿洖鎴戠殑鏃ф秷鎭?鈫?鏈潯鏄垜
    #     路 璁惧瀛樻椿缂撳瓨闄堟棫 鈫?琚垽瀹氥€孉pp 閲屼笉瀛樺湪銆?
    #     路 20 鍒嗛挓/24 灏忔椂鍙ｅ緞銆佸喎鍗村彴璐︺€丩2 鏈 鈥?
    #   鐢ㄦ埛鍙ｅ緞寰堟竻妤氾細**璁惧搴撻噷 unReadCount>0 鐨勪細璇濓紝灏辨槸鏈変汉鐪熺殑鍦ㄧ瓑鎴戝洖**銆?
    #   鎵€浠ヨ繖閲屽仛涓€娆℃棤鏉′欢瀵硅处锛氳澶囪鏈銆佷絾娌¤繘 out 鐨勶紝閫愪釜鏌ユ槑鍘熷洜骞跺己鍒惰ˉ鍏ャ€?
    #   浠讳綍涓婃父杩囨护閮戒笉鑳芥妸瀹冩潃鎺?鈥斺€?杩欐槸銆屾柊娑堟伅涓嶈婕忓鐞嗐€嶇殑鏈€鍚庝繚璇併€?
    #   琛ュ叆鍚庝粛鐒惰蛋銆屽畾浣?/ 韬唤鏍￠獙 / 鍙戦€佷笁鎬佺‘璁ゃ€嶏紝涓嶄細鍙戦敊浜恒€?
    try:
        _have = {str(x[0]) for x in out}
        _missing = [s for s in _unread_sids if s not in _have]
        _added = 0
        # 馃敶馃敶 2026-11-12锛圖S-13锛氬璐﹁ˉ鍏ュ皝椤?5 -> 8锛?
        #   鍙栬垗璇存槑锛氫笂闄愪粠 5 鎻愬埌 8锛?*涓嶆斁寮€鍒版棤涓婇檺** 鈥斺€?鍥犱负锛?
        #     路 鏈€缁?out 浠嶄細琚?`limit`锛坈andidates 璋冪敤鏂逛紶 CAND_SCAN=60锛夋埅鏂紝
        #       涓?handle_pending 姣忚疆瀹為檯鍙鐞?max_n=5 涓紝琛ュ叆 8 涓笉浼氬啿鐖嗛槦鍒楋紱
        #     路 琛ュ叆鐨勪細璇濊嫢瀹氫綅/鍙戦€佸け璐ヤ細璧?mark_skip 鍐峰嵈锛坋nter_fail / notfound锛夛紝
        #       涓嬩竴杞嚜鐒惰 should_skip 鎸℃帀锛屼笉浼氬弽澶嶇櫧鐑э紱
        #     路 鑻ュ畬鍏ㄦ斁寮€锛堜笉灏侀《锛夛紝璁惧涓€鏃︽湁鍑犲崄鏉＄Н鍘嬫湭璇伙紝浼氬叏閮ㄧ粫杩囦笂娓?
        #       杩囨护纭叆闃燂紝鍗曡疆鐧界儳楠ゅ 鈥斺€?杩欐鏄€岄槻闃熷垪鍐茬垎銆嶈閬垮厤鐨勩€?
        #   鍙?8 = 鍘?5 + 3 浣欓噺锛屽吋椤俱€岃澶囨湭璇诲浜?5 鏉℃椂涓嶆紡銆嶄笌銆屼笉鍐茬垎銆嶃€?
        #   璁惧鏈瀵硅处鏈韩浠?*涓嶅彈鍐峰嵈闄愬埗**锛堝畠鏄€岃澶囨槑璇存湁浜虹瓑銆嶇殑鏈€鍚庝繚璇侊紝
        #   鍐峰嵈鏄湰鍦板彴璐︼紝涓嶈兘鍙嶈繃鏉ユ帺鐩栬澶囩湡鍊硷級鈥斺€?淇濇寔鍘熸剰锛屽彧璋冨皝椤躲€?
        for _s in _missing:
            if _added >= 8:            # 涓€娆℃渶澶氳ˉ 8 涓紝鍒妸闃熷垪鍐茬垎
                break
            # 馃敶 2026-11-12 澶滅彮淇锛圖4锛夛細褰掓。浼氳瘽涓嶈ˉ鍏ワ紙C4锛夈€?
            #   鏀瑰墠杩欐瀵硅处琛ュ叆寰幆娌℃湁浠讳綍褰掓。杩囨护 鈥斺€?褰掓。浼氳瘽鑻ヨ澶?unReadCount>0
            #   浼氳寮哄埗琛ュ叆闃熷垪锛岃繚鑳屻€屽綊妗ｄ笉鍥炪€佷笉鍞ら啋銆佷笉璁″緟鍥炪€嶏紙涓诲惊鐜?879-903 鏈夎繃婊わ級銆?
            #   _archived 鏄?candidates() 寮€澶寸殑褰掓。闆嗗悎锛屽悓涓€鍑芥暟浣滅敤鍩熷唴鍙洿鎺ョ敤銆?
            if str(_s) in _archived:
                log.info("璁惧鏈瀵硅处锛歴id=%s 宸插綊妗ｏ紙C4锛夆啋 涓嶈ˉ鍏?, _s)
                continue
            try:
                _dig = db.session_digest(_s) or {}
            except Exception:
                _dig = {}
            _t = (_dig.get("text") or "").strip()
            _uid2 = str(_dig.get("to_uid") or "")
            _ts2 = int(_dig.get("ts") or 0)
            if not _t or not _uid2 or not _ts2:
                log.debug("璁惧鏈瀵硅处锛歴id=%s 鎽樿涓嶅畬鏁达紙text=%r uid=%r ts=%s锛夆啋 鏃犳硶琛ュ叆",
                          _s, _t[:16], _uid2, _ts2)
                continue
            if _uid2.startswith(SKIP_UID_PREFIX):
                continue
            if _t in SYS_TEXTS:
                log.info("璁惧鏈瀵硅处锛歴id=%s 鏈潯鏄郴缁熸枃鏈?%r 鈫?涓嶈ˉ", _s, _t[:16])
                continue
            log.warning("璁惧鏈瀵硅处锛歴id=%s uid=%s 璁惧璇存湭璇诲嵈娌¤繘闃熷垪 "
                        "锛堣涓婃父杩囨护婕忔帀锛夆啋 寮哄埗琛ュ叆锛屾湯鏉?%r",
                        _s, _uid2, _t[:24])
            out.append((_s, _uid2, _t, _ts2, _burst_n(db, _s, db.uid)))
            _added += 1
        if _missing:
            _lv = log.info if _added else log.debug
            _lv("璁惧鏈瀵硅处锛氳澶囨湭璇?%d 涓紝鍏朵腑 %d 涓笉鍦ㄩ槦鍒楋紙宸茶ˉ %d 涓級",
                len(_unread_sids), len(_missing), _added)
    except Exception as _e:
        log.warning("璁惧鏈瀵硅处寮傚父锛堜笉褰卞搷宸叉湁鍊欓€夛級: %r", _e)

    # 馃敶 2026-11-03 鐢ㄦ埛鍙ｅ緞锛?*鏈€鑰佸緟鍥炰紭鍏?*锛堝厛鐏伀锛屽啀鑱婃柊鐨勶級銆?
    #    鍘熸潵鎸?session.timestamp 鍊掑簭 + 鍑戝 limit 灏?break = 鏈€鏂颁紭鍏堬紝
    #    缁撴灉鏄€屽ス 10 灏忔椂鍓嶉偅鍙ャ€嶆案杩滄帓鍦ㄣ€屽ス 2 鍒嗛挓鍓嶉偅鍙ャ€嶅悗闈紝
    #    瓒婅€佽秺娌′汉绠★紝p90 寤惰繜琚嫋鍒?156min銆?
    #    娉ㄦ剰涓ょ偣锛堟敼鐨勬椂鍊欒俯杩囷級锛?
    #      鈶?鎵弿绐楀彛浠嶆寜 timestamp DESC 鍙?SCAN_SESSIONS 涓紙淇濊瘉瑕嗙洊鏈€杩戜細璇濓級锛?
    #         鍙妸**杈撳嚭椤哄簭**鏀规垚鎸夊ス鏈潯鏃堕棿鍗囧簭锛?
    #      鈶?蹇呴』鎵畬绐楀彛鍐嶆帓锛屼笉鑳藉噾澶?limit 灏?break锛堝惁鍒欐案杩滃彧鎷垮埌鏈€鏂伴偅鍑犱釜锛夈€?
    #    鍏钩鎬х敱銆屽洖澶嶅彴璐?/ should_skip 鍐峰嵈銆嶄繚璇侊細澶勭悊瀹屼竴涓氨鑷劧寰€鍚庤蛋锛?
    #    涓嶉渶瑕侀澶栬疆杞紙_ROT 宸插簾锛夈€?
    # 馃敶 2026-11-03锛堢敤鎴峰彛寰勶細銆屾湁绾㈢偣灏变竴瀹氭湁鏂版秷鎭紝鏂版秷鎭笉鑳借绉帇鎸や綇銆嶏級锛?
    #   鍘熸潵鏁翠綋鎸夈€屾渶鑰佷紭鍏堛€嶁啋 绉帇 54 涓椂锛屽垰鍙戞潵娑堟伅鐨勪汉鎺掑湪闃熷熬锛?
    #   瀹炴祴涓€鏉?24h 鍓嶇殑鍜屼竴鏉″垰鍒扮殑鍚岀瓑瀵瑰緟锛屾柊娑堟伅绛変簬娌℃姠鍒伴槦銆?
    #   鐜板湪**鏂拌€佷氦閿?*锛氭渶杩?FRESH_H 灏忔椂鐨勫拰鑰佺Н鍘嬩氦鏇垮嚭闃燂紝
    #   姣忚疆涓よ竟閮芥帹杩涳紙3 鏂?+ 3 鑰侊級锛屾棦涓嶈鏂版秷鎭タ姝伙紝涔熶笉璁╄€佷細璇濇案杩滆疆涓嶅埌銆?
    now_ms = time.time() * 1000.0
    # 馃敶 2026-11-04锛堝疄鏃舵€э級锛氫笂闈㈡槸銆屾柊鑰佷氦鏇裤€嶏紝浣?fresh 鐨勭獥鍙ｆ槸 6 灏忔椂 鈥斺€?
    #   瀹炴祴濂?9 鍒嗛挓鍓嶅彂鐨勯偅鏉℃帓鍦ㄤ簡涓€鍫?4 灏忔椂鍓嶇殑鍚庨潰锛?9:15:42 鐨勬秷鎭?09:24 鎵嶅洖锛夈€?
    #   **寰堟柊锛?20 鍒嗛挓锛夌殑涓€寰嬫彁鍒版渶鍓嶉潰**锛屾寜鏃堕棿鍊掑簭锛涜€佺Н鍘嬩粠绗?N 涓箣鍚庡紑濮嬩氦鏇裤€?
    # 馃敶 2026-11-03锛堢敤鎴峰彛寰勶細銆屼紭鍏堝洖闀挎秷鎭拰濂瑰彂鏉ョ殑澶氭潯娑堟伅锛屼綆浜?3 瀛楃殑鎺掑悗闈€嶏級锛?
    #   涓诲簭鏀规垚銆屽唴瀹规。浣嶃€嶁€斺€?鐢?*绋冲畾鎺掑簭**鎸夋。浣嶉噸鎺掞紝鍚屾。浣嶄粛淇濇寔涓婇潰鐨勬柊鑰佷氦閿?
    #   锛堜笉鐮村潖涔嬪墠銆屾柊娑堟伅涓嶈兘琚Н鍘嬫尋浣忋€嶇殑鏃堕棿鍏钩鎬э級锛?
    #     妗?0锛氬ス杩炲彂澶氭潯锛堚墺2 鏉★級      鈫?淇℃伅鏈€澶氥€佷笖澶氬崐鏄垰鍙戞潵鍦ㄧ瓑锛屾渶浼樺厛
    #     妗?1锛氬崟鏉￠暱娑堟伅锛堚墺6 瀛楋級      鈫?鏈夊唴瀹广€佸ソ鎺?
    #     妗?2锛氫腑绛夛紙3~5 瀛楋級
    #     妗?3锛氱煭锛?3 瀛楋紝濡傘€屽摝/婊?锛熴€嶏級鈫?鎺掓渶鍚庯紙杩欑被鎼滅储涓嶅敮涓€銆佹槗绌鸿浆锛?
    # Fresh/stale interleave 鈫?content tier 鈫?strict 20-minute hot window.
    # The policy is pure and covered by tests/t_pending_policy.py.
    merged = PP.rank_candidates(out, fresh_hours=FRESH_H, hot_minutes=20,
                                now_ms=now_ms)
    merged = PP.prioritize_voice(merged, _VOICE_SIDS, hot_minutes=20,
                                 now_ms=now_ms)
    # 2026-11-03锛氭妸銆屽ス鏈潯鏃堕棿銆嶄竴璧疯繑鍥烇紙绗?4 椤癸級鈥斺€?
    #   handle_pending 瑕佺敤瀹冨垽銆屾槸涓嶆槸鏂お涔呫€佽璧伴噸鏂板紑鍦恒€嶃€?
    #
    # 馃敶馃敶 2026-11-08 12:5x锛堜慨鎴柇/杩囨护椤哄簭棰犲€?鈥斺€?search-diagnostician 鎸囧嚭锛?
    #
    #   鍘熸潵杩欓噷灏?`merged = merged[:limit]` 鎴柇浜嗭紝鑰?*杩囨湡闂稿湪涓嬮潰**銆?
    #   handle_pending 浼?limit=60锛圕AND_SCAN锛夛紝涓€鏃︽睜瀛愰噷鍓?60 涓伆濂介兘鏄€佸€欓€夛紝
    #   鏂伴矞鍊欓€変細鍦ㄨ繖涓€琛?*琚埅鎺夈€佹牴鏈蛋涓嶅埌杩囨湡闂?*锛岀瓑浜庨椄褰㈠悓铏氳銆?
    #   褰撳墠寰呭洖 22 < 60 涓嶈Е鍙戯紝浣嗙Н鍘嬩竴娑ㄥ氨浼氳俯鍒帮紙鍘嗗彶宄板€?63~64 浜猴級銆?
    #
    #   鈬?鍏堣繃婊わ紙杩囨湡闂革級锛屽啀鎴柇銆傝涔変笂鏈潵灏辫濡傛锛?
    #     limit 鏄€屾湰杞渶澶氬鐞嗗嚑涓?*鏈夋晥**鍊欓€夈€嶏紝涓嶆槸銆屽厛鍙?60 涓啀鐪嬫湁鍑犱釜鏈夋晥銆嶃€?
    #   娉ㄦ剰锛氭埅鏂Щ鍒拌繃鏈熼椄涔嬪悗锛堣涓嬫柟 `merged = merged[:limit]`锛夈€?
    # 馃敶馃敶 2026-11-08 02:50锛圥0 姝婚攣淇锛氱Н鍘嬫案杩滄竻涓嶆帀 鈫?鍖归厤姘歌繙琚タ姝伙級
    #
    #   鐜扮綉瀹炲喌锛氬緟鍥?63~64 浜猴紝鍏朵腑缁濆ぇ閮ㄥ垎鏄?**92~158 灏忔椂**锛?~6.6 澶╋級鍓嶇殑鑰佷細璇濄€?
    #   杩欎簺浼氳瘽鐨勫叡鍚岀偣鏄細
    #     路 缈?3 灞忔壘涓嶅埌锛堝垪琛?1270 鏉★紝鏃╄椤跺埌鍑犵櫨鍚嶅紑澶栵級
    #     路 鎼滅储鎼滀笉鍒帮紙濂?4 澶╁墠閭ｅ彞璇濓紝Soul 鎼滅储鍙储寮曡繎鏈熻亰澶╄褰曪級
    #   浜庢槸姣忎釜鍊欓€夌櫧鐑?40~50s锛氱炕灞?21s 鈫?鍙屽嚮 鈫?杩涙悳绱?鈫?7.3s銆屾湭鎵惧埌鐩稿叧缁撴灉銆嶁啋 鏀惧純銆?
    #   涓€杞檷绾у鐞?10 涓?= 鐧界儳 300~500s锛?*涓€涓汉閮藉洖涓嶆帀**銆?
    #
    #   鍚庢灉鏄閿侊細
    #     绉帇娓呬笉鎺?鈫?has_dot_now 鎭?True 鈫?daemon 绾㈢偣闂搁棬 `浠嶆湁绾㈢偣 鈫?鏈疆涓嶅尮閰峘
    #     鈫?杩炵画鍖归厤锛圡ATCH_STREAK_N=12锛?*涓€娆￠兘杩涗笉鍘?*锛堝疄娴?11-08 鍏ㄥぉ鍖归厤 3 娆★紝
    #       鏀瑰畬杩炵画鍖归厤鍚?0 娆★級銆?
    #
    #   淇硶锛氱粰銆屽畾浣嶅皾璇曘€嶈涓€涓?*杩囨湡闂?*銆傝秴杩?STALE_GIVEUP_H 灏忔椂鐨勪細璇濓紝
    #   涓嶅啀娴垂缈诲睆/鎼滅储锛堥偅鏄敞瀹氬け璐ョ殑锛夛紝鐩存帴鎺掗櫎鍑烘湰杞€欓€夈€?
    #   娉ㄦ剰锛?*涓嶆槸涓嶅洖浜?* 鈥斺€?瀹冧滑浠嶅湪搴撻噷锛岀瓑鍝ぉ濂瑰啀鍙戞柊娑堟伅锛坱s 鍙樻柊锛夎嚜鐒跺洖鍒伴槦鍒楋紱
    #   鑰屼笖銆屽洖涓€鏉?4 澶╁墠鐨勮瘽銆嶆湰韬篃娌℃剰涔夛紙濂规棭蹇樹簡锛岀敤鎴疯鐨勬槸鑳借亰璧锋潵鐨勪汉锛夈€?
    #
    #   闃堝€煎彇 72h锛氬疄娴?24h 鍐呯殑鍊欓€夊畾浣嶆垚鍔熺巼楂樺緱澶氾紝72h 澶栫殑鍑犱箮鍏ㄦ槸 notfound銆?
    #
    # 馃敶馃敶 2026-11-08 12:4x锛圥0-1锛宻earch-diagnostician 鍏ㄩ噺鍙栬瘉 _team/search_diag.md 搂2.1锛?
    #
    #   涓婇潰銆屽彇 72h銆嶇殑璇存硶琚疄娴嬫暟鎹帹缈伙紝鎸夊勾榫勫垎娈电殑**鍥炲嚭鐜?*锛?4h 绐楀彛锛夛細
    #     0-1h 鈫?49.2%   鈫?鍑犱箮鎵€鏈夋垚鍔熼兘鍦ㄨ繖涓€娈?
    #     3-6h 鈫?0.0%
    #     6-12h 鈫?10.7%
    #     12-24h 鈫?0.0%
    #     24h+  鈫?0.8% / 0.0%
    #   鍊欓€夐噷 61.4% 骞撮緞 鈮?4h銆?8h+ 鍗?50.1%锛岃€?48h+ 鍥炲嚭鐜?**0.0%**銆?
    #   缈诲睆鍛戒腑鐜囧彧鏈?8.1%锛屽钩鍧?21.2s/娆★紝44 灏忔椂鐑ф帀 373.7 鍒嗛挓銆?
    #
    #   鈬?24h 杩欎釜闂稿お鏉俱€傞檷鍒?12h 鑳界爫鎺?61.4% 鐨勬棤鏁堢炕灞忥紙绾?229 鍒嗛挓/44h锛夛紝
    #     鎶婂崟杞绠楄缁欑湡姝ｅ洖寰楀嚭鐨勪汉銆?
    #   璇箟涓嶅彉锛?*涓嶆槸涓嶅洖浜?* 鈥斺€?濂瑰啀鍙戞柊娑堟伅 ts 鍙樻柊灏辫嚜鍔ㄥ洖鍒伴槦鍒椼€?
    # 馃敶 2026-11-10 搂104锛歋TALE_GIVEUP_H 24 鈫?72锛堜笌 RESTART_H 瀵硅皟锛夈€?
    #    涓婇潰鍘嗗彶娉ㄩ噴閲岀殑銆?4h銆嶆槸鏀瑰墠鍙ｅ緞锛屼繚鐣欎綔鍐崇瓥鐣欑棔锛?
    #    鐜板湪 >72h 鐨勪細璇濈敱 verdict 鍒?archived 骞跺啓鍙拌处锛屾湰闂稿彧浣滃厹搴曘€?
    try:
        _stale_ms = STALE_GIVEUP_H * 3600000.0
        _keep, _dropped = [], 0
        for x in merged:
            _age = now_ms - float(x[3] or 0)
            if _age >= _stale_ms:
                _dropped += 1
                try:
                    from data import reply_state as _RSd
                    _RSd.set_archived(str(x[0]), True)
                except Exception:
                    pass
                continue
            _keep.append(x)
        if _dropped:
            scan_stats["stale"] += _dropped
            log.debug("杩囨湡娣樻卑锛?d 涓€欓€夎秴杩?%.0fh 鏈椿璺冿紙缈诲睆/鎼滅储娉ㄥ畾澶辫触锛夆啋 鏈疆涓嶆帓瀹冧滑锛?
                      "闃熷垪鍓?%d 涓?, _dropped, STALE_GIVEUP_H, len(_keep))
        merged = _keep
    except Exception as _e:
        log.warning("杩囨湡娣樻卑寮傚父锛堝拷鐣ワ紝鎸夊師闃熷垪璧帮級: %r", _e)
    # 馃敶 2026-11-08 12:5x锛氭埅鏂Щ鍒拌繖閲岋紙**杩囨护涔嬪悗**锛夈€傝涓婃柟椤哄簭棰犲€掔殑娉ㄩ噴銆?
    merged = merged[:limit]
    state_n = sum(v for k, v in scan_stats.items() if k.startswith("state:"))
    cooldown_n = int(scan_stats.get("cooldown", 0) or 0)
    reasons = PP.compact_reason_counts(scan_stats)
    sig = (
        int(scan_stats.get("source", 0) or 0),
        len(out),
        int(scan_stats.get("archived", 0) or 0),
        state_n,
        cooldown_n,
        int(scan_stats.get("stale", 0) or 0),
    )
    now = time.time()
    publish = sig != _CAND_SCAN_LOG.get("sig") or now - float(_CAND_SCAN_LOG.get("ts") or 0) >= 60
    msg = (
        "鍊欓€夋壂鎻忔眹鎬伙細婧?%d 鈫?鏈夋晥 %d锛涘綊妗?%d銆佺姸鎬佹満 %d銆佸喎鍗?%d銆佽繃鏈?%d"
        % (sig[0], sig[1], sig[2], sig[3], sig[4], sig[5])
    )
    (log.info if publish else log.debug)(msg)
    if publish:
        _CAND_SCAN_LOG.update(sig=sig, ts=now)
        MET.emit(
            "candidates",
            source=sig[0],
            actionable=sig[1],
            archived=sig[2],
            state_skip=sig[3],
            cooldown=sig[4],
            stale=sig[5],
            cooldown_reasons=reasons,
            returned=min(len(merged), int(limit or 0)),
            uid=str(getattr(db, "uid", "") or ""),
        )
    value = [x[:4] for x in merged]
    _CANDIDATE_CACHE.update(key=_cache_key, at=time.time(), value=list(value))
    return value


NICK_FILE = STATE / "nick_cache.json"


def _load_nick_file():
    """璇荤洏涓婄殑鏄电О缂撳瓨锛坰id -> 鏄电О锛夈€?

    馃敶 2026-11-10锛歚extMap` 閲岀殑鏄电О鍙鐩?48% 鐨勮€佷細璇濓紝浣?*鍒楄〃琛?浼氳瘽鏍囬涓?
      涓€瀹氬啓鐫€鏄电О**銆傛墍浠ュ嚒鏄湪鐣岄潰涓婄湅瑙佽繃鐨勬樀绉伴兘璁颁笅鏉ワ紝
      涓嬫杩欐壒 40h+ 鐨勮€佷細璇濆氨鏈夋樀绉板彲鎼滀簡锛堣繖鏄敮涓€鑳芥晳瀹冧滑鐨勬墜娈碉級銆?
    """
    out = {}
    try:
        if NICK_FILE.exists():
            import json as _json
            d = _json.loads(NICK_FILE.read_text(encoding="utf-8"))
            now = time.time()
            for k, v in (d or {}).items():
                if isinstance(v, str) and v.strip():
                    out[str(k)] = (now, v.strip())
    except Exception as e:
        log.debug("鏄电О缂撳瓨璇诲彇澶辫触锛堝綋浣滅┖锛? %r", e)
    return out


_NICK_CACHE = _load_nick_file()
_NICK_LOG_CACHE = {"at": 0.0, "map": {}}


def _nick_from_logs(sid):
    """Recover nicknames already seen by flow logs when the DB extMap lacks name."""
    now = time.time()
    if now - float(_NICK_LOG_CACHE.get("at") or 0) >= 300:
        mapping = {}
        try:
            p = LOGS / "brain.flow.log"
            raw = p.read_bytes()
            # Nicknames from older sessions may sit near the tail after a week.
            tail = raw[-4 * 1024 * 1024:].decode("utf-8", "replace")
            pat = re.compile(r"\[([^\]\r\n]{1,20})\].*?\bsid=(\d{6,})")
            for line in tail.splitlines():
                if "蹇矾寰? not in line and "鎱㈣矾寰? not in line:
                    continue
                m = pat.search(line)
                if m:
                    mapping[str(m.group(2))] = m.group(1).strip()
        except Exception as e:
            log.debug("浠?flow 鏃ュ織鎭㈠鏄电О澶辫触: %r", e)
        _NICK_LOG_CACHE.update(at=now, map=mapping)
    return _NICK_LOG_CACHE["map"].get(str(sid))


def nick_of(db, sid, uid):
    """鍙?*瀵规柟鏄电О**锛堝簱閲屽敮涓€鍙潬鐨勬樀绉版潵婧愶細chatmsg.extMap 鐨?name锛夈€?

    馃敶 2026-11-10锛堢敤鎴峰彛寰勩€屾悳鏄电О銆嶏級
      IM-SDK 搴撴病鏈夋樀绉拌〃锛宍soul_app.db.im_user.alias` 鍙紦瀛樻湰浜恒€?
      濂瑰彂鏉ョ殑娑堟伅 `extMap` 閲屽甫鍙戦€佽€呮樀绉帮紙JSON锛屽瓧娈靛悕 name/nickName 閮芥湁杩囷級锛?
      瀹炴祴 73 涓?>20h 寰呭洖浼氳瘽閲?35 涓兘鎷垮埌锛?8%锛夛紝鎷夸笉鍒板氨鏄?None銆?

      缂撳瓨 10 鍒嗛挓锛氫竴娆′細璇濆唴鏄电О涓嶄細鍙橈紝閬垮厤姣忎釜鍊欓€夐兘閲嶆煡涓€閬?SQL銆?
    """
    key = str(sid)
    hit = _NICK_CACHE.get(key)
    if hit and (time.time() - hit[0]) < 600.0:
        return hit[1]
    nice = None
    try:
        rows = db.con.execute(
            "SELECT extMap FROM chatmsg WHERE sessionId=? AND senderId<>? "
            "AND extMap IS NOT NULL AND extMap != '' "
            "ORDER BY localTime DESC LIMIT 12", (sid, str(db.uid))).fetchall()
        import json as _json
        for row in rows:
            # 馃敶 2026-11-10锛欼MDB.con 甯?row_factory=sqlite3.Row锛孯ow 鏃笉鏄?tuple
            #   涔熶笉鏄?list 鈥斺€?鎸?isinstance 鍒ゆ柇浼氭妸瀹冨綋瀛楃涓插杩?json.loads锛?
            #   寮傚父鍙堣 debug 鍚炴帀锛岃〃鐜板氨鏄€屾樀绉版案杩滃彇涓嶅埌銆嶃€?
            em = row[0]
            if not em or "name" not in em:
                continue
            try:
                d = _json.loads(em)
            except Exception:
                continue
            for k in ("name", "nickName", "nickname"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    nice = v.strip()
                    break
            if nice:
                break
    except Exception as e:
        log.debug("鍙栨樀绉板紓甯?sid=%s: %r", sid, e)
    if not nice:
        nice = _nick_from_logs(sid)
        if nice:
            log.info("浠?flow 鏃ュ織鎭㈠鏄电О sid=%s: %r", sid, nice)
    _NICK_CACHE[key] = (time.time(), nice)
    if len(_NICK_CACHE) > 500:
        _NICK_CACHE.clear()
    return nice


def _usable_word(w, min_len):
    """杩欎釜璇嶈兘涓嶈兘鎷垮幓鎼滐紙Soul 鎼滅储瀵圭煭璇?绾鍙峰熀鏈棤鏁堬級銆?

    瀹炴祴锛歚鎼滅储 '鍡?`銆乣'鍝?`銆乣'馃'` 涓€寰?0 缁撴灉锛?
    鏄电О `銆俙銆乣馃檱` 鍚岀悊銆傛嬁瀹冧滑鎼滃彧鏄櫧鐑?30~50s 鍐嶈涓€娆″け璐ュ彴璐︺€?
    """
    t = (w or "").strip()
    if len(t) < min_len:
        return False
    # 鑷冲皯鍚竴涓眽瀛?瀛楁瘝/鏁板瓧锛氱函 emoji銆佺函鏍囩偣銆佺函绌虹櫧閮芥悳涓嶅埌
    return bool(re.search(r"[0-9A-Za-z\u4e00-\u9fff\uff10-\uff19]", t))


def remember_nick(sid, nick):
    """鎶婄晫闈笂鐪嬪埌鐨勬樀绉拌涓嬫潵锛堝垪琛ㄨ/浼氳瘽鏍囬锛夛紝渚涗互鍚庛€屾悳鏄电О銆嶇敤銆?""
    t = (nick or "").strip()
    if not _usable_word(t, 2):
        return
    key = str(sid)
    old = _NICK_CACHE.get(key)
    if old and old[1] == t:
        return
    _NICK_CACHE[key] = (time.time(), t)
    try:
        import json as _json
        data = {k: v[1] for k, v in _NICK_CACHE.items() if v and v[1]}
        NICK_FILE.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        log.info("璁颁綇鏄电О sid=%s 鈫?%r锛堜笅娆″彲鎼滄樀绉帮級", key[-10:], t)
    except Exception as e:
        log.debug("鏄电О缂撳瓨钀界洏澶辫触: %r", e)


def _sessions_with(db, text):
    """鏂囨湰鍑虹幇鍦ㄥ嚑涓笉鍚屼細璇濋噷锛堝墠缂€鍖归厤锛屽吋瀹?kw_of 鐨?20 瀛楁埅鏂級銆?

    杩斿洖 -1 = 鏌ヤ笉鍒?寮傚父锛堜繚瀹堬紝涓嶅惁鍐筹級銆?
    """
    t = (text or "").strip()
    if len(t) < 4:
        return -1
    try:
        r = db.con.execute(
            "SELECT COUNT(DISTINCT sessionId) FROM chatmsg WHERE text LIKE ?",
            (t + "%",)).fetchone()
        return int(r[0] or 0) if r else 0
    except Exception:
        return -1


def _search_plan(db, sid, to_uid, kw, direct_text=""):
    """鎼滅储涓夌骇绛栫暐锛堢敤鎴?2026-11-10 鍙ｅ緞锛夈€?

      鈶?鏄电О 鈥斺€?鍞竴鎬ф渶寮猴紝鍛戒腑鍗虫湰浜猴紱
      鈶?瀵硅瘽鍐呭閲?*鐙竴鏃犱簩**鐨勪竴鍙ワ紙鍙湪鏈細璇濆嚭鐜帮級锛涘浼氳瘽閲嶅鐨勭洿鎺ヤ笉鎼滐紝
         鍥犱负鎷垮畠鎼滃繀鐒惰繘閿欎汉/鎼滀笉鍒帮紙瀹炴祴妯℃澘鍙?notfound 鐜囨瀬楂橈級锛?
      鈶?閮芥病鏈?鈫?杩斿洖绌猴紝涓婂眰鏀惧純鏈疆銆?

    涓轰粈涔堜笉鏄€屾湁鍐呭灏辨悳銆嶏細鏃ュ織瀹炶瘉 `鎼滅储 '灏遍偅鎻愮ず锛屾病鍟ョ敤'` 鑳戒腑銆佽€?
    `'钁涗紭韬猴紝閭ｆ槸鐦嚭澧冪晫浜?` 涓嶄腑 鈥斺€?宸埆涓嶅湪闀跨煭锛屽湪浜庤繖鍙ヨ瘽鏄惁鍞竴鎸囧悜涓€涓汉銆?

    杩斿洖 [(label, word), ...]锛屾寜浼樺厛绾ф帓濂姐€?
    """
    plan = []
    nk = nick_of(db, sid, to_uid)
    if _usable_word(nk, 2):
        plan.append(("鏄电О", nk))
    elif nk:
        log.info("鏄电О %r 澶煭/绾鍙?鈫?涓嶆嬁瀹冩悳", nk[:12])
    # A voice item's transcript is absent from the local chatmsg column, but
    # Soul's own search index may still contain its server-side ASR text.
    # Try it before falling back to an older text message.
    if _usable_word(direct_text, 5):
        plan.append(("璇煶杞啓", direct_text[:30]))
    if _usable_word(kw, 5):
        n = _sessions_with(db, kw)
        # 馃敶馃敶 2026-11-10锛堣韩浠芥牎楠岃繛缁け璐ョ殑鐪熸鏉ユ簮锛夛細
        #   `n == 0` 鍘熸潵涔熻鏀捐锛屼絾瀹冪殑鐪熷疄鍚箟鏄?*杩欏彞璇濆湪浠讳綍 chatmsg 閲岄兘涓嶅瓨鍦?*
        #   鈥斺€?鍙彲鑳芥潵鑷?session 鎽樿锛堝ス鐨勪釜浜虹畝浠?/ Soul 鎺ㄨ崘鏂囨锛夈€?
        #   Soul 鎼滅储浼氭妸銆岀敤鎴疯祫鏂欍€嶄竴璧锋悳锛屼簬鏄悳 `甯屾湜 Ta 鑳介亣瑙?35 宀佸悗鐨刞
        #   鍛戒腑涓€鍫?*绠€浠嬮噷鍐欑潃杩欏彞璇濈殑闄岀敓浜?*锛岀偣杩涘幓 4 娆″叏鏄埆浜猴細
        #     23:07:42 杞悳绱?鈫?23:08:51銆岃韩浠芥牎楠岃繛缁?4 娆″け璐ャ€嶁啋 闀垮喎鍗?2h 鈫?杩欐潯姘歌繙涓嶅洖
        #   鐜板湪锛? 涓細璇濆嚭鐜拌繃 鈫?鍒ゅ畾銆屼笉鏄亰澶╁唴瀹广€嶏紝涓嶈鎷垮幓鎼溿€?
        #   -1锛堟煡璇㈠紓甯革級淇濆畧鏀捐锛岄伩鍏嶈浼ゃ€?
        if n in (-1, 1):
            plan.append(("鍐呭", kw))
        elif n == 0:
            log.info("鍐呭鍏抽敭璇?%r 鍦ㄥ簱鍐?0 涓細璇濆嚭鐜帮紙鍍忔槸绠€浠?鎺ㄨ崘鏂囨锛夆啋 涓嶆嬁瀹冩悳",
                     kw[:16])
        else:
            log.info("鍐呭鍏抽敭璇?%r 鍦?%d 涓細璇濋噷閮芥湁锛堜笉鐙竴鏃犱簩锛夆啋 涓嶆嬁瀹冩悳",
                     kw[:16], n)
    elif kw:
        log.info("鍐呭鍏抽敭璇?%r 澶煭/绾鍙?鈫?涓嶆嬁瀹冩悳", kw[:12])
    return plan


def kw_of(db, sid, txt, min_len=3, skip_text=False):
    """閫夋悳绱㈠叧閿瘝锛氭湯鏉″お鐭氨寰€鍓嶆壘涓€鏉℃洿闀跨殑锛涘帇缂╁浣欑┖鏍笺€?

    瀹炴祴澶辫触妗堜緥锛?026-11-02锛夛細
      銆屽摝锛熴€? 瀛?-> 鎼滅储 0 鏉＄粨鏋?
      銆屾姈闊? 鐣寗灏忚銆嶅弻绌烘牸 -> 鎼滅储 0 鏉?
    鎵€浠ヨ繖閲屾妸绌虹櫧鍘嬫垚涓€涓紝闀垮害涓嶅灏遍€€鍥炰笂涓€鏉℃洿闀跨殑娑堟伅銆?

    馃敶 2026-11-08锛氭柊澧?`skip_text` 鈥斺€?璇煶浼氳瘽涓撶敤銆?
      璇煶杞啓鍑烘潵鐨勬枃瀛?*鍙瓨鍦ㄤ簬鎴戜滑鍐呭瓨閲?*锛孲oul 鍒楄〃棰勮鏄剧ず鐨勬槸銆孾璇煶]銆嶏紝
      鎷胯浆鍐欐枃瀛楀幓鎼滅储 100% 寰楀埌銆屾湭鎵惧埌鐩稿叧缁撴灉銆嶏紝鐧界瓑 11~30s銆?
      鎵€浠ヨ闊充細璇濈洿鎺ヨ烦杩囥€岀敤鏈潯鏂囧瓧鎼溿€嶏紝鏀硅蛋涓嬮潰鐨勫巻鍙查暱鍙ュ厹搴曘€?
    """
    cand = re.sub(r"\s+", " ", txt or "").strip()
    # 鍘绘帀 [琛ㄦ儏] 鏍囪鍐嶆悳锛氬甫 [绗慮 杩欑被璇嶆悳绱細鍛戒腑涓嶅埌锛?026-11-02 瀹炴祴锛?
    cand = re.sub(r"\[[^\]]{1,6}\]", "", cand).strip()
    # 馃敶 2026-11-04锛堢幇缃?09:09 瀹炴祴锛夛細`鎼滅储 '鏈哄櫒浜猴紵' -> 绛夋弧 30s 浠嶆棤缁撴灉`銆?
    #    甯﹀叏瑙掓爣鐐圭殑鍏抽敭璇嶅湪 Soul 鎼滅储閲屽懡涓笉浜嗭紙闂彞銆佹劅鍙瑰彞鍑犱箮蹇呬腑锛夈€?
    #    鍙幓鎺?*棣栧熬**鏍囩偣锛屼腑闂翠笉鍔紙涓棿鏍囩偣鏄師璇濈殑涓€閮ㄥ垎锛夈€?
    _PUNC = r"\s锛屻€傦紒锛熴€?.!?~锝炩€-鈥擾:锛?锛沑"'锛堬級()\[\]銆愩€?
    cand = re.sub("^[" + _PUNC + "]+", "", cand)
    cand = re.sub("[" + _PUNC + "]+$", "", cand).strip()
    # 馃敶馃敶 2026-11-08 12:4x锛圥0-3锛宻earch-diagnostician 鍏ㄩ噺鍙栬瘉 _team/search_diag.md 搂2.4锛?
    #
    #   瀹炴祴鍏抽敭璇嶉暱搴?vs 鎼滅储鎴愬姛鐜囷紙44h 绐楀彛锛?139 鍊欓€夛級锛?
    #     3~4 瀛?鈫?43.5%   5~8 瀛?鈫?**74.1%锛堟渶楂橈級**   绾暟瀛椾覆 鈫?97% 瓒呮椂
    #   3~4 瀛楄秴鏃剁疮璁?358 娆?脳 30s 鈮?179 鍒嗛挓绾氮璐癸紱
    #   绾暟瀛楋紙鎵嬫満鍙?寰俊鍙凤紝濡?'159****0632'锛夎秴鏃?131 娆★紝鍑犱箮蹇呰秴鏃躲€?
    #
    #   鎵€浠ユ妸銆屽涓嶅闀裤€嶇殑闂镐粠 min_len(榛樿3) 鎻愬埌 5锛屽苟鏄惧紡绂佹帀绾暟瀛椾覆銆?
    #   闀垮害澶熺殑鍊欓€変粛鐒朵紭鍏堬紱涓嶅灏卞線涓嬭蛋銆屽巻鍙查暱鍙ュ厹搴曘€嶏紝鑰屼笉鏄‖鎼滀竴涓繀璐ョ殑璇嶃€?
    # 馃敶 2026-11-12锛堜慨 TIMEOUT 175 娆★級锛氫笂闈㈢殑姝ｅ垯 `[0-9锛?锛橾+` 鍙尮閰?*绾暟瀛?*锛?
    #   鑰屽疄娴嬫帺鐮佹墜鏈哄彿锛堝 '159****0632'锛屾敞閲婇噷鐐瑰悕鐨勪緥瀛愶級甯?4 涓?`*`锛?
    #   瀹屽叏缁曡繃浜嗚繖閬撻椄 鈫?鎷垮畠鍘绘悳绱?97% 瓒呮椂锛堟瘡 30s 鐧界儳锛夛紝姝ｆ槸鏈?issue 鐨?
    #   brain.pendingq.log TIMEOUT 涓诲姏鏉ユ簮銆傝ˉ涓?`*` / 鍏ㄨ `锛奰锛屾帺鐮佸彿涔熺銆?
    _KW_MIN = max(min_len, 5)
    _is_digits = bool(cand) and re.fullmatch(r"[0-9锛?锛?锛奭+", cand or "") is not None
    if len(cand) >= _KW_MIN and not _is_digits and not skip_text:
        out = cand[:20]
        # 鎴柇鍙兘鎶娿€孾鏃烘煷]銆嶅垏鎴愩€孾鏃恒€嶁€斺€?娈嬬暀鐨?[ 浼氳鎼滅储澶辫触锛堝疄娴嬶級
        out = re.sub(r"\[[^\]]*$", "", out).strip()
        return out
    try:
        msgs = list(db.messages(sid, limit=8))
        # 馃敶 2026-11-03 淇細**浼樺厛鐢ㄣ€屽ス銆嶅彂鐨勯暱鍙?*锛屽叾娆℃墠鏄垜鐨勩€?
        #    鍘熷洜锛堝疄娴?16:09-16:12 杩炵画 3 娆?id_mismatch锛夛細濂规湯鏉℃槸銆岃銆嶃€屼笉鐭ラ亾銆?
        #    杩欑鐭瘝鏃讹紝閫€鍥炵殑銆屾渶杩戜竴鏉￠暱鍙ャ€嶅線寰€鏄垜鍙戠殑**寮€鍦虹櫧妯℃澘**
        #    锛堛€屾湁绌鸿亰涓ゅ彞涓嶃€嶃€屼綘骞虫椂杩欎釜鐐归兘骞插暐銆嶏級锛屽悓涓€鍙ヨ瘽鍦ㄥ嚑鍗佷釜浼氳瘽閲岄兘鏈?鈥斺€?
        #    鎼滃嚭鏉ョ涓€鏉′笉涓€瀹氭槸濂癸紝杩涢敊浼氳瘽鍚庤韩浠芥牎楠屽繀鐒跺垽銆屼笉鍞竴銆嶏紝
        #    鐧界儳涓€杞?30~50s锛岃繕瑕佺瓑鍐峰嵈閲嶈瘯銆傚ス鐨勮瘽鎵嶆槸杩欎釜浼氳瘽鍞竴鐨勩€?
        for want_mine in (False, True):      # 鍏堝ス鐨勮瘽锛屽啀鎴戠殑璇?
            for m in reversed(msgs):         # 鍚勮嚜閮戒粠鏈€鏂板線鍓嶆壘
                is_mine = str(m.sender) == str(db.uid)
                if is_mine != want_mine:
                    continue
                t = re.sub(r"\s+", " ", (m.text or "")).strip()
                t = re.sub(r"\[[^\]]{1,6}\]", "", t).strip()
                # 馃敶 2026-11-08锛氬厹搴曞彞鍚屾牱瑕佽繃銆? 瀛椾笅闄?+ 闈炵函鏁板瓧銆嶁€斺€?
                #   鍚﹀垯鏈潯澶煭鏃跺張浼氶€€鍥炲埌涓€涓繀璐ョ殑鍏抽敭璇嶏紙瀹炴祴 3~4 瀛楁垚鍔熺巼浠?43.5%锛?
                # 馃敶 2026-11-12锛圱IMEOUT 鏍规不锛夛細鍏滃簳鍙ュ悓鏍疯鎸?*鎺╃爜鎵嬫満鍙?*
                #   锛?137****8899'锛夆€斺€?瀹冮暱搴﹀銆佷絾甯?`*` 浼氱粫杩囨棫姝ｅ垯琚綋鎴?
                #   鍏抽敭璇嶇‖鎼滃繀瓒呮椂銆備笌涓婃柟涓婚椄鍚屽彛寰勶細鏁板瓧 + 鏄熷彿涓€寰嬪垽蹇呰触銆?
                if re.fullmatch(r"[0-9锛?锛?锛奭+", t or ""):
                    continue
                if m.msg_type != 1 or len(t) < 6:
                    continue
                # 馃敶馃敶 2026-11-08 13:2x锛圥0-C锛宺eply-diagnostician 瀹炶瘉鏀剁泭鏈€楂樼殑涓€鏉★級
                #
                #   瀹炴祴锛坃team/reply_diag.md 搂9锛夛細鎶婃瘡娆?`鎼滅储 'KW'` 鎷垮幓 chatmsg 绮剧‘鍙嶆煡锛?
                #     `鏈壘鍒扮浉鍏崇粨鏋渀 45 娆￠噷 **鍙湁 3 娆★紙7%锛?* 鍏抽敭璇嶅湪鏈細璇濈湡瀹炲瓨鍦ㄣ€?
                #     鑰?219 娆?notfound 涓緢澶ф瘮渚嬫槸**鎴戞柟寮€鍦虹櫧妯℃澘**锛?
                #     銆岄噸搴嗗ソ鐜╃殑鍦版柟鏈夊緢澶氬憖锛屼綘瑕侀棶鏄庛€嶅湪 **4 涓笉鍚?sid** 涓婇噸澶嶅嚭鐜帮紝
                #     涓斿叏閮?notfound 鈥斺€?瀹冩槸**缇ゅ彂妯℃澘**锛屼笉鏄繖涓細璇濈殑鐙湁鍐呭銆?
                #
                #   涓轰粈涔堟ā鏉垮彞蹇呰触锛氭ā鏉垮彞鍦ㄥ嚑鍗佷釜浼氳瘽閲岄兘鏈変竴妯′竴鏍风殑鍓湰锛?
                #   Soul 鎼滅储瑕佷箞杩斿洖涓€鍫嗕笉鐩稿叧鐨勪汉锛堣韩浠芥牎楠屽け璐ワ級锛?
                #   瑕佷箞骞茶剢绱㈠紩涓嶅埌锛坣otfound锛夈€備袱澶撮兘鏄櫧鐑?30~50s銆?
                #
                #   淇硶锛?*鍏堟煡杩欎釜鍙ュ瓙鏄笉鏄兢鍙戞ā鏉?* 鈥斺€?鍦ㄥ簱閲屾湁 鈮? 涓笉鍚屼細璇?
                #   鍑虹幇杩囧悓鏍风殑璇濓紝灏辫烦杩囧畠锛岀户缁線鍓嶆壘涓嬩竴鍙ャ€傛垚鏈槸涓€娆℃湰鍦?SQL锛?
                #   鐪佺殑鏄?30~50s 鐨勫繀璐ユ悳绱?+ 涓€娆?3 灏忔椂鍐峰嵈璇綒銆?
                if _is_broadcast_template(db, t):
                    log.debug("鍏滃簳鍏抽敭璇?%r 鏄兢鍙戞ā鏉匡紙澶氫細璇濋噸澶嶏級鈫?璺宠繃", t[:20])
                    continue
                return t[:20]
    except Exception as e:
        log.warning("鍙栧閫夊叧閿瘝寮傚父: %r", e)
    return cand[:20]


_TEMPLATE_CACHE = {}


def _is_broadcast_template(db, text, min_sessions=3):
    """杩欏彞璇濇槸涓嶆槸銆岀兢鍙戞ā鏉裤€嶏紙鍦?鈮in_sessions 涓笉鍚屼細璇濋噷閮藉嚭鐜拌繃锛夈€?

    馃敶 2026-11-08 13:2x锛圥0-C 鐨勫疄鐜帮級

      鑳屾櫙瑙?`kw_of` 閲岀殑娉ㄩ噴锛氭垜鏂瑰紑鍦虹櫧妯℃澘锛堛€岄噸搴嗗ソ鐜╃殑鍦版柟鏈夊緢澶氬憖鈥︺€嶏級
      浼氬湪鍑犲崄涓細璇濋噷閲嶅鍑虹幇锛屾嬁瀹冨綋鎼滅储鍏抽敭璇?*蹇呯劧澶辫触**锛?
        路 Soul 鎼滃嚭涓€鍫嗕笉鐩稿叧鐨勪汉 鈫?韬唤鏍￠獙澶辫触
        路 鎴栧共鑴嗙储寮曚笉鍒?鈫?notfound
      涓ょ缁撴灉閮界櫧鐑?30~50s锛岃繕浼氳缃?3 灏忔椂鍐峰嵈銆?

      鍒ゆ嵁锛氱敤 chatmsg 閲屽悓鏍风殑鏂囨湰鏁?*涓嶅悓 sessionId 鐨勪釜鏁?*銆?
        鈮? 鈫?鍒や负妯℃澘锛岃烦杩囥€?
      涓轰粈涔堟槸 3锛氬疄娴嬫甯稿璇濋噷鍚屼竴鍙ヨ瘽璺?3 涓細璇濋噸澶嶇殑姒傜巼鏋佷綆
        锛堜汉涓嶄細瀵逛笁涓汉璇翠竴瀛椾笉宸殑璇濓級锛岃€屾ā鏉垮彞鍔ㄨ緞 4~40 涓細璇濄€?

      鎴愭湰锛氫竴娆℃湰鍦?SQL锛堟湁 60s 缂撳瓨锛夛紝鐩告瘮瀹冪渷鎺夌殑 30~50s 鎼滅储鍙拷鐣ャ€?
      澶辫触涓€寰嬭繑鍥?False锛?*淇濆畧**锛氬垽涓嶅嚭灏卞綋瀹冧笉鏄ā鏉匡紝淇濇寔鏃ц涓猴級銆?
    """
    t = (text or "").strip()
    if not t or len(t) < 6:
        return False
    key = t[:40]
    now = time.time()
    hit = _TEMPLATE_CACHE.get(key)
    if hit and (now - hit[0]) < 60.0:
        return hit[1]
    ans = False
    try:
        row = db.con.execute(
            "SELECT COUNT(DISTINCT sessionId) FROM chatmsg WHERE text = ?",
            (t,)).fetchone()
        n = int(row[0] or 0) if row else 0
        ans = n >= min_sessions
        if ans:
            log.info("妯℃澘鍙ユ娴嬶細%r 鍑虹幇鍦?%d 涓細璇?鈫?涓嶅綋鎼滅储鍏抽敭璇?, t[:24], n)
    except Exception as e:
        log.debug("妯℃澘鍙ユ娴嬪け璐ワ紙褰撲綔闈炴ā鏉匡級: %r", e)
        ans = False
    _TEMPLATE_CACHE[key] = (now, ans)
    if len(_TEMPLATE_CACHE) > 400:
        _TEMPLATE_CACHE.clear()
    return ans


def _norm(s):
    """鍘绘帀绌虹櫧鍜屽父瑙佹爣鐐癸紝渚夸簬棰勮鏂囨湰涓庡簱鍐呭師鏂囨瘮瀵广€?""
    import re
    return re.sub(r"[\s锛屻€傦紒锛熴€?.!?~锝炩€-鈥擾:锛?锛沑"'锛堬級()\[\]銆愩€慮+", "", s or "")


def _swipe_once(actor, x1, y1, x2, y2, budget=8.0):
    """鍒楄〃鎵嬪娍锛?*绉掔骇瓒呮椂鍏滃簳**銆?

    馃敶 2026-11-04 浜嬫晠锛堝繀椤讳繚鐣欙級锛歝lear._pull_down 鐩存帴璋?u2 鐨?swipe锛?
      u2 鐨?HTTP 榛樿瓒呮椂 600s 鈥斺€?08:20:50 閭ｆ涓嬫媺鍒锋柊鎸備簡鏁存暣 10 鍒嗛挓锛?
      鏁磋疆 cycle 鍋滄憜锛岄偅 10 鍒嗛挓閲屽ス涓ゆ潯鏂版秷鎭竴鏉℃病澶勭悊銆?
      鎵€浠ヤ换浣曟墜鍔块兘瑕佸帇 client timeout + 绾跨▼ join 鍏滃簳銆?
    """
    try:
        d = actor.dev.u2()
    except Exception as e:
        log.warning("鎵嬪娍鍙?u2 澶辫触: %r", e)
        return False
    # 馃敶 2026-11-04锛坉uration 鍗曚綅浜嬫晠锛夛細
    #   u2 鐨?duration 鏄?*绉?*锛堟簮鐮?steps = int(duration * 200)锛屾瘡 step 绾?5ms锛夈€?
    #   鍘熸潵杩欓噷浼?duration=500 鈫?绛変环 500 绉掔殑鎵嬪娍锛屾瘡娆￠兘琚?join(10s) 鏀惧純锛?
    #   琚斁寮冪殑鎵嬪娍杩樺湪璁惧涓婄户缁窇锛屽悗缁偣鍑诲叏鎺掑湪瀹冨悗闈?鈥斺€?缈婚〉绛変簬娌＄炕銆?
    #   鍙﹀ `d._client.timeout` 鍦?u2 3.7.1 閲屾牴鏈笉瀛樺湪锛堢┖鎿嶄綔锛夛紝宸插垹銆?
    box = {"ok": False, "err": None}

    # 馃敶馃敶 2026-11-08锛圓2 瀹堝崼婕忔礊淇锛夛細杩欓噷**缁曡繃 Hand 鐩存帴璋?u2**锛?
    #   鍘熸潵娌℃湁 note_action() 鈬?鍔ㄤ綔浠ｆ暟涓嶅彉 鈬?婊戝畬绱ц窡鐨勯潪 force `actor.snap()`
    #   锛坒ind_row:972 / _scroll_top:882锛変細**澶嶇敤婊戝姩鍓嶉偅涓€甯?* 鈬?琛屾寚绾圭浉鍚?
    #   鈬?璇垽銆屽垪琛ㄥ凡鍒板簳銆嶁噿 鎻愬墠鏀惧純缈诲睆銆佽鍥炵殑浜鸿璺宠繃銆?
    #
    #   涓轰粈涔堣繖鏄?*鐪熷疄鍙Е鍙?*鐨勶紙瀹炴祴锛岄潪鎺ㄦ祴锛夛細_swipe_once 婊戝畬鍒拌皟鐢ㄦ柟鍙栧抚
    #   鍙湁 `duration 0.35 + time.sleep(0.7) = 1.05s`锛?*灏忎簬 Actor.FRAME_TTL 1.2s**锛?
    #   涓ら亾瀹堝崼锛堝姩浣滀唬鏁版湭鍙?/ Activity 鏈彉锛夊叏閮ㄦ斁琛屻€傛帰閽?`_test_a2_swipe.py`
    #   淇鍓?3/3 FAIL锛坉umps=1銆佽澶囧凡缈诲埌绗?2 灞忓嵈璇诲洖绗?1 灞忥級銆?
    #   璁惧瓒?蹇?锛坲2 寰€杩旇秺鐭級瓒婂鏄撹俯鍒帮細rtt<=0.15s 钀藉湪绐楀彛鍐咃紝>=0.20s 鎵嶅畨鍏ㄣ€?
    #
    #   鏀惧湪**鍙戣捣鎵嬪娍涔嬪墠**锛歶2 鐨?swipe 涓嶆槸鍘熷瓙鐨勶紝涓€斿紓甯镐篃鍙兘宸茬粡婊氫簡灞忥紱
    #   澶氫綔搴熶竴甯у彧澶氫粯涓€娆?dump锛屾紡浣滃簾鍒欐槸瀹氫綅閿欒锛堟柟鍚戝繀椤讳繚瀹堬級銆?
    def _job():
        try:
            from core.device import note_action
            note_action()            # A2锛氳８ u2 鎵嬪娍锛屾墜宸ヨ甯х紦瀛樹綔搴?
            d.swipe(x1, y1, x2, y2, duration=0.35)   # 绉掞紒0.35s 鈮?70 steps
            box["ok"] = True
        except Exception as e:      # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_job, name="lswipe", daemon=True)
    t.start()
    t.join(budget)
    if t.is_alive():
        log.warning("鍒楄〃鎵嬪娍瓒呮椂锛?%.0fs锛夛紝鏀惧純鏈", budget)
        return False
    if not box["ok"]:
        log.warning("鍒楄〃鎵嬪娍澶辫触: %r", box["err"])
        return False
    time.sleep(0.7)
    return True


def _swipe_list(actor, up=True):
    """浼氳瘽鍒楄〃缈讳竴灞忋€倁p=True 鈫?鐪嬫洿鏃╃殑浜猴紙鎵嬫寚鑷笅鑰屼笂锛夈€?""
    if up:
        return _swipe_once(actor, 450, 1100, 450, 400)
    return _swipe_once(actor, 450, 400, 450, 1100)


def first_dot_row(actor):
    """褰撳墠灞忋€岀涓€涓孩鐐硅銆嶃€?

    2026-11-04锛堟柊娑堟伅蹇呭洖锛夛細鏈潯鏄€孾鍒嘳銆嶃€岋紵锛熴€嶈繖绉?1~2 瀛?绾〃鎯呮椂锛?
    find_row 鐨勫洓灞傛枃鏈尮閰嶅叏钀界┖锛堚憼 瑕?鈮? 瀛椼€佲憿 瑕?鈮? 瀛楋級锛岃€?kw_of 閫€鍥炵殑
    鏄?*鎴戣嚜宸卞彂鐨勫紑鍦虹櫧妯℃澘**锛屾悳瀹冨繀鐒躲€屾湭鎵惧埌鐩稿叧缁撴灉銆嶁€斺€?瀹炴祴涓ゆ潯鍒氬彂鏉ョ殑
    娑堟伅灏辫繖鏍疯缃氫簡 3 灏忔椂鍐峰嵈銆?
    鍒氬彂鏉ョ殑娑堟伅蹇呯劧鍦ㄥ垪琛ㄩ《閮ㄣ€佷笖甯︾孩鐐?鈬?鐩存帴杩涚涓€涓孩鐐硅銆?
    杩涢敊浜轰笉浼氫覆鍙帮細杩涗細璇濆悗 `韬唤鏍￠獙` 鐢?session 鎽樿瀵逛笉涓婂氨 fail-closed 涓嶅彂銆?
    """
    try:
        from eyes.chatlist import rows as _rows
        snap = actor.snap(force=True)
        for r in _rows(snap):
            if r.has_dot:
                return r
    except Exception as e:
        log.warning("鍙栫孩鐐硅澶辫触: %r", e)
    return None


def _list_sig(snap):
    """褰撳墠灞忕殑琛屾寚绾癸紙鍒ゆ柇銆岀湡鐨勬粦鍔ㄤ簡/鍒伴《浜嗐€嶏級銆?""
    try:
        from eyes.chatlist import rows as _rows
        return tuple((r.blob or "")[:24] for r in _rows(snap))
    except Exception:
        return ()


def _scroll_top(actor, rounds=4, preempt=None):
    """鍥炲垪琛ㄩ《閮紙鏈€澶?rounds 娆★級锛屽惁鍒欎笅娆¤繘鏉ヤ粠涓棿寮€濮嬩細婕忎笂闈㈢殑浜恒€?""
    try:
        prev = _list_sig(actor.snap())
    except Exception:
        prev = ()
    for _ in range(max(1, rounds)):
        if preempt and preempt():
            return False
        if not _swipe_list(actor, up=False):
            return False
        try:
            cur = _list_sig(actor.snap())
        except Exception:
            return False
        if cur and cur == prev:
            return True
        prev = cur
    return True


def find_row(actor, txt, kw=None, min_len=4, pages=None, nick=None, db=None, sid=None,
             preempt=None):
    """鍦?*浼氳瘽鍒楄〃**閲屾壘杩欐潯娑堟伅鎵€灞炵殑琛岋紙棣栧睆 鈫?閫愬睆涓嬬炕锛夈€?

    鐢ㄦ埛 2026-11-02/03 鍙嶅寮鸿皟锛氥€屾槑鏄庤繖涓汉灏卞湪灞忓箷涓?绾㈢偣涔熸湁 涓轰粈涔堣繕瑕佽蛋鎼滅储銆?
      鈥斺€?鍒楄〃閲岀湅寰楄灏辩洿鎺ョ偣琛岋紝鎼滅储鏄渶鍚庢墜娈碉紙涓€娆¤ 11s锛夈€?

    馃敶 2026-11-03 淇紙绾㈢偣琛屼紭鍏?+ 鐭秷鎭笉鍐嶇洿鎺ユ斁寮冿級锛?
      鍘熸潵鍙嬁銆屾湯鏉℃枃鏈€嶅尮閰嶃€佷笖 <4 瀛楃洿鎺?return None 鈥斺€?鏈潯鏄€屽摝/婊?瀵瑰憖/
      鐪嬩笉鎳傘€嶈繖绉嶇煭娑堟伅鏃讹紝灞忓箷涓婃槑鏄庢湁濂圭殑绾㈢偣琛岋紝鍗磋繛璇曢兘涓嶈瘯灏辩敥缁欐悳绱?
      锛堝疄娴?17:47~18:03 璧版悳绱㈢殑 6 涓€欓€夋湯鏉″叏鏄煭娑堟伅锛夈€?

    馃敶 2026-11-04 淇紙**棣栧睆鍛戒腑鐜囧彧鏈?14%**锛夛細
      瀹炴祴涓€杞?52 娆″鐞嗛噷 20 娆°€屾悳绱㈡湭鎵惧埌銆嶃€?3 娆℃垚鍔燂紙25%锛夆€斺€旀牴鍥犳槸杩欎釜鍑芥暟
      鍙湅褰撳墠涓€灞忥紙8~10 琛岋級锛屽€欓€?60 涓紝86% 鐨勪細璇濄€屽湪鍒楄〃閲屼絾涓嶅湪绗竴灞忋€嶃€?
      鐜板湪閫愬睆涓嬬炕锛堥粯璁?3 灞忥級锛屾瘡灞忕敤琛屾寚绾圭‘璁ゃ€岀湡鐨勬粦鍔ㄤ簡銆嶏紝婊戜笉鍔ㄧ珛鍒诲仠锛?
      鍏ㄨ惤绌哄垯鍥為《锛堝惁鍒欎笅娆′粠涓棿寮€濮嬶紝涓婇潰鐨勪汉姘歌繙鎵句笉鍒帮級銆?

    姣忓睆鐨勫垎灞傜瓥鐣ワ紙鍛戒腑鍗宠繑鍥烇級锛?
      鈶?绾㈢偣琛?+ 鏈潯鐭枃鏈紙鈮? 瀛楋級鈥斺€?绾㈢偣=鏈夋湭璇?寰呭洖瀵硅薄锛岃鏁板皯銆佷釜涓鍥烇紝
         鍏佽鐢ㄥ緢鐭殑鏂囨湰瀹氫綅锛岃鍛戒腑椋庨櫓浣庯紱
      鈶?绾㈢偣琛?+ kw锛堝ス鍘嗗彶闀垮彞锛夆€斺€?棰勮鑻ユ樉绀哄ス閭ｅ彞闀跨殑锛岃繖閲屽懡涓紱
      鈶?鍏ㄥ垪琛?+ 鏈潯闀挎枃鏈紙鈮? 瀛楋級鈥斺€?甯歌璺緞锛?
      鈶?鍏ㄥ垪琛?+ kw 鈥斺€?鐭秷鎭絾鏃犵孩鐐癸紙鑰佺Н鍘嬬孩鐐规棭娑堬級鏃剁殑鏈€鍚庢枃鏈皾璇曘€?
    """
    from eyes.chatlist import rows
    from eyes.page import detect

    snap = actor.snap()
    if detect(snap) != "chatlist":
        return None
    raw = _norm(txt)
    kwn = _norm(kw) if kw else ""
    # 搴撴憳瑕侊紙= 鍒楄〃棰勮鍘熸枃锛夈€傜函琛ㄦ儏/璇煶/鐭秷鎭潬瀹冨畾浣嶏紝涓嶅悆闀垮害闂ㄦ銆?
    dkey = ""
    if db is not None and sid:
        try:
            _dg = db.session_digest(sid) or {}
            _dk = re.sub(r"\[[^\]]{1,6}\]", "", (_dg.get("text") or "")).strip()[:8]
            dkey = _norm(_dk) or ""
        except Exception:
            dkey = ""

    def _hit(c, r, mlen):
        if not c or len(c) < mlen:
            return False
        blob = _norm(r.blob)
        if not blob:
            return False
        if c[:12] and c[:12] in blob:
            return True
        for k in (c[:8], c[-8:]):
            if len(k) >= mlen and k in blob:
                return True
        return False

    def _scan(sn):
        """鍦?*杩欎竴灞?*閲屾壘锛岃繑鍥?(row, 鏃ュ織鏂囨) 鎴?(None, '')銆?

        馃敶馃敶 2026-11-10锛堝繀鍥?P0锛氱煭娑堟伅缁撴瀯鎬у懡涓巼涓?0锛夛細
          鍘熷疄鐜板彧闈?`_hit()` 鍖归厤琛?blob锛岃€屽畠瑕佹眰 `len(c) >= mlen`
          锛堢孩鐐硅 2 瀛?/ 鍏ㄥ垪琛?4 瀛楋級銆傛湯鏉℃槸 '濂? / '鍡? / '鍟? / '[琛ㄦ儏]'
          杩欑被鏃?*浠讳綍涓€灞傞兘涓嶅彲鑳藉尮閰?*锛屼簬鏄細
            澶勭悊 '486483065'锛堟湯鏉?'濂?锛?h 鍓嶏級鈫?缈诲畬 3 灞忎粛鏈懡涓?鈫?杞悳绱?
          鈥斺€?濂?3 鍒嗛挓鍓嶅垰鍙戙€佸氨鍦ㄥ垪琛ㄧ涓€灞忕殑浜猴紝鐓ф牱瀹氫綅涓嶅埌锛岀櫧鐑?40s 鎼滅储銆?
          鏄电О鏄垪琛ㄤ笂**鍞竴绋冲畾銆佷笉鍙楁秷鎭唴瀹瑰奖鍝?*鐨勪俊鍙凤紝鎵€浠ユ彁鍒版渶鍓嶏細
          灞忎笂鏄电О鍞竴 鈫?鐩存帴鐢紱鏈夋涔夛紙'銆?杩欑鎾炲悕锛夆啋 閫€鍥炴枃鏈尮閰嶃€?
          韬唤鐪熶吉浠嶇敱 `_session_matches()` fail-closed 鍏滃簳锛屼笉浼氫覆鍙般€?
        """
        ni = _norm(nick) if nick else ""
        if len(ni) >= 2:
            _cand = []
            for r in rows(sn):
                rn = _norm(r.nickname)
                if rn and (rn == ni or ni in rn or rn in ni):
                    _cand.append(r)
            if len(_cand) == 1:
                try:
                    return _cand[0], "鍒楄〃鏄电О鍛戒腑 y=%d %r" % (_cand[0].center[1], _cand[0].nickname)
                except Exception:
                    return _cand[0], "鍒楄〃鏄电О鍛戒腑 %r" % _cand[0].nickname
        all_rows = rows(sn)
        # 馃敶馃敶 2026-11-10锛堢函琛ㄦ儏鏈潯缁撴瀯鎬у懡涓嶄腑锛夛細
        #   `_norm('[涓崍濂絔')` 鈫?'涓崍濂?锛? 瀛楋級锛岃€屽叏鍒楄〃灞傝姹?mlen=4 鈫?
        #   濂规湯鏉℃槸绾〃鎯呫€佸張娌℃湁绾㈢偣锛?8h 鍓嶇殑鑰佷細璇濆繀鐒跺姝わ級鏃讹紝
        #   **浠讳綍涓€灞傞兘涓嶅彲鑳藉懡涓?*锛?
        #     澶勭悊 '500117554'锛堟湯鏉?'[涓崍濂絔'锛?8h 鍓嶏級鈫?缈诲畬 3 灞忎粛鏈懡涓?鈫?鐑?43s 鎼滅储
        #   杩欓噷琛ヤ竴灞傘€屽簱鎽樿銆嶅尮閰嶏細鍒楄〃棰勮鏂囨湰 == 搴撻噷鐨?lastMsgText 鍘熸枃锛?
        #   璇箟绮剧‘锛堜笌 clear._rows_for_lib 宸插湪鐢熶骇楠岃瘉鐨勫彛寰勪竴鑷达級锛屼笉鍚?mlen 闂ㄦ銆?
        #   浣嗙煭鏂囨湰鍙兘鎾炲琛?鈫?**鍙帴鍙楀睆涓婂敮涓€鍛戒腑**锛屾湁姝т箟灏遍€€鍥炲師閫昏緫銆?
        if dkey:
            _hr = [r for r in all_rows if (r.blob or "") and dkey in _norm(r.blob)]
            if len(_hr) == 1:
                return _hr[0], "鍒楄〃棰勮鍛戒腑锛堝簱鎽樿 %r锛? % dkey[:8]
        dotted = [r for r in all_rows if r.has_dot]
        for r in dotted:
            if _hit(raw, r, mlen=2):
                return r, "绾㈢偣琛屽懡涓紙鏈潯 %r锛? % raw[:8]
        for r in dotted:
            if _hit(kwn, r, mlen=4):
                return r, "绾㈢偣琛屽懡涓紙鍏抽敭璇?%r锛? % kwn[:8]
        for r in all_rows:
            if _hit(raw, r, mlen=min_len):
                return r, "鍒楄〃鐩存帴鍛戒腑锛堝叏鏂囷級"
        for r in all_rows:
            if _hit(kwn, r, mlen=4):
                return r, "鍒楄〃鐩存帴鍛戒腑锛堝叧閿瘝 %r锛? % kwn[:8]
        return None, ""

    r, why = _scan(snap)
    if r is not None:
        log.info("%s %r", why, r.nickname)
        return r

    pages = FIND_PAGES if pages is None else int(pages)
    moved_total = 0

    # 馃敶馃敶 2026-11-10锛堝繀鍥?P0锛氭柟鍚戞€ч敊璇級锛?
    #   `_swipe_list(up=True)` 鏄妸鍒楄〃寰€**鏇磋€?*鐨勬柟鍚戠炕銆傝€?handle_pending 澶勭悊瀹?
    #   涓婁竴涓€欓€夊悗锛屽垪琛ㄥ凡缁忓仠鍦ㄤ腑涓嬮儴 鈥斺€?涓嬩竴涓€欓€夊鏋滄瘮濂规洿鏂帮紝鐩爣灏卞湪
    #   **涓婇潰**锛岀户缁悜涓嬬炕绛変簬鏈濆弽鏂瑰悜鎵撅紝缈?3 灞忓繀鐒惰惤绌恒€?
    #   鏃ュ織瀹炶瘉锛?2:53 娓呯孩鐐硅繘銆岄湝楦cy銆嶆椂濂圭殑琛屽湪 y=469/622锛堝睆骞曚腑閮級锛?
    #   鑰?22:56 pendingq 鎵惧悓涓€涓汉 鈫?缈诲畬 3 灞忔湭鍛戒腑 鈫?鐧界儳 43s 鎼滅储銆?
    #   淇硶锛氬厛鍚戜笂鎺竴灞忥紙鍙湪纭疄鑳芥粴鍔ㄦ椂鎵嶅仛锛岄伩鍏嶅凡鍦ㄩ《閮ㄧ櫧鐑?4s锛夈€?
    _up_sig = _list_sig(snap)
    try:
        if _swipe_list(actor, up=False):
            # 馃敶馃敶 2026-11-10锛堝疄娴?P0锛氬悜涓婃帰灞忓悗鐐归敊浜猴級
            #   23:11:38 棣栨鐢熸晥灏卞嚭浜嬩簡锛?
            #     `鍒楄〃鏄电О鍛戒腑 '涓€鍙緤'锛堝悜涓?1 灞忥級'涓€鍙緤'` 鈫?鐩存帴鐐瑰垪琛ㄨ
            #     鈫?`韬唤鏍￠獙澶辫触锛堣繘鐨勬槸鍒殑浼氳瘽锛氭竻闆?['9669164683008498']锛屾湡鏈?9669164631844588锛塦
            #   鏍瑰洜锛歚_swipe_list` 杩斿洖鍚庡垪琛?*杩樺湪鎯€ф粴鍔?*锛岀珛鍒诲彇鏍戞嬁鍒扮殑
            #   鏄粴鍔ㄤ腑閫旂殑鍧愭爣锛岀瓑鐪熸 click 鏃堕偅涓€琛屽凡缁忕Щ浣?鈫?鐐瑰埌鐩搁偦浼氳瘽銆?
            #   锛坒ail-closed 鎸′綇浜嗛敊鍙戯紝浣嗚繖娆＄櫧璺戜竴瓒?25s銆傦級
            #   淇硶锛氱瓑鎯€у仠 + 寮哄埗鍙栨柊甯э紝鍧愭爣鎵嶆槸鐐瑰嚮閭ｄ竴鍒荤殑鐪熷疄浣嶇疆銆?
            time.sleep(0.8)
            _s_up = actor.snap(force=True)
            if detect(_s_up) == "chatlist":
                _up_sig2 = _list_sig(_s_up)
                if _up_sig2 and _up_sig2 != _up_sig:
                    r, why = _scan(_s_up)
                    if r is not None:
                        try:
                            log.info("%s锛堝悜涓?1 灞?y=%d锛?r", why, r.center[1], r.nickname)
                        except Exception:
                            log.info("%s锛堝悜涓?1 灞忥級%r", why, r.nickname)
                        return r
                    snap = _s_up
                else:
                    log.debug("鍚戜笂鎺㈠睆鏃犱綅绉伙紙宸插湪椤堕儴锛夛紝缁х画鍘熸柟鍚?)
    except Exception as _e_up:
        log.debug("鍚戜笂鎺㈠睆澶辫触锛堢户缁悜涓嬬炕锛? %r", _e_up)

    for attempt in (0, 1):
        prev_sig = _list_sig(snap)
        moved = 0
        hit_bottom = False
        for i in range(max(0, pages)):
            if preempt and preempt():
                log.info("鍒楄〃缈诲睆閫斾腑妫€娴嬪埌鏂版秷鎭?鈫?鍋滄鏈疆瀹氫綅锛屼紭鍏堟柊娑堟伅")
                return None
            if not _swipe_list(actor, up=True):
                break
            moved += 1
            moved_total += 1
            try:
                snap = actor.snap()
            except Exception as e:
                log.warning("缈诲睆鍙栧睆澶辫触: %r", e)
                hit_bottom = True
                break
            if preempt and preempt():
                log.info("鍒楄〃缈诲睆鎷垮埌鏂板抚鍚庡彂鐜版柊娑堟伅 鈫?鍋滄鏈疆瀹氫綅锛屼紭鍏堟柊娑堟伅")
                return None
            if detect(snap) != "chatlist":
                hit_bottom = True
                break
            cur_sig = _list_sig(snap)
            if not cur_sig or cur_sig == prev_sig:
                log.info("鍒楄〃宸插埌搴曪紙绗?%d 灞忔棤鍙樺寲锛?, i + 1)
                hit_bottom = True
                break
            prev_sig = cur_sig
            r, why = _scan(snap)
            if r is not None:
                log.info("%s锛堢 %d 灞忥級%r", why, i + 2, r.nickname)
                return r
        if not hit_bottom or attempt == 1:
            break
        # 馃敶 2026-11-04锛堢幇缃?09:03 瀹炴祴锛夛細璧风偣涓嶅湪椤堕儴鏃跺悜涓嬬炕涓€灞忓氨銆屽埌搴曘€嶏紝
        #   鑰屽€欓€夋槸**鏈€鑰佸緟鍥炰紭鍏?*锛堢洰鏍囧線寰€鍦ㄥ垪琛ㄦ洿娣卞/鏇翠笂闈㈤兘鏈夛級锛?
        #   鐩存帴鏀惧純绛変簬鎶婅繖涓€杞簾鎺夈€傚埌搴?鈫?鍥為《鍐嶇炕涓€閬嶏紙鍙噸鏉ヤ竴娆★級銆?
        log.info("缈诲睆鍒板簳涓旀湭鍛戒腑 鈫?鍥炲垪琛ㄩ《閮ㄥ啀缈讳竴閬?)
        if not _scroll_top(actor, rounds=min(6, max(2, pages + 2)), preempt=preempt):
            break
        if preempt and preempt():
            log.info("鍥為《缈诲睆鏃舵娴嬪埌鏂版秷鎭?鈫?鍋滄鏈疆瀹氫綅锛屼紭鍏堟柊娑堟伅")
            return None
        try:
            snap = actor.snap()
        except Exception:
            break
        if detect(snap) != "chatlist":
            break

    if moved_total:
        log.info("缈诲畬 %d 灞忎粛鏈懡涓紙鏈潯 %r / 鍏抽敭璇?%r锛夆啋 杞悳绱?,
                 moved_total, (txt or "")[:10], (kw or "")[:10])
        # 馃敶 2026-11-04锛堝悶鍚愶級锛氳繖閲屽師鏉ヨ繕 _scroll_top 鏈€澶?4 娆?鈮?24s/浜恒€?
        #   鑰屼笅涓€杞紑澶存湰鏉ュ氨浼氬洖椤朵竴娆?鈬?绾氮璐广€傜暀鍦ㄥ師浣嶏紝涓嬩竴杞粺涓€鍥為《銆?
    return None


def handle_pending(actor, dev, db, max_n=MAX_N, dry_run=False, budget_s=60.0):
    """澶勭悊宸茶鏈洖銆傝繑鍥?dict(sent, tried, skipped, results, aborted)銆?""
    t_handle = time.time()
    # 馃敶 2026-11-08锛氭柊澧?"aborted" 鈥斺€?鍖哄垎銆屾甯告敹宸ャ€嶅拰銆岃澶囩骇鏁呴殰涓銆嶃€?
    #   "" = 姝ｅ父缁撴潫锛?not_chatlist" = 杩炵画澶氭鍥炰笉鍒?chatlist锛堣 NOT_CHATLIST_MAX锛夈€?
    #   daemon.py 浼氭秷璐瑰畠鎵撲竴鏉?warning锛屾柟渚垮湪鏃ュ織閲屼竴鐪煎垎杈ㄨ繖涓や欢浜嬨€?
    out = {"sent": 0, "tried": 0, "skipped": 0, "results": [], "aborted": ""}
    # 馃敶 2026-11-08锛氱啍鏂鏁版寜**杞?*閲嶇疆锛坙ead 鍙ｅ緞锛氥€屽悓涓€杞繛缁?N 娆°€嶏級銆?
    #   _NOT_CHATLIST_STREAK 鏄ā鍧楃骇锛堣法杞瓨娲伙級锛岃繖閲屾瘡杞紑澶存竻闆讹紝
    #   淇濊瘉銆岃繛缁?3 娆°€嶅垽瀹氱殑鏃堕棿绐椾笉璺ㄨ疆 鈥斺€?涓婁竴杞?2 娆?+ 鏈疆 1 娆?
    #   涓嶈鍑戞垚 3 娆¤鍒よ澶囨晠闅溿€傝疆鍐呮垚鍔熷洖涓€娆′篃浼氭竻闆讹紙瑙佷富寰幆锛夈€?
    _NOT_CHATLIST_STREAK[0] = 0
    # 璇煶 sid 闆嗗悎鎸夎疆閲嶇疆锛堝彧鏈嶅姟鏈疆鍊欓€夛紝瑙?_VOICE_SIDS 娉ㄩ噴锛夈€?
    _VOICE_SIDS.clear()
    # 馃敶 2026-11-08 12:56锛氭妸 device 寮曠敤鎸備笂锛屼緵 _device_live_uids 鍋氥€岃澶囧瓨娲绘牎楠屻€嶃€?
    #   candidates() 鍙嬁鍒?db锛屾嬁涓嶅埌 dev锛涜繖閲屾槸瀹冨敮涓€鑳芥嬁鍒?dev 鐨勫叆鍙ｃ€?
    _DEV_REF["dev"] = dev
    # 馃敶 2026-11-03锛堢敤鎴锋斁琛屄风Н鍘嬮檷绾э級锛氫竴娆″鍙栧嚑涓€欓€夛紝鐢ㄦ暟閲忓垽鏂Н鍘嬨€?
    #    绉帇 >=10 鏃讹細鍙蛋鍒楄〃鐩磋揪锛堣烦杩?11~15s/娆＄殑鎼滅储锛夈€佸崟杞渶澶氬洖 2 鏉°€?
    #    棰勭畻鏀惧鍒?130s銆傚惁鍒欓珮宄版湡姣忚疆 1 鏉°€?0s 涓€杞紝绉帇鍙細瓒婃粴瓒婂ぇ銆?
    cands = candidates(db, max(max_n, CAND_SCAN))
    backlog = len(cands)
    # 馃敶 2026-11-03锛堢敤鎴峰彛寰勶級锛氱Н鍘嬨€岃秴杩?5 鏉°€嶅氨杩涘叆闄嶇骇锛堟竻绾㈢偣浼樺厛銆佸皯鎼滅储锛夈€?
    degraded = backlog > 5
    # 馃敶 2026-11-04锛圥1 鍚炲悙锛夛細绉帇鍒嗕袱妗ｃ€傚師鏉ラ檷绾у悗 max_n = min(5, 6) = **5** 鏉★紝
    #   鑰岀Н鍘嬮暱鏈?40~60 涓€佸崟杞?200s 鈫?杩戒笉涓婃柊澧烇紙瀹炴祴 52 娆″鐞嗛噷 7 娆℃槸
    #   銆岄绠楃敤灏姐€嶆暎鐨勫満锛夈€?=30 鏃舵斁瀹藉埌 10 鏉?/ 300s銆?
    heavy = backlog >= 30
    if degraded:
        # 馃敶 2026-11-03 鎻愰珮鍚炲悙锛氬師鏉ラ檷绾у埌 2 鏉?杞紝鑰岀Н鍘?54 涓€?
        #   涓€杞?90~240s 鈫?姣忓皬鏃跺彧鍥?15~20 鏉★紝杩戒笉涓婃柊澧烇紝瓒婂爢瓒婂銆?
        #   鐜板湪 6 鏉?杞?+ 200s 棰勭畻锛圧OUND_BUDGET 600s 浠嶅厹寰椾綇锛夈€?
        max_n = max(max_n, 10 if heavy else 6)
        budget_s = max(budget_s, 300.0 if heavy else 200.0)
        # 馃敶 2026-11-03 淇紙鍥炲綊锛夛細鍘熸潵闄嶇骇浼氥€岃烦杩囨悳绱€嶏紝浣嗗垪琛ㄩ噷鐪嬩笉瑙佺殑浼氳瘽
        #    蹇呴』闈犳悳绱㈡墠鑳借繘 鈥斺€?涓€鏃︾Н鍘?鈮?0 灏辨案杩滆烦杩囷紝鍊欓€変汉姘歌繙鍥炰笉鍒帮紝
        #    绉帇姘歌繙 鈮?0锛屽舰鎴愭閿侊紙瀹炴祴 uid=*** 15:07 鐨勬秷鎭绌烘斁涓ゆ锛夈€?
        #    鐜板湪闄嶇骇**鍙檷鏉℃暟鍜岄绠楋紝涓嶇爫鎼滅储**銆?
        # 馃敶 2026-11-03 浜屾淇細鍊欓€夊凡鏀逛负**鏈€鑰佸緟鍥炰紭鍏?*锛堣 candidates锛夛紝
        #    杩欐湰韬氨鏄渶鍏钩鐨勬帓闃熸柟寮?鈥斺€?澶勭悊瀹屼竴涓彴璐﹀氨璺宠繃瀹冿紝鑷劧寰€鍚庤蛋銆?
        #    鍘熸潵鐨?_ROT 杞浆浼氭妸銆屾渶鑰佷紭鍏堛€嶆墦涔憋紝宸插幓鎺夈€?
        log.warning("宸茶鏈洖绉帇 %d 涓?鈫?闄嶇骇锛氬崟杞渶澶?%d 鏉°€侀绠?%.0fs锛堟悳绱繚鐣欙紝鏈€鑰佷紭鍏堬級",
                    backlog, max_n, budget_s)
    # 馃敶 2026-11-03锛氫笉鍐嶆妸鍊欓€夊厛鎴埌 max_n 鈥斺€?銆岄噸鏂板紑鍦恒€嶈鎸夎疆鎺у悕棰濄€?
    #   鍏堝垏鐗囩殑璇濓紝闃熼鍏ㄦ槸鑰佷細璇濇椂杩欎竴杞氨鍙仛鑰佷細璇濓紝鍒氬彂鏉ユ秷鎭殑娲讳汉缁х画绛夈€?
    #   鐜板湪鎵畬鏁村€欓€夎〃锛岄潬 restarts_done 璁℃暟鏀捐锛堣寰幆鍐咃級銆?
    if not cands:
        log.info("宸茶鏈洖锛氭病鏈夊€欓€?)
        return out

    # 馃敶 2026-11-04锛歠ind_row 浠?*褰撳墠灞?*寰€涓嬬炕锛岃捣鐐硅嫢鍋滃湪鍒楄〃涓棿锛?
    #   涓婇潰鐨勪汉杩欎竴杞叏閮界炕涓嶅埌锛?9:03 瀹炴祴銆岀 1 灞忔棤鍙樺寲銆嶏級銆?
    #   姣忚疆杩涘垪琛ㄥ墠鍥為《涓€娆★紙涓€娆℃€?~2-6s锛夛紝姣旀瘡涓€欓€夊悇鑷洖椤朵究瀹滃緱澶氥€?
    if FIND_PAGES > 0:
        try:
            from brain import nav as _nav
            _s0, _p0 = _nav.to_chatlist(actor)
            if _p0 == "chatlist":
                _scroll_top(actor, rounds=6)
        except Exception as _e:
            log.warning("杞鍥炲垪琛ㄩ《閮ㄥけ璐ワ紙缁х画锛? %r", _e)

    log.info("宸茶鏈洖锛?d 涓€欓€?, len(cands))
    try:
        from brain import ratelimit as _RL
        if not _RL.can_send():
            log.warning("鏈皬鏃跺彂閫佸凡杈句笂闄?鈫?鏈疆涓嶅仛宸茶鏈洖")
            return out
    except Exception:
        pass
    t_budget = time.monotonic()
    restarts_done = 0
    # 杩涘惊鐜墠娓呬竴娆″簱鍙樺寲淇″彿锛氳繖涓€杞墠闈紙娓呯孩鐐?鍥炲鑷繁鍐欑殑搴擄級鍙兘杩樻寕鐫€ dirty锛?
    # 涓嶆竻鎺夌殑璇濈涓€涓汉灏变細琚嚜宸卞垰鍐欑殑閭ｇ瑪鎷︿笅锛坵ake 閭ｈ竟韪╄繃鍚屾牱鐨勫潙锛夈€?
    try:
        from data import watch as _W0
        _W0.consume()
    except Exception:
        pass

    def _new_msg_urgent():
        try:
            from data import watch as _W
            return bool(_W.urgent())
        except Exception:
            return False

    for cand in cands:
        sid, to_uid, txt, her_ts = cand
        # A voice conversation already survived normal preemption twice in the
        # last few minutes. Once it starts locating, keep its bounded search
        # window atomic; otherwise steady traffic can starve it indefinitely.
        # New messages are still honored at the next candidate boundary.
        _cand_preempt = None if str(sid) in _VOICE_SIDS else _new_msg_urgent
        # 鈿?2026-11-04锛堢敤鎴峰彛寰勶細鏂版秷鎭笉鑳借绉帇鎸や綇锛夛細
        #   瀹炴祴 09:15:42 濂瑰彂 'hi '锛?9:17:46~09:23:07 涓€鐩村湪澶勭悊 4~144h 鐨勮€佸€欓€夛紝
        #   09:24:18 鎵嶅洖鍑哄幓 = **寤惰繜 8.6 鍒嗛挓**銆?
        #   杩欓噷涓€鏈夊簱鍙樺寲淇″彿灏辨敹宸ワ紝鎶婂睆骞曡缁欎笅涓€杞殑寮€澶达紙娓呯孩鐐?鈫?蹇矾寰勶級銆?
        try:
            from data import watch as _W
            if _new_msg_urgent():
                log.info("鈿?绉帇澶勭悊閫斾腑妫€娴嬪埌鏂版秷鎭?鈫?涓鏈疆绉帇锛屼紭鍏堝洖鍘诲鐞嗘柊娑堟伅")
                _W.consume()
                out["aborted"] = "preempted"
                break
        except Exception:
            pass
        # 馃敂 濂囬亣閾冩姠鍗犱竴鍒囷紙鐢ㄦ埛 2026-11-09 瀹氶摼锛氶搩 > 鏂版秷鎭?> 绾㈢偣 > 宸茶鏈洖锛夛細
        #   宸茶鏈洖澶勭悊閫斾腑閾冨脊鍑烘潵 鈫?灏卞湴澶勭悊瀹屽啀鏀跺伐锛堝榻?clear.py 鏃㈡湁鍋氭硶锛夈€?
        if not dry_run:
            try:
                from brain import bell as _BELL
                _snap_r = actor.snap(force=True)
                if _BELL.is_bell(_snap_r, dev=dev):
                    log.info("馃敂 宸茶鏈洖閫斾腑鏉ヤ簡濂囬亣閾?鈫?灏卞湴澶勭悊锛屼腑鏂湰杞?)
                    _ok, _why = _BELL.handle(actor, dev, dry_run=dry_run)
                    log.info("馃敂 閾冨鐞?ok=%s %s", _ok, _why)
                    break
                # 馃敶 2026-11-10 搂111锛堢敤鎴峰師璇濓級锛氥€屾竻鐞嗗凡璇绘湭鍥炵殑閫斾腑 鍙戝畬娑堟伅鍥炲埌鑱婂ぉ椤?
                #   濡傛灉妫€娴嬪埌绾㈢偣 閭ｅ氨浼樺厛澶勭悊绾㈢偣銆嶃€?
                #   澶嶇敤涓婇潰杩欏紶 snap锛堟湰鏉ュ氨瑕佷负閾冩鏌ユ媿涓€寮狅級锛岄浂棰濆 OCR 鎴愭湰銆?
                #   鍙湪銆屾湰杞凡鍥炶繃浜恒€嶆椂璁╀綅锛氫竴鏉℃病鍥炲氨涓柇浼氱┖杞紝浜ょ粰涓嬩竴杞孩鐐规銆?
                try:
                    from brain import clear as _CL
                    _bd_r = _CL.badge_chat(_snap_r)
                except Exception:
                    _bd_r = 0
                if _bd_r and int(out.get("sent", 0) or 0) > 0:
                    log.info("馃敶 宸茶鏈洖閫斾腑鑱婂ぉ瑙掓爣=%s 鈫?涓鏈疆锛屼紭鍏堝洖鍘绘竻绾㈢偣", _bd_r)
                    break
            except Exception as _e:
                log.debug("杞唴閾冩鏌ュ紓甯革紙缁х画宸茶鏈洖锛? %r", _e)
        _t_cand = time.monotonic()
        if out["sent"] >= max_n:
            break
        # 鐢ㄦ埛 2026-11-02锛氫竴鍒嗛挓鍐呮病杩涘睍灏辫繘涓嬩竴姝ワ紱宸茬粡鍥炶繃浜哄垯鍒伴绠楀氨鏀?
        used = time.monotonic() - t_budget
        if used > budget_s and out["sent"] > 0:
            log.info("宸茶鏈洖宸茬敤 %.0fs锛?%.0fs 棰勭畻锛夆啋 鍏堝仠锛屽墿涓嬬殑涓嬩竴杞?, used, budget_s)
            break
        if used > budget_s * 2:
            log.warning("宸茶鏈洖 %.0fs 涓€鏉￠兘娌″洖鎴?鈫?鏀跺伐锛堝紓甯革級", used)
            break
        # 馃敶 2026-11-03锛堢敤鎴峰畾 B 鏂规锛夛細鏂お涔?鈫?涓嶆帴鏃ц瘽锛屾敼閲嶆柊寮€鍦恒€?
        #   鍚嶉鎸夎疆鎺э細鑰佷細璇濓紙鍑犲崄涓級涓嶈兘鎶婅繖涓€杞殑棰濆害鍏ㄥ悆鎺夈€?
        age_h = (time.time() * 1000.0 - float(her_ts or 0)) / 3600000.0
        # 馃敶 2026-11-10 搂104 C3锛氶噸鏂板紑鍦虹敱鐘舵€佹満鍒わ紙age>=24h 涓旀湰鍥炲悎 0 鏉★級锛?
        #    涓嶈兘鍙湅 age 鈥斺€?鍚﹀垯 24~72h 涓€寰嬮噸寮€銆佸凡鍙戣繃鐨勪汉涔熼噸澶嶅紑鍦恒€?
        restart = bool(RESTART_H > 0 and age_h >= RESTART_H)
        try:
            from brain import sendgate as _SG4
            from brain import verdict as _VD4
            # 馃敶馃敶 2026-11-12锛圖S-05锛夛細琛ヤ紶 my_last_ts_ms锛堣涓婃柟娉ㄩ噴锛夈€?
            _rv = _SG4.state_of(str(sid), her_ts_ms=float(her_ts or 0), has_human=True,
                                my_last_ts_ms=_my_last_ts_ms(db, str(sid)))
            restart = (_rv.state == _VD4.PENDING_RESTART)
        except Exception as _e_rv:
            log.debug("閲嶅惎鐘舵€佹満寮傚父锛堟部鐢?age 鍒ゆ嵁锛? %r", _e_rv)
        if restart and restarts_done >= RESTART_PER_ROUND:
            log.info("璺宠繃鑰佷細璇?uid=%s锛堝ス鏈潯 %.0fh 鍓嶏級锛氭湰杞噸鏂板紑鍦哄悕棰?%d 宸茬敤瀹岋紝鍏堢暀缁欐柊娑堟伅",
                     to_uid, age_h, RESTART_PER_ROUND)
            continue
        # 馃敶馃敶 2026-11-10 23:3x锛堥€熷害 P0锛氳€佷細璇濇槸褰撳墠鏈€澶х殑绾氮璐癸級
        #   瀹炴祴 23:29:15 澶勭悊 69151915锛?0h 鍓嶏級锛氱炕 6 灞?30s 鏈懡涓?鈫?鎼滅储 32s 瓒呮椂
        #   = **62s / 浜?/ 0 鏀剁泭**锛岃€屼笖瀹冧笅涓€杞紙30 鍒嗛挓 nocue 鍐峰嵈鍒版湡锛夎繕浼氬啀鏉ヤ竴娆°€?
        #   23:32:12 鐨?498845877锛?3h锛夊悓鏍凤細6 灞?28s + 鎼滅储 32s銆?
        #   杩欑被浼氳瘽鐨勫叡鍚岀偣锛氬嚑鍗佸皬鏃跺墠锛屽垪琛ㄩ噷鏃╄椤跺埌鍗佸嚑灞忎箣澶栵紱Soul 鎼滅储
        #   鍙储寮曡繎鏈熻褰曪紝鎼滃ス閭ｅ彞 60h 鍓嶇殑璇濆繀瓒呮椂銆?*鏃犺缈昏繕鏄悳閮戒笉鍙兘鎴愬姛銆?*
        #   鐢ㄦ埛鍙ｅ緞鏄€屾秷鎭繀鍥?+ 閫熷害浼樺厛銆嶏細鎶婇绠楄姳鍦ㄥ繀璐ョ殑浼氳瘽涓婏紝
        #   绛変簬璁╃湡姝ｆ柊椴滅殑娑堟伅鎺掗槦绛夈€傛墍浠ワ細>48h 涓?*鏃犳樀绉?*锛堟棤鍞竴寮哄畾浣嶄俊鍙凤級
        #   鐩存帴鏀捐繃锛? 灏忔椂鍐峰嵈锛屼笉鍐嶇櫧鐑с€傛湁鏄电О鐨勪粛鐒舵斁琛岋紙鏄电О鏄彲闈犱俊鍙凤級銆?
        try:
            _nick_pre = nick_of(db, sid, to_uid)
        except Exception:
            _nick_pre = None
        kw = kw_of(db, sid, txt, skip_text=str(sid) in _VOICE_SIDS)

        # 馃敶馃敶 2026-11-10 23:38锛堥€熷害 P0路鏈€鐙犵殑涓€鏉★級
        #   瀹炴祴 23:36~23:38 杩炵画 5 涓€欓€夛紝鍏ㄦ槸銆岀函琛ㄦ儏鏈潯 + 鏃犳樀绉?+ 鍏抽敭璇?''銆嶏細
        #     281045688  '銆屾崅鑴稿摥銆? 47h  鈫?缈?6 灞?28s 鈫?鏄电О/鍐呭閮芥嬁涓嶅埌 鈫?鏀惧純
        #     414317126  '銆屽娣变簡銆?   45h  鈫?缈?6 灞?27s 鈫?鍚屼笂
        #     442658559  '銆屼腑鍗堝ソ銆?   36h  鈫?缈?6 灞?28s 鈫?鍚屼笂
        #     380724318  '銆屾櫄涓婂ソ銆?   28h  鈫?缈?6 灞?27s 鈫?鍚屼笂
        #     48554555   '鍝?         47h  鈫?缈?6 灞?27s 鈫?鍚屼笂
        #   鈬?涓€杞?140s銆? 鏀剁泭銆?
        #
        #   涓轰粈涔堝繀鐒舵槸 0锛氬畾浣嶅彧鏈変笁鏉¤矾 鈥斺€?鈶犳湯鏉℃枃鏈紙`[鎹傝劯鍝璢` 褰掍竴鍖栧悗 3 瀛楋紝
        #   杈句笉鍒板叏鍒楄〃灞?4 瀛楅棬妲涳紝涓旇繖绉嶈〃鎯呭嚑鍗佽閮芥湁锛夛紱鈶℃樀绉帮紙搴撻噷娌℃湁锛夛紱
        #   鈶㈠唴瀹瑰叧閿瘝锛坄kw_of` 杩斿洖 ''锛屽洜涓哄ス鏈€杩?8 鏉″叏鏄〃鎯?鍗曞瓧锛夈€?
        #   **涓夋潯璺叏鏂殑鎯呭喌涓嬶紝缈诲睆鍜屾悳绱㈤兘涓嶅彲鑳藉懡涓?*锛岀户缁仛鍙槸鐑ф椂闂淬€?
        #
        #   鍒ゆ嵁鍏ㄩ儴鏄函鍐呭瓨鍒ゆ柇锛坄_usable_word` 鍙仛闀垮害/瀛楃妫€鏌ワ級锛岄浂棰濆 SQL銆?
        #   涓嶈浼わ細濂瑰彧瑕佸巻鍙蹭笂璇磋繃涓€鍙?鈮? 瀛楃殑姝ｅ父璇濓紝`kw_of` 灏变細杩斿洖瀹冿紝杩欓噷涓嶆尅銆?
        if not _usable_word(_nick_pre, 2) and not _usable_word(kw, 5):
            log.info("鏃犳樀绉颁笖鏃犲彲鐢ㄥ唴瀹硅瘝锛堟湯鏉?%r锛?.0fh 鍓嶏級鈫?缈诲睆/鎼滅储閮戒笉鍙兘鏈夌粨鏋滐紝鐩存帴鏀捐繃 uid=%s",
                     (txt or "")[:10], age_h, to_uid)
            mark_skip(sid, txt, "nocue_hard", hours=6.0)
            out["skipped"] += 1
            continue

        if age_h >= 48.0 and not _usable_word(_nick_pre, 2):
            log.info("鑰佷細璇濓紙%.0fh锛変笖鏃犳樀绉?鈫?鐩存帴鏀捐繃锛屼笉缈诲睆涓嶆悳绱?uid=%s", age_h, to_uid)
            mark_skip(sid, txt, "stale_nocue", hours=6.0)
            out["skipped"] += 1
            continue

        out["tried"] += 1
        _used_nick = None      # 鎼滅储鑻ヨ蛋浜嗘樀绉帮紝杩涗細璇濆悗鐢ㄥ畠鍋氳韩浠芥牎楠?
        log.info("鈹€鈹€ 澶勭悊 %r锛堟湯鏉?%r锛?.0fh 鍓?s锛屽叧閿瘝 %r锛?, to_uid, txt[:14], age_h,
                 "路閲嶆柊寮€鍦? if restart else "", kw[:16])

        # 浠庡垪琛ㄨ繘锛氳兘鐩存帴鐪嬭灏辩洿鎺ョ偣琛岋紝鐪嬩笉瑙佹墠鍘绘悳绱?
        from brain import nav
        # 馃敶 2026-11-08锛圥0銆岀瀻鎿嶄綔銆嶆牴鍥犱慨澶?路 鍓嶇疆闂革級锛?
        #   鏀瑰墠锛歚if pg != "chatlist": break` 鈥斺€?鍥炰笉鍒板垪琛ㄥ氨浣滃簾鏁磋疆锛堣 NOT_CHATLIST_MAX 娉ㄩ噴锛夈€?
        #   涓轰粈涔堝繀椤诲湪**杩涘€欓€夊墠**鏂█椤甸潰鑰屼笉鏄け璐ュ悗琛ユ晳锛歀ead 瀹炴祴 20 娆¤繛缁?dump 鏈?
        #   **13 娆★紙65%锛?* `main_tab_msg` / `recycler_view` / `c_ct_chat_fragment_search`
        #   涓変釜鍏抽敭 res 鍏ㄩ儴缂哄け锛堥偅浜涚灛闂磋澶囨牴鏈笉鍦?chatlist锛宒aemon 鑷繁鍦ㄦ搷浣溿€?
        #   鍋滃湪 chat 椤垫垨杞満涓級銆傚嵆銆屽簳鏍忎笉瀛樺湪銆嶆槸杩炵画鎿嶄綔鏈熼棿鐨?*甯告€?*锛屼笉鏄伓鍙戙€?
        #   椤甸潰涓嶅鏃讹紝鍚庨潰 double_tap_tab 蹇呯劧銆屾湭鍛戒腑銆嶃€乷pen_search 蹇呯劧銆屾壘涓嶅埌鎼滅储鍏ュ彛銆?
        #   锛堝疄娴?72 娆℃湭鍛戒腑閲?71 娆′笅涓€琛屽氨鏄€屽綋鍓嶅睆娌℃湁鎼滅储鍏ュ彛銆嶏級銆?
        snap, pg = nav.to_chatlist(actor)
        if pg != "chatlist":
            # nav 鐨?unknown 鎭㈠姊瓙甯哥埇涓嶄笂鍘伙紙nav.py 鍐?stuck 浼氳鍚勫垎鏀竻闆讹級锛?
            # 杩欓噷缁欎竴娆°€宎m start 棣栭〉 + 鍐嶅彇鏍戙€嶇殑纭浣嶏紝浠嶄笉琛屾墠璁″叆杩炵画澶辫触銆?
            log.warning("鍥炰笉鍒板垪琛紙pg=%s锛夆啋 am start 棣栭〉纭浣嶅悗閲嶈瘯涓€娆?, pg)
            nav.goto_main(dev)
            snap, pg = nav.to_chatlist(actor)
        if pg != "chatlist":
            # 璁惧绾ф晠闅滅啍鏂細杩炵画澶氭澶嶄綅鏃犳晥 鈫?鏁磋疆鏀跺伐锛屽埆鍐嶉€愪釜鎺掗槦鎾炲銆?
            _NOT_CHATLIST_STREAK[0] += 1
            log.warning("纭浣嶅悗浠嶅洖涓嶅埌鍒楄〃锛坧g=%s锛夛紝杩炵画绗?%d 娆?,
                        pg, _NOT_CHATLIST_STREAK[0])
            if _NOT_CHATLIST_STREAK[0] >= NOT_CHATLIST_MAX:
                log.warning("杩炵画 %d 娆″洖涓嶅埌 chatlist 鈫?鍒ゅ畾璁惧绾ф晠闅滐紝鏈疆鎻愬墠鏀跺伐",
                            _NOT_CHATLIST_STREAK[0])
                out["aborted"] = "not_chatlist"
                break
            mark_skip(sid, txt, "not_chatlist", hours=0.034)
            out["skipped"] += 1
            continue          # 鈫?娉ㄦ剰锛歝ontinue 涓嶆槸 break锛屽彧璺宠繃杩欎釜浜?
        _NOT_CHATLIST_STREAK[0] = 0    # 鎴愬姛鍥炲埌 chatlist 鈫?椤甸潰鎭㈠浜嗭紝娓呴浂

        # 馃敶 2026-11-10锛堝繀鍥?P0锛夛細鎶婃樀绉颁竴璧蜂氦缁?find_row 鈥斺€?濂圭殑鏈潯鏄崟瀛?琛ㄦ儏鏃讹紝
        #   鏂囨湰鍖归厤缁撴瀯鎬уけ鏁堬紝鏄电О鎵嶆槸鍞竴绋冲畾鐨勫畾浣嶄俊鍙枫€?
        try:
            _nick_try = nick_of(db, sid, to_uid)
        except Exception as _e_nk:
            log.debug("鍙栨樀绉板け璐ワ紙閫€鍥炵函鏂囨湰瀹氫綅锛? %r", _e_nk)
            _nick_try = None
        # 馃敶 2026-11-10锛堝繀鍥烇級锛氶噸鏂板紑鍦虹殑浼氳瘽閮芥槸鍑犲崄灏忔椂鍓嶇殑鑰佷細璇濓紝鍒楄〃閲屾棭琚《鍒?
        #   鍗佸嚑灞忎箣澶?鈥斺€?榛樿 3 灞忔牴鏈涓嶅埌銆傚疄娴嬩竴涓?58h 鍓嶇殑浼氳瘽锛?
        #   缈?3 灞忚惤绌?鈫?璧版悳绱?34s 鈫?鎼滅储缁撴灉鍏ㄦ槸鍒汉 鈫?韬唤鏍￠獙杩炵画 4 娆″け璐?鈫?
        #   闀垮喎鍗?2h 鈫?杩欐潯**姘歌繙鍥炰笉浜?*銆傛繁缈?6 灞忓彧瑕?~12s锛屾瘮鎼滅储蹇竴鍊嶅锛?
        #   鑰屼笖涓嶄細瑙﹀彂 clear_text 鎶?App 椤跺洖妗岄潰銆?
        # 馃敶 2026-11-10 23:45锛堥€熷害锛夛細>=48h 鐨勪細璇濅笉缈诲睆銆?
        #   瀹炴祴 69151915锛?1h锛夎繛缁袱娆￠兘鏄€岀炕 6 灞?30s 鏈懡涓?鈫?鎼滅储 32s 瓒呮椂銆? 62s / 0 鏀剁泭銆?
        #   60 灏忔椂鍓嶇殑璇濆湪鍒楄〃鍗佸嚑灞忎箣澶栵紝缈诲睆姘歌繙澶熶笉鍒?鈥斺€?缈诲睆瀵瑰畠绾补鏄氮璐癸紝
        #   鎵€浠ョ洿鎺ヨ繘鎼滅储锛堜竴娆?32s锛夛紝澶辫触鍚?6 灏忔椂鍐峰嵈锛堣涓嬮潰鐨?_cool锛夈€?
        #   <48h 鐨勪粛鎸?restart 娣卞害缈伙紙24~48h 鐨勪細璇濆線寰€鍙椤朵笅鍘?3~6 灞忥紝缈诲緱鍒帮級銆?
        if age_h >= 48.0:
            _pg_n = 0
        elif restart:
            _pg_n = 6
        else:
            _pg_n = None
        # Voice rows often have no text/nickname in the DB. If we recovered a
        # nickname from logs, inspect a deeper list window before paying for a
        # likely-miss textual search. Recent sessions are usually near the top.
        if str(sid) in _VOICE_SIDS and age_h < 48.0:
            _pg_n = max(int(_pg_n or FIND_PAGES), 12)
        row = find_row(actor, txt, kw=kw, nick=_nick_try, db=db, sid=sid,
                       pages=_pg_n, preempt=_cand_preempt)
        if _cand_preempt is not None and _new_msg_urgent():
            out["aborted"] = "preempted"
            try:
                from data import watch as _Wp
                _Wp.consume()
            except Exception:
                pass
            break
        if row is None and age_h * 60.0 <= 30.0:
            # 馃敶 2026-11-08锛圥0 淇€岃韩浠芥牎楠屽け璐?261 娆°€嶇殑鏀惧ぇ鍣級锛?
            #   鏀瑰墠锛氭棤鏉′欢璧?first_dot_row 鈥斺€?瀹冩槸**璁捐涓婄殑銆屽厛鐐硅繘鍘诲啀楠岃韩浠姐€?*
            #   锛堣 first_dot_row docstring锛氥€岃繘閿欎汉涓嶄細涓插彴锛氳繘浼氳瘽鍚庤韩浠芥牎楠岀敤
            #   session 鎽樿瀵逛笉涓婂氨 fail-closed 涓嶅彂銆嶏級锛屾墍浠ュ畠鐐硅繘鍘荤殑閭ｄ竴鍒?
            #   鏈潵灏变笉鐭ラ亾鐐圭殑鏄皝锛岃繘閿欏繀鐒?fail-closed銆?
            #   鏃ュ織瀹炶瘉锛歚鏂版秷鎭枃鏈畾浣嶄笉鍒帮紙鏈潯 鈥︼級鈫?鐩存帴杩涚涓€涓孩鐐硅` 13 娆★紝
            #   姣忎竴娆￠兘浼氭妸璇?sid 鐨?_idfail 璁℃暟鎺ㄩ珮 1锛涜€岃鏁板張琚?
            #   `_prev_n = _IDFAIL[...]["n"]` 鐩存帴褰?skip 鐢紙瑙佷笅闈?enter_first 璋冪敤锛夛紝
            #   浜庢槸 skip 琚帹鍒扮 2/3/4 鏉℃悳绱㈢粨鏋?鈥斺€?瓒婅烦瓒婇敊锛屾伓鎬у惊鐜€?
            #   鐜板湪锛氬彧鏈夎 sid **鏈疆杩樻病 idfail 杩?*鏃舵墠鍚敤杩欎釜鍏滃簳锛?
            #   宸茬粡澶辫触杩囩殑浜ょ粰姝ｅ父鎼滅储璺緞锛堟寜 skip 渚濇璇曠粨鏋滐級锛屼笉鍐嶉潬鐩茬偣绾㈢偣琛屽姞鐮併€?
            _idn = int((_IDFAIL.get(_idfail_key(sid, txt)) or {}).get("n", 0))
            if _idn == 0:
                row = first_dot_row(actor)
                if row is not None:
                    log.info("鏂版秷鎭枃鏈畾浣嶄笉鍒帮紙鏈潯 %r锛夆啋 鐩存帴杩涚涓€涓孩鐐硅 %r",
                             txt[:10], row.nickname)
            else:
                log.info("璇ヤ細璇濆凡 idfail %d 娆?鈫?涓嶅啀璧扮孩鐐瑰厹搴曪紙閬垮厤鐩茬偣鍔犵爜锛屾敼璧版悳绱級",
                         _idn)
        if row is None:
            # 馃敶 2026-11-03锛堢敤鎴峰彛寰勶細銆屽爢绉?5 鍏堟竻褰撳墠灞忕孩鐐癸紝娓呭畬鍙屽嚮鑱婂ぉ缁х画娓咃紝
            #    灏介噺涓嶈蛋鎼滅储椤点€嶏級锛氬弻鍑昏亰澶?tab 浼氳烦鍒颁笅涓€涓湁绾㈢偣鐨勯敋鐐癸紝
            #    鐩爣浼氳瘽鑻ヨ繕鏈夋湭璇荤孩鐐瑰氨鑳界洿杈撅紝姣旀悳绱紙11~15s銆佺煭娑堟伅杩樻槗杩涢敊浜猴級蹇笖鍑嗐€?
            #    鍙瘯涓€娆°€乻ettle 鐭紝鎺ㄤ笉鍔ㄧ珛鍒昏浆鎼滅储锛岀粷涓嶇┖绛夈€?
            try:
                _snap2, _pg2 = actor.double_tap_tab("鑱婂ぉ", expect="chatlist", settle=1.0)
                if _pg2 == "chatlist":
                    # 鍙壂褰撳墠灞忥紙pages=0锛夛細鍙屽嚮璺宠繃鍘荤殑鏄€屾煇涓湁绾㈢偣鐨勮銆嶏紝
                    # 涓嶆槸鍒楄〃椤堕儴锛涘啀缈?3 灞忕瓑浜庢妸 24s 鐧界儳涓€閬嶏紙09:13 瀹炴祴缈讳簡涓よ疆锛夈€?
                    row = find_row(actor, txt, kw=kw, pages=0)
            except Exception as _e:
                log.warning("鍙屽嚮鎵捐寮傚父: %r", _e)
        if row is not None:
            log.info("鐩存帴鐐瑰垪琛ㄨ %r锛堜笉璧版悳绱級", row.nickname)
            remember_nick(sid, row.nickname)
            mark_before_enter(actor)      # 鏈蹇収锛堣繘浼氳瘽鍚庣敤瀹冨仛 sid 宸垎鏍￠獙锛?
            actor.hand.tap_node(row.node, settle=1.8)
            s2, pg2 = actor.wait_page(("chat",), timeout=6)
            # 馃敶 2026-11-03锛堢敤鎴风幇鍦哄彛寰勶級锛氱偣琛?*鏈夋椂鍙粰閫変腑鍙嶉銆佷笉璺宠浆**锛?
            #    銆岀户缁啀鐐逛竴娆″氨杩涘幓浜嗭紝浣嗕笉鏄瘡娆￠兘杩欐牱銆嶃€?
            #    鎼滅储缁撴灉琛岃蛋 enter_first 鐨勫惊鐜紝杩欓噷琛ュ悓鏍风殑锛氶噸鏂扮湅灞?鈫?閲嶆柊瀹氫綅 鈫?鍐嶇偣銆?
            for _try in range(2, 4):
                if pg2 == "chat":
                    break
                row2 = find_row(actor, txt, kw=kw, nick=_nick_try, db=db, sid=sid, pages=_pg_n)
                if row2 is None:
                    log.info("鍒楄〃閲屽凡鎵句笉鍒?%r锛堝彲鑳借椤朵笅鍘伙級鈫?鏀硅蛋鎼滅储", txt[:12])
                    break
                log.info("绗?%d 娆＄偣鍒楄〃琛屽悗浠嶆槸 %s 鈫?閲嶆柊瀹氫綅鍐嶇偣", _try, pg2)
                actor.hand.tap_node(row2.node, settle=1.8)
                s2, pg2 = actor.wait_page(("chat",), timeout=5)
        else:
            # 馃敶 2026-11-04锛圓鎵规彁閫熉风煭娑堟伅蹇純锛夛細鐭秷鎭?绾〃鎯?find_row 4 灞傝惤绌哄悗锛?
            #   璧版悳绱㈠ぇ姒傜巼銆屾湭鎵惧埌/姝т箟銆嶏紙瀹炴祴 18:41 涓€杞?9 鍊欓€夊彧鍥炴垚 1 涓紝8 涓?
            #   澶辫触鐧界儳 ~100s锛夈€傝繖绫荤洿鎺ョ煭鍐峰嵈锛屼笉娴垂 11~15s 鎼滅储銆?
            #   鎺掗櫎锛氶棶鍙ワ紙銆屽湪鍚椼€嶅緱鍥烇級銆侀噸鏂板紑鍦猴紙鏂お涔呰涓诲姩鑱旂郴锛夈€?
            _plain = re.sub(r"\[[^\]]{1,6}\]", "", txt or "").strip()
            _is_q = bool(re.search(r"[锛?鍚楀憿鍢沒", _plain))
            if len(_plain) < 4 and not _is_q and not restart:
                # 馃敶 2026-11-04锛堝繀鍥灺风煭娑堟伅涓嶅啀鐩存帴鏀惧純锛夛細鍘熸潵 find_row 鍙湅棣栧睆锛?
                #   鐭秷鎭嚑涔庡繀鐒惰惤绌?鈫?璁?short_msg 0.5h 鈫?鍒版湡鍚庡垪琛ㄤ綅缃病鍙樸€?
                #   杩樻槸鎵句笉鍒?鈫?杩欏彞**姘歌繙鍥炰笉浜?*锛堝疄娴?08:42:54 uid=***
                #   鏈潯銆屽惉涓嶆噦銆嶏紝鑷充粖 0 鍥炲锛夈€?
                #   鐜板湪 find_row 宸茬炕 3 灞忥紝鍛戒腑鐜囧ぇ骞呮彁楂橈紱浠嶈惤绌烘墠璧版悳绱紝
                #   鎼滅储鐢?kw锛堝ス鐨勫巻鍙查暱鍙ワ級鑰岄潪鐭枃鏈紝notfound 鎸?notfound 鍐峰嵈銆?
                _n2 = _norm(_nick_try or "")
                if len(_n2) < 2:
                    # 馃敶 2026-11-10锛堥€熷害锛夛細鍘熸潵杩欓噷鏃犳潯浠躲€屼粛灏濊瘯鎼滅储涓€娆°€嶏紝
                    #   鑰屾病鏈夋樀绉板彲鎼滄椂 open_search 瑕?40~50s 鎵惧叆鍙ｏ紝鍐嶇敤鍗曞瓧
                    #   鍘绘悳蹇呯劧 notfound 鈥斺€?绾櫧鐑с€傛棩蹇楀疄璇?22:57~22:58 杩炵画涓や汉
                    #   杩欐牱鐑ф帀 90s锛屼竴鏉℃病鍥炴垚銆傜幇鍦ㄧ洿鎺ョ煭鍐峰嵈锛岀暀缁欎笅涓€杞€?
                    log.info("鏈潯 %r 鐭秷鎭笖鏃犲彲鐢ㄦ樀绉?鈫?鏀惧純鏈疆锛堢渷 40s 鎼滅储锛塽id=%s",
                             txt[:12], to_uid)
                    mark_skip(sid, txt, "short_nocue", hours=SHORT_RETRY_H)
                    out["skipped"] += 1
                    continue
                log.info("鏈潯 %r 鐭秷鎭紝鏄电О %r 鍙敤 鈫?璧版樀绉版悳绱?, txt[:12], (_nick_try or "")[:10])
            # 馃敶 2026-11-04锛堝悶鍚愶級锛氬崟涓汉宸茬粡鑰楁帀 45s锛堢炕灞?21s + 鍙屽嚮 + dump锛夛紝
            #   鍐嶈蛋鎼滅储锛?~30s锛夊氨鎶婃暣杞悆鍏夈€傝 6 鍒嗛挓鍐峰嵈锛屼笅涓€杞啀鏉ャ€?
            _soft_s = 120.0 if str(sid) in _VOICE_SIDS else 45.0
            if time.monotonic() - _t_cand > _soft_s:
                log.info("杩欎釜浜哄凡鑰楁椂 %.0fs锛堜笂闄?%.0fs锛夆啋 鏈疆鏀捐繃锛? 鍒嗛挓鍚庡啀璇?uid=%s",
                         time.monotonic() - _t_cand, _soft_s, to_uid)
                mark_skip(sid, txt, "slow", hours=0.1)
                out["skipped"] += 1
                continue
            # 馃敶 2026-11-10 搂113锛堢敤鎴峰彛寰勶級锛氭悳绱笁绾?鈥斺€?鏄电О 鈫?鐙竴鏃犱簩鍐呭 鈫?鏀惧純
            #   鍏堝湪**寮€鎼滅储椤典箣鍓?*绠楄鍒掞細open_search 璧版參璺緞瑕?40~50s锛?
            #   娌℃湁鍙悳绾跨储灏辫鐩存帴璺宠繃锛屼笉鑳藉厛鎶婅繖 40s 鐑ф帀鍐嶆斁寮冦€?
            _plan = _search_plan(
                db, sid, to_uid, kw,
                direct_text=(txt if str(sid) in _VOICE_SIDS else ""))
            if not _plan:
                log.info("鏄电О鍜岀嫭涓€鏃犱簩鍐呭閮芥嬁涓嶅埌 鈫?鏀惧純鏈疆 uid=%s锛堢瓑濂瑰彂鏂版秷鎭啀璇曪級",
                         to_uid)
                mark_skip(sid, txt, "nocue", hours=NO_CUE_H)
                out["skipped"] += 1
                continue
            if not S.open_search(actor, preempt=_cand_preempt):
                if getattr(S, "LAST_REASON", "") == "preempted":
                    out["aborted"] = "preempted"
                    try:
                        from data import watch as _Wp0
                        _Wp0.consume()
                    except Exception:
                        pass
                    try:
                        S.leave(actor)
                    except Exception:
                        pass
                    break
                out["skipped"] += 1
                continue
            if _cand_preempt is not None and _new_msg_urgent():
                out["aborted"] = "preempted"
                try:
                    from data import watch as _Wp1
                    _Wp1.consume()
                except Exception:
                    pass
                S.leave(actor)
                break
            _got = 0
            for _label, _word in _plan:
                log.info("鎼滅储[%s] %r", _label, _word[:16])
                _got = S.search(actor, dev, _word, preempt=_cand_preempt)
                if _got < 0:
                    out["aborted"] = "preempted"
                    try:
                        from data import watch as _Wp2
                        _Wp2.consume()
                    except Exception:
                        pass
                    S.leave(actor)
                    break
                if _got:
                    if _label == "鏄电О":
                        _used_nick = _word
                        remember_nick(sid, _word)
                    break
                # 鐔旀柇/瓒呮椂閮芥槸**閫氶亾**闂锛岃窡鍏抽敭璇嶆棤鍏?鈫?鎹㈢浜屼釜璇嶄篃鏁戜笉鍥炴潵銆?
                # 馃敶 2026-11-10锛堥€熷害锛夛細鍘熸潵鍙尅 breaker锛宼imeout 杩樿鍐嶇儳涓€涓瘝
                #   锛堝疄娴?22:56:17 鎼滅储[鏄电О] 瓒呮椂 30s 鈫?22:56:49 鍙堟悳鍐呭 7s = 43s/浜猴級銆?
                if getattr(S, "LAST_REASON", "") in ("breaker", "timeout"):
                    break
            if out.get("aborted") == "preempted":
                break
            if not _got:
                # 馃敶馃敶 2026-11-08 13:1x锛坄breaker` 蹇呴』鍗曠嫭涓€鏀紝鍚﹀垯姣斿師 bug 鏇寸碂锛?
                #
                #   `search.py` 鐜板湪鐔旀柇鏃╅€€浼氳 `LAST_REASON="breaker"`锛堜互鍓嶈璁?timeout锛夈€?
                #   浣嗗鏋滆繖閲屽彧鍒?timeout銆佸叾浣欏叏钀借繘 else锛宍breaker` 灏变細琚綋鎴?
                #   **notfound 鈫?缃?3 灏忔椂鍐峰嵈** 鈥斺€?姣斿師鏉ャ€岃璁拌秴鏃剁綒 10 鍒嗛挓銆嶄弗閲嶅緱澶氾細
                #   鐔旀柇鏄?*鍏ㄥ眬閫氶亾**鐘舵€侊紝璺熻繖涓汉鐨勫叧閿瘝姣棤鍏崇郴锛?
                #   鎷垮畠鍘绘儵缃氬崟涓細璇濈瓑浜庛€屽洜涓轰粖澶╀笅闆紝鎵€浠ヨ繖涓汉 3 灏忔椂涓嶈鍥炪€嶃€?
                #   瀹炴祴浠ｄ环锛?65 娆＄啍鏂棭閫€锛岃嫢鍚勭綒 3h锛屾秹鍙婄殑浜烘暣娈垫椂闂村叏鐏€?
                #
                #   鈬?breaker 鍗曠嫭澶勭悊锛氫笉璁颁换浣曚汉鐨勫彴璐︼紙閫氶亾闂涓嶅綊浜猴級锛?
                #     鍙妸鏈疆杩欎釜鍊欓€夋斁杩囷紝涓嬩竴杞啍鏂粨鏉熷悗鑷劧浼氶噸璇曘€?
                _why = getattr(S, "LAST_REASON", "")
                if _why == "breaker":
                    log.info("鎼滅储閫氶亾鐔旀柇涓紙涓嶆槸杩欎釜浜虹殑闂锛夆啋 涓嶈鍙拌处銆佷笅杞啀璇?uid=%s", to_uid)
                    S.leave(actor)
                    out["skipped"] += 1
                    continue
                # 馃敶 2026-11-10 23:45锛?=48h 鐨勮€佷細璇濇悳绱㈠け璐ュ悗鍐?6 灏忔椂銆?
                #   鍘熸潵缁熶竴 10 鍒嗛挓 鈥斺€?鑰?60h 鍓嶇殑浼氳瘽姣?10 鍒嗛挓鍥炴潵鍐嶇儳 32s锛?
                #   瀹炴祴 69151915 涓€鏅氳閲嶈瘯 4 娆?= 128s 鍏ㄥ簾銆傝€佷細璇濇湰鏉ュ氨鎼滀笉鍒?
                #   锛圫oul 鍙储寮曡繎鏈熻褰曪級锛屽喎鍗存媺闀夸笉褰卞搷鎴愬姛鐜囷紝鍙槸涓嶅啀绌鸿浆銆?
                _cool = 6.0 if age_h >= 48.0 else TIMEOUT_RETRY_H
                if _why == "timeout":
                    # 瓒呮椂 鈮?鎼滀笉鍒帮細缃氫竴娈垫椂闂村啀璇曪紝缁濅笉 12 灏忔椂鎷夐粦锛堥偅绛変簬涓嶅洖濂癸級
                    log.info("鎼滅储瓒呮椂锛堟湭鍒ゅ畾鏈壘鍒帮級锛?.0f 鍒嗛挓鍚庡啀璇?, _cool * 60)
                    mark_skip(sid, txt, "timeout", hours=_cool)
                else:
                    # 馃敶 2026-11-09 R3锛堢敤鎴锋媿鏉裤€屾悳绱笉鍒板氨涓嶆悳浜嗗晩 绛夐棽涓嬫潵鐨勬椂鍊欐悳銆嶏級
                    #   鏃э細notfound 缃?3 灏忔椂 + 鏂版秷鎭?10 鍒嗛挓銆傝〃鐜颁负銆屾秷鎭繘鏉ュ緢涔呮病浜哄洖銆嶏紝
                    #   瀹炴祴 21:08 浠嶆湁浼氳瘽鍓?89 鍒嗛挓鍐峰喕缁撱€傚喕缁撴儵缃氭湰灏变笉璇ョ敤鍦ㄨ繖涓汉韬笂銆?
                    #   鏂帮細鏈疆涓嶆悳 鈫?5 鍒嗛挓鍚庯紙闂茬潃鏃讹級鑷劧閲嶈瘯锛?0 鍒嗛挓鍐呮挒澧?鈮? 娆℃墠鍗囩骇 30 鍒嗛挓銆?
                    _nf = _nf_hits(sid)
                    if _nf >= NOTFOUND_STORM_N:
                        log.warning("鎼滅储鏃犵粨鏋滅疮璁?%d 娆?30min 鈫?鍗囩骇 %.0f 鍒嗛挓鍐峰嵈锛堥槻鐧界儳锛塻id=%s",
                                    _nf, NOTFOUND_STORM_H * 60, sid)
                        mark_skip(sid, txt, "notfound_storm", hours=NOTFOUND_STORM_H)
                    else:
                        _cool2 = 6.0 if age_h >= 48.0 else NOTFOUND_COOL_H
                        log.info("鎼滅储鏃犵粨鏋滐紙绗?%d 娆?30min锛夆啋 %.0f 鍒嗛挓鍚庨噸璇曪紝涓嶅喕缁?3 灏忔椂 sid=%s",
                                 _nf, _cool2 * 60, sid)
                        mark_skip(sid, txt, "notfound", hours=_cool2)
                S.leave(actor)
                out["skipped"] += 1
                continue
            # 馃敶 2026-11-04锛堝繀鍥為棴鐜級锛氭寜璇ヤ細璇?*鍘嗗彶澶辫触娆℃暟**渚濇鐐圭 2銆? 鏉℃悳绱㈢粨鏋溿€?
            #   鍘熸潵 enter_first 姘歌繙鐐圭涓€鏉?鈫?鐩爣浜轰笉鍦ㄧ涓€鏉℃椂姝诲惊鐜け璐?
            #   锛堝疄娴嬨€岄偅涓嶇煡閬撱€嶃€孾鐙楀瓙]銆嶅悇澶辫触 8 娆°€佹案杩滃洖涓嶄簡锛夈€?
            try:
                _prev_n = int((_IDFAIL.get(_idfail_key(sid, txt)) or {}).get("n", 0))
            except Exception:
                _prev_n = 0
            mark_before_enter(actor)      # 鏈蹇収锛堝悓涓婏級
            s2, pg2 = S.enter_first(actor, skip=_prev_n)

        if pg2 != "chat":
            log.info("娌¤繘浼氳瘽锛?s锛夛紝璁板彴璐﹀悗璺宠繃", pg2)
            mark_skip(sid, txt, "enter_fail", hours=ENTER_RETRY_H)
            if row is None:
                S.leave(actor)
            out["skipped"] += 1
            continue

        # 鐢ㄦ埛 2026-11-02锛氭悳绱?璺宠浆閮戒笉瑕佺偣澶揩锛岄〉闈㈣繕娌″姞杞藉畬灏辨搷浣滀細澶辫触
        time.sleep(1.5)

        # 馃敶 2026-11-03 淇 P1锛堥槻閿欏彂锛夛細鍒楄〃/鎼滅储瀹氫綅鍙兘杩涢敊浼氳瘽锛?
        #    鍙戜箣鍓嶅厛鏍￠獙褰撳墠浼氳瘽韬唤 == 鍊欓€?sid锛屼笉纭灏变笉鍙戯紙鍙戦敊浜?= 楂樺嵄锛夈€?
        #    馃敶 2026-11-03 涓変慨锛堟琛€路鐢ㄦ埛鎷嶆澘锛夛細鍘熸潵鐨勩€岃繛缁?2 娆″け璐ュ悗闄嶇骇鍙?
        #    閫氱敤瀹夊叏鍙ャ€? 鍦ㄣ€屾棤娉曠‘璁よ繖鏄皝銆嶇殑鏃跺埢鍙戜换浣曡瘽閮芥槸璧岋紝瀹炴祴涓插彴
        #    锛?9:21 鎶娿€屽湪鍛紝鍒氱湅鍒颁綘璇寸殑銆嶅彂缁欎簡涓嶇浉骞茬殑銆庢悶绗戞憜鐑傜粨鍚堛€忥級锛?
        #    涓斿浐瀹氬畨鍏ㄥ彞鍑犲崄涓細璇濋兘鏈?鈫?鍙嶆薄鏌?kw_of 鍏抽敭璇?鈫?瀹氫綅閿欎汉銆?
        #    鏀逛负 fail-closed锛氳韩浠戒笉鏄庝竴寰嬩笉鍙戦€侊紝璁板彴璐︾煭鍐峰嵈涓嬭疆閲嶈瘯銆?
        _nick_hint = getattr(row, "nickname", None) if row is not None else None
        if _nick_hint is None:
            _nick_hint = _used_nick      # 璧版樀绉版悳杩涙潵鐨勶紝鐢ㄥ悓涓€涓樀绉伴獙鏍囬
        if not _session_matches(actor, db, sid, nick=_nick_hint):
            # 璁℃暟**钀界洏**锛堥噸鍚笉娓呴浂锛夆€斺€?瑙?IDFAIL_FILE 娉ㄩ噴銆?
            _n = _idfail_bump(sid, txt)
            if _n >= IDFAIL_MAX_TRIES:
                # 馃敶 2026-11-04锛堝繀鍥為棴鐜风啍鏂級锛氭悳绱㈢粨鏋滃凡缁忛€愭潯璇曡繃锛堢 2/3 鏉￠兘鐐硅繃锛?
                #   杩樻槸璁や笉鍑烘潵 鈫?璇存槑杩欎釜 sid 鍦ㄥ綋鍓嶇晫闈笂纭疄瀹氫綅涓嶅埌锛堜細璇濊椤朵笅鍘?
                #   鎼滅储缁撴灉鍙湁鍒殑浜猴級銆傜户缁?2 鍒嗛挓涓€娆￠噸璇曞彧鏄櫧鐑?15~20s/娆★紝
                #   涓?*姘歌繙鍥炰笉浜?*銆傛敼闀垮喎鍗达紝绛夊ス鍙戞柊娑堟伅锛堟湯鏉″彉浜嗭級鑷姩閲嶆柊缁欐満浼氥€?
                log.warning("韬唤鏍￠獙杩炵画 %d 娆″け璐ワ紙鎼滅储缁撴灉閮借瘯杩囷級鈫?闀垮喎鍗?%.1fh锛?
                            "绛夊ス鍙戞柊娑堟伅鍐嶈瘯", _n, IDFAIL_GIVEUP_H)
                mark_skip(sid, txt, "id_mismatch_giveup", hours=IDFAIL_GIVEUP_H)
                # 璁℃暟褰掗浂锛?h 鍚庨噸璇曟椂浠庣 1 鏉＄粨鏋滈噸鏂拌瘯涓€杞紙浼氳瘽椤哄簭/鏂版秷鎭細鍙橈級锛?
                # 鍚﹀垯 skip 浼氫竴鐩村仠鍦ㄧ 4銆? 鏉★紝姘歌繙璇曚笉鍒版纭殑閭ｆ潯銆?
                _idfail_clear(sid, txt)
            else:
                log.warning("韬唤鏍￠獙澶辫触锛堢 %d 娆★紝娑堟伅 %r锛夆啋 涓嶅彂閫侊紝闃蹭覆鍙?
                            "锛坒ail-closed锛夛紝涓嬫璇曠 %d 鏉℃悳绱㈢粨鏋?,
                            _n, txt[:12], _n + 1)
                # 2min 鍐峰嵈锛氭瘡娆￠噸璇曢兘瑕侀噸鎼?11s + 杩涗細璇濓紝澶煭鐧界儳锛涘お闀垮ス绛夊お涔呫€?
                mark_skip(sid, txt, "id_mismatch", hours=0.034)
            actor.hand.back(settle=1.5)
            if row is None:
                S.leave(actor)
            out["skipped"] += 1
            continue
        _idfail_clear(sid, txt)

        # 馃敶 2026-11-10 搂104锛氬彂閫侀椄 鈥斺€?鍏堥棶銆岃繖涓細璇濈幇鍦ㄨ兘鍙戝嚑鏉°€嶏紝鍐嶆寜棰濆害鍑鸿瘽銆?
        #    搂6.6-2锛欰DAPT_CAP=2 涓€杞袱鍙ュ氨浼氭妸 24h 鐨?2 鏉￠搴︾敤鍏夛紝
        #    鎵€浠?n_cand 蹇呴』琚椄瑁佽繃锛涘彂閫佹垚鍔熷悗鎸夌湡瀹炴潯鏁拌璐︼紙涓嶇瓑搴?pull锛夈€?
        _gate_n = 0
        try:
            from brain import sendgate as _SG5
            _gate = _SG5.allow(str(sid), 99, her_ts_ms=float(her_ts or 0), has_human=True)
            if not _gate.ok:
                log.info("璺熻繘闃舵鎷︽埅 sid=%s state=%s锛?s锛夆啋 鏈疆涓嶅洖",
                         sid, _gate.state, _gate.reason)
                out["skipped"] += 1
                time.sleep(2.0)
                actor.hand.back(settle=1.5)
                if row is None:
                    S.leave(actor)
                continue
            _gate_n = _gate.n
        except Exception as _e_gate:
            log.debug("鍙戦€侀椄寮傚父锛堥檷绾ф寜鍘熻涓猴級: %r", _e_gate)
            _gate_n = 0

        # 鍑鸿瘽锛堢敤搴撻噷鐨勭湡瀹炲巻鍙诧級
        if restart:
            # 馃敶 鐢ㄦ埛 2026-11-03 瀹?B 鏂规锛氬ス閭ｆ潯宸茬粡 %.0fh 鍓嶏紝**涓嶅綋鎺ヨ瘽澶勭悊**銆?
            #   涓嶅杺 hist锛堟棫瀵硅瘽锛夈€佷笉鍠傚ス閭ｆ潯锛堝杺浜嗘ā鍨嬪氨浼氬幓绛斻€屽棷銆嶏級锛?
            #   鐢卞紩鎿庛€岄噸鏂板紑鍦恒€嶆ā寮忓嚭涓€鍙ユ柊鐢卞ご锛屽彧鍙戜竴鏉°€?
            log.info("濂规湯鏉″凡 %.0fh锛?%.0fh锛夆啋 涓嶆帴鏃ц瘽锛岃蛋閲嶆柊寮€鍦?, age_h, RESTART_H)
            hist = []
            lines = R.generate(sid, "", hist=[], n_cand=1, restart_h=age_h)
        else:
            msgs = db.messages(sid, limit=12)
            hist = R.build_hist(msgs, db.uid)
            # 鐢ㄦ埛 2026-11-02锛氬ス杩欎竴鍙ュ彲鑳芥槸鍑犲彞 鈫?鍏堝彇濂硅繛鍙戯紱鍥炲涔熷彲浠ュ鏉°€?
            from brain.flow import her_burst
            burst = her_burst(db, sid, db.uid)
            if not burst:
                burst = [txt]
            feed = R.merge_burst(burst)
            # 鍚屼笂锛氬ス鐨勬湯鏉″彲鑳藉彧鍦?session 鎽樿閲岋紝琛ヨ繘鍘嗗彶鏈熬
            hist = R.hist_with_her(hist, feed)
            # 鏉℃暟鎸夊ス鏈€鍚庝竴鏉＄畻锛堝悎骞跺悗鎬婚暱浼氭拺澶?target_n锛岃 flow.py 鍚屽娉ㄩ噴锛?
            n = R.target_n([burst[-1]] if burst else [txt], hist)
            if _gate_n:
                n = max(1, min(n, _gate_n))
            lines = R.generate(sid, feed, hist=hist, n_cand=n)
        if not lines:
            # 馃敶 蹇呭洖閾佸緥锛氬凡璇绘湭鍥炲悓鏍锋槸銆屽ス璇磋繃璇濄€嶏紝寮曟搸缁欎笉鍑鸿瘽涔熷繀椤诲洖涓€鍙ワ紝
            #    涓嶈兘鍥犱负鐢熸垚澶辫触灏遍潤榛樿烦杩囷紙flow.py 閲屽悓鏍峰鐞嗭級
            from brain.flow import fallback_line
            lines = [fallback_line()]
            log.warning("鍑鸿瘽澶辫触 鈫?鐢ㄥ厹搴曡瘽鏈?%r", lines[0])
        if _gate_n and len(lines) > _gate_n:
            lines = lines[:_gate_n]
            log.info("鍙戦€侀椄瑁佸壀锛氭湰杞渶澶氬彂 %d 鏉★紙棰濆害锛?, _gate_n)

        if dry_run:
            log.info("[dry] 浼氬洖 %d 鏉? %r", len(lines), lines)
        else:
            # 馃敶 2026-11-04锛堟彁閫燂級锛氳繖閲屽師鏉ュ啀 dump 涓€娆＄‘璁ゅ湪 chat 椤?鈥斺€?浣?
            #   `_session_matches()` 鍒氱敤銆屾湭璇绘竻闆跺樊鍒?/ 浼氳瘽鍐呮皵娉°€嶇‘璁よ繃褰撳墠
            #   浼氳瘽韬唤锛堥€氳繃鐨勭灛闂村繀鐒跺湪 chat 椤碉級锛屼箣鍚庡彧鏈夊簱璇诲啓涓庢ā鍨嬭皟鐢紝
            #   娌℃湁浠讳綍 UI 鍔ㄤ綔 鈫?杩欐 dump(3~4s) 绾噸澶嶃€?
            #   瀹夊叏缃戜粛鍦細鐪熶笉鍦?chat 椤垫椂 type_and_verify 鎵句笉鍒拌緭鍏ユ浼氱洿鎺ュけ璐ワ紝
            #   涓嶄細鎶婅瘽鐏岃繘鎼滅储妗嗐€?
            inp = Input(dev)
            sent_n = 0
            for i, r in enumerate(lines):
                if i:
                    time.sleep(1.6)
                ok, got = inp.type_and_verify(r, actor)
                if not ok:
                    log.warning("绗?d鏉＄亴瀛楀け璐ワ紙%r锛?, i + 1, got)
                    inp.clear()
                    break
                # settle 1.2(脳slow_factor 2.5=3s) -> 0.25锛氱揣璺熺殑 sent_ok 閲?
                # sleep(0.7)+dump(3s) 宸茬粡鍦ㄧ瓑锛岄噸澶嶇瓑寰呯函娴垂銆?
                if not inp.tap_send(actor, settle=0.25):
                    log.warning("绗?d鏉℃壘涓嶅埌鍙戦€佹寜閽?, i + 1)
                    inp.clear()
                    break
                # 馃敶 2026-11-04 淇紙闂幆锛夛細**鍏堝仛涓夋€佺‘璁わ紝鍐嶈璐?*銆?
                #   鏃х増銆宼ap_send 鎴愬姛灏辩珛鍗宠璐︺€嶆妸銆岃緭鍏ユ杩樻湁娈嬬暀鏂囨湰 = 鏄庣‘娌″彂鍑哄幓銆?
                #   涔熻鎴愬凡鍥?鈫?姘镐笉閲嶈瘯 = 姘镐箙婕忓洖锛堣繚鑳屽繀鍥為搧寰嬶級銆?
                #   鐜板湪鍖哄垎锛歳esidual=纭疄娌″彂 鈫?涓嶈璐︺€佷笅杞噸璇曪紱
                #             ok/unknown=纭娓呯┖鎴栬涓嶅埌杞満甯?鈫?鎸夊凡鍙戣璐︼紙闃查噸澶嶅彂閫侊級銆?
                _ok = inp.sent_ok(actor, r, timeout=4)
                _why = getattr(inp, "last_reason", "") or ""
                if (not _ok) and _why == "residual":
                    log.warning("绗?d鏉＄‘璁ゆ湭鍙戝嚭锛堣緭鍏ユ浠嶆湁鍐呭锛夆啋 涓嶈璐︼紝涓嬭疆閲嶈瘯", i + 1)
                    inp.clear()
                    break
                _mark_replied(to_uid, sid=sid, text=txt)
                sent_n += 1
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
                if not _ok:
                    log.warning("绗?d鏉″彂閫佺‘璁よ涓嶅埌杈撳叆妗嗭紙鎸夊凡鍙戝嚭璁拌处锛屼笉鍐嶉噸鍙戯級", i + 1)
                log.info("鉁?宸插洖(%d/%d) uid=%s: %r", i + 1, len(lines), to_uid, r)

            if sent_n:
                # 馃敶 搂104锛氭寜**瀹為檯鍙戝嚭鏉℃暟**钀借处锛屼笉绛夊疄鏃跺簱 pull锛? 鍒嗛挓寤惰繜浼氶噸澶嶅彂锛夈€?
                try:
                    from brain import sendgate as _SG6
                    _SG6.note_sent(str(sid), sent_n)
                except Exception as _e_ns:
                    log.warning("璺熻繘鍙拌处璁拌处澶辫触 sid=%s: %r", sid, _e_ns)
                out["sent"] += 1
                if restart:
                    restarts_done += 1
                _idfail_clear(sid, txt)     # 宸插洖锛屾竻鎺夎韩浠芥牎楠屽け璐ヨ鏁?
                # 馃摑 2026-11-03锛堢敤鎴峰彛寰勶級锛氬彂鍑哄幓鐨勬秷鎭?*涓嶅啓鏈湴搴?L2**锛岀瓑瀹炴椂搴?
                #   锛坕m_data.db 鐨?pull 鍚屾锛夎嚜鐒跺嚭鐜般€傚師鏉ヤ富鍔?append_l2_once 鐨勫壇浣滅敤锛?
                #   鍥哄畾瀹夊叏鍙?鎴戠殑寮€鍦虹櫧鍐欒繘 L2 鍚庤 kw_of 褰撴垚鍏抽敭璇?鈫?鍑犲崄涓細璇濋兘鏈?
                #   鈫?瀹氫綅閿欎汉 鈫?涓插彴銆傞槻閲嶅宸茬敱 `_mark_replied` 鍙拌处 + 搴撴湯鏉?sender
                #   鍙岄噸瑕嗙洊锛堣 tap_send 鍚庣珛鍗宠璐︼級锛屼笉鍐嶉渶瑕?L2 杩欎唤鏈湴缂撳瓨銆?
                backed = CP.ensure_profile(actor, sid, db)
                if backed:
                    log.info("  宸茶ˉ寤轰釜浜轰富椤垫。妗?)
            else:
                out["skipped"] += 1

        # 鍙戦€佸悗闈欓粯 2s 鍐嶉€€鍑猴紙鐢ㄦ埛锛氶〉闈㈡病鍔犺浇瀹屽氨鐐逛細鍑洪敊锛?
        time.sleep(2.0)
        actor.hand.back(settle=1.5)
        if row is None:          # 鍙湁璧版悳绱㈣繘鏉ョ殑鎵嶉渶瑕侀€€鎼滅储灞?
            S.leave(actor)
        time.sleep(0.6)

    log.info("宸茶鏈洖缁撴潫锛氬洖 %d 鏉?/ 璇?%d / 璺宠繃 %d",
             out["sent"], out["tried"], out["skipped"])
    MET.emit(
        "pending_end",
        elapsed_s=round(time.time() - t_handle, 3),
        sent=int(out["sent"]),
        tried=int(out["tried"]),
        skipped=int(out["skipped"]),
        aborted=str(out.get("aborted") or ""),
        uid=str(getattr(db, "uid", "") or ""),
        dry_run=bool(dry_run),
    )
    return out
