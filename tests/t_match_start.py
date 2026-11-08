# -*- coding: utf-8 -*-
"""测试星球匹配：点「开始匹配」-> 等待 -> 看是否匹配到人（不自动发消息）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import nav  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402
from eyes import ocr  # noqa: E402
from eyes.page import detect  # noqa: E402

MAX_WAIT = 45


def find(a, text):
    """文本定位（不写坐标）。"""
    snap = a.snap()
    n = snap.hit(text=text)
    return snap, n


def main():
    dev = Device.get()
    a = Actor(dev)
    nav.ensure_app(dev)

    snap, pg = nav.to_tab(a, "星球")
    print("起点 page=%s" % pg)
    if pg != "planet":
        print("不在星球页")
        return 1

    print("\n== 找「开始匹配」==")
    snap, btn = find(a, "开始匹配")
    if btn is None:
        print("   没找到，打印含匹配的节点：")
        for n in snap.nodes:
            if n.label and "匹配" in n.label:
                print("      %r b=%s click=%s" % (n.label[:16], n.bounds, n.clickable))
        return 2
    print("   命中 %r b=%s click=%s center=%s"
          % (btn.label[:12], btn.bounds, btn.clickable, btn.center))

    print("\n>> 点击开始匹配")
    a.hand.tap_node(btn, settle=2.0)

    print("   等待匹配（最多 %ds）..." % MAX_WAIT)
    t0 = time.time()
    last_sig = None
    while time.time() - t0 < MAX_WAIT:
        s = a.snap(force=True)
        sig = s.signature()
        pg2 = detect(s)
        if sig != last_sig:
            print("   %4.0fs page=%-8s nodes=%-4d texts=%s"
                  % (time.time() - t0, pg2, len(s.nodes),
                     [t[:10] for t in s.texts()[4:9]]))
            last_sig = sig
        # 匹配成功的迹象：出现「打招呼/发送/对方昵称/共同点」
        ts = s.texts()
        if any(k in t for t in ts for k in ("共同点", "打招呼", "匹配成功", "灵魂契合")):
            print("\n   >>> 疑似匹配成功")
            break
        time.sleep(1.5)

    s = a.snap(force=True)
    print("\n== 最终页面 page=%s nodes=%d ==" % (detect(s), len(s.nodes)))
    for t in s.texts()[:22]:
        print("   %s" % t[:44])

    png = dev.screencap()
    (LOGS / "_match.png").write_bytes(png)
    print("\n截图 logs/_match.png  %d bytes" % len(png))
    print("\nOCR 前 16 条：")
    for it in ocr.read(png)[:16]:
        print("   y=%-5d %r" % (it.cy, it.text[:26]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
