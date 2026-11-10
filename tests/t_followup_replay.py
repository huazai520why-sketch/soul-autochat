# -*- coding: utf-8 -*-
"""跟进阶梯（obs §104）回放测试：纯函数 + 台账 + 发送闸 + 系统消息分类。

跑法：python tests/t_followup_replay.py     （BAD=0 表示全过）
本机 / 副机都跑；不连设备、不写生产日志、不碰生产 state（台账重定向到临时目录）。
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _nolog  # noqa: F401  必须在 import brain/data 之前，避免写生产日志

from brain import verdict as V  # noqa: E402
from brain import sendgate as SG  # noqa: E402
from data import reply_state as RS  # noqa: E402
from eyes import sysmsg as SM  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


# 台账重定向到临时目录，绝不碰 data/state/reply_state.json
_tmp = Path(tempfile.mkdtemp(prefix="soul_followup_"))
RS.FILE = _tmp / "reply_state.json"
print("临时台账:", RS.FILE)

H = 3600.0
NOW = 1_700_000_000.0


def ms(sec):
    return sec * 1000.0


# ---------------------------------------------------------------- 1 · verdict
print("\n--- 1 · 状态机 C1~C7 ---")
her = NOW - 2 * H

v = V.state_of("s1", ms(her), [], now=NOW, n_lines=2)
ck(v.state == V.PENDING and v.allowed == 2, "新消息：pending，可发 2 条（C6 首回占额度）")

v = V.state_of("s1", ms(her), [her + 60, her + 120], now=NOW, n_lines=2)
ck(v.state == V.FOLLOWING and v.allowed == 0, "24h 内已发 2 条 → following 不再入队（C1）")

v = V.state_of("s1", ms(her), [her + 60], now=NOW, n_lines=2)
ck(v.state == V.PENDING and v.allowed == 1, "已跟过 1 条 → 本轮最多 1 条（§6.6-2 ADAPT_CAP 冲突）")

v = V.state_of("s1", 0, [], now=NOW)
ck(v.state == V.NO_HUMAN and v.allowed == 0, "无真人消息 → no_human（C5）")

v = V.state_of("s1", ms(her), [], now=NOW, has_human=False)
ck(v.state == V.NO_HUMAN, "只有系统卡的会话 → no_human，不计待回")

v = V.state_of("s1", ms(her), [], now=NOW, my_last_ts_ms=ms(her + 30))
ck(v.state == V.AWAITING and v.allowed == 0, "我方末条晚于她 → awaiting，等她回")

v = V.state_of("s1", ms(NOW - 25 * H), [], now=NOW)
ck(v.state == V.PENDING_RESTART and v.restart, "age 25h 且本回合 0 条 → 重新开场（C3）")

v = V.state_of("s1", ms(NOW - 25 * H), [NOW - 24 * H], now=NOW)
ck(v.state != V.PENDING_RESTART, "age 25h 但已发过 → 不重复开场，走跟进（C3）")

v = V.state_of("s1", ms(NOW - 73 * H), [], now=NOW)
ck(v.state == V.ARCHIVED and v.allowed == 0, "age 73h → 归档，不回复不唤醒（C4/C7）")

# 档位：24/48/72 分别允许累计 2/4/6 条（tier_cap = min(6, 2*(floor(age/24)+1)))
for age_h, expect_cap in ((2, 2), (25, 4), (50, 6), (71, 6)):
    v = V.state_of("s1", ms(NOW - age_h * H), [], now=NOW)
    ck(v.tier_cap == expect_cap, "age %dh 档位上限 = %d 条" % (age_h, expect_cap))

# 累计 6 条硬上限：即便跨到 48h 档也不许超过
sends = [NOW - 50 * H + i * 2 * H for i in range(6)]
v = V.state_of("s1", ms(NOW - 50 * H), sends, now=NOW)
ck(v.state == V.FOLLOWING and v.sent_total == 6, "累计 6 条封顶（C1）")

# C2：她再发真人消息 → 计数清零、回第 1 档
new_her = NOW - 60
v = V.state_of("s1", ms(new_her), [NOW - 50 * H + i * 2 * H for i in range(6)], now=NOW)
ck(v.state == V.PENDING and v.sent_total == 0, "她再发人话 → 本回合计数清零（C2）")

# 滚动 24h 窗口：两条一条在 23h 前、一条在 25h 前 → 只算 1 条
v = V.state_of("s1", ms(her), [NOW - 23 * H, NOW - 25 * H], now=NOW, n_lines=1)
ck(v.sent_24h == 1 and v.allowed == 1, "滚动 24h 口径正确（非自然日）")


# ------------------------------------------------------------ 2 · reply_state
print("\n--- 2 · 水位线台账 C2/C5/C8 ---")
RS.reset("t1")
RS.on_her("t1", ms(NOW - 10 * H), human=True)
ck(RS.her_ts_of("t1") == ms(NOW - 10 * H), "真人消息推进 her_ts")
RS.note_sent("t1", 2)
ck(len(RS.sends_of("t1")) == 2, "发送成功即追加 2 条（不等库 pull）")

# 系统消息：不推进水位线、不清 sends、不解除归档
RS.on_her("t1", ms(NOW - 1 * H), human=False)
ck(RS.her_ts_of("t1") == ms(NOW - 10 * H), "系统消息不更新 her_ts（C5）")
ck(len(RS.sends_of("t1")) == 2, "系统消息不冷却、不清计数（C8）")

# 归档 + 她再发人话自动解除
RS.set_archived("t1", True)
ck(RS.is_archived("t1") and "t1" in RS.archived_sids(), "归档可查（candidates/wake 双处排除）")
RS.on_her("t1", ms(NOW - 30), human=True)
ck(not RS.is_archived("t1") and RS.sends_of("t1") == [],
   "她再发人话 → 解除归档 + 回合重置（C4/C2）")


# --------------------------------------------------------------- 3 · sendgate
print("\n--- 3 · 发送闸 ---")
d = SG.allow("", 3)
ck(d.ok and d.n == 3 and d.state == "unbound", "无主会话（奇遇铃/匹配开场白）不纳入跟进额度")

RS.reset("g1")
SG.on_her("g1", ms(time.time() - 3600), human=True)
d = SG.allow("g1", 2)
ck(d.ok and d.n == 2, "正常待回放行 2 条")
SG.note_sent("g1", d.n)
d2 = SG.allow("g1", 2)
ck(not d2.ok and d2.n == 0 and d2.state == V.FOLLOWING, "发满 2 条后本日闸死")

RS.set_archived("g1", True)
d3 = SG.allow("g1", 1)
ck(not d3.ok and d3.state == V.ARCHIVED, "归档会话发送闸拒绝")

# 🔴 冷启动兜底：台账为空 + 调用方没传 her_ts_ms（flow/wake/picreq 就是这么调的）
#    若判 no_human 拒绝，会把「必回」链路整条掐死 —— 上线前实测发现的致命洞。
RS.reset("g_cold")
d = SG.allow("g_cold", 2)
ck(d.ok and d.n == 2, "台账未建立 → 冷启动放行，不掐死必回")
SG.note_sent("g_cold", 2)
d = SG.allow("g_cold", 2)
ck(not d.ok, "冷启动后 2/6 条额度仍正常生效（发满即闸死）")

# 一键回滚开关
_old_on = SG.ON
SG.ON = False
ck(SG.allow("g1", 5).n == 5, "SOUL_FOLLOWUP_ON=0 全放行（生产一键回滚）")
SG.ON = _old_on


# --------------------------------------------------------------- 4 · sysmsg
print("\n--- 4 · 系统消息分类 C5 ---")
ck(SM.is_human("[语音]"), "[语音] 是真人占位，不能当系统消息")
ck(SM.is_human("[图片]"), "[图片] 是真人占位")
ck(SM.is_human("今天忙不忙呀"), "普通人话 = human")
ck(not SM.is_human("互相关注后即可聊天"), "系统引导卡 = system")
ck(not SM.is_human("[系统消息]"), "SYS_TEXTS = system")
ck(not SM.is_human("随便什么", msg_type=27), "msgType=27 = system")
ck(SM.classify("积分兑换限时福利", uid="2042683123") == SM.AD, "官方营销号 = ad")
ck(not SM.is_human(""), "空文本不当人话（不推进水位线）")
ck(SM.is_human("我刚领了个礼物"), "普通人话含营销词不误杀为广告（误杀=永久漏回）")


# ------------------------------------------------- 6 · §6.6 常量对调断言
print("\n--- 6 · 常量对调（§6.6 单做任一条都会留坑） ---")
import re  # noqa: E402
_pq = (Path(__file__).resolve().parents[1] / "brain" / "pendingq.py").read_text(
    encoding="utf-8", errors="replace")
_m1 = re.search(r'^STALE_GIVEUP_H\s*=\s*float\(os\.environ\.get\("SOUL_STALE_GIVEUP_H",\s*"(\d+)"',
                _pq, re.M)
_m2 = re.search(r'^RESTART_H\s*=\s*float\(os\.environ\.get\("SOUL_RESTART_H",\s*"(\d+)"',
                _pq, re.M)
ck(bool(_m1 and _m1.group(1) == "72" and _m2 and _m2.group(1) == "24"),
   "STALE_GIVEUP_H=72 / RESTART_H=24 已对调（否则重开永不触发或 72h 还在接旧话）")


# ---------------------------------------------- 5 · 43 会话 × 72h 容量回放
print("\n--- 5 · 容量回放（§6.7：最坏 43 会话 × 6 条 / 72h） ---")
total = 0
max_24h = 0
for i in range(43):
    sid = "replay_%d" % i
    her0 = NOW - (i % 8) * H
    sends = []
    for step in range(0, 73, 3):          # 每 3h 尝试一轮，共 25 轮
        t = NOW + step * H
        v = V.state_of(sid, ms(her0), sends, now=t, n_lines=2)
        if v.allowed:
            for k in range(v.allowed):
                sends.append(t + 1.0 * k)
                total += 1
        w24 = sum(1 for x in sends if x > t - 24 * H)
        max_24h = max(max_24h, w24)
ck(total <= 43 * 6, "72h 全量发送 %d 条 ≤ 43×6=258 条" % total)
ck(max_24h <= 2, "任意滚动 24h 最多 %d 条 ≤ 2" % max_24h)
print("回放结果：43 会话 / 72h 共发 %d 条，滚动 24h 峰值 %d 条" % (total, max_24h))


print("\n==== BAD=%d ====" % len(BAD))
if BAD:
    for x in BAD:
        print(" -", x)
    sys.exit(1)
print("FOLLOWUP_REPLAY_OK")
