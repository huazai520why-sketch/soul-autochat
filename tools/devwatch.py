# -*- coding: utf-8 -*-
"""soul_devwatch.py —— 设备层看门狗（2026-10-31 新增）

为什么需要它（现场事故）：
  10-31 14:33 起 MuMu **深层挂死** —— `adb devices` 变成
  `127.0.0.1:16384 offline / emulator-5554 offline`，而
  · `MuMuNxDevice.exe` 进程还在（540MB），`MuMuManager control -v 0 shutdown` **返回成功但不生效**；
  · daemon 侧只把它当"截图异常"计入熔断（`FAIL_MAX=5` → 暂停 30 分钟），**不会去重建模拟器**；
  · 结果：**14:33 → 16:06 约 1.5 小时全机零发送**（她来信也回不出去）。
  真正的解药（实测 66 秒恢复）：`taskkill /F /T /IM MuMuNxMain.exe` → `MuMuManager control -v 0 launch`。
  注意：重建后 `emulator-5554` 这条 serial 会消失，只剩 `127.0.0.1:16384` ——
  任何硬编码 serial 的脚本都要改成自动探测。

策略（保守，绝不误杀）：
  · 每 5 分钟跑一次（计划任务 SoulDevWatch）；
  · **只有连续 2 次**（≈10 分钟）都拿不到 `\tdevice` 才动手 —— 单次抖动不动；
  · 动手顺序：重启 adb server → shutdown → 仍在则强杀 MuMuNxMain → launch → 最多等 6 分钟；
  · 全程只写自己的日志 `uimap\\daemon\\devwatch.log`，不碰 daemon / 锁 / 状态文件。
用法：python soul_devwatch.py [--force]
"""
import io
import os
import re
import subprocess
import sys
import time

BASE = r"E:\soul1.0"
ADB = os.path.join(BASE, "..")
MUMU = r"D:\Program Files\Netease\MuMu"
ADB_EXE = os.path.join(MUMU, "nx_main", "adb.exe")
MM_EXE = os.path.join(MUMU, "nx_main", "MuMuManager.exe")
LOG = os.path.join(BASE, "uimap", "daemon", "devwatch.log")
STATE = os.path.join(BASE, "uimap", "daemon", "devwatch.json")
NEED = 2            # 连续失败多少次才动手
WAIT_ADB = 360      # launch 后等 adb 的上限（秒）

# 🔴 2026-11-03（用户放行·去重）：daemon 进程内已有 _dev_rescue 三级梯度
#    （≥3 次 adb 重启 / ≥6 次补 root+u2 / ≥9 次重建 MuMu）。两条链路同时动手
#    会互相打断（一个刚 launch 另一个又 taskkill）。这里只在 **daemon 不在岗**
#    （进程没了，或锁心跳 >480s 判卡死）时才接管设备救援。
PIDF = os.path.join(BASE, "data", "state", "daemon.pid")
LOCK = os.path.join(BASE, "data", "state", "daemon.lock")
HANG_S = 480


def daemon_watching():
    """daemon 是否在岗（进程活着 + 锁心跳新鲜）。在岗就让 daemon 自己救设备。"""
    try:
        pid = int(io.open(PIDF, encoding="utf-8").read().strip())
    except Exception:
        return False
    alive = False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            alive = True
    except Exception:
        pass
    if not alive:
        # 跨 session 时 OpenProcess 可能失败，用 tasklist 兜底
        try:
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                               capture_output=True, timeout=10)
            txt = (r.stdout or b"").decode("gbk", "ignore")
            alive = str(pid) in txt
        except Exception:
            alive = False
    if not alive:
        return False
    try:
        import json
        d = json.load(io.open(LOCK, encoding="utf-8"))
        return (time.time() - float(d.get("ts") or 0)) <= HANG_S
    except Exception:
        return False

if not os.path.isfile(ADB_EXE):
    sys.exit(0)


def log(s):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), s)
    try:
        with io.open(LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(args, t=120):
    try:
        p = subprocess.run(args, capture_output=True, timeout=t,
                           creationflags=0x08000000)
        return (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    except Exception as e:
        return "ERR %r" % (e,)


def devices():
    return run([ADB_EXE, "devices"], 30)


def has_device():
    # ⚠️ 必须先去 \r：Windows 下 adb 输出是 CRLF，`device$` 会因行尾 \r 永远不匹配
    #    （2026-10-31 实测踩到：健康设备被误判成"不可用"，若上线会每 10 分钟误重启一次）
    out = devices().replace("\r", "")
    return bool(re.search(r"^\S+\tdevice\s*$", out, re.M))


def first_serial():
    out = devices().replace("\r", "")
    m = re.search(r"^(\S+)\tdevice\s*$", out, re.M)
    return m.group(1) if m else None


def render_ok(timeout=30):
    """渲染健康探测（2026-10-31 18:5x 白屏事后补）。

    背景：白屏有两种形态，第一种（adbd 也死）已被 `has_device` 覆盖；
    **第二种是 adb 活、activity 也正常，但 `screencap` 直接挂住**（SurfaceFlinger/HWC 卡死）——
    实测 18:54 那次 `screencap` 在 60s 内不返回，而 `dumpsys window` 一切正常，
    所以只查 `adb devices` 的看门狗完全看不见它。
    判据（任一不满足即判渲染异常）：
      ① `screencap` 在 timeout 内返回（超时=管线卡死）
      ② 落盘 PNG > 20000B（720x1280 纯白图压缩后只有几 KB，正常界面 100KB+）
    返回 (ok, why)。
    """
    ser = first_serial()
    if not ser:
        return False, "no-serial"
    t0 = time.time()
    out = run([ADB_EXE, "-s", ser, "shell",
               "screencap -p /sdcard/_dwchk.png; stat -c %s /sdcard/_dwchk.png"], timeout)
    dt = time.time() - t0
    if out.startswith("ERR"):
        return False, "screencap 超时/异常 %.0fs（%s）" % (dt, out[:60])
    nums = [x.strip() for x in out.replace("\r", "").splitlines() if x.strip().isdigit()]
    if not nums:
        return False, "screencap 无输出（%.0fs）" % dt
    size = int(nums[-1])
    if size < 20000:
        return False, "画面疑似空白（PNG 仅 %dB，正常 100KB+）" % size
    return True, "ok %dB/%.1fs" % (size, dt)


def load_state():
    try:
        import json
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_state(d):
    try:
        import json
        with io.open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def main():
    force = "--force" in sys.argv
    if not force and daemon_watching():
        # daemon 在岗 → 设备归它的 _dev_rescue 管，这里不抢
        return
    st = load_state()
    if not has_device():
        why = "adb 无可用设备"
        ok = False
    else:
        ok, why = render_ok()
    if ok:
        if int(st.get("miss", 0)):
            log("设备恢复（此前连续 %d 次异常：%s）→ 计数清零" % (st.get("miss", 0), st.get("why", "")))
        st["miss"] = 0
        st["why"] = ""
        st["last_ok"] = int(time.time())
        save_state(st)
        return

    st["miss"] = int(st.get("miss", 0)) + 1
    st["why"] = why
    save_state(st)
    log("设备异常 第 %d/%d 次：%s ｜ %s" % (st["miss"], NEED, why,
                                        devices().strip().replace("\r", "").replace("\n", " | ")[:120]))
    if st["miss"] < NEED and not force:
        return

    log("⚠️ 连续 %d 次异常（最近原因：%s）→ 开始深度救援"
        "（重启 adb → shutdown → 强杀 MuMuNxMain → launch）" % (st["miss"], st.get("why", "")))
    log("  adb kill/start: " + run([ADB_EXE, "kill-server"], 30).strip()[:80])
    time.sleep(2)
    run([ADB_EXE, "start-server"], 30)
    time.sleep(3)
    if has_device():
        _ok2, _why2 = render_ok()
        if _ok2:
            log("  ✅ 仅重启 adb server 即恢复（%s）" % _why2)
            st["miss"] = 0
            st["why"] = ""
            save_state(st)
            return
        log("  adb 已连上但渲染仍异常（%s）→ 继续重建实例" % _why2)

    log("  shutdown: " + run([MM_EXE, "control", "-v", "0", "shutdown"], 120).strip()[:80])
    for _ in range(6):
        time.sleep(5)
        if not run(["cmd", "/c", "tasklist", "/FI", "IMAGENAME eq MuMuNxDevice.exe"], 30).count("MuMuNxDevice"):
            break
    log("  taskkill MuMuNxMain: " + run(["cmd", "/c", "taskkill", "/F", "/T", "/IM", "MuMuNxMain.exe"], 60).strip()[:120])
    log("  taskkill MuMuNxDevice: " + run(["cmd", "/c", "taskkill", "/F", "/T", "/IM", "MuMuNxDevice.exe"], 60).strip()[:120])
    time.sleep(8)
    run([ADB_EXE, "kill-server"], 30)
    log("  launch: " + run([MM_EXE, "control", "-v", "0", "launch"], 120).strip()[:80])

    t0 = time.time()
    while time.time() - t0 < WAIT_ADB:
        time.sleep(8)
        if has_device():
            _ok3, _why3 = render_ok()
            if not _ok3:
                continue          # 连上了但还白着 → 继续等（渲染要等 SurfaceFlinger 起来）
            log("  ✅ 救援成功，用时 %.0fs（%s）；当前：%s"
                % (time.time() - t0, _why3,
                   devices().strip().replace("\r", "").replace("\n", " | ")[:100]))
            st["miss"] = 0
            st["why"] = ""
            st["rescued_at"] = int(time.time())
            save_state(st)
            # 拉起 Soul（等价于生产 launch_app 的 adb 部分）
            ser = re.search(r"^(\S+)\tdevice", devices(), re.M)
            if ser:
                run([ADB_EXE, "-s", ser.group(1), "shell",
                     "monkey -p cn.soulapp.android -c android.intent.category.LAUNCHER 1"], 60)
                log("  已拉起 Soul（serial=%s）" % ser.group(1))
            return
    log("  ❌ 救援失败（%.0fs 内 adb 仍未就绪）→ 交人工处理" % (time.time() - t0))


if __name__ == "__main__":
    main()
