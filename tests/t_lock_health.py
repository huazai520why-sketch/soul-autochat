# -*- coding: utf-8 -*-
"""Offline lock self-heal contract."""
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guard import lock as L  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "daemon.lock"
        with mock.patch.object(L, "LOCK_FILE", path):
            L._held = False
            ok, _ = L.acquire("test")
            assert ok and path.exists()
            path.unlink()
            ok, why = L.ensure("test")
            assert ok and path.exists(), why
            assert L.touch("test-step")
            assert L.status()[0] is False   # own pid is not "busy"
            L.release()
            assert not path.exists()
    print("PASS t_lock_health")


if __name__ == "__main__":
    main()
