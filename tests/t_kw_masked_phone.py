# -*- coding: utf-8 -*-
"""kw_of 掩码手机号关键词回归测试（2026-11-12 专项 · issue #12）。

跑法：python tests/t_kw_masked_phone.py      （BAD=0 表示全过）

背景：nightly_collect 巡检报 `brain.pendingq.log.2` 的 TIMEOUT 一天 175 次（阈值 20）。
根因：`brain/pendingq.py::kw_of` 的「纯数字串必超时」闸用正则
      `[0-9０-９]+` 只匹配**纯数字**，而注释里点名的掩码手机号
      （`159****0632`，带 4 个 `*`）完全绕过这道闸 —— 拿它当搜索关键词
      实测 97% 超时（每次白烧满 30s），`S.search()` 返回 timeout 后
      `pendingq` 记 `搜索超时` 台账、10 分钟后重试，如此循环 = 一天 175 次。

修法：两道闸（主路径 + 历史长句兜底）的正则都补上 `*` / 全角 `＊`，
      掩码手机号与纯数字串同样判「必超时」，落到「她」的历史长句兜底。

本测试验证（行为级，用假 db，不连设备）：
  1. 末条是掩码手机号 → 关键词退到历史长句（不再用 `159****0632`）
  2. 末条是纯数字 → 同样退到历史长句（旧行为保持）
  3. 末条是正常文本 → 直接用（回归保护）
  4. 兜底路径：历史里最新的「她长句」是掩码手机号 → 跳过它继续往前找
  5. 全角星号掩码号也挡
  6. 正常含字母的微信号不误伤（含字母的串仍可当关键词）
"""
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _nolog  # noqa: F401  必须在 from brain import ... 之前，避免写生产日志

from brain import pendingq as P  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


class FakeMsg:
    def __init__(self, sender, text, msg_type=1):
        self.sender = sender
        self.text = text
        self.msg_type = msg_type


class FakeCon:
    def execute(self, sql, params):
        return self

    def fetchone(self):
        return (0,)          # 0 个会话重复 → 不是群发模板


class FakeDB:
    uid = "me_uid"

    def __init__(self, msgs):
        self._msgs = msgs
        self.con = FakeCon()

    def messages(self, sid, limit=8):
        return self._msgs[:limit]


def run(db, txt):
    return P.kw_of(db, "s1", txt)


# ------------------------------------------------------------------ 1 · 末条掩码手机号
print("\n--- 1 · 末条是掩码手机号 → 退历史长句 ---")
db = FakeDB([
    FakeMsg("her", "159****0632"),            # 掩码手机号（末条）
    FakeMsg("her", "今晚我们一起去吃火锅吧"),  # 她的历史长句
])
kw = run(db, "159****0632")
ck(kw == "今晚我们一起去吃火锅吧",
   "kw=%r（期望历史长句，不是 159****0632）" % kw)
ck("159" not in kw, "关键词不含掩码手机号片段")

# ------------------------------------------------------------------ 2 · 纯数字（旧行为）
print("\n--- 2 · 末条纯数字 → 仍退历史长句（回归保护）---")
db2 = FakeDB([
    FakeMsg("her", "13800138000"),
    FakeMsg("her", "明天下午有空一起去爬山"),
])
kw2 = run(db2, "13800138000")
ck(kw2 == "明天下午有空一起去爬山", "kw=%r" % kw2)

# ------------------------------------------------------------------ 3 · 正常文本直接用
print("\n--- 3 · 末条正常文本 → 直接用（回归保护）---")
db3 = FakeDB([FakeMsg("her", "今晚吃什么好")])
kw3 = run(db3, "今晚吃什么好")
ck(kw3 == "今晚吃什么好", "kw=%r" % kw3)

# ------------------------------------------------------------------ 4 · 兜底路径掩码号
print("\n--- 4 · 历史兜底：最新「她长句」是掩码号 → 跳过继续往前 ---")
db4 = FakeDB([
    FakeMsg("her", "哦"),                     # 短末条 → 走兜底
    FakeMsg("her", "137****8899"),            # 兜底最新 = 掩码号（必超时）
    FakeMsg("her", "明天下午有空一起去爬山"),  # 再往前一条 = 正常
])
kw4 = run(db4, "哦")
ck(kw4 == "明天下午有空一起去爬山", "kw=%r" % kw4)

# ------------------------------------------------------------------ 5 · 全角星号
print("\n--- 5 · 全角星号掩码号也挡 ---")
db5 = FakeDB([
    FakeMsg("her", "159＊0632"),
    FakeMsg("her", "明天下午有空一起去爬山"),
])
kw5 = run(db5, "159＊0632")
ck(kw5 == "明天下午有空一起去爬山", "kw=%r" % kw5)

# ------------------------------------------------------------------ 6 · 含字母微信号不误伤
print("\n--- 6 · 含字母的微信号不误伤（仍可用）---")
db6 = FakeDB([FakeMsg("her", "wxid_abc123"), FakeMsg("her", "明天下午有空一起去爬山")])
kw6 = run(db6, "wxid_abc123")
ck(bool(kw6), "kw 非空=%r（含字母的串不被当成纯数字/掩码号）" % kw6)


print("\n" + "=" * 74)
print("BAD = %d" % len(BAD))
sys.exit(0 if not BAD else 1)
