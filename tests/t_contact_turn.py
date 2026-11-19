# -*- coding: utf-8 -*-
"""联系方式轮单测（离线，不碰设备/不改生产台账）。

跑法（副机）：python tests\\t_contact_turn.py
期望末行：BAD=0 / CONTACT_TURN_OK
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain import contact as CT  # noqa: E402

BAD = 0


def ck(name, cond):
    global BAD
    if not cond:
        BAD += 1
    print(("ok   " if cond else "BAD  ") + name)


# 台账隔离到临时文件，绝不碰 data/state/contact_sent.json
_tmp = os.path.join(tempfile.gettempdir(), "contact_sent_test.json")
if os.path.exists(_tmp):
    os.remove(_tmp)
CT._LEDGER = _tmp

# ── 1. 她「要联系方式」识别 ────────────────────────────────
for s in ("你号码多少", "加个微信嘛", "给个联系方式", "你电话多少", "vx号发我", "留个号呗"):
    ck("is_ask+ %r" % s, CT.is_ask(s))
for s in ("我手机没电了", "半夜被电话吵醒", "手机搁腿上", "今天好累", "[地铁老人看手机]"):
    ck("is_ask- %r" % s, not CT.is_ask(s))

# ── 2. 分片识别（用生产实际 MY_CONTACT，不硬编码默认号）────
from brain.engine import rules as _R  # noqa: E402

_MC = str(getattr(_R, "MY_CONTACT", "") or "").strip()
print("MY_CONTACT 前3位=%s*** 长度=%d" % (_MC[:3], len(_MC)))
ck("MY_CONTACT 可用", len(_MC) >= 8)
ck("lines 3-4-4", CT.is_contact_lines([_MC[:3], _MC[3:7], _MC[7:]]))
ck("lines 3+8", CT.is_contact_lines([_MC[:3], _MC[3:]]))
ck("lines 整段", CT.is_contact_lines([_MC]))
ck("lines 带前缀", CT.is_contact_lines(["我号 " + _MC[:3], _MC[3:7], _MC[7:]]))
ck("lines 非号码", not CT.is_contact_lines(["今天好累", "早点睡"]))
ck("lines 空", not CT.is_contact_lines([]))

# ── 3. 一生一次台账 ───────────────────────────────────────
ck("done 初始 False", not CT.done("s1"))
CT.mark_done("s1")
ck("done 标记后 True", CT.done("s1"))
ck("done 别的 sid 仍 False", not CT.done("s2"))
ck("done 空 sid 视为已用", CT.done(""))

# ── 4. contact_allow 闸行为 ───────────────────────────────
from brain import sendgate as SG  # noqa: E402

d0 = SG.contact_allow("s1", 3, her_ts_ms=1000.0, my_last_ts_ms=0.0)
ck("已给过 → 拒绝", (not d0.ok) and d0.state == "contact_used")

d1 = SG.contact_allow("s9", 3, her_ts_ms=1000.0, my_last_ts_ms=0.0)
ck("未给过 → 放行 3 条", d1.ok and d1.n == 3 and d1.state == "contact")

d2 = SG.contact_allow("s9", 99, her_ts_ms=1000.0, my_last_ts_ms=0.0)
ck("上限封顶 3", d2.ok and d2.n == 3)

d3 = SG.contact_allow("s8", 3, her_ts_ms=1000.0, my_last_ts_ms=2000.0)
ck("我方末条更晚（AWAITING）→ 拒绝", (not d3.ok) and d3.state == "awaiting")

d4 = SG.contact_allow("", 3)
ck("无 sid → 拒绝", not d4.ok)

# ── 5. 对照：正常额度确实只有 2 条 ──────────────────────────
from brain import verdict as V  # noqa: E402

now = 1_800_000_000.0
her = (now - 600) * 1000.0
v1 = V.state_of(sid="x", her_ts_ms=her, sends=[], now=now, my_last_ts_ms=0.0, n_lines=3)
ck("正常额度首轮 ≤2 条（=3 时被限）", v1.allowed <= 2)
v2 = V.state_of(sid="x", her_ts_ms=her, sends=[now - 300], now=now,
                my_last_ts_ms=0.0, n_lines=3)
ck("正常额度次轮 =1 条（第三段必被裁）", v2.allowed == 1)
ck("→ 这正是 11-07「没说完的号码」的代码成因", v2.allowed < 3)

print("BAD=%d" % BAD)
print("CONTACT_TURN_OK" if BAD == 0 else "CONTACT_TURN_FAIL")
sys.exit(0 if BAD == 0 else 1)
