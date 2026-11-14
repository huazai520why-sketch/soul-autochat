# -*- coding: utf-8 -*-
"""鍙戦€侀椄锛氭墍鏈夈€屽疄闄呭彂鍑烘秷鎭€嶇殑璺緞鍦ㄥ彂閫佸墠蹇呰繃杩欓噷锛坥bs 搂104 搂6.5锛夈€?

缁熶竴鍙ｅ緞锛氫竴涓細璇濊兘鍙戝嚑鏉★紝鍙敱 ``brain.verdict.state_of`` 鍒ゅ畾锛?
鍙戦€佹垚鍔熷悗蹇呴』鐢辫皟鐢ㄦ柟璋?``note_sent(sid, 瀹為檯鏉℃暟)`` 钀借处锛?
鍚﹀垯 2/6 鏉￠搴︿細琚郴缁熸€у嚮绌裤€?

涓€閿洖婊氾細``SOUL_FOLLOWUP_ON=0`` 鏃跺叏鏀捐涓斾笉钀借处锛?
鐢熶骇鍑轰换浣曞紓甯稿彲绔嬪埢閫€鍥炴敼閫犲墠琛屼负锛屼笉鐢?revert 浠ｇ爜銆?
"""
import os
import time
from dataclasses import dataclass
from typing import Optional

from brain import verdict as V
from core.log import get_logger
from data import reply_state as RS

log = get_logger("brain.sendgate")

ON = (os.environ.get("SOUL_FOLLOWUP_ON", "1") or "1") != "0"


@dataclass(frozen=True)
class Decision:
    """鍙戦€侀椄瑁佸喅銆?

    Attributes:
        ok: 鏄惁鍏佽鍙戦€併€?
        n: 鍏佽鍙戝嚭鐨勬潯鏁帮紙宸叉寜棰濆害鎴柇锛夈€?
        state: verdict 鍏。鐘舵€併€?
        reason: 鎺掗殰璇存槑銆?
    """

    ok: bool
    n: int
    state: str
    reason: str


def allow(
    sid: str,
    n_lines: int = 1,
    *,
    her_ts_ms: Optional[float] = None,
    my_last_ts_ms: float = 0.0,
    has_human: bool = True,
    now: Optional[float] = None,
) -> Decision:
    """鍙戦€佸墠闂竴娆★細杩欎釜浼氳瘽鐜板湪鑳藉彂鍑犳潯銆?

    Args:
        sid: 浼氳瘽 id銆傜┖涓?= 鏃犱富浼氳瘽锛堝閬囬搩 / 鍖归厤寮€鍦虹櫧绛夋柊浼氳瘽锛夛紝
            涓嶅睘浜庛€岃窡杩涜€佸弸銆嶏紝鐩存帴鏀捐涓斾笉绾冲叆棰濆害锛堣 搂6.5 澶囨敞锛夈€?
        n_lines: 鏈鎵撶畻鍙戠殑鏉℃暟銆?
        her_ts_ms: 濂规湯鏉＄湡浜烘秷鎭椂闂达紙姣锛夛紱鏈夊€兼椂椤哄甫鏇存柊姘翠綅绾裤€?
        my_last_ts_ms: 鎴戞柟鏈潯鏃堕棿锛堟绉掞級锛岀敤浜?awaiting 鍒ゅ畾銆?
        has_human: 鏄惁鏈夌湡浜烘秷鎭紱绯荤粺鍗′紶 False銆?
        now: 鍥炴斁娴嬭瘯鐢ㄥ浐瀹氬綋鍓嶆椂闂达紙绉掞級銆?

    Returns:
        Decision(ok, n, state, reason)銆備换浣曞紓甯搁兘闄嶇骇涓烘斁琛岋紝
        缁濅笉璁╁彴璐?鐘舵€佹満鎶娿€屽繀鍥炪€嶉摼璺帎姝汇€?
    """
    if not ON:
        return Decision(True, max(1, int(n_lines)), "off", "SOUL_FOLLOWUP_ON=0 宸插叧闂樁姊?)
    if not sid:
        return Decision(True, max(1, int(n_lines)), "unbound", "鏃犱富浼氳瘽锛堝紑鍦虹櫧锛夛紝涓嶇撼鍏ヨ窡杩涢搴?)
    try:
        if RS.is_archived(sid):
            return Decision(False, 0, V.ARCHIVED, "宸插綊妗ｏ紙C4锛夛紝涓嶅洖澶嶄笉鍞ら啋")
        if her_ts_ms and float(her_ts_ms) > 0:
            RS.on_her(sid, float(her_ts_ms), human=has_human)
        rec = RS.get(sid)
        _her = float(rec.get("her_ts_ms") or 0) or float(her_ts_ms or 0)
        _sends = rec.get("sends") or []
        if _her <= 0:
            # 馃敶 涓嶄吉閫?her_ts 钀界洏锛氬彴璐︽病鏈夌湡浜烘秷鎭椂闂存埑鏃讹紝
            #    鐢ㄦ湰鍥炲悎鏈€鏃╀竴鏉″彂閫佹椂鍒讳綔璧风偣锛堜竴鏉￠兘娌″彂鍒欑敤褰撳墠鏃跺埢锛夈€?
            #    杩欐牱 note_sent 鍐欏叆鐨?sends 浠嶈兘琚?state_of 姝ｇ‘褰掑睘锛岄搴︿笉浼氬け鏁堛€?
            _her = (min(_sends) if _sends else float(now if now is not None else time.time())) * 1000.0
            log.info("鍙戦€侀椄 sid=%s 鏃犵湡瀹炴按浣嶇嚎 鈫?鎸?sends 璧风偣瑁佸喅锛堜笉钀界洏銆佷笉姹℃煋鍙拌处锛?, sid)
        v = V.state_of(
            sid=sid,
            her_ts_ms=_her,
            sends=rec.get("sends") or [],
            now=now,
            my_last_ts_ms=my_last_ts_ms,
            # has_human 鐢辫皟鐢ㄦ柟鐢?eyes.sysmsg 鍒よ繃锛涘彴璐﹂噷鐨?sys_only 鍙槸鍘嗗彶鏍囪锛?
            # 涓嶈兘鍙嶈繃鏉ユ妸銆屽ス鍒氳鐨勭湡浜鸿瘽銆嶅垽鎴?no_human锛堜細婕忓洖锛夈€?
            has_human=has_human,
            n_lines=n_lines,
        )
        ok = v.allowed > 0
        log.info("鍙戦€侀椄 sid=%s state=%s 鍏佽 %d/%d 鏉?锝?%s",
                 sid, v.state, v.allowed, n_lines, v.reason)
        return Decision(ok, v.allowed, v.state, v.reason)
    except Exception as e:
        log.warning("鍙戦€侀椄寮傚父锛堥檷绾ф斁琛岋紝涓嶉樆鏂繀鍥烇級sid=%s: %r", sid, e)
        return Decision(True, max(1, int(n_lines)), "error", "闄嶇骇鏀捐: %r" % (e,))


def note_sent(sid: str, n: int = 1) -> None:
    """鍙戦€佹垚鍔熷悗璁拌处锛堟寜鐪熷疄鏉℃暟锛屼笉鎸夎疆娆★級銆?""
    if not ON or not sid:
        return
    try:
        RS.note_sent(sid, n)
    except Exception as e:
        log.warning("璁拌处澶辫触 sid=%s n=%d: %r", sid, n, e)


def on_her(sid: str, her_ts_ms: float, human: bool = True) -> None:
    """濂规潵娑堟伅鏃舵帹杩涙按浣嶇嚎锛涚郴缁熸秷鎭紶 human=False锛圕5/C8锛夈€?""
    if not ON or not sid:
        return
    try:
        RS.on_her(sid, her_ts_ms, human=human)
    except Exception as e:
        log.warning("姘翠綅绾挎洿鏂板け璐?sid=%s: %r", sid, e)


def is_archived(sid: str) -> bool:
    """鍊欓€夐摼/鍞ら啋閾惧叡鐢細鏄惁宸茶褰掓。銆?""
    if not ON or not sid:
        return False
    try:
        return RS.is_archived(sid)
    except Exception:
        return False


def archived_sids():
    """鍏ㄩ噺褰掓。 sid锛堜緵 candidates 涓€娆℃€ф帓闄わ級銆?""
    if not ON:
        return []
    try:
        return RS.archived_sids()
    except Exception:
        return []


def state_of(sid: str, **kw):
    """缁?data.pending.summary() 鐨勫洓妗剁粺璁＄敤锛氳繑鍥?Verdict銆?""
    if not sid:
        return V.state_of(has_human=False)
    try:
        rec = RS.get(sid)
        return V.state_of(
            sid=sid,
            her_ts_ms=float(rec.get("her_ts_ms") or kw.get("her_ts_ms") or 0),
            sends=rec.get("sends") or [],
            now=kw.get("now"),
            my_last_ts_ms=kw.get("my_last_ts_ms") or 0.0,
            has_human=kw.get("has_human", True),
            n_lines=kw.get("n_lines", 1),
        )
    except Exception:
        return V.Verdict(V.PENDING, 0.0, 0, 0,
                         max(1, int(kw.get("n_lines", 1))), V.CAP_24H,
                         "鍙拌处寮傚父 鈫?闄嶇骇鏀捐锛堝繀鍥炰紭鍏堬級")


__all__ = ["ON", "Decision", "allow", "note_sent", "on_her",
           "is_archived", "archived_sids", "state_of"]
