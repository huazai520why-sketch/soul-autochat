# -*- coding: utf-8 -*-
"""鍏ㄥ眬閿侊細淇濊瘉鍚屼竴鏃跺埢鍙湁涓€涓?daemon 鍦ㄦ搷浣滄ā鎷熷櫒銆?
瀵瑰簲鏃ф灦鏋?`guard/soul_global_lock.py` 鐨勬牳蹇冨垽鎹紙淇濈暀涓夋潯锛屽幓鎺夎皟搴﹀鏉傚害锛夛細

  鈶?鎸侀攣 pid 宸叉        鈫?绔嬪嵆鎺ョ锛堟棫鏋舵瀯鏈€甯歌鐨勪汉宸ラ噸鍚悗瀛ゅ効閿侊級
  鈶?蹇冭烦瓒呰繃 HEARTBEAT_S 鈫?鎺ョ锛堣繘绋嬫椿鐫€浣嗗崱姝伙級
  鈶?TTL 鍒版湡             鈫?鎺ョ

鏃ф灦鏋勯噷韪╄繃鐨勫潙锛堣繖閲屼竴骞惰閬匡級锛?  - **鍙崲 pid 涓嶅垹閿?*锛歭ive_push 杞噸鍚悗鏃ц繘绋嬮€€鍑烘病鍒犻攣锛屾柊杩涚▼璇诲埌"娲婚攣
    涓?owner 鍦ㄨ繍琛?鈫?涓€鐩寸瓑锛岀┖杞?2.5~15 鍒嗛挓銆傛墍浠ヨ繖閲屾瘡娆?start_round 鍓?    閮?*鍏堝垽 owner 鏄惁鐪熸椿鐫€**锛屾浜嗙珛鍒绘帴绠″苟鎵撳嵃鎺ョ鍘熷洜銆?  - **鎶婂埆浜虹殑蹇冭烦鍒锋垚鑷繁鐨?*锛氬彧鏈夌湡鎷垮埌閿佹墠 touch锛屾病鎷垮埌缁濅笉鍐欐枃浠躲€?
鐢ㄦ硶锛?    from guard import lock
    ok, why = lock.acquire("daemon")
    if ok:
        try:
            lock.touch("pull")
            ...
        finally:
            lock.release()
"""
import json
import os
import socket
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("guard.lock")

LOCK_FILE = STATE / "daemon.lock"
HEARTBEAT_S = 15 * 60        # 蹇冭烦瓒呰繃 15 鍒嗛挓 -> 鍒ゆ
TTL_S = 55 * 60              # 閿佹渶闀?55 鍒嗛挓锛堥槻鍍靛案锛?STEP_HANG_S = 8 * 60         # 鍚屼竴姝ラ瓒呰繃 8 鍒嗛挓 -> 鍒ゅ崱姝?
_held = False
_pid = os.getpid()


# ---------------- 杩涚▼瀛樻椿 ----------------
def _alive(pid):
    if not pid:
        return False
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid == _pid:
        return True
    if os.name == "nt":
        # Windows锛氬厛鐢?OpenProcess 鎺㈡祴锛堝揩銆佷笉闄愭潈闄愶級
        try:
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
        except Exception:
            pass
        # 馃敶 2026-11-03 淇 P0锛堝畧鎶ら噸澶嶆媺璧凤級锛氳鍒掍换鍔￠噷鐨?watchdog 璺戝湪
        #    session 1锛岃€?WMI 浠?SSH 璧风殑 daemon 鍦?session 0 鈥斺€?璺ㄤ細璇濇椂
        #    OpenProcess 鍙兘杩斿洖绌哄彞鏌勶紝鎶?*娲昏繘绋嬪垽姝?* 鈫?clear_stale 鍒犻攣 鈫?        #    鍐嶆媺涓€涓?daemon锛堝疄娴?14:44 鍑虹幇 8752/16108 鍙屽疄渚嬶級銆?        #    tasklist 鏄法浼氳瘽鍙鐨勶紝鐢ㄥ畠鍏滃簳纭銆?        try:
            import subprocess
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                               capture_output=True, timeout=10)
            txt = (r.stdout or b"").decode("gbk", "ignore") + \
                  (r.stderr or b"").decode("gbk", "ignore")
            if str(pid) in txt:
                return True
        except Exception:
            pass
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


# ---------------- 鏂囦欢 ----------------
def _read():
    try:
        return json.loads(LOCK_FILE.read_text("utf-8"))
    except Exception:
        return {}


def _write(d):
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        return True
    except Exception as e:
        log.warning("鍐欓攣澶辫触: %r", e)
        return False


def _atomic_create(d):
    """鍘熷瓙鍒涘缓閿佹枃浠讹紙O_EXCL锛夛紝宸插瓨鍦ㄥ垯澶辫触銆傝繑鍥?True/False銆?
    馃敶 2026-11-03 淇 P2锛歛cquire 鍘熸潵銆宻tatus() 璇荤┖ + write_text 鍐欓攣銆嶄袱姝?    闈炲師瀛愶紝涓や釜 daemon 鍚屾椂鍚姩鍙兘閮借鍒扮┖閿併€佸厛鍚庤鐩栥€佸弻鍙屾寔閿佽繍琛屻€?    O_EXCL 鍒涘缓淇濊瘉鍚屼竴鏃跺埢鍙湁涓€涓繘绋嬭兘鍒涘缓鎴愬姛銆?    """
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except Exception as e:
        log.warning("鍒涘缓閿佹枃浠跺け璐? %r", e)
        return False
    try:
        os.write(fd, json.dumps(d, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def status():
    """杩斿洖 (鏄惁琚埆鐨勮繘绋嬫寔鏈? 閿佷俊鎭?銆?""
    if not LOCK_FILE.exists():
        return False, {}
    d = _read()
    if not d:
        return False, {"why": "閿佹枃浠朵负绌烘垨鎹熷潖"}
    pid = d.get("pid")
    ts = float(d.get("ts") or 0)
    age = time.time() - ts
    if pid == _pid:
        return False, d
    if not _alive(pid):
        return False, dict(d, why="owner %s 宸叉" % pid)
    if age > HEARTBEAT_S:
        return False, dict(d, why="蹇冭烦 %.0fs 瓒呮椂" % age)
    if age > TTL_S:
        return False, dict(d, why="TTL 鍒版湡")
    return True, d


# ---------------- 瀵瑰 ----------------
def acquire(owner="daemon"):
    """鎶㈤攣銆傝繑鍥?(ok, why)銆俹k=True 鏃舵湰杩涚▼鎸侀攣銆?
    馃敶 2026-11-03 淇 P2锛氬師鏉ャ€宻tatus() 鍒ょ┖ + _write 鍐欓攣銆嶄袱姝ラ潪鍘熷瓙锛?    涓や釜 daemon 鍚屾椂鍚姩鍙兘閮借鍒扮┖閿併€佸厛鍚庤鐩栥€佸弻鍙岃繘鍏ヨ繍琛屻€?    鏀逛负 O_EXCL 鍘熷瓙鍒涘缓閿佹枃浠讹細鍙湁涓€涓繘绋嬭兘鍒涘缓鎴愬姛锛涙閿佹帴绠″厛鍘熷瓙鎼蛋鏃ч攣銆?    """
    global _held
    if _held:
        return True, "宸叉寔鏈?
    busy, info = status()
    if busy:
        return False, "琚?pid=%s 鍗犵敤锛?s锛? % (info.get("pid"), info.get("step") or "?")

    now = time.time()
    why = info.get("why")
    # 姝婚攣鎺ョ锛坥wner 姝?/ 蹇冭烦瓒呮椂 / TTL 鍒版湡锛夛細鍏堝師瀛愭惉璧版棫閿侊紝鍐嶅師瀛愬垱寤烘柊閿併€?    # os.replace 鍘熷瓙閲嶅懡鍚嶏紝涓や釜杩涚▼绔炰簤鎺ョ鏃跺彧鏈変竴涓兘鎴愬姛鎼蛋銆?    if why and LOCK_FILE.exists():
        try:
            bak = LOCK_FILE.with_name(LOCK_FILE.name + ".bak-%d-%d" % (int(time.time()), _pid))
            os.replace(str(LOCK_FILE), str(bak))
        except FileNotFoundError:
            pass            # 鍒汉宸叉惉璧帮紝缁х画灏濊瘯鍒涘缓锛堝ぇ姒傜巼鍒涘缓澶辫触锛屽畨鍏級
        except Exception as e:
            return False, "鎼蛋姝婚攣澶辫触: %r" % e

    d = {"pid": _pid, "owner": owner, "host": socket.gethostname(),
         "ts": now, "start": now, "step": "acquire", "gen": info.get("gen", 0) + 1}
    if not _atomic_create(d):
        # 绔炴€侊細鍙︿竴杩涚▼鍒氬垱寤轰簡閿侊紙鎴栧垰鎺ョ锛夆啋 淇濆畧鏀惧純锛屼笅涓€杞啀璇?        return False, "閿佸垰琚叾浠栬繘绋嬫姠鍗狅紝绋嶅悗鍐嶈瘯"
    _held = True
    if why:
        log.warning("鎺ョ閿侊細%s锛堟棫 pid=%s锛?, why, info.get("pid"))
    log.info("馃敀 鎷垮埌閿?pid=%s gen=%s", _pid, d["gen"])
    return True, "ok"


def ensure(owner="daemon"):
    """Ensure this process still owns a lock.

    This is a safety net for a lock file being removed or replaced while the
    daemon is already running. If the file merely vanished, the current owner
    atomically recreates it. If another live process owns it, this process
    reports failure so the caller can stop instead of running a second daemon.
    """
    global _held
    if not _held:
        return acquire(owner)
    d = _read()
    if d.get("pid") == _pid:
        return True, "宸叉寔鏈?

    _held = False
    ok, why = acquire(owner)
    if ok:
        log.warning("daemon 閿佷涪澶?琚浛鎹?鈫?褰撳墠杩涚▼宸茶嚜鎰堥噸寤?)
    return ok, why


def touch(step=""):
    """鍒锋柊蹇冭烦銆傚彧鏈夋寔閿佹椂鎵嶅啓銆?""
    if not _held:
        return False
    d = _read()
    if d.get("pid") != _pid:
        # 閿佽鍒汉鎺ョ浜嗭紙鑷繁鐨勫績璺充笉璇ョ画鍒汉鐨勫懡锛?        log.error("蹇冭烦澶辫触锛氶攣 owner 宸插彉涓?pid=%s锛堟湰杩涚▼ pid=%s锛?, d.get("pid"), _pid)
        return False
    d["ts"] = time.time()
    if step:
        if d.get("step") != step:
            d["step"] = step
            d["step_ts"] = time.time()
    return _write(d)


def step_age():
    d = _read()
    if d.get("pid") != _pid:
        return 0
    return time.time() - float(d.get("step_ts") or d.get("ts") or 0)


def release():
    global _held
    if not _held:
        return
    d = _read()
    if d.get("pid") == _pid:
        try:
            LOCK_FILE.unlink()
            log.info("馃敁 閲婃斁閿?pid=%s", _pid)
        except Exception as e:
            log.warning("鍒犻攣澶辫触锛堢暀瀛ゅ効閿侊級: %r", e)
    _held = False


def clear_stale():
    """寮哄埗娓呯悊姝婚攣锛堜汉宸ヨ繍缁寸敤锛夈€傝繑鍥炶鏄庛€?""
    busy, info = status()
    if busy:
        return "浠嶈娲昏繘绋嬫寔鏈夛紙pid=%s锛夛紝涓嶆竻" % info.get("pid")
    if LOCK_FILE.exists():
        try:
            bak = LOCK_FILE.with_suffix(".lock.bak-%d" % int(time.time()))
            LOCK_FILE.replace(bak)
            return "宸叉竻鐞嗭紙澶囦唤 %s锛? % bak.name
        except Exception as e:
            return "娓呯悊澶辫触: %r" % e
    return "娌℃湁閿佹枃浠?
