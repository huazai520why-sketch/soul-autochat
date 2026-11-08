# -*- coding: utf-8 -*-
"""关系阶段 + 本轮方向（v11）。

为什么方向从「本地模型裁决」改成「轮数阶梯」：
  2026-11-05 实测线上 32 份 brief，**方向 100% 是「稳一稳」**，一次「撩一下」都没有；
  同时 356 个会话里 308/297/280 轮的那批人还在原地陪聊（goal_hit 只有 8 个）。
  ⇒ 本地 9B 模型在「要不要推进」这件事上只会选最安全的答案，让它裁决 = 永远不推进。
  方向必须由**轮数**决定（可复现、不被模型情绪带走），本地模型只负责提供素材。

阶梯仍是用户 2026-10-25 定稿的按轮数分档（不看任何关键词 —— 实测已婚/未婚
聊得一样热，用昵称关键词封顶会误杀正常人），只是把「该干什么」写成本轮动作。

旧版「60 轮转维护」已废弃：它让 41 个 60+ 轮会话直接停止推进，正是
「聊了很久一点进展都没有」的制度性原因。现在 60 轮 = 推进档，90 轮才下最后通牒。
"""
import os

from brain.pack import store

# (最小轮数, 档位号, 名称, 这一档该干什么)
LADDER = [
    (0, 0, "破冰", "让她觉得你好聊：接住她这句 + 一个只有她能答的具体问题"),
    (20, 1, "熟悉", "交换信息、接住情绪；说一件你自己的小事，让她觉得你是真人"),
    (30, 2, "私人", "把话题往生活里带：吃啥、几点睡、住哪一片、一个人还是有人陪"),
    (45, 3, "暧昧", "带一点男女之间的张力：夸她这个人（不是她做的事）、试探她对你的态度"),
    (60, 4, "推进", "该拿联系方式或见面了：她动身过来，别再原地陪聊"),
]

# 到这一档开始，每轮必须往前走一格（不是「可以」，是「必须」）
PUSH_LV = 2
# 超过这么多轮还没拿到任何东西 → 下最后通牒，逼一个推进动作
HARD_TURNS = int(os.environ.get("SOUL_HARD_TURNS", "90") or 90)
GOAL_LV = 3

# 她这条是收尾语 → 本轮不推进（和 persona.voice 的「收尾就短回」对齐）
HER_CLOSE = ("睡了", "晚安", "困了", "不聊了", "拜拜", "去忙", "先睡", "睡觉", "睡啦", "告辞")


def _is_close(her_msg):
    s = str(her_msg or "").strip()
    return bool(s) and len(s) <= 14 and any(k in s for k in HER_CLOSE)


def level(turns):
    """轮数 → (档位号, 名称, 这一档该做什么)。只按轮数。"""
    try:
        t = max(0, int(turns or 0))
    except Exception:
        t = 0
    cur = LADDER[0]
    for row in LADDER:
        if t >= row[0]:
            cur = row
        else:
            break
    return cur[1], cur[2], cur[3]


def line(sid, her_msg=""):
    """给提示词用的关系摘要 + 本轮方向。没数据返回 ""。"""
    if not sid:
        return ""
    try:
        st = store.read_state(sid)
    except Exception:
        return ""
    turns = int(st.get("turns") or 0)
    lv, name, goal = level(turns)

    out = ["【当前关系】%s（累计 %d 轮）" % (name, turns)]

    # 她说要睡了/告辞 —— 这一轮唯一该做的就是好好收尾，推进留给下一次。
    if _is_close(her_msg):
        out.append("她这条是收尾 → 本轮不推进、不提问，只回一句短的（8 字内）。")
        return "\n".join(out)

    out.append("**这一轮必须做到的**：%s" % goal)

    if st.get("goal_hit"):
        out.append("✅ 联系方式 / 见面已经拿到 → 别再推了，把力气花在聊得舒服上。")
        return "\n".join(out)

    if turns >= HARD_TURNS:
        out.append(
            "⛔ 已经 %d 轮还没进展。这一轮**必须真的做出来**（选一个，写进要发的话里）：\n"
            "· 问她一个私人问题：「你一个人住还是有人陪」这类\n"
            "· 说一句带男女意思的话（暗示，不露骨）\n"
            "· 她最近提过一个人/无聊/住哪 → 给她一个过来的台阶：「你哪天过来耍」\n"
            "要接住她这句再带出来，不能硬插。推不动就晾她两天，别再原地陪聊。" % turns)
    elif lv >= PUSH_LV:
        out.append("⚠️ 这一轮必须比上一轮多走一格：多知道她一件私事，或多给她一句你自己的事。"
                   "只是接住她这句、再问个无关的，不算。")

    if st.get("giveup"):
        # 🔴 2026-11-05：giveup 是从 2.1 旧台账继承来的历史标记（rebuild 时写入），
        #    原来它让 91/262/280/297/308 轮这批人**永久停在「只回不推」** ——
        #    她主动来消息了就是新机会，不该被一条历史判断锁死。
        #    现在它只降级为「本轮只挪一格」，不再阻断。
        out.append("⚠️ 这个号以前判过推不动：这一轮只挪一格，她接了再继续，别加码。")

    out.append("⚠️ 每轮最多推进一格；她不接就退回一级，不硬顶、不重复试探。")
    return "\n".join(out)


def bump(sid, n=1):
    """轮数 +n（对话落盘时调）。返回新轮数。"""
    st = store.read_state(sid)
    turns = int(st.get("turns") or 0) + int(n)
    lv, name, goal = level(turns)
    store.write_state(sid, turns=turns, lv=lv, name=name, goal=goal)
    return turns


__all__ = ["LADDER", "PUSH_LV", "HARD_TURNS", "GOAL_LV", "level", "line", "bump"]
