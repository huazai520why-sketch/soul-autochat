# -*- coding: utf-8 -*-
"""调度闸：唤醒/匹配的「间隔 + 小时上限 + 单批预算」。

⚠️ 2026-11-02 全局体检：**本模块当前没有被主流程调用**（daemon 用的是
   guard/daemon.py 顶部的 MATCH_EVERY / WAKE_EVERY / IDLE_SLEEP 常量）。
   保留原因：它实现了「小时上限 + 单批预算」这两个 daemon 还没有的能力，
   以后要加频控时可以直接接。不要以为它在生效。

参数来源与教训（2026-10-31 事故）：
  旧架构用 `data/wake_tuning.json` 把间隔压到 60s、每轮 6 人、小时上限 200，
  在线上跑了 3 天没人发现 → 单阶段 951s 撞 900s 阶段闸自杀。
  所以这里**不给外部 json 覆盖**，全部走代码常量 + 环境变量，且默认值保守。

用户 2026-11-02 定：唤醒间隔 **60 秒**（原 10 分钟）。
"""
import json
import os
import time

from core.log import get_logger
from core.paths import STATE

log = get_logger("brain.scheduler")

STATE_FILE = STATE / "sched.json"


class Scheduler(object):
    """一个任务类型（wake / match）的调度状态。"""

    def __init__(self, kind, every_s, cap_h, budget_s=240.0):
        self.kind = kind
        self.every_s = float(every_s)          # 最小间隔
        self.cap_h = int(cap_h)                # 每小时最多发几条
        self.budget_s = float(budget_s)        # 单批墙钟预算
        self._st = {"last_ts": 0.0, "hour": "", "hour_n": 0}
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        try:
            allst = json.loads(STATE_FILE.read_text("utf-8"))
        except Exception:
            allst = {}
        st = allst.get(self.kind) or {}
        self._st.update({k: st.get(k, self._st[k]) for k in self._st})
        self._roll_hour()

    def _save(self):
        try:
            allst = {}
            if STATE_FILE.exists():
                try:
                    allst = json.loads(STATE_FILE.read_text("utf-8"))
                except Exception:
                    allst = {}
            allst[self.kind] = self._st
            STATE_FILE.write_text(json.dumps(allst, ensure_ascii=False, indent=2), "utf-8")
        except Exception as e:
            log.warning("保存调度状态失败: %r", e)

    # ---------- 状态 ----------
    def _roll_hour(self):
        h = time.strftime("%Y%m%d%H")
        if self._st.get("hour") != h:
            self._st["hour"] = h
            self._st["hour_n"] = 0

    def wait_left(self):
        """距下次允许的秒数（<=0 表示可以跑）。"""
        return self.every_s - (time.time() - float(self._st.get("last_ts") or 0))

    def hour_left(self):
        self._roll_hour()
        return max(0, self.cap_h - int(self._st.get("hour_n") or 0))

    def due(self):
        """是否到点且还有额度。返回 (bool, 原因)。"""
        left = self.wait_left()
        if left > 0:
            return False, "间隔未到（还剩 %.0fs）" % left
        hl = self.hour_left()
        if hl <= 0:
            return False, "本小时额度已用完（上限 %d）" % self.cap_h
        return True, "ok"

    def mark(self, n=1):
        self._st["last_ts"] = time.time()
        self._roll_hour()
        self._st["hour_n"] = int(self._st.get("hour_n") or 0) + int(n)
        self._save()

    def snapshot(self):
        self._roll_hour()
        return {
            "kind": self.kind, "every_s": self.every_s, "cap_h": self.cap_h,
            "used_this_hour": self._st.get("hour_n"), "wait_left": round(self.wait_left(), 1),
            "last_ts": self._st.get("last_ts"),
        }


def wake_scheduler():
    """唤醒调度。

    用户 2026-11-02 定：**按人计**（同一人 24h 只唤醒一次，见 wake.WOKE_COOLDOWN_H），
    所以小时总量不再是主闸，这里 cap_h 只作为**失控安全阀**（默认 200/h）。
    """
    return Scheduler(
        "wake",
        every_s=float(os.environ.get("SOUL_WAKE_EVERY_S", "60")),
        cap_h=int(os.environ.get("SOUL_WAKE_CAP_H", "200")),
        budget_s=float(os.environ.get("SOUL_WAKE_BUDGET", "240")),
    )


def match_scheduler():
    """匹配调度：默认 5 分钟一次（旧架构口径），每小时 40 条。"""
    return Scheduler(
        "match",
        every_s=float(os.environ.get("SOUL_MATCH_EVERY_S", "300")),
        cap_h=int(os.environ.get("SOUL_MATCH_CAP_H", "40")),
        budget_s=float(os.environ.get("SOUL_MATCH_BUDGET", "240")),
    )
