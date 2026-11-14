# -*- coding: utf-8 -*-
"""Offline tests for shared pending cooldown/reply ledgers."""
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import pending_ledger as L  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with mock.patch.object(L, "SKIP_FILE", root / "pending_skip.json"), \
             mock.patch.object(L, "REPLIED_FILE", root / "replied.json"), \
             mock.patch.object(L, "_REPLIED", {}):
            L.mark_skip("s1", "同一句话", "timeout", hours=0.1)
            assert L.should_skip("s1", "同一句话")
            assert not L.should_skip("s1", "她换了新话")

            L.mark_replied("u1", sid="s1", text="回过了")
            assert L.recently_replied("u1", sid="s1", text="回过了")
            assert not L.recently_replied("u1", sid="s1", text="她又说一句")
            assert not L.recently_replied(
                "u1", sid="s1", text="回过了", her_ts_ms=9_999_999_999_999)
    print("PASS t_pending_ledger")


if __name__ == "__main__":
    main()
