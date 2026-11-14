# -*- coding: utf-8 -*-
"""鎵嬶細鐏屽瓧涓庡彂閫併€傚彧鎵ц鍔ㄤ綔锛屼笉鍋氬垽鏂€?
瀹炴祴锛?026-11-02锛?00x1600锛寀2 3.7.1锛夛細
- 杈撳叆妗?res=et_sendmessage b=(118,1501,658,1561)锛岀┖鏃舵樉绀?placeholder銆屾枃鏄庤亰澶╋紝鍙嬪杽浜ゅ弸~銆?- u2 `send_keys()` 鍘熺敓鏀寔涓枃锛屾棤闇€鍒囪闊?鏂囧瓧妯″紡銆佹棤闇€绗笁鏂硅緭鍏ユ硶
- **鍙戦€佹寜閽亴瀛楀悗鎵嶅嚭鐜?*锛歳es=btn_send b=(750,1495,878,1567) text='鍙戦€?
  鍚屾椂杈撳叆妗嗗彸杈圭晫浠?658 鏀剁缉鍒?594
- 娓呯┖鍚?placeholder 鍥炴潵

鏃ф灦鏋勶紙soul_send._input锛夐偅濂椼€屽厛鍒囪闊虫ā寮忊啋鐐归敭鐩樺浘鏍団啋鍐嶇亴瀛椼€嶇殑浠紡锛?鍦ㄦ湰鐜涓嶉渶瑕?鈥斺€?鐩存帴鐐规 + send_keys 鍗虫垚鍔熴€?"""
import time

from core.log import get_logger

log = get_logger("hands.input")

BOX_RES = "et_sendmessage"
SEND_RES = "btn_send"
PLACEHOLDER = "鏂囨槑鑱婂ぉ锛屽弸鍠勪氦鍙媬"


class Input(object):
    def __init__(self, device):
        self.dev = device
        self._d = None
        self._snap = None      # 鏈€杩戜竴娆＄亴瀛楀悗鐨勫揩鐓э細tap_send 澶嶇敤锛岀渷涓€娆?dump
        # 馃敶 2026-11-04锛歚sent_ok` 鐨勪笁鎬佺粨璁猴紙"ok"/"unknown"/"residual"锛夛紝
        #   涓婂眰鎹鍖哄垎銆屾棤娉曠‘璁わ紙鎸夊凡鍙戣璐︼級銆嶅拰銆屾槑纭病鍙戯紙涓嶈璐︺€侀噸璇曪級銆嶃€?        self.last_reason = ""

    @property
    def d(self):
        if self._d is None:
            self._d = self.dev.u2()
        return self._d

    # ---------- 璇?----------
    @staticmethod
    def box(snap):
        return snap.find_one(res=BOX_RES)

    @staticmethod
    def box_text(snap):
        n = Input.box(snap)
        if n is None:
            return None
        t = (n.text or "").strip()
        return "" if t == PLACEHOLDER else t

    # ---------- 鍐?----------
    def _reset(self):
        """u2 鎺夌嚎鏃堕噸缃繛鎺ワ紙涓嬫 self.d 浼氶噸鏂板彇鏂拌繛鎺ワ級銆?""
        try:
            self.dev.reset_u2()
        except Exception:
            pass
        self._d = None

    def clear(self):
        try:
            self.d.clear_text()
        except Exception as e:
            # 馃敶 2026-11-03 淇 P2锛氬師鏉ュ彧鎵撴棩蹇椾笉閲嶈繛锛屽悗缁户缁敤澶辨晥杩炴帴銆?            log.warning("clear_text 寮傚父: %r 鈫?閲嶇疆 u2 閲嶈瘯", e)
            self._reset()
            try:
                self.d.clear_text()
            except Exception as e2:
                log.warning("clear_text 閲嶈瘯浠嶅け璐? %r", e2)

    def type_text(self, text, settle=1.0):
        """鐏屽瓧銆傝繑鍥?True/False锛堜互杈撳叆妗嗗疄闄呮枃鏈负鍑嗭紝涓嶇湅杩斿洖鍊硷級銆?""
        try:
            self.d.send_keys(text)
        except Exception as e:
            # 馃敶 2026-11-03 淇 P2锛氬師鏉ュ彧鎵撴棩蹇楄繑鍥?False锛岃繛鎺ヤ繚鎸佸け鏁堬紝
            #    鍚庣画 type_and_verify 閲嶈瘯涔熸墦鍚屼竴澶辨晥杩炴帴銆?            log.warning("send_keys 寮傚父: %r 鈫?閲嶇疆 u2 閲嶈瘯", e)
            self._reset()
            try:
                self.d.send_keys(text)
            except Exception as e2:
                log.warning("send_keys 閲嶈瘯浠嶅け璐? %r", e2)
                return False
        if settle:
            time.sleep(settle)
        return True

    def type_and_verify(self, text, actor, tries=2):
        """鐐规 -> 娓呯┖ -> 鐏屽瓧 -> 鐢?UI 鏍戦獙璇併€傝繑鍥?(ok, 瀹為檯鏂囨湰)銆?
        馃敶 鎻愰€燂紙2026-11-02锛夛細楠岃瘉鐢ㄧ殑杩欎唤蹇収**鍚屾椂缂撳瓨涓嬫潵缁?tap_send 鐢?*銆?        瀹炴祴璁惧鍗℃椂鍗曟 dump 瑕?2~4s锛屽師鏉ョ亴瀛楅獙涓€娆°€佹壘鍙戦€佹寜閽啀涓€娆°€?        鍙戦€佸悗鍐嶈疆璇竴娆?= 3 娆?dump 鈮?6~12s/浜猴紝鍏ㄧ▼涓€鍗婃椂闂磋€楀湪杩欍€?        """
        for i in range(tries):
            snap = actor.snap()
            n = self.box(snap)
            if n is None:
                log.warning("绗?d娆★細鎵句笉鍒拌緭鍏ユ", i + 1)
                return False, None
            # 馃敶 2026-11-12锛團-04锛夛細棣栬疆涔熷繀椤诲厛娓呯┖銆傚師鏉ラ杞彧 tap 涓?clear锛?            #   鑻ユ鍐呮湁娈嬬暀锛宻end_keys 浼?*杩藉姞**鑰岄潪鏇挎崲锛屾牎楠岀敤瀛愪覆鍒ゅ畾浠嶉€氳繃 鈫?            #   鍙戝嚭銆屾畫鐣?鏂版枃鏈€嶇殑鎷兼帴娑堟伅銆傜幇鍦ㄦ瘡杞紙鍚杞級閮藉厛 clear銆?            actor.hand.tap_node(n, settle=0.7)
            self.clear()
            time.sleep(0.3)
            self.type_text(text, settle=0.9)
            snap2 = actor.snap()
            got = self.box_text(snap2)
            if got and text.strip() in got:
                self._snap = snap2          # 缁?tap_send 澶嶇敤
                return True, got
            log.warning("绗?d娆＄亴瀛楁湭钀藉湴锛氭湡鏈?%r 瀹為檯 %r", i + 1, text, got)
        return False, self.box_text(actor.snap())

    def tap_send(self, actor, settle=1.2, snap=None):
        """鐐瑰彂閫佹寜閽€傝繑鍥?True/False銆?
        浼樺厛鐢?type_and_verify 缂撳瓨鐨勫揩鐓э紙閲岄潰宸茬粡鏈?btn_send锛夛紝
        缂撳瓨娌℃湁鎵嶅幓閲嶆柊 dump銆?        馃敶 2026-11-10锛堟紨绀哄疄寮瑰彂鐜帮級锛歜tn_send 鏄亴瀛楀悗鎵嶇敱 App 娓叉煋鍑烘潵鐨勶紝
          璁惧璐熻浇楂樻椂娓叉煋浼氭櫄浜庝袱娆?dump锛堢紦瀛?force 閲嶆壘鍏ㄧ┖锛夆啋 璇垽澶辫触銆?          瀹炲脊鏍锋湰锛?3:17:16 绛変竴鏉熷厜 / 13:18:01 骞哥绾﹀畾锛屼袱娆?dump 鍧囨棤鎸夐挳銆?          淇锛氭壘涓嶅埌鏃剁瓑 0.8s 绗笁娆?dump锛堢粰娓叉煋涓€甯ф満浼氾級锛涗粛澶辫触鍒欒
          杈撳叆妗嗗尯鍒嗐€屽瓧杩樺湪锛堟覆鏌撴參锛夈€嶄笌銆屽瓧琚悆锛堟槑纭け璐ワ級銆嶅苟鎵撹繘鏃ュ織銆?        """
        s = snap or self._snap or actor.snap()
        btn = s.hit(res=SEND_RES)
        if btn is None:
            s = actor.snap(force=True)
            btn = s.hit(res=SEND_RES)
        if btn is None:
            time.sleep(0.8)
            s = actor.snap(force=True)
            btn = s.hit(res=SEND_RES)
        if btn is None:
            got = self.box_text(s)
            log.warning("鎵句笉鍒板彂閫佹寜閽紙涓夋 dump 鍧囨棤锛涜緭鍏ユ鏂囨湰=%r锛?, got)
            return False
        log.info("鐐瑰彂閫?%s", btn.bounds)
        actor.hand.tap_node(btn, settle=settle)
        self._snap = None
        return True

    def sent_ok(self, actor, text, timeout=4.0):
        """鍙戦€佸悗鏍￠獙锛?*鍙湁纭杈撳叆妗嗗凡娓呯┖锛坧laceholder 鍥炴潵锛夋墠绠楁垚鍔?*銆?
        馃敶 2026-11-03 淇 P0锛堥潤榛樻紡鍙戯級锛?          `box_text()` 鍦ㄦ壘涓嶅埌杈撳叆妗嗘椂杩斿洖 None锛屾棫鍐欐硶 `if not got` 鎶?None
          褰撴垚"宸叉竻绌?鈫?椤甸潰璺宠蛋/琚脊绐楅伄鎸?鏍戜负绌烘椂锛屾秷鎭牴鏈病鍙戝嚭鍘伙紝
          涓婂眰鍗磋銆屽凡鍙戦€併€嶅苟鍐?L2銆佽 24h 鍞ら啋鍙拌处锛屾案涓嶉噸璇曘€?        涓夋€佽涔夛細
          ""   杈撳叆妗嗗湪涓斿凡娓呯┖ 鈫?鎴愬姛
          None 鎵句笉鍒拌緭鍏ユ锛屾棤娉曠‘璁?鈫?鎸?*澶辫触**澶勭悊锛堝繀鍥炰紭鍏堬紝涓嬭疆閲嶈瘯锛?          闈炵┖ 杩樻湁娈嬬暀鏂囨湰 鈫?澶辫触

        馃敶 2026-11-04锛堥棴鐜慨澶嶏級锛氭妸涓夋€佺粨璁哄啓杩?`self.last_reason`锛岃涓婂眰鑳藉尯鍒?          "ok"       纭宸叉竻绌?= 纭疄鍙戝嚭鍘?          "unknown"  鎵句笉鍒拌緭鍏ユ = 鏃犳硶纭锛堝ぇ姒傜巼宸插彂锛屼笂灞傛寜宸插彂璁拌处闃查噸澶嶅彂閫侊級
          "residual" 杈撳叆妗嗚繕鏈夊瓧 = **鏄庣‘娌″彂鍑哄幓**锛堜笂灞傚繀椤讳笉璁拌处銆佷笅杞噸璇曪級
        涔嬪墠涓婂眰鍙綋甯冨皵鐢?鈫?銆岃緭鍏ユ杩樻湁瀛?鐪熸病鍙戙€嶄篃琚鎴愬凡鍥?= 姘镐箙婕忓洖銆?        """
        self.last_reason = "unknown"
        time.sleep(0.7)
        got = self.box_text(actor.snap(force=True))
        if got == "":
            self.last_reason = "ok"
            return True
        if got is None:
            # 鍐嶇粰涓€甯ф満浼氾細鍙戦€佺灛闂寸殑杞満甯у父甯歌涓嶅埌杈撳叆妗?            time.sleep(0.8)
            got = self.box_text(actor.snap(force=True))
            if got == "":
                self.last_reason = "ok"
                return True
            if got is None:
                log.warning("鍙戦€佹牎楠岋細鎵句笉鍒拌緭鍏ユ锛屾棤娉曠‘璁ゆ槸鍚﹀彂鍑?鈫?鎸夋湭鍙戝嚭澶勭悊")
                self.last_reason = "unknown"
                return False
        self.last_reason = "residual"
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.6)
            if self.box_text(actor.snap(force=True)) == "":
                self.last_reason = "ok"
                return True
        return False
