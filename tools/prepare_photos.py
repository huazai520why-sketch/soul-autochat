# -*- coding: utf-8 -*-
"""把本地照片准备到模拟器相册里（供发图使用）。

为什么需要这三步（2026-11-02 实测，缺一不可）：
  ① **必须放 /sdcard/DCIM/Camera/**：放 /sdcard/Pictures/ 时
     `MEDIA_SCANNER_SCAN_FILE` 广播不生效，媒体库 1427 张里一张都查不到。
  ② **必须发扫描广播**：Android 10+ 不会自动扫新文件。
     `am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://...`
  ③ **必须 touch 改时间**：push 保留原文件 mtime（桌面那三张是 10-28），
     相册按时间倒序 → 它们会排在很后面，翻不到。touch 成当前时间才排最前面。

用法（在副机上跑）：
    python tools/prepare_photos.py
    python tools/prepare_photos.py "C:\\Users\\me\\Desktop\\1.jpg" ...
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADB_CANDIDATES = [
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\MuMuPlayer\nx_main\adb.exe",
]
SERIAL = "127.0.0.1:16384"
DEV_DIR = "/sdcard/DCIM/Camera"
DEFAULT_SRC = [os.path.expanduser(r"~\Desktop\%d.jpg" % i) for i in (1, 2, 3)]


def adb_path():
    for p in ADB_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("找不到 adb")


def run(adb, args, timeout=120):
    cmd = [adb, "-s", SERIAL] + args
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def main():
    srcs = sys.argv[1:] or DEFAULT_SRC
    adb = adb_path()

    rc, out, err = run(adb, ["connect", SERIAL], timeout=30)
    print("connect:", out.strip() or err.strip())
    time.sleep(1.0)
    rc, out, err = run(adb, ["shell", "mkdir -p %s" % DEV_DIR], timeout=30)

    pushed = []
    for i, s in enumerate(srcs, 1):
        if not os.path.exists(s):
            print("!! 本地文件不存在: %s" % s)
            continue
        dst = "%s/soul%d.jpg" % (DEV_DIR, i)
        rc, out, err = run(adb, ["push", s, dst])
        if rc == 0:
            pushed.append(dst)
            print("push OK %s -> %s" % (os.path.basename(s), dst))
        else:
            print("push FAIL %s: %s" % (s, err[:120]))

    # ② touch 成当前时间（排到相册最前）
    if pushed:
        run(adb, ["shell", "touch " + " ".join(pushed)], timeout=30)

    # ③ 逐个发媒体扫描广播
    for p in pushed:
        run(adb, ["shell",
                  "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://%s" % p],
            timeout=30)
        print("scan %s" % p)

    time.sleep(1.0)
    rc, out, err = run(adb, ["shell", "ls -la %s/" % DEV_DIR], timeout=30)
    print("\n设备目录：\n%s" % out)
    print("完成：%d 张" % len(pushed))
    return 0 if pushed else 1


if __name__ == "__main__":
    sys.exit(main())
