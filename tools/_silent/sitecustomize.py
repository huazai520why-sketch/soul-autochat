"""Auto-loaded by CPython when PYTHONPATH contains this directory.

Makes every child process started through subprocess.run / subprocess.Popen
windowless on Windows, unless the caller explicitly sets creationflags.
Loaded ONLY by processes started through tools/silent_launch.py.
"""
import os
import subprocess

if os.name == "nt":
    _CNW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _orig_init = subprocess.Popen.__init__

    def _silent_init(self, *args, **kwargs):
        if "creationflags" not in kwargs:
            kwargs["creationflags"] = _CNW
        _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _silent_init
