# -*- coding: utf-8 -*-
"""三技能装回后的行为测试：用假模型重放，锁住调用顺序 / 落档 / 失败降级。

跑法：python tests/t_skills_replay.py    （BAD=0 表示全过）
"""
import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _nolog  # noqa: F401  必须在 import brain 之前，避免写生产日志

from brain import skills as SK  # noqa: E402
from brain.engine import llm  # noqa: E402
from brain.pack import store  # noqa: E402

BAD = []


def ck(cond, msg):
    if not cond:
        BAD.append(msg)
        print("[BAD]", msg)
    else:
        print("[OK] ", msg)


calls = []
FAKE = [
    "【内部参考·禁止复述】\n类型：嘴硬心软\n投入度：30\n下一步最可能：沉默不回",
    "【内部参考】\n状态：试探\n动作三档：稳\n收束：留个不压迫的钩子",
    "## 方向\n稳一稳\n\n## 一个开口\n可改：今天忙不忙",
]


def fake_analyze(messages, **_kw):
    calls.append(messages)
    sys_txt = messages[0]["content"]
    if "她的性格建模" in sys_txt:
        return FAKE[0]
    if "技能② 推进策略" in sys_txt:
        return FAKE[1]
    return FAKE[2]


def main():
    # ① 三份技能文件确实装回来了
    ck(SK.available(), "三份技能提示词均可加载（config/skills/）")
    ck(all((Path(SK.SKILLS_DIR) / f).is_file() for f in SK.FILES.values()),
       "config/skills/ 下三份文件在位")

    # ② 正常链路：三次调用，顺序与内容正确
    llm.analyze = fake_analyze
    calls.clear()
    r = SK.run_all("test_sid_skills", "今天有点累", "我: 在忙啥\n她: 今天有点累",
                   write=False)
    ck(len(calls) == 3, "共 3 次模型调用（①画像 / ②③方案 / 合成裁决）")
    ck("她的性格建模" in calls[0][0]["content"], "第①次用 analyze_her 原文")
    ck("技能② 推进策略" in calls[1][0]["content"]
       and "技能③ 人性判断" in calls[1][0]["content"], "第②次把②③两份原文合并")
    ck("只选一个" in calls[2][0]["content"], "第③次是单一方向裁决（禁两个方向）")
    ck("【内部参考" not in r["l0"], "L0 剥掉了工具提示行")
    ck(r["ok"] is True and r["l0"] and r["l1"] and r["brief"],
       "返回 l0 / l1 / brief 三段且 ok=True")
    ck(len(r["brief"]) <= 600, "裁决段有字数上限")

    # ③ 落档：l0.md / l1.md / brief.md，且 brief 带 her 指纹
    tmp = Path(tempfile.mkdtemp(prefix="t_skills_"))
    _orig_dir, _orig_meta = store.pack_dir, store.write_meta
    store.pack_dir = lambda sid: tmp
    store.write_meta = lambda *a, **k: None
    try:
        SK.save("test_sid_skills", "今天有点累", r)
        ck((tmp / "l0.md").is_file() and "嘴硬心软" in (tmp / "l0.md").read_text(encoding="utf-8"),
           "L0 画像落到 l0.md")
        ck((tmp / "l1.md").is_file() and "试探" in (tmp / "l1.md").read_text(encoding="utf-8"),
           "L1 方案落到 l1.md")
        b = (tmp / "brief.md").read_text(encoding="utf-8")
        from brain.engine.brief import her_stamp
        ck(("<!-- her:%s -->" % her_stamp("今天有点累")) in b,
           "brief.md 带正确 her 指纹（出话侧能读到）")
    finally:
        store.pack_dir, store.write_meta = _orig_dir, _orig_meta

    # ④ 模型挂了：不抛、ok=False、三段为空
    def boom(*_a, **_k):
        raise RuntimeError("ollama down")
    llm.analyze = boom
    r2 = SK.run_all("test_sid_skills", "今天有点累", "", write=False)
    ck(r2["ok"] is False and not r2["l0"] and not r2["l1"] and not r2["brief"],
       "模型异常时静默降级，不抛不阻塞")

    # ⑤ 关掉合成开关：只跑 2 次、不产出 brief
    llm.analyze = fake_analyze
    import os
    os.environ["SOUL_SKILLS_MERGE"] = "0"
    calls.clear()
    try:
        r3 = SK.run_all("test_sid_skills", "今天有点累", "", write=False)
        ck(len(calls) == 2 and not r3["brief"],
           "SOUL_SKILLS_MERGE=0 时只落 L0/L1，不写 brief")
    finally:
        os.environ.pop("SOUL_SKILLS_MERGE", None)

    # ⑥ reply.py 确实接上了开关，且 brief 仍可一键回退
    src = (Path(SK.BASE) / "brain" / "reply.py").read_text(encoding="utf-8")
    ck('LOCAL_FLOW = (os.environ.get("SOUL_LOCAL_FLOW", "skills")' in src,
       "reply.py 默认 SOUL_LOCAL_FLOW=skills")
    ck("if LOCAL_FLOW == \"skills\"" in src and "SK.run_all(sid, her, turns)" in src,
       "_local_worker 接上三技能分支")
    ck("_brief.generate(sid, her, turns)" in src, "brief 回退分支仍在")

    print("\nBAD =", len(BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
