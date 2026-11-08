# -*- coding: utf-8 -*-
"""L1 验收：眼睛层（UI 树读取/解析/查询）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from eyes.uitree import Screen  # noqa: E402


def main():
    dev = Device.get()
    scr = Screen(dev)

    print("== L1 眼睛层 ==")
    # 连续 3 次强制 dump，看稳定耗时（首次含 u2 server 初始化）
    snap = None
    for i in range(3):
        t0 = time.time()
        snap = scr.get(force=True)
        print("  dump#%d     %.3fs  nodes=%d  xml=%.1fKB"
              % (i + 1, time.time() - t0, len(snap.nodes), len(snap.xml) / 1024.0))

    out = Path(__file__).resolve().parent.parent / "logs" / "_tree.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(snap.xml, encoding="utf-8")
    print("  saved      %s" % out.name)
    print("  visible    %d" % len(snap.labeled()))
    print("  signature  %s" % snap.signature())

    print("\n-- 可见文本（阅读顺序，前 30） --")
    for i, t in enumerate(snap.texts()[:30]):
        print("  %02d  %s" % (i, t[:46]))

    print("\n-- 命中测试（hit：自动上溯到可点击祖先） --")
    for name in ("聊天", "广场", "星球", "我的", "发送", "返回"):
        n = snap.hit(text=name)
        if n is None:
            n2 = snap.hit(desc=name)
            print("  %-4s  text->None   desc->%r" % (name, n2))
        else:
            print("  %-4s  click=%-5s b=%s center=%s"
                  % (name, n.clickable, n.bounds, n.center))

    return 0


if __name__ == "__main__":
    sys.exit(main())
