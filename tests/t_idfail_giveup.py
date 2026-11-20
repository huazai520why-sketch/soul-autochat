# -*- coding: utf-8 -*-
"""Offline tests for §52: id_mismatch loc_fail giveup gate and nick->sid lookup."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _nolog  # noqa: F401,E402  必须在 from brain import ... 之前，避免写生产日志

from brain import pendingq as PQ  # noqa: E402
from data import reply_state as RS  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        lf = root / "loc_fail.json"
        nf = root / "nick_cache.json"
        archived = []
        with mock.patch.object(PQ, "LOCFAIL_FILE", lf), \
             mock.patch.object(PQ, "NICK_FILE", nf), \
             mock.patch.object(PQ, "_LOCFAIL", {}), \
             mock.patch.object(RS, "set_archived",
                               lambda s, a=True: archived.append(str(s))):
            # 新鲜会话：第 4 次定位/身份失败才归档（LOC_GIVEUP_N=4）
            for i in range(PQ.LOC_GIVEUP_N - 1):
                assert PQ._loc_giveup("s1", "u1", "id_mismatch", age_h=1.0) is False
            assert PQ._loc_giveup("s1", "u1", "id_mismatch", age_h=1.0) is True
            assert archived == ["s1"]
            # 归档后计数清零，下一轮从 1 重新累计
            assert "s1" not in PQ._LOCFAIL

            # 老会话（≥24h）：2 次即归档（LOC_GIVEUP_N_OLD=2，回出率仅 0.8%）
            assert PQ._loc_giveup("s2", "u2", "id_mismatch", age_h=30.0) is False
            assert PQ._loc_giveup("s2", "u2", "id_mismatch", age_h=30.0) is True
            assert archived[-1] == "s2"

            # 落盘文件存在且是合法 JSON
            assert lf.exists()
            json.loads(lf.read_text(encoding="utf-8"))

            # sid_by_nick：昵称反查 sid（clear.her_stuck 兜底用）
            nf.write_text(json.dumps(
                {"1001": "小鱼干儿", "1002": "观雨"}, ensure_ascii=False),
                encoding="utf-8")
            assert PQ.sid_by_nick("小鱼干儿") == "1001"
            assert PQ.sid_by_nick(" 观雨 ") == "1002"
            assert PQ.sid_by_nick("不存在的昵称") is None
            assert PQ.sid_by_nick("") is None
            assert PQ.sid_by_nick(None) is None

            # remember_nick 落盘必须读磁盘全量合并，不能用内存子集覆盖
            # （nick_of 的 >500 clear() 后，旧逻辑会把磁盘历史昵称清空，
            # 实测 nick_cache 380 条被截到 49 条）。
            nf.write_text(json.dumps(
                {"1001": "小鱼干儿", "1002": "观雨"}, ensure_ascii=False),
                encoding="utf-8")
            with mock.patch.object(PQ, "_NICK_CACHE", {}):
                PQ.remember_nick("1003", "新人昵称")
            merged = json.loads(nf.read_text(encoding="utf-8"))
            assert merged.get("1001") == "小鱼干儿"   # 磁盘历史保留
            assert merged.get("1002") == "观雨"
            assert merged.get("1003") == "新人昵称"   # 内存增量写入
    print("PASS t_idfail_giveup")


if __name__ == "__main__":
    main()
