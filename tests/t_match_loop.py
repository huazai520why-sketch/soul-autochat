# -*- coding: utf-8 -*-
"""星球匹配循环：发通用开场白 -> 匹配下一个（没有就回星球重新匹配）-> 重复。

用法:
    python tests/t_match_loop.py            # 跑 3 轮
    python tests/t_match_loop.py 5          # 跑 5 轮
    python tests/t_match_loop.py 3 dry      # 只读卡片不发

铁律：**开场白没发成功，绝不点「匹配下一个」**（会白费一次匹配次数）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import casepack as CP  # noqa: E402
from brain import match as M  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import profile as P  # noqa: E402
from eyes.page import detect  # noqa: E402

ROUNDS = 3
DRY = False
for arg in sys.argv[1:]:
    if arg.lower() == "dry":
        DRY = True
    elif arg.isdigit():
        ROUNDS = int(arg)


def describe(snap):
    card = M.read_card(snap)
    return "匹配度=%-5s 星座=%-5s 引力签=%s 共同点=%s" % (
        card["extra"].get("匹配度", "?"), card["extra"].get("星座", "?"),
        card["tags"] or "-", card["common"] or "-")


def main():
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    print("账号 uid=%s" % db.uid)

    snap = a.snap(force=True)
    pg = detect(snap)
    print("起始 page=%s sig=%s" % (pg, snap.signature()))

    # 不在会话页就从星球开始匹配一个
    if pg != "chat":
        print("不在会话页，先回星球开一次匹配")
        snap, pg = M.start_match(a)
        print("匹配结果 page=%s" % pg)
        if pg != "chat":
            print("没匹配到会话页（%s），退出" % pg)
            return 1

    ok_cnt = 0
    fail = []
    for i in range(1, ROUNDS + 1):
        print("\n========== 第 %d/%d 轮 ==========" % (i, ROUNDS))
        snap = a.snap(force=True)
        pg = detect(snap)
        if pg != "chat":
            print("  当前不是会话页（%s），尝试重新匹配" % pg)
            snap, pg = M.start_match(a)
            if pg != "chat":
                fail.append("第%d轮进不了会话页(%s)" % (i, pg))
                break

        card = M.read_card(snap)
        card_tags, card_common = card["tags"], card["common"]
        print("  资料: %s" % describe(snap))

        said, bs = M.said_already(dev, snap)
        if said:
            print("  该会话我已经说过话（气泡 %d 条），不重复发，直接前进" % len(bs))
        else:
            # ① 先进对方主页建档（用户 2026-11-02：匹配到人要进一次主页）
            prof = None
            try:
                prof, pok = M.visit_profile(a)
                print("  主页建档: ok=%s %s" % (pok, P.summary(prof) if prof else "-"))
            except Exception as e:
                print("  主页建档异常 %r（继续发开场白）" % e)

            # ② 发通用开场白
            text, cands = M.opening(None, M.read_card(a.snap(force=True)))
            print("  开场白: %r" % text)
            if DRY:
                print("  [dry] 不发送")
            else:
                t0 = time.time()
                ok, why = M.send(a, dev, text)
                print("  发送: ok=%s %s (%.1fs)" % (ok, why, time.time() - t0))
                if not ok:
                    # 发不出去就不许点匹配下一个，否则白费次数
                    fail.append("第%d轮发送失败: %s" % (i, why))
                    print("  !! 发送失败，停止（不点匹配下一个，保留这次匹配）")
                    break
                ok_cnt += 1
                time.sleep(0.8)

                # ③ 落到旧案情包 L4
                if prof:
                    try:
                        sid = CP.find_sid(db, text, device=dev)
                        if sid:
                            okp = CP.save_profile(sid, prof, tags=card_tags,
                                                  common=card_common)
                            print("  案情包: sid=%s 写入=%s" % (sid, okp))
                        else:
                            print("  案情包: 反查不到 sid，跳过")
                    except Exception as e:
                        print("  案情包异常 %r" % e)

        if i == ROUNDS:
            print("  已是最后一轮，不再前进")
            break

        snap2, pg2, how = M.advance(a)
        print("  前进: how=%s page=%s" % (how, pg2))
        if how == "fail":
            fail.append("第%d轮前进失败(%s)" % (i, pg2))
            break

    print("\n===== 结果 =====")
    print("成功发送 %d 条" % ok_cnt)
    if fail:
        for f in fail:
            print("失败: %s" % f)
    snap = a.snap(force=True)
    print("收尾 page=%s sig=%s" % (detect(snap), snap.signature()))
    return 0 if ok_cnt and not fail else 2


if __name__ == "__main__":
    sys.exit(main())
