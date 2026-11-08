# -*- coding: utf-8 -*-
"""探针：从设备侧找「当前登录账号 uid」，用于选对 IM 库。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402

BASE = "/data/data/cn.soulapp.android"
UIDS = ["96691646", "402857053"]


def main():
    dev = Device.get()

    print("== shared_prefs 文件 ==")
    out = dev.text("ls %s/shared_prefs/" % BASE)
    names = [n.strip() for n in out.replace("\r", "").split("\n") if n.strip()]
    print("  共 %d 个" % len(names))
    for n in names[:30]:
        print("    %s" % n)

    print("\n== 在 shared_prefs 里搜 uid ==")
    for uid in UIDS:
        out = dev.text("grep -rl '%s' %s/shared_prefs/ 2>/dev/null" % (uid, BASE), timeout=60)
        hits = [x.strip() for x in out.replace("\r", "").split("\n") if x.strip()]
        print("  %s -> %d 个文件" % (uid, len(hits)))
        for h in hits[:6]:
            print("     %s" % h)

    print("\n== 两个 IM 库的 mtime ==")
    out = dev.text("ls -l --time-style=+%%Y-%%m-%%d_%%H:%%M:%%S %s/databases/IM-SDK-*-DATA.db" % BASE)
    for line in out.replace("\r", "").split("\n"):
        if "IM-SDK" in line:
            print("  %s" % line.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
