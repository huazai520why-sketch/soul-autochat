# -*- coding: utf-8 -*-
"""soul1.0 主循环（对应旧架构 `guard/soul_daemon.py` 的 `_cycle`）。

旧架构的循环骨架（2026-11-02 从 soul_daemon.py 原文核对的顺序）：

    抢锁 → 清旧截图 → 设备就绪 → 画面健康 → 报页面 → 账号跟随
    → 合并库 → pending() → 过滤(可达/假末条/陌生人/冷却/僵尸)
    → 有真待回：回复队列（回完 15s 后允许匹配）
    → 无待回：匹配（到期才做；**匹配前先看红点，有红点就先回去回消息**）
              → 匹配后看红点
              → 唤醒（间隔到期）
              → 空闲等待

soul1.0 保留同样的顺序，只换实现：
    待回/必回  -> brain.clear.sweep（进会话=必回，用户口径「不是进入返回」）
    匹配       -> brain.match（通用开场白 + 主页建档 + 匹配下一个）
    唤醒       -> brain.wake（24h 同人冷却）
    锁         -> guard.lock

与旧架构的差异（有意为之，都是用户当天定的）：
  - 不做奇遇铃、不做账号轮转（用户没要求，先不加，留 TODO 位置）
  - 开场白用通用库，不用本地模型现生成
  - 匹配/唤醒间隔都从 10min/30min 降到 60s（用户 2026-11-02 定）
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain import acct as AC  # noqa: E402
from brain import bell as BELL  # noqa: E402
from brain import clear as CL  # noqa: E402
from brain import match as M  # noqa: E402
from brain import nav  # noqa: E402
from brain import pendingq as PQ  # noqa: E402
from brain import reply as R  # noqa: E402
from brain import wake as W  # noqa: E402
from brain.act import Actor  # noqa: E402
from core.device import Device  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.paths import STATE  # noqa: E402
from data import watch as DBW  # noqa: E402  (注意：W 已被 brain.wake 占用)
from data.imdb import open_account  # noqa: E402
from eyes.page import detect  # noqa: E402
from guard import lock  # noqa: E402

log = get_logger("guard.daemon")

# ---- 节奏（用户 2026-11-02 定；写死不给外部 json 覆盖，防 wake_tuning.json 重演）----
# 🔴🔴 2026-11-08（用户口径：「现在脚本没人聊天去连续匹配吧 灵魂匹配次数花光」）
#   改前：MATCH_EVERY=60s + 每轮只匹配 1 个人 + 匹配完 return "matched" 就结束本轮，
#         下一轮又要等 60s。实测一天 24h 只匹配 ~600 次，而额度是每天 999+，
#         **额度根本花不完**；大量时间浪费在「没红点、没待回、干等 60 秒」。
#   改后（连续匹配）：空闲时**一轮里连着匹配多个**，直到：
#         · 匹配额度用完（match.quota_out 或返回 no_quota）
#         · 出现红点 / 有新消息（立刻让位去回复，用户硬规则）
#         · 撞到本轮墙钟预算（MATCH_STREAK_BUDGET）
#         · 连续失败 MATCH_STREAK_FAIL_MAX 次（通道坏了就别硬烧）
#   为什么这样是安全的：匹配 = 发通用开场白 + 记台账，不依赖对方在线；
#   有红点立刻中断的规则仍然在（HAVE_DOT_BLOCK_MATCH），不会被匹配挤掉回复。
MATCH_EVERY = 8.0         # 两次匹配之间（一轮内连打也保留小间隔，别点太快）
WAKE_EVERY = 60.0         # 两次唤醒之间
IDLE_SLEEP = 30.0         # 无事可做时的空转间隔
DEV_RETRY = 180.0         # 设备不可用后等多久再试
# 🔴🔴 2026-11-11（watchdog_restart 风暴·根治）：启动初始化（设备探测+root+开库）
#   失败时**不退出**，每隔这么久重试一次，让 daemon 等设备/库恢复而不是秒崩。
#   稳态主循环本就有 device_ready()+DEV_RETRY 兜底，但启动路径原来没有——
#   这就是「watchdog 拉起→再崩→再拉」风暴（243 次/日）的根因。
STARTUP_RETRY_S = float(os.environ.get("SOUL_STARTUP_RETRY_S", "30") or 30)
# 连续匹配的参数（用户 2026-11-08：把额度花光）
MATCH_STREAK_N = int(os.environ.get("SOUL_MATCH_STREAK_N", "12") or 12)   # 一轮最多连打几个
MATCH_STREAK_BUDGET = float(os.environ.get("SOUL_MATCH_STREAK_BUDGET", "420") or 420)  # 连打总预算(s)
MATCH_STREAK_FAIL_MAX = 3   # 连打里连续失败几次就停（通道坏了）
# 🔴 2026-11-03：只重试不动作 = 死循环。夜间 00:46 起设备挂死，
#    这条路径空转 55 次（2h46m）全机零产出。下面加自愈梯度。
DEV_RESCUE_GAP = 300.0     # 两次自愈动作最短间隔（别把刚起来的设备又打断）
DEV_RESCUE_L3 = os.environ.get("SOUL_DEV_RESCUE_L3", "1") != "0"
_RESCUE = {"at": 0.0}
# 启动首巡只在本进程内布防一次（不写盘）：每次启动/重启后也按「先红点、后奇遇铃」走一遍。
_BOOT_SWEEP = {"armed": False}
ROUND_BUDGET = 600.0      # 单轮墙钟上限（超了就结束本轮，防阶段闸自杀）
MATCH_SILENT = 1800.0     # 匹配连续失败后的静默期
DB_CHECK_EVERY = 1800.0   # 库完整性体检间隔（30 分钟）
# 🔴 2026-11-09 21:44（用户口径）：「切号之后优先消除红点，然后再找聊天页面的
#    奇遇铃 稍后再聊，点进去看看里面有没有人等着我去聊」。
#   原链 ①-b（奇遇铃-稍后再聊）排在 ②红点**之前** —— 切号进来时先钻铃列表，
#   而这个号上积压的真未读一直没人动，正是「来了消息半天不回」的一部分。
#   现在切号后首巡拆两阶段：
#     阶段 dot  → 先清红点（①-b 本轮延后，日志写明）
#     阶段 bell → 红点这一轮扫完，立刻进「稍后再聊」看有没有人等我去聊
#   只作用于**切号后的首巡**；非切号轮次仍按原链（奇遇铃最高，2026-11-08 口径）。
POST_SWITCH_MAX_S = float(os.environ.get("SOUL_POST_SWITCH_MAX_S", "1800") or 1800)

HAVE_DOT_BLOCK_MATCH = True   # 有红点就不匹配（用户口径）

# 🔴 2026-11-08 03:26（P0 死锁·空烧降级）
#   现网死锁的本质：积压 63 人里 82.5% 定位不到（翻 3 屏未命中 633 次、
#   搜索 notfound 598 次），于是「还有待回」恒成立 → 有红点闸门恒真 → 匹配永远进不去，
#   而这些人又永远回不掉。**回复侧彻底失效时，匹配是唯一还有产出的出路。**
#   规则：连续这么多轮「一个都没回成」→ 认定回复侧此刻失效 → 放行匹配。
#   一旦某轮真的回成人 → 计数清零，立即恢复「回复优先」。
#   取 3：一轮空烧已异常，连续 3 轮（约 15~30 分钟）足够判定，又不至于太久不匹配。
PENDING_ZERO_MAX = int(os.environ.get("SOUL_PENDING_ZERO_MAX", "3") or 3)

# ---- 状态 ----
STATE_FILE = STATE / "daemon.json"


def load_state():
    import json
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_state(st):
    import json
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:
        log.warning("存状态失败: %r", e)


# ---------------- 设备 ----------------
def device_ready(dev, actor=None):
    """设备可用性：adb 通 + root + 截图能出图 + Soul 在前台。"""
    try:
        if not dev.root_ok():
            log.warning("设备无 root → 尝试 adb root")
            if not dev.ensure_root():
                return False
        w, h = dev.wm_size()
        if not (w and h):
            return False
        png = dev.screencap()
        if not png or len(png) < 5000:
            log.warning("截图异常（%d bytes）", len(png or b""))
            return False
        return True
    except Exception as e:
        log.warning("设备自检失败: %r", e)
        return False


def _adb_raw(dev, args, timeout=20):
    """直接跑 adb（不走 dev.run —— serial 失效时仍要能执行）。"""
    import subprocess as _sp
    try:
        p = _sp.run([dev.adb] + list(args), capture_output=True, timeout=timeout)
        out = (p.stdout + p.stderr).decode("utf-8", "ignore").strip().replace("\r", " ")
        log.info("adb %s -> rc=%s %s", " ".join(args[:2]), p.returncode, out[:80])
        return p.returncode
    except Exception as e:
        log.warning("adb %s 异常: %r", " ".join(args[:2]), e)
        return -1


def _rebuild_emulator(dev):
    """MuMu 深层挂死时的重建（2026-10-31 实测解药：约 66s 恢复）。"""
    import subprocess as _sp
    from core.paths import MUMU_MANAGER_CANDIDATES
    mm = ""
    for p in MUMU_MANAGER_CANDIDATES:
        if os.path.exists(p):
            mm = p
            break
    log.warning("[自愈L3] 重建模拟器（MuMuManager=%s）", mm or "未找到")
    try:
        _sp.run(["taskkill", "/F", "/T", "/IM", "MuMuNxMain.exe"],
                capture_output=True, timeout=30)
    except Exception as e:
        log.warning("taskkill MuMuNxMain 异常: %r", e)
    time.sleep(3)
    if mm:
        try:
            _sp.run([mm, "control", "-v", "0", "launch"], capture_output=True, timeout=120)
        except Exception as e:
            log.warning("MuMuManager launch 异常: %r", e)
    for i in range(12):
        time.sleep(5)
        try:
            ser = dev.probe_serial()
            if ser:
                dev.serial = ser
                log.info("[自愈L3] 设备已上线 serial=%s（等了 %ds）", ser, (i + 1) * 5)
                for fn in ("ensure_root", "reset_u2"):
                    try:
                        getattr(dev, fn)()
                    except Exception:
                        pass
                return True
        except Exception:
            pass
    log.warning("[自愈L3] 重建后 60s 仍未上线")
    return False


def _dev_rescue(dev, fails):
    """设备连续不可用 fails 次时的自愈梯度。

    2026-11-03 夜间事故：00:46 screencap rc=124 timeout + 无 root，
    daemon 每 180s 只打印一行「设备不可用」就重试，55 次 / 2h46m 无人救。
    梯度：
      >=3 次（约 9min）：adb kill-server / start-server / connect
      >=6 次（约 18min）：再补 root + u2 重连
      >=9 次（约 27min）：重建模拟器（SOUL_DEV_RESCUE_L3=0 可关）
    """
    if fails < 3:
        return
    now_t = time.time()
    if now_t - float(_RESCUE.get("at", 0) or 0) < DEV_RESCUE_GAP:
        return
    _RESCUE["at"] = now_t
    level = 1 if fails < 6 else (2 if fails < 9 else 3)
    if level >= 3 and not DEV_RESCUE_L3:
        level = 2
    log.warning("⚡ 设备自愈 L%d（连续失败 %d 次）", level, fails)
    _adb_raw(dev, ["kill-server"])
    time.sleep(1.5)
    _adb_raw(dev, ["start-server"])
    serial = dev.serial or ""
    _adb_raw(dev, ["connect", serial if ":" in serial else "127.0.0.1:16384"])
    if level >= 2:
        for fn in ("ensure_root", "reset_u2"):
            try:
                getattr(dev, fn)()
            except Exception:
                pass
    if level >= 3:
        _rebuild_emulator(dev)


def ensure_app(dev):
    nav.ensure_app(dev)


# ---------------- 单轮 ----------------
def _hb(tag=""):
    """轮内心跳 —— 让 watchdog 知道「我还在干活，不是卡死」。

    🔴🔴 2026-11-08 04:05（stability-forensics 专项定位 · 186 次重启的真因）
      改前：`lock.touch()` 只在 cycle() **返回之后**和少数几个阶段末尾打点，
            而 pendingq / sweep 单轮内部能跑 300~500s，中间**一个心跳都没有**。
            watchdog 的 HANG_S=480 因此判「心跳过期」→ 强杀。
      实测：81 次强杀的心跳值 median 548s、37% 落在刚过线 0~40s 内，
            最极端一例「485s > 480s」—— 过线 5 秒就动手。
            而 ROUND_BUDGET=600 本来就允许单轮跑 600s ⇒ **数学上必然冲突**，
            「干得越卖力越被判卡死」。
      现在：在长耗时段内部主动打心跳，watchdog 只在「真的没动静」时才动手。
    """
    try:
        lock.touch(tag or "hb")
    except Exception:
        pass


def _post_switch_phase(st, db):
    """切号后首巡当前处在哪一段。

    返回：
      "dot"  → 还在清红点阶段，奇遇铃「稍后再聊」本轮必须延后
      "bell" → 红点这一轮已经扫完，可以去「稍后再聊」看有没有人等我去聊
      ""     → 不在切号首巡，走原优先级链

    只读状态、不做任何设备动作，便于单测直接断言。
    超过 POST_SWITCH_MAX_S 自动作废：万一红点永远清不完（僵尸积压），
    也不能把奇遇铃永久压住。
    """
    try:
        uid = str(getattr(db, "uid", "") or "")
    except Exception:
        return ""
    if not uid or str(st.get("post_switch_uid") or "") != uid:
        return ""
    t0 = float(st.get("post_switch_t0", 0) or 0)
    if t0 and (time.time() - t0) > POST_SWITCH_MAX_S:
        for _k in ("post_switch_uid", "post_switch_t0",
                   "post_switch_dot_seen", "post_switch_bell_done"):
            st.pop(_k, None)
        log.info("切号首巡超时（>%.0f 分钟）→ 作废，恢复原优先级链",
                 POST_SWITCH_MAX_S / 60.0)
        return ""
    if st.get("post_switch_bell_done"):
        return ""
    return "bell" if st.get("post_switch_dot_seen") else "dot"


def cycle(a, dev, db, st, dry_run=False):
    """跑一轮。返回本轮的 'what'。

    顺序按用户 2026-11-08 定稿：
        ① 奇遇铃（全局最高，弹铃立刻插队）
        ② 处理新消息 / 消除红点（进会话=必回）
        ③ 已读未回（红点清完才走搜索）
        ④ 匹配（用户：没人聊就去匹配）
        ⑤ 好友唤醒（三次、一天一次、找不到人也算）
        ⑥ 账号轮转（榨干 或 8h 强制）
        ⑦ 空闲（无人可聊时才等）
    """
    t_round = time.time()
    lock.touch("round-start")

    # 0) 拉库：**5 分钟同步一次**（用户 2026-11-02），有新消息信号时立刻强制刷新。
    #    原来每轮都 pull 10MB，又慢又容易拉到不一致的库。
    _dirty = False
    try:
        _dirty = DBW.urgent()
    except Exception:
        pass
    try:
        db = open_account(dev, force=_dirty)
        AC.note_online(db.uid)
        # 🔴🔴 2026-11-08 11:2x（P0·用户：「没人聊天去星球匹配啊」「今日还剩 55 次匹配」）
        #
        #   【真 bug】`match_quota_day` 是**按账号**算的，但代码把它当成**按天全局**存：
        #     11:06 daemon 从 402857053 切到 96691646 后，daemon.json 里
        #     `match_quota_day` 仍是 402 那天写下的 "2026-11-08"，
        #     于是 daemon.py 的 `if st.get("match_quota_day") == 今天: 跳过匹配`
        #     **一整天都不再匹配**，而新号额度是满的（日志自相矛盾：
        #     「今日匹配额度已用完（已记）→ 跳过匹配」紧跟着
        #     「今日还剩 55 次匹配」）。
        #   修法：记录 `match_quota_uid`，账号一变就清掉当天的额度标记。
        #   顺带把 `bell_list_n`（稍后再聊已处理人数）也按账号/按天重置。
        _qu = str(st.get("match_quota_uid") or "")
        if _qu != str(db.uid):
            if _qu:
                log.info("账号已变（%s → %s）→ 重置当日匹配额度标记", _qu, db.uid)
            st["match_quota_uid"] = str(db.uid)
            st.pop("match_quota_day", None)
            st.pop("bell_list_n", None)
            # 🔴 2026-11-09 21:44（用户口径）：切号之后先清红点，再看奇遇铃「稍后再聊」。
            #   布防后就由 _post_switch_phase() 决定本轮走到哪一段，
            #   `bell_list_n` 已在上面随账号重置，所以新号首巡能重新进一次铃列表。
            st["post_switch_uid"] = str(db.uid)
            st["post_switch_t0"] = time.time()
            st.pop("post_switch_dot_seen", None)
            st.pop("post_switch_bell_done", None)
            log.info("切号首巡布防：先清红点 → 再进奇遇铃「稍后再聊」（uid=%s）", db.uid)

        # 启动首巡（每进程一次）：daemon 起来时和切号后是同一个场景 ——
        # 这个号上可能积压了一堆真未读，必须先清红点再去钻铃列表。
        if not _BOOT_SWEEP["armed"]:
            _BOOT_SWEEP["armed"] = True
            st["post_switch_uid"] = str(db.uid)
            st["post_switch_t0"] = time.time()
            st.pop("post_switch_dot_seen", None)
            st.pop("post_switch_bell_done", None)
            log.info("启动首巡布防：先清红点 → 再进奇遇铃「稍后再聊」（uid=%s）", db.uid)
        # 跨天也重置一次（daemon 连续跑几天时不至于永久卡住）
        if st.get("bell_list_day") != time.strftime("%Y-%m-%d"):
            st["bell_list_day"] = time.strftime("%Y-%m-%d")
            st.pop("bell_list_n", None)
        # 🔴 2026-11-04（P0-2）：切号后 IM 库文件名会变（token 进文件名），
        #   而 watch 原来只在启动 attach 一次 ⇒ 切号后一直在看旧账号的库，
        #   「新消息打断」失效到下次重启（实测 02:46 那次 12 分钟才恢复）。
        #   目录级指纹已能覆盖，这里再显式跟随一次，日志可核。
        try:
            DBW.set_path('/data/data/cn.soulapp.android/databases/' + db.path.name)
        except Exception as _e:
            log.warning("监控跟随库失败: %r", _e)
        if _dirty:
            log.info("库有变化信号 → 已强制同步最新数据")
            # 🔴🔴 2026-11-09 P0 修复（18:42 新消息未处理故障 · 根因 A+B）：
            #   故障链路：
            #     1. DBW.urgent() 检测到库变化 → open_account(force=True) 同步了最新库
            #     2. 但 _device_unread_sids() 的 60s TTL 缓存还是旧的 → 新消息 sid 不在缓存里
            #     3. candidates() 里新消息被 _recently_replied/should_skip 掐掉（没有硬放行保护）
            #     4. cycle() 继续线性往下走（铃→红点→已读未回→匹配→唤醒→空闲）
            #        不会回头重查新消息 → 新消息永久搁置
            #   修法（双管齐下）：
            #     A. 清掉 _device_unread_sids 缓存 → 让 candidates() 重新查设备库
            #     B. 设一个 _dirty_recheck 标志 → 在步骤②入口处重新跑 candidates()
            #        确保新消息能进入待回队列
            #   顺带把「设备存活 uid」缓存也清掉：它 120s TTL，
            #   新会话刚进来时缓存里没有这个人 → 会被当成「App 里已不存在」
            #   从候选里移出（实测一次移出 180 个），和未读缓存是同一个病。
            try:
                PQ.invalidate_unread_cache()
            except Exception:
                pass
            try:
                PQ.invalidate_live_cache()
            except Exception:
                pass
    except Exception as e:
        # 🔴🔴 2026-11-12（DS-10：刷新失败降级 · 不再静默）
        #   现象：刷新库失败只 warning「沿用旧对象」，不计数 —— 若连续失败
        #   （库被锁/adb 抖动/磁盘满），daemon 一直用旧镜像跑，日志却看不出
        #   已降级多久，排查时误以为数据是新的。
        #   修法：加失败计数 + 阈值告警，明确降级路径（不静默、不打断本轮）。
        _rf = int(st.get("refresh_fail_n", 0) or 0) + 1
        st["refresh_fail_n"] = _rf
        st["refresh_fail_t"] = time.time()
        if _rf >= 3:
            log.warning("刷新库连续失败 %d 次（沿用旧对象，已降级 %.0f 分钟）：%r",
                        _rf, _rf * 5.0, e)
        else:
            log.warning("刷新库失败（第 %d 次，沿用旧对象）: %r", _rf, e)
    else:
        # 刷新成功：清掉连续失败计数，避免告警残留。
        if st.get("refresh_fail_n"):
            st.pop("refresh_fail_n", None)
            st.pop("refresh_fail_t", None)

    # 0.5) 每 30 分钟给本地库做一次完整体检：坏了立刻重建
    #      （2026-11-02 踩过：库变成 malformed 后所有查询全崩，daemon 静默瘫痪）
    if time.time() - float(st.get("last_dbcheck", 0) or 0) > DB_CHECK_EVERY:
        try:
            from data import imdb as _IM
            if _IM.health(db):
                log.info("库体检 OK（%d 会话）", db.stats().get("sessions", 0))
            else:
                log.warning("⚠️ 本地库体检失败 → 重建缓存")
                _IM.invalidate()
                db = open_account(dev, force=True)
                log.info("库已重建（%d 会话）", db.stats().get("sessions", 0))
        except Exception as e:
            log.warning("库体检异常（继续用当前库）: %r", e)
        st["last_dbcheck"] = time.time()

    # ① 奇遇铃 —— 最高优先级，看到就先处理
    try:
        snap0 = a.snap(force=True)
        if BELL.is_bell(snap0, dev=dev):
            log.info("🔔 轮首发现奇遇铃")
            ok, why = BELL.handle(a, dev, dry_run=dry_run, db=db)
            st["last_bell"] = time.time()
            if ok:
                return "bell"
            log.info("奇遇铃没处理成（%s），继续正常流程", why)
    except Exception as e:
        log.warning("奇遇铃检查异常（不阻断）: %r", e)

    # ①-b 奇遇铃「稍后再聊」列表 —— 同属奇遇铃，最高优先级（用户 2026-11-08）
    #
    #   🔴 用户原话：「奇遇铃 稍后再聊 里面有三个人等着对话啊 优先级奇遇铃不是最高吗
    #      怎么没动静」「进入对话页那么久了 开场白还发不出去」「怎么不进入她的主页 建档呢」
    #
    #   实测根因：`bell.py` 原来只认弹窗里的「立即私聊」按钮（is_bell），
    #   而「奇遇铃-稍后再聊」是会话列表里的一个**普通行**，点进去是
    #   LoveBellChatListActivity（3 行：傻子看傻子 10:26 / BB叽 09:53 / 余生不将就 09:48）。
    #   这条链路完全没人管 ⇒ 3 个已送到嘴边的人一直晾着。
    #
    #   现在：轮首只要列表里有这个入口，就进去逐个「发开场白 + 进主页建档」。
    #   放在 ① 之后、清红点之前 —— 用户口径就是奇遇铃最高。
    #   2026-11-13 改为小批多轮清空：每轮最多 BELL_BATCH_MAX，后续轮次继续；
    #   每日只保留一个安全上限 BELL_DAILY_MAX（默认 40，可用环境变量调整）。
    try:
        try:
            _bell_n = BELL.bell_daily_count(db.uid)
        except Exception:
            _bell_n = int(st.get("bell_list_n", 0) or 0)
        _psw = _post_switch_phase(st, db)
        if _psw:
            # 切号首巡期间铃列表统一由 ③-b 在**红点之后**处理（用户 2026-11-09 21:44）
            log.info("切号首巡（阶段 %s）：铃列表让位给红点，清完红点当轮再进 ③-b", _psw)
        elif _bell_n < BELL.BELL_DAILY_MAX:
            ok_l, why_l = BELL.open_list(a)
            if ok_l:
                log.info("🔔 进入奇遇铃「稍后再聊」：%s", why_l)
                _lim = min(BELL.BELL_BATCH_MAX, BELL.BELL_DAILY_MAX - _bell_n)
                _n_ok, _msg = BELL.handle_list(
                    a, dev, dry_run=dry_run, limit=_lim, db=db, uid=db.uid)
                try:
                    st["bell_list_n"] = BELL.bell_daily_count(db.uid)
                except Exception:
                    st["bell_list_n"] = _bell_n + _n_ok
                st["last_bell"] = time.time()
                log.info("🔔 稍后再聊本轮结果：%s（今日已发 %d / 上限 %d）",
                         _msg, st["bell_list_n"], BELL.BELL_DAILY_MAX)
                # 处理完回会话列表，别把后续阶段丢在铃页面里
                try:
                    nav.to_chatlist(a)
                except Exception:
                    pass
                if _n_ok:
                    return "bell"
    except Exception as e:
        log.warning("奇遇铃稍后再聊处理异常（不阻断）: %r", e)

    # 1) 画面与页面
    snap, pg = nav.to_chatlist(a)
    lock.touch("page")
    if pg != "chatlist":
        _bn = int(st.get("blocked_n", 0) or 0) + 1
        st["blocked_n"] = _bn
        st["blocked_pg"] = pg
        log.warning("回不到会话列表（%s）连续 %d 轮", pg, _bn)
        # 🔴 2026-11-06（greeting 卡 128 轮教训）：nav 的 stuck/dead 计数都是单次调用内
        #    的，跨轮持续性卡死它看不到。这里按**跨轮**升级：
        #    连续 5 轮 blocked → am start 回首页；连续 8 轮 → 重启 App。
        if _bn >= 8:
            log.warning("连续 %d 轮回不到列表 → 重启 App", _bn)
            try:
                nav.restart_app(dev)
            except Exception as e:
                log.warning("重启 App 异常: %r", e)
            st["blocked_n"] = 0
        elif _bn >= 5:
            log.warning("连续 %d 轮回不到列表 → 强制回首页(am start)", _bn)
            try:
                nav.goto_main(dev)
            except Exception as e:
                log.warning("goto_main 异常: %r", e)
        return "blocked"
    st["blocked_n"] = 0
    st.pop("blocked_pg", None)

    # ⏰ 8h 强制切号原来放在这里（回消息**之前**），有个致命副作用：
    #   到点会在进会话前直接切走 → 本轮所有待回/红点全丢，而切回来要等
    #   SWITCH_COOL_H(4h) → 那批人白等 4 小时（违背必回）。
    #   ⇒ 已下移到本轮回复段之后（见下方「本轮回复之后」处），那里切走不丢消息。

    # ② 红点 / 待回 —— 用户口径：清红点就是进会话回消息
    # 🔴 2026-11-08（库直读 P0）：传 db 让判据走库（0.05s、100% 覆盖），
    #   否则 has_dot_now 只能看屏幕行内红点 —— 而 `unread_msg_number` 实测
    #   连续 4 轮 0 个节点、底栏「聊天」角标也恒为 0 ⇒ 恒判「没有红点」。
    #
    # 🔴🔴 2026-11-08 04:12（P0 死锁·入口闸）
    #   has_dot_now(db=db) 内部用 **7 天口径** count_pending（恒 63~65）⇒ has_dot 恒 True
    #   ⇒ 每轮都进 `CL.sweep()`（耗时 300~500s、且几乎清不掉任何东西）
    #   ⇒ 轮次预算被 sweep 吃光，匹配/唤醒连门都出不去。
    #   现在：入口也按 candidates（唯一判据）判；库不可用才退回 has_dot_now。
    #
    # 🔴🔴🔴 2026-11-09 P0 修复（18:42 新消息未处理 · 根因 B）：
    #   原来同步完库后直接走线性流程，candidates() 可能因为缓存陈旧判空，
    #   新消息就永远进不了队列。现在：如果本轮 _dirty=True，
    #   在这里强制重跑一次 candidates（上面的 invalidate 已经清了设备未读缓存，
    #   这次 candidates 会重新查设备库拿到最新未读集合）。
    #   _dirty 已经在上面 DBW.consume() 里被清掉了，这里用 _dirty_recheck 标志。
    _has_dot_n = -1
    try:
        _has_dot_n = len(PQ.candidates(db, limit=1) or [])
    except Exception as _e:
        log.debug("入口待回判定失败，退回 has_dot_now: %r", _e)
        _has_dot_n = -1
    if _has_dot_n >= 0:
        # 真有可处理候选 → 才去清红点；否则连 sweep 都不启动（省下整轮预算）
        has_dot = bool(_has_dot_n > 0)
        try:
            badge = CL.badge_chat(a.snap()) if has_dot else 0
        except Exception:
            badge = 0
        ndots = _has_dot_n
        if not has_dot:
            log.debug("入口：24h 内无真待回（7天口径另有 %s 个僵尸）→ 跳过清红点",
                      CL.count_pending(db))
    else:
        has_dot, badge, ndots = CL.has_dot_now(a, db=db)
    # 🔴 2026-11-03 修复 P0：门禁原来用 db.pending()（只含 unReadCount>0 的会话），
    #    而「已读未回」恰恰是 unReadCount=0（进去看过一眼红点就清零）——
    #    全库无未读时 pendingq 永不触发。门禁改为「是否有已读未回候选」，
    #    由 pendingq.candidates 扫全库判定（它不依赖 unread，见 pendingq.py）。

    replied_any = False
    left = 0
    entered = 0
    dot_blocks = False          # 红点是否真的要挡后续阶段（虚高角标不算）
    st.setdefault("last_msg_ts", time.time())   # 空闲切号的时间基准
    # 信号已用于触发上面的强制刷新，这里清掉（自己发消息也会写库，别自己骗自己）
    try:
        DBW.consume()
    except Exception:
        pass
    if has_dot:
        log.info("── 有红点：%d 个（角标 %s）──", ndots, badge)
        _hb("sweep-begin")          # 🔴 心跳：清扫可能跑 300~500s
        res = CL.sweep(a, db, dry_run=dry_run, dev=dev)
        _hb("sweep-end")
        st["last_reply"] = time.time()
        lock.touch("replied")
        # 🔴 2026-11-03 修复：原来用 entered>0 当「已回」。进了会话但没发出去
        #    （假红点/被打断/末条是我）也返回 replied → 主循环 1.5s 后立刻重来，
        #    这就是「轮次零间隔空烧」的一半。只有真正发出话才算 replied。
        replied_any = res["replied"] > 0
        left = res["left"] if res["left"] is not None else -1
        entered = res["entered"]
        # 🔴 2026-11-03 修复 P1（唤醒/匹配被永久饿死）：
        #    原来只要角标 != 0 就 return "replied"，而角标是 App 侧累计未读
        #    （本号长期虚高）。实测角标 2~4、屏上一个行内红点都没有，仍然
        #    每轮回去"清红点"，唤醒/匹配永远轮不到。
        #    现在只有「屏上真有行内红点」或「确实进了人」才挡后续。
        # 🔴🔴 2026-11-10（匹配段被饿死 11.8 小时 · 修）：
        #   稳态流入下（每 3 分钟进一条 / 一轮 200~440s）角标几乎永不为 0，
        #   `left != 0` 于是恒真 → dot_blocks 恒真 → 匹配段一次都进不去
        #   （实测「距上次匹配 42462s = 11.8h」，奇遇铃 9 个人一次没处理）。
        #   用户口径是「消息必回」优先、匹配只是带来新会话，不能拿它换掉回复。
        #   本轮已经跑过 sweep、且**真的发出话**（replied_any）→ 回复通道健康、
        #   红点已处理一轮，剩下的是这期间新到的，交给下一轮；本轮放行匹配。
        dot_blocks = bool(left != 0 and (ndots > 0 or entered > 0) and not replied_any)
        if left != 0 and not dot_blocks:
            log.info("角标=%s 但屏上无行内红点、也没进到人 → 判为虚高，不挡后续流程", left)
            try:
                CL._FAKE_DOT["until"] = time.time() + 300   # 短冷却，别再空转双击
            except Exception:
                pass

    # ③ 已读未回：**不再被红点闸挡住**（2026-11-03 修）。
    #    红点会话 ⊂ 「末条是她」的会话；dot_blocks 只表示"红点优先"，
    #    不该变成"互斥"。实测 15:09-15:24 每轮都被挡，她的消息等了 21 分钟。
    #    重复风险由 L2 末行 + 300s 回复台账兜住（dot 路径回过就会跳过）。
    if has_dot and left != 0 and dot_blocks:
        log.info("红点还没清完（剩 %s）→ 先补已读未回，下一轮继续清红点", left)
    try:
        _hb("pending-begin")        # 🔴 心跳：已读未回是最大的长耗时段（实测单轮 300~500s）
        pq = PQ.handle_pending(a, dev, db, dry_run=dry_run,
                               budget_s=(45.0 if dot_blocks else 60.0))
        _hb("pending-end")
        st["pending_sent"] = int(st.get("pending_sent", 0)) + pq["sent"]
        # 🔴 2026-11-08：消费 aborted，区分「正常收工」和「设备级故障中止」。
        #   pendingq 连续 3 次回不到 chatlist 会提前收工并置 aborted="not_chatlist"
        #   （见 pendingq.NOT_CHATLIST_MAX）。这里单独打一条，避免和正常结束混在一起，
        #   也便于事后统计「这台设备一天假死几次」。
        if pq.get("aborted") == "not_chatlist":
            log.warning("已读未回被设备级故障中止（连续多次回不到 chatlist）→ 本轮不再重试，"
                        "交给下一轮/watchdog")
        if pq["sent"]:
            replied_any = True
            log.info("已读未回补回 %d 条", pq["sent"])
    except Exception as e:
        log.warning("已读未回处理异常（不影响主流程）: %r", e)

    # 🔴🔴 2026-11-08 03:28（P0 死锁·空烧计数落地）
    #   这里是「回复侧到底行不行」的唯一权威判定点：
    #     · 本轮回成了人（清红点 or 补已读未回）→ 计数清零，恢复「回复优先」
    #     · 本轮一个人都没回成 → 计数 +1；连续 PENDING_ZERO_MAX 轮后闸门放行匹配
    #   注意用 `replied_any`（只有**真的发出话**才算，进会话但没发不算，
    #   见 clear.py / pendingq 的既有口径），不能拿「试过几次」当回成。
    try:
        if replied_any:
            if int(st.get("pending_zero_rounds", 0) or 0):
                log.info("本轮回成了人 → 空烧计数 %d 清零，恢复回复优先",
                         int(st.get("pending_zero_rounds", 0) or 0))
            st["pending_zero_rounds"] = 0
        else:
            _z = int(st.get("pending_zero_rounds", 0) or 0) + 1
            st["pending_zero_rounds"] = _z
            if _z >= PENDING_ZERO_MAX:
                log.warning("连续 %d 轮一个都没回成（回复侧失效）→ 闸门放行匹配，"
                            "先让匹配带来新会话", _z)
    except Exception as _e:
        log.debug("空烧计数更新失败（不阻断）: %r", _e)

    # ③-b 切号首巡 · 第二阶段：红点这一轮已经扫完 → 再去奇遇铃「稍后再聊」看有没有人等我去聊
    #
    #   🔴 2026-11-09 21:44 用户原话：「切号之后优先消除红点，然后再找聊天页面的
    #      奇遇铃 稍后再聊，点进去看看里面有没有人等着我去聊」。
    #   原来 ①-b 在红点之前，切号进来先钻铃列表；现在切号首巡把顺序倒过来：
    #     本轮 ②/③ 红点段已跑完 → 打上 post_switch_dot_seen → 这里进铃列表。
    #   只跑一次（post_switch_bell_done 置位后 _post_switch_phase 返回 ""），
    #   之后的轮次恢复「奇遇铃最高」的原链，不会每轮都去铃列表吃预算。
    try:
        _psw = _post_switch_phase(st, db)
        if _psw == "dot":
            # 红点段已经走完（不管清干净没清干净，这一轮该做的都做了）→ 进入阶段 B
            st["post_switch_dot_seen"] = True
            _psw = _post_switch_phase(st, db)
        if _psw == "bell":
            try:
                _bell_n = BELL.bell_daily_count(db.uid)
            except Exception:
                _bell_n = int(st.get("bell_list_n", 0) or 0)
            if _bell_n >= BELL.BELL_DAILY_MAX:
                # 🔴 2026-11-09 21:44 用户原话：「**点进去看看**里面有没有人等着我去聊」。
                #   今日已达到安全上限时不再发开场白，但仍进去看一眼，
                #   把「还有几个人在等」写进日志，
                #   否则用户看到的就是「悄无声息地没进去」。
                _ok_l, _why_l = BELL.open_list(a)
                if _ok_l:
                    try:
                        _rows = BELL.bell_list_rows(a.snap(force=True))
                    except Exception:
                        _rows = []
                    if _rows:
                        log.info("切号首巡：稍后再聊还有 %d 人等着（今日已发 %d / 上限 %d）"
                                 "：%s", len(_rows), _bell_n, BELL.BELL_DAILY_MAX,
                                 "、".join([r[0] for r in _rows[:5]]))
                    else:
                        log.info("切号首巡：稍后再聊没人等着")
                    try:
                        nav.to_chatlist(a)
                    except Exception:
                        pass
                else:
                    log.info("切号首巡：没有「奇遇铃-稍后再聊」入口（%s）", _why_l)
                st["post_switch_bell_done"] = True
            else:
                _ok_l, _why_l = BELL.open_list(a)
                if not _ok_l:
                    log.info("切号首巡：会话列表没有「奇遇铃-稍后再聊」或没人在等（%s）"
                             "→ 首巡结束", _why_l)
                    st["post_switch_bell_done"] = True
                else:
                    log.info("🔔 切号首巡：红点已扫过一轮 → 进入奇遇铃「稍后再聊」：%s", _why_l)
                    _lim = min(BELL.BELL_BATCH_MAX, BELL.BELL_DAILY_MAX - _bell_n)
                    _n_l, _msg_l = BELL.handle_list(
                        a, dev, dry_run=dry_run, limit=_lim, db=db, uid=db.uid)
                    try:
                        st["bell_list_n"] = BELL.bell_daily_count(db.uid)
                    except Exception:
                        st["bell_list_n"] = _bell_n + _n_l
                    st["last_bell"] = time.time()
                    st["post_switch_bell_done"] = True
                    log.info("🔔 切号首巡：「稍后再聊」结果 %s（今日已发 %d / 上限 %d）→ 恢复原链",
                             _msg_l, st["bell_list_n"], BELL.BELL_DAILY_MAX)
                    # 处理完回会话列表，别把后续阶段丢在铃页面里
                    try:
                        nav.to_chatlist(a)
                    except Exception:
                        pass
                    if _n_l:
                        return "bell"
    except Exception as _e:
        log.warning("切号首巡「稍后再聊」异常（不阻断）: %r", _e)

    # 🔴 2026-11-03 修复：预算判断原来放在 `if replied_any: return` 之后 —
    #    只要回过人，本轮永远不会被 600s 预算截断（实测 max 155.8s 尚未越界，
    #    但清红点+已读未回叠加时有越界风险）。先判预算，再判"刚回过人"。
    #
    # 🔴🔴 2026-11-08 03:22（P0 死锁第二处 · 用户：「我不是叫你去匹配吗」）
    #   改前：无条件 `return "budget"` —— 而积压处理会烧满 420~500s，
    #         于是每一轮都在「回复段」就把 600s 预算耗尽，**匹配段永远执行不到**。
    #   日志实证：`本轮已用 Xs（>600s 预算）→ 先收工` 218 次，
    #             而 `无人聊 → 星球匹配` 全天只有 49 次、连续匹配只跑过 1 次。
    #   改后：预算超了**不再直接 return**，先看「本轮到底有没有真的回过人」：
    #     · 回过人 → 正常收工（下一轮继续回）
    #     · 一条都没回成（纯空烧）→ **继续往下走匹配**，别让空烧把匹配也吃掉
    if time.time() - t_round > ROUND_BUDGET:
        if replied_any:
            log.warning("本轮已用 %.0fs（>%.0fs 预算）且已回过人 → 收工，下一轮继续",
                        time.time() - t_round, ROUND_BUDGET)
            return "budget"
        log.warning("本轮已用 %.0fs（>%.0fs 预算）但一条都没回成（纯空烧）"
                    "→ 不直接收工，继续走匹配", time.time() - t_round, ROUND_BUDGET)
        dot_blocks = False      # 空烧轮不再让红点挡匹配（否则又是同一个死锁）

    # ⏰ 8h 强制切号（本轮回复段**之后**执行 —— 这里切走不会丢掉刚回的这批消息）
    #   唯一例外：还有红点没清完时先回去清（切走那批红点就等 4h 了）；
    #   但超过 FORCE_HARD_H(10h) 硬顶时不管红点也切 —— 账号风控优先，别烧号。
    try:
        _due_hard = AC.online_hours() >= AC.FORCE_HARD_H
        if _due_hard or not dot_blocks:
            _sw, _why = AC.force_switch_if_due(a, dev, db, st)
            if _sw:
                log.warning("🔄 已切号：%s", _why)
                return "switched"
        else:
            # 2026-11-04 修日志误导：这段 else 的真含义是「有红点，所以本轮不去查强制切号」，
            #   并不代表已经到点。实测 online=1.3h 时它也打「到点该切号」，看着像要切号。
            _oh = AC.online_hours()
            if _oh >= AC.FORCE_SWITCH_H:
                log.info("⏰ 已在线 %.1fh（≥%.0fh）但还有红点 → 先清红点，下一轮再切",
                         _oh, AC.FORCE_SWITCH_H)
            else:
                log.debug("有红点 → 先清红点（在线 %.1fh，未到切号点）", _oh)
    except Exception as _e:
        log.warning("强制切号检查异常（不阻断）: %r", _e)

    if replied_any:
        # 刚回过人 -> 记时间（重置空闲计时）+ 立刻进下一轮，不空等
        st["last_msg_ts"] = time.time()
        # 🔴🔴 2026-11-08 02:45（用户：「先让副机脚本去匹配」「没人聊天就连续匹配花光额度」）
        #   原来这里**无条件 return** —— 只要本轮回过任意一条消息，匹配段永远执行不到。
        #   而现网积压 52~64 人、每轮降级只处理 10 条，于是：
        #     每一轮都有 replied_any=True → 每一轮都 return → 匹配被**永久饿死**。
        #   日志实证：11-08 全天只匹配 3 次，改了连续匹配（N=12）后仍然 1 次都没跑满，
        #   因为根本轮不到（02:13 那轮结尾就是「仍有红点 → 本轮不匹配」）。
        #
        #   现在：回过人之后**仍然允许匹配**，但加两道闸，防止"回消息"被挤掉：
        #     ① 本轮还没匹配过（last_match 距今 >= MATCH_EVERY）
        #     ② 本轮耗时没超预算的一半（留时间给下一轮回消息）
        #   红点/新消息优先级不变 —— 上面 dot_blocks 分支已经先 return 了。
        _now_r = time.time()
        _can_match = (
            _now_r - float(st.get("last_match", 0) or 0) >= MATCH_EVERY
            and (_now_r - t_round) < (ROUND_BUDGET * 0.5)
            and st.get("match_quota_day") != time.strftime("%Y-%m-%d")
        )
        if _can_match:
            log.info("已回过人，但匹配也到点（距上次 %.0fs）→ 继续走匹配段",
                     _now_r - float(st.get("last_match", 0) or 0))
            # 注意：**不 return**，往下走到 ④唤醒 / ⑤匹配
        else:
            return "replied"

    # 有红点没清完 / 回列表失败：先回去看消息，别急着匹配
    #
    # 🔴🔴 2026-11-08 03:58（P0 死锁·第三处硬闸）
    #   改前：`if dot_blocks: return "replied"` —— 而 dot_blocks = left != 0，
    #        left 是「清完红点还剩几个」，现网恒为 45~65（僵尸积压），
    #        于是**每一轮都在这里 return**，匹配段从函数出口就被堵死。
    #        实证：修复上线后 `无人聊 → 星球匹配` 仍为 0 次。
    #   改后：只有「真的还有**能回**的人没回完」才挡（24h 口径）；
    #        剩下全是过期僵尸 → 不挡，继续往下走匹配。
    if dot_blocks:
        _left_real = 0
        try:
            # 🔴 2026-11-08 04:02（统一判据）：和闸门/匹配循环一样用 candidates，
            #   不再用 should_reply（它不看冷却，会虚高）。
            _left_real = len(PQ.candidates(db, limit=1) or [])
        except Exception as _e:
            log.debug("剩余待回复核失败，保守按有红点处理: %r", _e)
            _left_real = 1
        if _left_real > 0:
            log.info("红点没清完（还剩 %d 个真能回的，原报 %s）→ 先回消息，下一轮再匹配",
                     _left_real, left)
            return "replied"
        log.info("红点剩余 %s 个全是过期僵尸（24h 内可回 0 人）→ 不挡匹配", left)

    # 🔴🔴 2026-11-08 03:35（用户口述定稿流程，**顺序必须改**）
    #
    #   用户的流程原话：
    #     「奇遇铃 → 新消息红点处理 → 已读未回 → **匹配** → **好友唤醒** →
    #       依然没人聊天 → 切号」
    #
    #   改前代码是 ④唤醒老友 → ⑤匹配，**和用户说的顺序相反**。
    #   后果（都是实测）：
    #     · 唤醒每 60s 才到点一次，但一旦触发就 `return "waked"` 直接结束本轮
    #       → 匹配段经常根本轮不到（`无人聊 → 星球匹配` 全天仅 49 次就是证据）
    #     · 用户要的是「没人聊天就去匹配」，先匹配（能带来**新**会话），
    #       唤醒老友是次选（老会话大多已冷）
    #   现在照用户口径对调：④匹配 → ⑤唤醒。
    #   两边都「有人可聊就不往下走」，优先级链保持完整。

    # ④ 匹配（有红点就不做，用户口径）
    if HAVE_DOT_BLOCK_MATCH:
        # 🔴 2026-11-08（库直读 P0）：同样传 db，走库判定（否则恒 False → 有未读还去匹配）
        # 🔴 2026-11-08 02:52（P0 死锁）：has_dot_now 单次 **10.5s**（含 dump + 重试导航），
        #   而连续匹配循环里每一步都要判一次，12 步 = 126s 纯开销。
        #   改成先用 count_pending（0.068s）快速判，只有它说"有"时才走慢的 has_dot_now。
        # 🔴🔴 2026-11-08 03:20（P0 死锁根治 · 用户：「我不是叫你去匹配吗」）
        #
        #   【改前】闸门判据是 CL.has_dot_now(a, db=db)：
        #     · 传了 db 时它**完全绕过屏幕**，只看 data.pending.count_pending(db)
        #     · count_pending(real_total=True) 数的是「末条是她」的**全部**会话（含冷却中、
        #       含过期积压），实测恒为 63 人
        #     · 而 pendingq.candidates() 里已按 STALE_GIVEUP_H=72 淘汰，实际可处理只剩 23~26
        #   ⇒ **淘汰逻辑改的是 candidates()，闸门判的却是 count_pending()，两者口径不一致**
        #     ⇒ 积压清不掉（定位 100% 失败）→ 闸门恒 True → 匹配永久饿死
        #   实测证据：`仍有红点 → 本轮不匹配` 28 次；`无人聊 → 星球匹配` 全库 49 次，
        #   而连续匹配的 `（本轮第 N/12 个）` **只出现过 1 次**。
        #
        #   【改后】闸门改用**真正拦得住人**的判据，三级递降：
        #     ① 有「新到的」待回（HOT，20 分钟内 / 未读）→ 必须立刻回，挡匹配
        #     ② 有「本轮真正可处理」的候选（candidates() 淘汰后仍有）→ 挡匹配
        #     ③ 以上都没有（积压全是过期/冷却中的僵尸）→ **放行匹配**
        #   这样用户要的「有活人等我必须先回」保持不变，但僵尸积压不再锁死匹配。
        has_dot2 = False
        _gate_why = ""
        try:
            from data import pending as _PD
            # 🔴🔴 2026-11-08 04:00（P0 死锁·统一判据）
            #   **全项目只允许一个「有没有人等我回」的判据 = PQ.candidates()**
            #   （它 = 24h 时效 + 冷却过滤 + 已回过滤 + 官方号过滤，是唯一和
            #     pendingq 实际会去处理的人一致的集合）。
            #   之前闸门用 count_pending/should_reply 各自算，导致：
            #     · 闸门说「没人能处理」→ 放行匹配
            #     · 匹配循环说「有人等」→ 立刻打断
            #   两句话自相矛盾，匹配永远跑不完。
            _n_fresh = 0
            _cands_now = None
            try:
                _cands_now = PQ.candidates(db, limit=5)
                _n_fresh = len(_cands_now or [])
            except Exception as _e:
                log.debug("candidates 预取失败: %r", _e)
                _cands_now = None
            # 🔴🔴 2026-11-12（DS-04 / HY-03 口径统一·最核心）：
            #   count_pending 之前用默认 real_total=True（含已回过/冷却中），
            #   而 candidates() 把冷却/已回/归档/verdict 全滤掉 → 两边差 N 倍。
            #   实测「待回 19 人但全是冷却中/已回的僵尸（candidates 为空）」→
            #   空烧 50~59 轮：闸门看到 count=19 以为「有人等」→ 不匹配，
            #   而这 19 个又全在冷却/已回台账里，candidates() 一个都拿不到 → 死锁。
            #   修法：改传 real_total=False，与 candidates 同口径（= 本轮真能处理）。
            #   （clear.py 的 has_dot_now 对应改动由流程层处理，此处只改这一处。）
            _np = _PD.count_pending(db, real_total=False,
                                    max_age_h=PQ.STALE_GIVEUP_H)
            # 🔴🔴 2026-11-08 03:26（P0 死锁·第三层：空烧降级）
            #   上面 ①②③ 仍然只是「队列里有没有人」——而现网的真问题是
            #   **队列里那 23~26 个人 100% 定位不到**（翻 3 屏未命中 633 次、
            #   搜索 notfound 598 次）。只要还有「名义上的待回」，闸门就恒真，
            #   匹配就永远进不去，而这些人又永远回不掉 —— 硬死锁。
            #
            #   用户口径是「没人聊天就去匹配」，不是「永远卡在回复失败里」。
            #   所以这里加**连续空烧降级**：
            #     连续 PENDING_ZERO_MAX 轮「一个都没回成」→ 承认回复侧此刻失效
            #     → 放行匹配（匹配至少还能带来新会话，比空烧强）
            #   一旦某轮真的回成了人 → 计数清零，闸门恢复正常（优先回复）。
            _zero = int(st.get("pending_zero_rounds", 0) or 0)
            if _n_fresh > 0:
                if _zero >= PENDING_ZERO_MAX:
                    has_dot2 = False
                    _gate_why = ("已有 %d 个待回，但连续 %d 轮一个都没回成（回复侧失效）"
                                 "→ 降级放行匹配" % (_n_fresh, _zero))
                else:
                    has_dot2 = True
                    _gate_why = "有 %d 个可立即处理的新待回（空烧 %d 轮）" % (_n_fresh, _zero)
            elif _np is not None and int(_np) > 0:
                # 注（2026-11-12 口径统一后）：_np 已是「本轮真能处理」口径，
                #   与 candidates 基本同源。此处作为**兜底安全网**仍保留：
                #   candidates 为空但 count(real_total=False) 说还有 ——
                #   说明差在 candidates 额外的设备存活/状态机过滤，这些不可处理
                #   就不该挡匹配（统一判据）。
                has_dot2 = False
                _gate_why = ("待回 %s 人但全是冷却中/已回的僵尸（candidates 为空）"
                             "→ 不挡匹配" % _np)
            else:
                has_dot2 = False
                _gate_why = "库里无待回（count_pending=%r）" % (_np,)
            if not has_dot2:
                log.info("红点闸放行匹配：%s", _gate_why)
        except Exception as _e:
            log.warning("待回快速判定异常，退回原判据: %r", _e)
            has_dot2, _b2, _n2 = CL.has_dot_now(a, db=db)
            _gate_why = "异常兜底，走 has_dot_now"
        if has_dot2:
            log.info("仍有红点 → 本轮不匹配，回去看消息（%s）", _gate_why)
            return "replied"

    now = time.time()
    if st.get("match_quota_day") == time.strftime("%Y-%m-%d"):
        log.info("今日匹配额度已用完（已记）→ 跳过匹配，直接走唤醒")
    elif now - float(st.get("last_match", 0)) >= MATCH_EVERY:
        broken = float(st.get("match_broken_at", 0) or 0)
        if broken and (now - broken) < MATCH_SILENT:
            log.info("匹配通道静默中（还剩 %.0fs）", MATCH_SILENT - (now - broken))
        else:
            # 🔴 2026-11-08（用户：把匹配次数花光）：连续匹配循环。
            #   每一步之前都重新检查「有没有红点 / 有没有新消息」——
            #   用户硬规则「有红点就先回复」优先于匹配，任何时候都不能被挤掉。
            t_streak = time.time()
            n_done = 0
            n_fail = 0
            last_res = ""
            for i in range(MATCH_STREAK_N):
                # ① 每步前看红点
                #   🔴 2026-11-08 02:52：原来每步都调 CL.has_dot_now（实测 **10.5s/次**，
                #   含 dump + 重试导航）→ 12 步 = 126s 纯开销，把 420s 预算吃掉 30%。
                #   改成先用 count_pending（0.068s，库直读）快速判：
                #     · 没待回 → 直接放行，连 dump 都不做
                #     · 有待回 → 再走一次 has_dot_now 确认（这才是慢的那个）
                try:
                    _hd = False
                    try:
                        # 🔴🔴 2026-11-08 04:00（P0 死锁·最后的逻辑矛盾）
                        #
                        #   现象（实测日志）：
                        #     03:53:15 红点闸放行匹配：待回 12 人但全是过期/冷却中的
                        #              （candidates 为空）→ 不挡匹配
                        #     03:53:16 ⚡ 连续匹配途中出现红点（24h 内真有人等）
                        #              → 立刻停下回去回复（已匹配 0 个）
                        #   两行**自相矛盾**：闸门刚说「没人能处理」，循环里又说「有人等」。
                        #
                        #   根因：两处用了不同判据 ——
                        #     · 闸门用 PQ.candidates()（含冷却过滤 + 24h 淘汰）
                        #     · 这里用 count_pending(max_age_h=24h)（**只按时间过滤，不看冷却**）
                        #   于是「24h 内但正在 notfound 冷却中」的人：
                        #     闸门认为「不可处理」→ 放行匹配，
                        #     循环认为「有人在等」→ 立刻打断匹配。
                        #   ⇒ 匹配永远刚起步就被打断，一次都跑不完。
                        #
                        #   改后：**统一用 PQ.candidates()**（和闸门完全同一个判据）。
                        #   只有「真的还能去回的人」才打断匹配。
                        _cands2 = PQ.candidates(db, limit=1)
                        _hd = bool(_cands2)
                    except Exception:
                        # 库不可用才退回屏幕判定（慢，但保底）
                        _hd, _b, _n = CL.has_dot_now(a, db=db)
                    if _hd:
                        log.info("⚡ 连续匹配途中出现红点（有可处理候选）"
                                 "→ 立刻停下回去回复（已匹配 %d 个）", n_done)
                        break
                except Exception:
                    pass
                # ② 每步前看库有没有新消息（比红点更早，不用等 App 同步未读数）
                try:
                    from data import watch as _W2
                    if _W2.urgent():
                        log.info("⚡ 连续匹配途中库有新消息 → 停下回去回复（已匹配 %d 个）", n_done)
                        _W2.consume()
                        break
                except Exception:
                    pass
                # ③ 预算/失败保护
                if time.time() - t_streak > MATCH_STREAK_BUDGET:
                    log.info("连续匹配用满 %.0fs 预算 → 先停（已匹配 %d 个，余下轮次继续）",
                             MATCH_STREAK_BUDGET, n_done)
                    break
                if n_fail >= MATCH_STREAK_FAIL_MAX:
                    log.warning("连续匹配失败 %d 次 → 停手（判定通道异常）", n_fail)
                    break

                log.info("── 无人聊 → 星球匹配（本轮第 %d/%d 个）──", i + 1, MATCH_STREAK_N)
                res = do_match(a, dev, db, st, dry_run=dry_run)
                st["last_match"] = time.time()
                lock.touch("matched")
                last_res = res or ""
                # 🔴 2026-11-13 修复 HY-05（P2 死代码）：do_match 早已只返回字符串
                #   （"fail"/"matched"/…），从不返回 False —— `or res is False` 恒假，
                #   是残留旧判断，混淆熔断语义。只保留 `res == "fail"`。
                if res == "fail":
                    n_fail += 1
                    st["match_fail"] = int(st.get("match_fail", 0)) + 1
                    if st["match_fail"] >= 2:
                        st["match_broken_at"] = time.time()
                        st["match_fail"] = 0
                        log.warning("匹配连续失败 → 静默 %.0f 分钟", MATCH_SILENT / 60)
                        break
                    continue
                else:
                    n_fail = 0
                    st["match_fail"] = 0
                    n_done += 1

                # ④ 额度用完就是终点（用户要的是"花光"）
                if res == "no_quota":
                    log.info("今日匹配额度已用完（本轮共匹配 %d 个）→ 转唤醒", n_done)
                    st["match_quota_day"] = time.strftime("%Y-%m-%d")
                    break
                # ⑤ 被人打断（新消息/铃）就立刻让位
                if res == "preempted":
                    log.info("匹配途中被打断 → 立刻回去处理消息（已匹配 %d 个）", n_done)
                    return "replied"
                # ⑥ 小间隔，避免连点太快被判机器
                if i < MATCH_STREAK_N - 1:
                    time.sleep(max(1.0, MATCH_EVERY - 5.0))

            if n_done:
                log.info("本轮连续匹配完成：成功 %d 个", n_done)
            if last_res == "no_quota":
                return "noquota"
            if n_done:
                return "matched"
            # 🔴 2026-11-08 03:35（用户流程）：匹配**一个都没成** → 不 return，
            #   继续往下走「⑤ 好友唤醒」。原来这里无条件 return "replied"，
            #   唤醒段在匹配到点的轮次里永远执行不到。
            log.info("本轮匹配一个都没成 → 转好友唤醒")

    # ⑤ 唤醒老友（用户流程：「匹配 → 好友唤醒」；按人计，24h 同人只唤一次）
    now = time.time()
    if now - float(st.get("last_wake", 0)) >= WAKE_EVERY:
        n = do_wake(a, dev, db, st, dry_run=dry_run)
        st["last_wake"] = time.time()
        lock.touch("waked")
        if n:
            return "waked"

    # ⑥ 账号轮转：榨干配额 或 在线 8h 强制切
    # 🔴 2026-11-09 R8（用户拍板「当前账号没榨干不切号」）：
    #   切号前先看「还有没有冷却中的人在等」——冷却中≠没人可聊。
    #   实测 21:21「待回 4 人全是冷却中」被判无人可聊 → 30 秒后切号，
    #   那 4 个人被丢给另一账号最多 8 小时。R3 已把 notfound 冷却压到 5 分钟，
    #   这里再多等一口气，等冷却到期重试完再决定切不切。
    #   注意：只挡切号，不动匹配闸门（避免 11-08「匹配饿死」回潮）。
    try:
        _n_wait, _left_min = PQ.cooldown_waiting(30.0)
        if _n_wait and _left_min > 0:
            log.info("切号前先等冷却：%d 个会话在冷却中（最久剩 %.0f 分钟）→ 本轮不切号",
                     _n_wait, _left_min)
            _skip_switch = True
        else:
            _skip_switch = False
    except Exception as _e:
        log.debug("冷却中检查异常（按可切处理）: %r", _e)
        _skip_switch = False

    if not _skip_switch:
        try:
            sw, why = AC.maybe_switch(a, dev, db, st)
            if sw:
                log.warning("🔄 已切号：%s", why)
                return "switched"
        except Exception as e:
            log.warning("账号轮转异常（不阻断）: %r", e)

    # ⑦ 空闲：只有「确实无人可聊、无事可做」才在这里等
    log.info("空闲 %.0fs（无待回/无红点/匹配与唤醒都在冷却）", IDLE_SLEEP)
    return "idle"


def wait_bell(actor, dev, total, step=5.0):
    """分片等待：每 step 秒扫一眼铃，弹了立刻抢占处理。返回是否处理了铃。

    用户 2026-11-02：「每 5 秒扫一次，弹了立刻抢占处理，没弹就走正常流程」。
    为什么分片而不是直接 sleep(total)：铃存活时间短（实测几十秒就消失），
    一整段睡过去就错过了。
    """
    end = time.time() + max(0.0, total)
    while time.time() < end:
        left = end - time.time()
        time.sleep(min(step, max(0.5, left)))
        try:
            if BELL.is_bell(actor.snap(force=True), dev=dev):
                ok, why = BELL.handle(actor, dev)
                log.info("🔔 等待期抢占：ok=%s %s", ok, why)
                return True
        except Exception as e:
            log.warning("等待期铃检查异常: %r", e)
    return False


def _preempt_now(a, dev, db):
    """匹配途中要不要立刻退出？返回原因字符串或 None。

    用户 2026-11-02：「有铃抢占」「匹配中有新消息也要退出来」。
    这个检查在**开场白发完之后**才调用（见 match.run_once），
    所以退出不会浪费匹配次数。
    """
    try:
        if BELL.is_bell(a.snap(force=True), dev=dev):
            return "奇遇铃"
    except Exception:
        pass
    try:
        if DBW.urgent():
            return "数据库有新写入（可能新消息）"
    except Exception:
        pass
    # 🔴 2026-11-02 修：**不能**再用 `session.unReadCount > 0` 当抢占判据。
    #    unReadCount 是 App 侧的累计未读，历史遗留（本号长期有 6 个）永远不为 0
    #    → 每次匹配发完开场白立刻被判「有新消息」退出，回去又清不掉，
    #      于是 12:08/12:11/12:13 反复「匹配→发一句→退出」，这就是用户看到的空烧。
    #    真正的新消息只认 WAL 指纹变化（DBW.urgent），而自己写库已被
    #    mark_self_write 封住（match.run_once 开头 mark 40s）。
    return None


def do_match(a, dev, db, st, dry_run=False):
    """走到星球页开一次匹配，处理这个人。返回是否真的匹配到人。"""
    snap, pg = M.start_match(a)
    if pg == "no_quota":
        # 今日额度 50/50 用完：当天不再尝试（明天自然恢复）。
        # 不去点「购次数卡」也不做任务 —— 那是花钱/耗时的事，不归我们干。
        log.warning("⚡ 今日匹配额度已用完 → 今天不再匹配（明天 0 点恢复）")
        st["match_quota_day"] = time.strftime("%Y-%m-%d")
        return "no_quota"
    if pg != "chat":
        # 🔴 2026-11-08 21:0x（P0 空烧的第二个根因）：
        #   这里原来 `return False`，而连打循环只把字符串 "fail" 当失败，`False`
        #   落进 else 分支被当成「成功匹配 1 个」→ n_fail 永远归零 → 熔断器
        #   （MATCH_STREAK_FAIL_MAX=3）一次都不会触发。
        #   实测 20:00-20:52：星球页识别坏掉后每轮连打 12 次、每次 ~45s
        #   （back→am start→重启 App 全走一遍），一轮空烧 9 分钟，回复彻底停摆。
        #   改成返回 "fail"，让熔断器真的起作用。
        log.warning("没进到匹配会话页（%s）→ 记一次失败", pg)
        return "fail"

    out = M.run_once(a, dev, db, dry_run=dry_run,
                     preempt=lambda: _preempt_now(a, dev, db))
    # 🔴 2026-11-03 修复 P1：抢占留会话时，下次进来 run_once 判「已说过话」，
    #    之前这里把它当失败直接 return、跳过 advance → 永远卡在同一张匹配卡。
    #    已说过话 = 这个会话已经聊过了，直接前进（不浪费额度，也不卡死）。
    if out.get("skip_said"):
        log.info("该匹配会话已说过话 → 前进到下一个人（不重发）")
        M.advance(a)
        return True
    if out["err"] and not out["sent"]:
        log.warning("本轮匹配未发送: %s", out["err"])
        # 没发出去就不要点匹配下一个（白费次数）
        return "ok" if out["ok"] else "fail"

    log.info("✓ 匹配开场白已发 %r", out["text"])

    # 🔴 用户铁律：「匹配中有新消息也要退出来，但是退出之前一定要把开场白发了来」。
    #    开场白已经在上面发出去了，这里才允许退出；**不点「匹配下一个」**，
    #    把这次匹配保留下来（下次进来会判"已说过话"再前进），不浪费次数。
    if out.get("preempted"):
        log.info("⚡ 因「%s」提前退出匹配（开场白已发，不点下一个）", out["preempted"])
        return "preempted"
    # 前进到下一个人，为下一轮准备（若没有「匹配下一个」会回星球重新匹配）
    M.advance(a)
    return True


def do_wake(a, dev, db, st, dry_run=False):
    """唤醒 1~2 个冷掉的老联系人。返回成功条数。"""
    plan = W.plan(db, n=W.MAX_PER_ROUND)
    if not plan:
        log.info("唤醒：没有候选")
        return 0
    # 🔴 进唤醒前先清一次库变化信号：这一轮前面（回复/红点/匹配）自己的写入
    #    还挂在 dirty 上，不清掉的话第一个人就会被「检测到新消息」拦下，
    #    唤醒永远发不出去（实测日志连续出现「唤醒 OK 后立刻中断」）。
    try:
        DBW.consume()
    except Exception:
        pass
    okn = 0
    for cand, text in plan:
        # ⚡ 唤醒途中新消息进来 → 立刻收工回去回消息（用户：不要让别人久等）
        try:
            if DBW.urgent():
                log.info("⚡ 唤醒途中检测到新消息 → 中断唤醒")
                break
        except Exception:
            pass
        # 🔔 奇遇铃抢占一切（用户 2026-11-09 定链：铃 > 新消息 > 红点 > 已读未回）：
        #   唤醒途中铃弹出来 → 就地处理完再收工，别让铃被后续动作盖掉
        #   （对齐 clear.py「回复途中来了奇遇铃 → 中断清扫先处理」的既有做法）。
        if not dry_run:
            try:
                if BELL.is_bell(a.snap(force=True), dev=dev):
                    log.info("🔔 唤醒途中来了奇遇铃 → 就地处理，中断本轮唤醒")
                    _ok, _why = BELL.handle(a, dev, dry_run=dry_run)
                    log.info("🔔 铃处理 ok=%s %s", _ok, _why)
                    break
            except Exception:
                pass
        # 🔴 2026-11-08 03:42（用户口径：找不到人也算一次，三次永久放弃）
        #   send_wake() 内部对「找不到人」的各类失败已调 wake._bump_miss() 记过一次
        #   （c<uid> +1，见 wake.py）。这里**只在它整个抛异常时**补记 ——
        #   那种情况说明它内部没走到记账分支。否则同一次失败会被算两次，
        #   让「三次放弃」实际变成「1.5 次就放弃」。
        _raised = False
        try:
            ok, why = W.send_wake(a, dev, cand, text, db)
        except Exception as e:
            log.warning("唤醒 uid=%s 异常: %r", cand.uid, e)
            ok, why = False, repr(e)
            _raised = True
        log.info("唤醒 uid=%s %r -> %s", cand.uid, text[:20], "OK" if ok else why)
        if ok:
            okn += 1
        elif _raised:
            try:
                W._bump_miss(cand.uid, "执行异常")
            except Exception as e:
                log.debug("异常记账失败: %r", e)
        lock.touch("wake:%s" % cand.uid)
    return okn


# ---------------- 主循环 ----------------
def _init_account(dev, max_retries=None):
    """启动初始化：确保 root + 打开账号库。失败则带自愈重试，**不退出进程**。

    🔴🔴 2026-11-11（watchdog_restart 一天 243 次专项 · 根因）：
      原实现把 `Device.get()` + `dev.ensure_root()` + `open_account(dev)` 直接
      写在 run() 里：
        · `Device.get()` 在 lock.acquire **之前**，设备不在时 probe_serial 抛
          RuntimeError → 进程连 pid 都没写就退出；
        · `ensure_root()` / `open_account()` 在**没有 except 的 try** 里，
          异常会穿过 finally 直接终结进程（watchdog 看到 pid 死 → 拉起 → 再崩）。
      两者都形成「watchdog 拉起→再崩→再拉」风暴（guard.watchdog.log 一天
      243 次「拉起 daemon」，即 nightly_collect 报的 watchdog_restart）。

      现在：启动初始化失败不再退出进程，而是复用主循环的设备自愈梯度
      （_dev_rescue）原地重试，期间持续 touch 心跳 —— watchdog 不会误判
      卡死；等设备/账号恢复后正常进入主循环。

    max_retries=None（daemon 常驻）：无限重试，进程必须活着等设备恢复。
    max_retries=N（once 演练）：最多试 N 次就抛异常，别让单轮命令挂死。
    """
    fails = 0
    while True:
        try:
            if dev is None:
                dev = Device.get()
            if not dev.ensure_root():
                raise RuntimeError("ensure_root 返回 False（adbd 非 root）")
            db = open_account(dev)
            log.info("当前账号 uid=%s sessions=%d", db.uid, db.stats().get("sessions", 0))
            return dev, db
        except Exception as e:
            fails += 1
            if max_retries is not None and fails > max_retries:
                raise
            log.warning("启动初始化第 %d 次失败: %r → 设备自愈 + %.0fs 后重试",
                        fails, e, STARTUP_RETRY_S)
            if dev is not None:
                try:
                    _dev_rescue(dev, fails)
                except Exception as _e2:
                    log.debug("启动自愈异常: %r", _e2)
            try:
                lock.touch("init-retry")
            except Exception:
                pass
            time.sleep(STARTUP_RETRY_S)


def run(once=False, dry_run=False):
    st = load_state()

    ok, why = lock.acquire("daemon")
    if not ok:
        log.error("拿不到锁：%s（另一个实例在跑？）", why)
        return 3

    # 🔴🔴 2026-11-11（watchdog_restart 异常 · 崩溃循环根治）：
    #   落 pid 必须**在设备探测/开库之前**。原代码 `Device.get()` 在 lock.acquire
    #   之前跑，设备不在时 probe_serial 抛 RuntimeError → 进程还没写 pid 就退出
    #   → watchdog 读到的还是上一个死 pid → 判死 → 反复拉起 → 崩溃循环（实测 243 次/日）。
    #   现在：确认持锁后立刻写 pid，让 watchdog 全程看到「本进程活着」。
    try:
        (STATE / "daemon.pid").write_text(str(os.getpid()), "utf-8")
    except Exception as e:
        log.warning("写 pid 失败: %r", e)

    log.info("=== soul1.0 daemon 启动 pid=%s ===", os.getpid())
    # 空闲计时从启动算起（acct 的兜底切号要用；不初始化会一直是 0 → 永不切）
    try:
        from brain import acct as _AC0
        _AC0.mark_active()
    except Exception:
        pass
    # 打印真正生效的模型（与 brain.engine.llm.ARK_MODEL 同源，避免日志与实跑口径不一致）
    try:
        from brain.engine.llm import ARK_MODEL as _ark_model_shown
    except Exception:
        _ark_model_shown = os.environ.get("SOUL_ARK_MODEL_DIRECT") or "(见 config/model.env.example)"
    log.info("出话模型: %s  @  %s", _ark_model_shown,
             os.environ.get("SOUL_ARK_URL_DIRECT", "(默认方舟)"))
    _v9 = os.environ.get("SOUL_PROMPT_V9", "1") == "1"
    log.info("出话结构: %s", "V9（人设+她的档案 → system，她的话 → user）" if _v9
             else "老结构（%s）" % os.environ.get("SOUL_FLOW", "hybrid"))
    if not _v9:
        log.info("老结构参数: 画像 %s | 三技能缓存 %ss | ③轮压缩 %s字",
                 os.environ.get("SOUL_PORTRAIT", "data"),
                 os.environ.get("SOUL_FC_MEMO", "900"),
                 os.environ.get("SOUL_FC_LEAN", "600"))
    log.info("节奏：匹配 %.0fs / 唤醒 %.0fs / 空闲 %.0fs", MATCH_EVERY, WAKE_EVERY, IDLE_SLEEP)

    rounds = 0
    try:
        # 🔴 2026-11-11：启动初始化带自愈重试（见 _init_account docstring）。
        #    避免 ensure_root/open_account 抛异常 → NameError → daemon 崩溃 →
        #    watchdog 无限拉起（watchdog_restart 一天 243 次）。
        #    Device.get() 也在重试循环内：设备不在时 probe_serial 抛异常，
        #    原代码因此连 pid 都没写就退出 → watchdog 判死反复拉起。
        #    once 模式（单轮演练）不无限重试：跑 3 次仍起不来就报错退出，
        #    否则 `run.py once` 在设备挂死时也会被拖进长循环。
        dev = None
        dev, db = _init_account(dev, max_retries=(2 if once else None))
        a = Actor(dev)
        # 把库句柄交给出话层：它要用它数「当前会话聊了多少轮」来判断关系阶段
        try:
            R.set_db(db)
        except Exception as e:
            log.warning("reply.set_db 失败（阶段注入会缺失）: %r", e)
        # 🔴 数据库实时监控（用户 2026-11-02）：后台 stat 库文件，有新写入立刻打断当前流程
        try:
            DBW.attach(dev, "/data/data/cn.soulapp.android/databases/" + db.path.name)
            log.info("数据库监控已挂上：%s", db.path.name)
        except Exception as e:
            log.warning("数据库监控挂载失败（降级为轮首查库）: %r", e)

        while True:
            rounds += 1
            t0 = time.time()
            lock.touch("round")
            try:
                if not device_ready(dev, a):
                    st["dev_fail"] = int(st.get("dev_fail", 0) or 0) + 1
                    _fails = st["dev_fail"]
                    log.warning("设备不可用（连续 %d 次）→ 自愈/%.0fs 后重试",
                                _fails, DEV_RETRY)
                    try:
                        _dev_rescue(dev, _fails)
                    except Exception as e:
                        log.warning("设备自愈异常: %r", e)
                    save_state(st)
                    time.sleep(DEV_RETRY)
                    continue
                if st.get("dev_fail"):
                    log.info("设备已恢复（此前连续失败 %s 次）", st.get("dev_fail"))
                    st["dev_fail"] = 0
                    save_state(st)

                ensure_app(dev)
                # 🔴 2026-11-10 §111（P0 安全缺陷）：原来这里漏传 dry_run，
                #   `cycle(a, dev, db, st)` 用的是默认 False —— 于是 `run.py once --dry`
                #   **一路真发**：实测 16:34 一轮 dry 给 4 个会话发出去 9 条消息
                #   （含给同一人连发 3 条开场白）。演练必须是演练。
                what = cycle(a, dev, db, st, dry_run=dry_run)
                # 🔴 2026-11-08 21:3x：把「真干了活」的轮次记成活跃时间，
                #   供 acct 的空闲兜底切号（读不到匹配次数时按空闲时长决定是否切）。
                if what in ("replied", "matched", "waked", "switched", "bell"):
                    try:
                        from brain import acct as _AC2
                        _AC2.mark_active()
                    except Exception:
                        pass
                log.info("[第 %d 轮] %s  用时 %.1fs", rounds, what, time.time() - t0)
                save_state(st)

                if once:
                    break
                if what == "idle":
                    # 🔔 奇遇铃抢占一切（用户 2026-11-09 定链）：
                    #   空闲等待也要分片扫铃 —— 铃只存活几十秒，一整段睡
                    #   IDLE_SLEEP(30s) 就错过（实测铃存活性短）。
                    #   wait_bell 每 5s 扫一眼，弹了就立刻处理，占满整个空闲窗。
                    try:
                        wait_bell(a, dev, IDLE_SLEEP)
                    except Exception:
                        time.sleep(IDLE_SLEEP)      # 扫铃异常兜底，别让空闲段白等
                elif what == "blocked":
                    time.sleep(30)
                elif what in ("replied", "bell"):
                    time.sleep(1.5)             # 刚回完人 -> 立刻看有没有新消息
                else:
                    time.sleep(2)
            except KeyboardInterrupt:
                log.info("收到中断 → 退出")
                break
            except Exception:
                log.error("单轮异常:\n%s", traceback.format_exc())
                save_state(st)
                time.sleep(60)
                if rounds > 10000:
                    break
    finally:
        lock.release()
    log.info("=== daemon 退出（共 %d 轮）===", locals().get("rounds", 0))
    return 0


def main():
    ap = argparse.ArgumentParser(description="soul1.0 daemon")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--dry", action="store_true", help="只判断不发送")
    args = ap.parse_args()
    return run(once=args.once, dry_run=args.dry)


if __name__ == "__main__":
    sys.exit(main())
