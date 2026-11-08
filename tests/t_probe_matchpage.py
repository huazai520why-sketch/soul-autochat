"""探查：匹配会话页 -> 找「匹配下一个」按钮 + 输入框 + 资料卡信息。不发任何消息。"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.device import Device  # noqa: E402
from brain.act import Actor  # noqa: E402
from eyes.page import detect, badges  # noqa: E402
from eyes import chat as C  # noqa: E402


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    pg = detect(snap)
    print("== 当前页 page=%s sig=%s nodes=%d ==" % (pg, snap.signature(), len(snap.nodes)))
    print("badges=%s" % badges(snap))

    print("\n-- 顶部区域节点（y<200） --")
    for n in sorted([x for x in snap.nodes if x.bounds[1] < 200 and (x.label or x.clickable)],
                    key=lambda x: (x.bounds[1], x.bounds[0])):
        if not (n.label or n.clickable):
            continue
        print("  %-11s b=%-24s click=%s text=%r desc=%r res=%r"
              % (n.cls, str(n.bounds), n.clickable, (n.label or "")[:22], (n.desc or "")[:18], (n.res_id or "")[:28]))

    print("\n-- 全页文本（前 40） --")
    for i, t in enumerate(snap.texts()[:40]):
        print("  %02d %r" % (i, t[:40]))

    print("\n-- 命中测试 --")
    for kw in ("匹配下一个", "下一个", "继续匹配", "放弃", "结束", "发送"):
        n = snap.hit(text=kw)
        print("  %-6s -> %s" % (kw, "None" if n is None else "b=%s click=%s text=%r" % (n.bounds, n.clickable, n.label)))

    # 如果已经在 chat 页，读气泡
    if pg == "chat":
        print("\n-- 会话气泡（截图 OCR） --")
        t0 = time.time()
        png = dev.u2().screenshot(format="raw")
        print("  shot %.2fs" % (time.time() - t0))
        bs = C.bubbles(png)
        for t, side, it in bs[-10:]:
            print("  [%s] %r" % (side, t[:44]))
        last = C.last_bubble(png)
        print("  last = %r" % (last[0] if last else None, ))

        print("\n-- 输入框 --")
        box = snap.find(res="et_sendmessage", limit=1)
        print("  et_sendmessage = %s" % (None if box is None else box.bounds))
        sbtn = snap.find(res="btn_send", limit=1)
        print("  btn_send       = %s" % (None if sbtn is None else sbtn.bounds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
