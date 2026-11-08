# -*- coding: utf-8 -*-
"""探针：从 shared_prefs 内容里判断「当前登录 uid」。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402

BASE = "/data/data/cn.soulapp.android/shared_prefs"
FILES = [
    "soul_im_sp.xml",
    "authStatus_cn.soulapp.android.xml",
    "ContextData.xml",
    "sp_info_gather.xml",
]
UIDS = ("96691646", "402857053")


def main():
    dev = Device.get()

    for f in FILES:
        out = dev.text("cat %s/%s 2>/dev/null" % (BASE, f), timeout=60)
        lines = [l for l in out.replace("\r", "").split("\n") if l.strip()]
        print("\n== %s (%d 行, %d 字符) ==" % (f, len(lines), len(out)))
        hits = [l for l in lines if any(u in l for u in UIDS)]
        print("   含 uid 的行 %d：" % len(hits))
        for l in hits[:10]:
            print("     %s" % l.strip()[:130])
        if len(lines) <= 40:
            for l in lines[:14]:
                print("   | %s" % l.strip()[:120])

    print("\n== 库文件时间 ==")
    out = dev.text("ls -l /data/data/cn.soulapp.android/databases/ | grep IM-SDK", timeout=60)
    for l in out.replace("\r", "").split("\n"):
        if "IM-SDK" in l:
            print("   %s" % l.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
