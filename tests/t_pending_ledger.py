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

            # 2026-11-20（§52）：空文本记录 = sid 级冷却，窗口内对任意文本命中
            # （her_stuck 语音会话 / sweep_budget / 媒体 enter_fail 都写空文本）。
            L.mark_skip("s2", "", "her_stuck", hours=2.0)
            assert L.should_skip("s2", "语音转写出来的长文本")
            assert L.should_skip("s2", "")
            assert not L.should_skip("s3", "别的 sid 不受影响")
            # 冷却到期后即使文本仍为空也放行
            all_rec = L.load_skip()
            all_rec["s2"]["ts"] = all_rec["s2"]["ts"] - 3 * 3600
            L.save_skip(all_rec)
            assert not L.should_skip("s2", "语音转写出来的长文本")

            L.mark_replied("u1", sid="s1", text="回过了")
            assert L.recently_replied("u1", sid="s1", text="回过了")
            assert not L.recently_replied("u1", sid="s1", text="她又说一句")
            assert not L.recently_replied(
                "u1", sid="s1", text="回过了", her_ts_ms=9_999_999_999_999)
    print("PASS t_pending_ledger")


if __name__ == "__main__":
    main()
