"""Enumerate VISIBLE top-level windows in the current interactive session.
Run with pythonw.exe from a scheduled task whose Principal is Interactive,
otherwise the SSH (session 0) context cannot see the user's desktop.
"""
import ctypes
import json
from ctypes import wintypes

u = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
rows = []


def cb(hwnd, lparam):
    if u.IsWindowVisible(hwnd):
        title_buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, title_buf, 512)
        class_buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, class_buf, 256)
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rows.append({
            "hwnd": int(hwnd),
            "pid": pid.value,
            "class": class_buf.value,
            "title": title_buf.value,
        })
    return True


u.EnumWindows(Proc(cb), 0)

# attach process names
import subprocess
names = {}
for r in rows:
    p = r["pid"]
    if p not in names:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "PID eq %d" % p, "/FO", "CSV", "/NH"],
                creationflags=0x08000000)
            first = out.decode("gbk", "replace").splitlines()[0]
            names[p] = first.split('","')[0].strip('"')
        except Exception:
            names[p] = "?"
    r["proc"] = names[p]

interesting = [r for r in rows if r["title"] or "Console" in r["class"] or "console" in r["class"].lower()]
with open(r"E:\soul1.0\logs\win_audit.json", "w", encoding="utf-8") as f:
    json.dump({"session": 1, "visible_total": len(rows), "windows": interesting},
              f, ensure_ascii=False, indent=1)
