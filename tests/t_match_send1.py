# -*- coding: utf-8 -*-
"""匹配会话页：读资料 -> 出开场白（带废句重试）-> 发送 -> 验证。**不点匹配下一个**。

用法: python tests/t_match_send1.py          # 真发
      python tests/t_match_send1.py dry      # 只出话不发送
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import match as M  # noqa: E402
from brain import reply as R  # noqa: E402
from brain.act import Actor  # noqa: E402
from brain.nav import to_tab  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes.page import detect  # noqa: E402

DRY = len(sys.argv) > 1 and sys.argv[1].lower() == "dry"


def main():
    dev = Device.get()
    a = Actor(dev)
    snap = a.snap(force=True)
    pg = detect(snap)
    print("起始 page=%s sig=%s nodes=%d" % (pg, snap.signature(), len(snap.nodes)))
    if pg != "chat":
        print("当前不在会话页（%s），先回聊天列表" % pg)
        snap, pg = to_tab(a, "聊天")
        print("回列表后 page=%s" % pg)
        return 1

    card_ok = M.has_card(snap)
    print("是匹配资料卡 = %s" % card_ok)
    card = M.read_card(snap)
    print("昵称=%r 引力签=%s 共同点=%s %s"
          % (card["nick"], card["tags"], card["common"], card["extra"]))

    b = R.engine()
    if b is None:
        print("出话引擎未加载")
        return 2

    t0 = time.time()
    text, cands = M.opening(b, card)
    dt = time.time() - t0
    print("\n== 候选 %d 条（%.1fs） ==" % (len(cands), dt))
    for i, (t, ok, why, sc) in enumerate(cands):
        print("  %d %-24r ok=%-5s %s score=%d" % (i + 1, t[:24], ok, why, sc))
    if not text:
        print("\n全部候选不合格 -> 不发送（避免发废句）")
        return 3
    print("\n采用: %r" % text)

    if DRY:
        print("\n[dry] 不发送")
        return 0

    ok, why = M.send(a, dev, text)
    print("\n发送: ok=%s %s" % (ok, why))
    if not ok:
        return 4

    time.sleep(1.2)
    snap2 = a.snap(force=True)
    print("发送后 page=%s" % detect(snap2))

    # 截图 OCR 确认最后一条是我发的这句
    png = dev.screencap()
    from eyes import chat as C
    bs = C.bubbles(png)
    print("\n-- 可见气泡（尾部 6 条） --")
    for t, side, it in bs[-6:]:
        print("  [%s] %r" % (side, t[:40]))
    last = C.last_bubble(png)
    print("最后一条 = %r side=%s" % ((last[0][:40] if last else None), last[1] if last else None))

    # 数据库确认
    try:
        db = open_account(dev)
        hit = db.sessions_for_texts([text])
        print("\n库内反查 %r -> %s" % (text[:20], hit[:2]))
        if hit:
            sid = hit[0][0]
            ms = db.messages(sid, limit=3)
            for m in ms:
                print("  DB %s [%s] %r" % (m.time_str if hasattr(m, "time_str") else "",
                                           "我" if str(m.sender) == str(db.uid) else "她",
                                           (m.text or "")[:40]))
    except Exception as e:
        print("库校验异常 %r" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
