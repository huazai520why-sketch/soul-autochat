# -*- coding: utf-8 -*-
"""Interactive planet-match runner used by `python run.py match [N]`.

2026-11-14 用户确认的完整流程：
  灵魂匹配 → 新匹配卡 → 点个人主页建档 → 发开场白
  → 点会话页左上角「匹配下一个」 → 等待新卡 → 重复到额度清零。

硬规则：
  * 建档没有回到原会话页，不发送、不点下一个；
  * 开场白没有被发送三态确认，不点下一个；
  * 点下一个后没有确认「新指纹 + 新匹配卡」，立即停手，不重复点击；
  * 不退回星球页重新匹配，避免多烧次数。
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain import casepack as CP  # noqa: E402
from brain import match as M  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from data.imdb import open_account  # noqa: E402
from eyes import profile as P  # noqa: E402
from eyes.page import detect  # noqa: E402


def describe(snap):
    card = M.read_card(snap)
    return "匹配度=%-5s 星座=%-5s 引力签=%s 共同点=%s" % (
        card["extra"].get("匹配度", "?"), card["extra"].get("星座", "?"),
        card["tags"] or "-", card["common"] or "-")


def _ensure_match_card(a):
    """确保当前是新匹配卡；必要时从星球页点一次灵魂匹配。"""
    snap = a.snap(force=True)
    pg = detect(snap)
    if pg == "chat" and M.has_card(snap):
        return snap, pg
    snap, pg = M.start_match(a)
    return snap, pg


def main(rounds=0, dry=False):
    # rounds=0 表示一直跑到额度清零；200 只是防失控的硬上限。
    max_rounds = int(rounds or 0) or 200
    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    print("账号 uid=%s，目标轮数=%s" % (
        db.uid, "直到额度清零" if not rounds else rounds))

    snap, pg = _ensure_match_card(a)
    if pg != "chat" or not M.has_card(snap):
        print("首轮没有拿到新匹配卡（page=%s），退出；不重复点击" % pg)
        return 1

    ok_cnt = 0
    fail = []
    quota_done = False
    for i in range(1, max_rounds + 1):
        print("\n========== 第 %d 轮 ==========" % i)
        snap, pg = M.wait_match_card(a, timeout=12.0)
        if pg != "chat" or not M.has_card(snap):
            print("  当前不是新匹配卡（page=%s），停手；不把普通会话误当匹配" % pg)
            fail.append("第%d轮不是新匹配卡(%s)" % (i, pg))
            break

        card = M.read_card(snap)
        card_tags, card_common = card["tags"], card["common"]
        print("  资料: %s" % describe(snap))

        said, bs = M.said_already(dev, snap)
        if said:
            print("  当前卡已说过话（气泡 %d 条），不重发，直接点下一个" % len(bs))
        else:
            # 用户要求先建档再发。建档失败/没回到原聊天页就停手保留这张卡。
            prof = None
            try:
                prof, pok = M.visit_profile(a)
                print("  主页建档: ok=%s %s" % (
                    pok, P.summary(prof) if prof else "-"))
            except Exception as e:
                pok = False
                print("  主页建档异常 %r" % e)
            if not pok:
                fail.append("第%d轮主页建档未闭环" % i)
                print("  !! 建档没有回到原会话页，停止；不发送、不点匹配下一个")
                break

            snap = a.snap(force=True)
            if detect(snap) != "chat" or not M.has_card(snap):
                fail.append("第%d轮建档后不是原匹配会话" % i)
                print("  !! 建档后页面=%s，停止；不发送、不点匹配下一个" % detect(snap))
                break

            text = M._local_opener(card)
            print("  开场白: %r" % text)
            if dry:
                print("  [dry] 不发送")
            else:
                t0 = time.time()
                ok, why = M.send(a, dev, text)
                print("  发送: ok=%s %s (%.1fs)" % (ok, why, time.time() - t0))
                if not ok:
                    fail.append("第%d轮发送失败: %s" % (i, why))
                    print("  !! 发送失败，停止；不点匹配下一个，保留这次匹配")
                    break
                ok_cnt += 1

                try:
                    sid = CP.find_sid(db, text, device=dev)
                    if sid:
                        okp = CP.save_profile(sid, prof, tags=card_tags,
                                              common=card_common)
                        print("  案情包: sid=%s 写入=%s" % (sid, okp))
                    else:
                        print("  案情包: 反查不到 sid，跳过（不猜测写错人）")
                except Exception as e:
                    print("  案情包异常 %r" % e)

        if dry:
            print("  [dry] 不前进")
            continue

        # 建档 + 发送完成，才允许点左上角「匹配下一个」。
        time.sleep(0.8)
        snap2, pg2, how = M.next_one(a, max_wait=10.0)
        print("  匹配下一个: how=%s page=%s sig=%s" % (
            how, pg2, snap2.signature() if snap2 else "?"))
        if how == "no_quota":
            quota_done = True
            print("  今日匹配额度已清零")
            break
        if how != "next":
            fail.append("第%d轮匹配下一个未确认(%s)" % (i, how))
            print("  !! 未确认新卡，停止；不重复点击")
            break

    print("\n===== 结果 =====")
    print("成功发送 %d 条" % ok_cnt)
    print("额度清零=%s" % quota_done)
    for f in fail:
        print("失败: %s" % f)
    snap = a.snap(force=True)
    print("收尾 page=%s sig=%s" % (detect(snap), snap.signature()))
    if fail and not quota_done:
        return 2
    return 0
