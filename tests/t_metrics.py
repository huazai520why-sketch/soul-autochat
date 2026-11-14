# -*- coding: utf-8 -*-
"""Offline structured-metrics contract."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import metrics as M  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "metrics.jsonl"
        with mock.patch.object(M, "FILE", path):
            assert M.emit("round_end", round=7, elapsed_s=12.5, result="replied")
            rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            assert rec["event"] == "round_end"
            assert rec["round"] == 7
            assert rec["elapsed_s"] == 12.5
            assert "ts" in rec and "time" in rec
    print("PASS t_metrics")


if __name__ == "__main__":
    main()
