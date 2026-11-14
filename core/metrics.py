# -*- coding: utf-8 -*-
"""Small structured event log for production diagnosis.

One JSON object per line keeps round/phase/send timings machine-readable without
adding another service or database. The file lives under data/state and is not
part of the source repository.
"""
import json
import os
import threading
import time

from core.paths import STATE

FILE = STATE / "metrics.jsonl"
MAX_BYTES = 10 * 1024 * 1024
_LOCK = threading.Lock()


def emit(event, **fields):
    """Append one structured event. Metrics must never break the bot loop."""
    rec = {
        "ts": round(time.time(), 3),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": str(event),
        **fields,
    }
    try:
        with _LOCK:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            if FILE.exists() and FILE.stat().st_size >= MAX_BYTES:
                backup = FILE.with_suffix(".jsonl.1")
                os.replace(str(FILE), str(backup))
            with FILE.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"),
                                   default=str) + "\n")
        return True
    except Exception:
        return False
