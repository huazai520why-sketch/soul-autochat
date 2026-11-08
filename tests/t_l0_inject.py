# -*- coding: utf-8 -*-
"""验证：出话时案情包 L0/L1 到底有没有被读进 prompt。

做法：给 soul_pack.read_l0 / read_l1 打桩，记录它们被调用时的返回长度，
      再跑一次真实 brain_reply。这样能确认「画像/方案真的注入」而不是猜。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"E:\soul2.1")
sys.path.insert(0, r"E:\soul2.1\brain")
sys.path.insert(0, r"E:\soul2.1\db")

from brain import reply as R  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402


def main():
    import soul_pack as PACK

    # 找一个已经有 L0 的会话
    best = None
    for d in Path(r"E:\soul2.1\memory\账号1").glob("*"):
        if not d.is_dir():
            continue
        # 文件名是 L0_人设.md（不同版本命名可能不同）→ 用通配
        hits = list(d.glob("L0*.md"))
        if hits and hits[0].stat().st_size > 100:
            best = (d.name, hits[0].stat().st_mtime)
            break
    if not best:
        print("没有已生成的 L0，先跑 tests/t_local_job.py")
        return 1
    sid = best[0]
    l0_txt, _ = PACK.read_l0(sid)
    l1_txt, _ = PACK.read_l1(sid)
    print("选中 sid=%s" % sid)
    print("  L0 = %d 字：%r" % (len(l0_txt), (l0_txt or "")[:80].replace("\n", " ")))
    print("  L1 = %d 字：%r" % (len(l1_txt), (l1_txt or "")[:80].replace("\n", " ")))

    # 打桩记录
    reads = {"l0": [], "l1": [], "l4": []}
    _r0, _r1, _r4 = PACK.read_l0, PACK.read_l1, PACK.read_l4

    def spy_l0(s):
        t = _r0(s)
        reads["l0"].append((s, len(t[0] or "")))
        return t

    def spy_l1(s):
        t = _r1(s)
        reads["l1"].append((s, len(t[0] or "")))
        return t

    def spy_l4(s):
        t = _r4(s)
        reads["l4"].append((s, len(str(t[0] or ""))))
        return t

    PACK.read_l0, PACK.read_l1, PACK.read_l4 = spy_l0, spy_l1, spy_l4
    try:
        hist = [{"role": "me", "text": "在忙啥呢"},
                {"role": "her", "text": "刚下班"},
                {"role": "me", "text": "辛苦咯"}]
        print("\n真实出话（走 hybrid，hist 手造）…")
        out = R.generate(sid, "你吃饭没嘛", hist=hist, n_cand=2)
        print("返回 %d 条: %r" % (len(out), out))
    finally:
        PACK.read_l0, PACK.read_l1, PACK.read_l4 = _r0, _r1, _r4

    print("\n=== 案情包读取记录 ===")
    for k, v in reads.items():
        print("  %s 被读 %d 次: %s" % (k, len(v), v[-3:]))
    ok = any(n > 0 for _, n in reads["l0"])
    print("\n结论：L0 %s注入 prompt" % ("已" if ok else "**没有**"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
