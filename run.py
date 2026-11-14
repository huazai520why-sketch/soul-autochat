# -*- coding: utf-8 -*-
"""soul1.0 统一入口。

    python run.py check             # 环境自检（设备/账号/库/引擎），不发任何消息
    python run.py screen            # 识屏：当前页面 + 红点 + 会话行
    python run.py once              # 跑一轮主循环就退出（会真发消息）
    python run.py once --dry        # 跑一轮但只判断不发送
    python run.py daemon            # 常驻主循环
    python run.py watchdog          # 看门狗（守护 daemon 存活）
    python run.py wake [N]          # 单独跑 N 个唤醒
    python run.py match [N]         # 单独跑 N 轮星球匹配
    python run.py clear             # 单独清一轮红点（进会话必回）
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 🔴 2026-11-03：模型配置外置到 config/model.env。
#    为什么不写进命令行：key 会出现在进程列表里（wmic 一眼可见）。
#    为什么必须在 import 其他模块之前：soul_brain 在 import 期就读 ARK_KEY/URL/MODEL。
def _load_model_env():
    import io as _io
    import os as _os
    p = _os.path.join(str(ROOT), "config", "model.env")
    if not _os.path.exists(p):
        return
    try:
        for ln in _io.open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            _os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_model_env()

from core.device import Device  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.paths import BASE  # noqa: E402

log = get_logger("run")


def cmd_check():
    """环境自检：不发消息，只报告能不能干活。"""
    from brain import reply as R
    from brain.act import Actor
    from data.imdb import open_account
    from eyes.page import badges, detect

    print("== soul1.0 自检 ==")
    print("目录 %s" % BASE)

    ok = 0
    fail = 0

    def line(name, val, good=True):
        nonlocal ok, fail
        print("  %-14s %s" % (name, val))
        if good:
            ok += 1
        else:
            fail += 1

    dev = Device.get()
    line("adb", dev.adb)
    line("serial", dev.serial)
    try:
        if not dev.root_ok():
            dev.ensure_root()
        line("root", "uid=0 OK" if dev.root_ok() else "NO", dev.root_ok())
    except Exception as e:
        line("root", "FAIL %r" % e, False)
    try:
        w, h = dev.wm_size()
        line("屏幕", "%dx%d" % (w, h), bool(w))
    except Exception as e:
        line("屏幕", "FAIL %r" % e, False)
    try:
        t0 = time.time()
        png = dev.screencap()
        line("截图", "%d bytes %.2fs" % (len(png), time.time() - t0), len(png) > 5000)
    except Exception as e:
        line("截图", "FAIL %r" % e, False)

    try:
        a = Actor(dev)
        t0 = time.time()
        snap = a.snap(force=True)
        line("UI 树", "%d 节点 %.2fs" % (len(snap.nodes), time.time() - t0))
        line("页面", detect(snap))
        line("红点", badges(snap) or "-")
    except Exception as e:
        line("UI 树", "FAIL %r" % e, False)

    try:
        db = open_account(dev, force=True)   # 自检要最新
        st = db.stats()
        line("账号", "uid=%s" % db.uid)
        line("数据", "会话 %s / 消息 %s / 未读 %s"
             % (st.get("sessions"), st.get("messages"), st.get("unread")))
    except Exception as e:
        line("数据", "FAIL %r" % e, False)

    try:
        b = R.engine()
        line("出话引擎", "OK (PERSONA %d 字)" % len(getattr(b, "PERSONA", "") or ""))
    except Exception as e:
        line("出话引擎", "FAIL %r" % e, False)

    try:
        from brain import casepack as CP
        line("案情包", "OK" if CP.engine() else "FAIL", bool(CP.engine()))
    except Exception as e:
        line("案情包", "FAIL %r" % e, False)

    print("\n通过 %d / 失败 %d" % (ok, fail))
    return 0 if fail == 0 else 1


def cmd_screen():
    from brain.act import Actor
    from brain import clear as CL
    from eyes.page import detect, badges

    a = Actor(Device.get())
    snap = a.snap(force=True)
    print("page=%s sig=%s nodes=%d" % (detect(snap), snap.signature(), len(snap.nodes)))
    print("badges=%s" % (badges(snap) or "-"))
    if detect(snap) == "chatlist":
        rs = CL.rows(snap)
        ds = CL.dots(snap)
        print("会话行 %d，其中红点 %d" % (len(rs), len(ds)))
        for r in rs[:12]:
            print("  y=%-5d %s%s" % (r.center[1], "[红点%s] " % r.badge if r.has_dot else "", r.blob[:52]))
    return 0


def cmd_once(dry=False):
    from guard import daemon as D
    return D.run(once=True, dry_run=dry)


def cmd_daemon():
    from guard import daemon as D
    return D.run(once=False)


def cmd_watchdog():
    from guard import watchdog as W
    # 🔴 2026-11-03 修复：watchdog.main() 自己会再 parse 一次 sys.argv，
    #    而顶层命令 `watchdog` 还在 argv 里 → argparse 判「未知参数」直接 exit 2
    #    （计划任务 LastTaskResult=2，守护根本起不来）。显式传空列表。
    return W.main([])


def cmd_wake(n=2):
    from brain import wake as W
    from brain.act import Actor
    from data.imdb import open_account

    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    print("账号 uid=%s" % db.uid)
    plan = W.plan(db, n=n)
    if not plan:
        print("没有唤醒候选（需 ≥%d 句、冷 ≥%dh、24h 内没唤过）"
              % (W.MIN_MSGS, W.COLD_HOURS))
        return 1
    ok = 0
    for cand, text in plan:
        print("\nuid=%s 冷 %.1fh  %r" % (cand.uid, cand.cold_h, text))
        good, why = W.send_wake(a, dev, cand, text, db)
        print("  -> %s %s" % ("OK" if good else "FAIL", why))
        if good:
            ok += 1
    print("\n成功 %d / %d" % (ok, len(plan)))
    return 0 if ok else 2


def cmd_match(n=3):
    from brain import match_runner as L
    return L.main(rounds=n, dry=False)


def cmd_bell(every=5, once=False):
    """只盯奇遇铃：每 5s 扫一次，弹了立刻处理。

    为什么要单独一条命令：铃只弹一次、存活时间短，daemon 一轮 80s 容易错过。
    想看铃能不能自动接住时，单独跑这个最直接。
    """
    import time as _t
    from brain import bell as B
    from brain.act import Actor

    dev = Device.get()
    a = Actor(dev)
    print("盯铃中（每 %.0fs 一次，Ctrl+C 退出）" % every)
    n = 0
    while True:
        try:
            snap = a.snap(force=True)
            if B.is_bell(snap, dev=dev):
                print("[%s] 🔔 发现奇遇铃" % _t.strftime("%H:%M:%S"))
                ok, why = B.handle(a, dev)
                print("[%s] 🔔 处理 ok=%s %s" % (_t.strftime("%H:%M:%S"), ok, why))
                n += 1
                if once:
                    return 0 if ok else 1
            else:
                if once:
                    print("没有铃")
                    return 2
        except KeyboardInterrupt:
            print("退出（共处理 %d 个铃）" % n)
            return 0
        except Exception as e:
            print("异常（继续盯）: %r" % e)
        _t.sleep(every)


def cmd_clear():
    from brain import clear as CL
    from brain.act import Actor
    from data.imdb import open_account

    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    res = CL.sweep(a, db, dev=dev)
    print("进 %d 人 / 回 %d 条 / 剩余角标=%s"
          % (res["entered"], res["replied"], res["left"]))
    return 0


def cmd_pending(n=5, dry=False):
    from brain import pendingq as PQ
    from brain.act import Actor
    from data.imdb import open_account

    dev = Device.get()
    a = Actor(dev)
    db = open_account(dev)
    cands = PQ.candidates(db, n)
    print("待回候选 %d 个：" % len(cands))
    now_ms = time.time() * 1000.0
    for sid, to_uid, txt, ts in cands:
        print("   sid=%-18s uid=%-10s %5.1fh前 %r"
              % (sid, to_uid, (now_ms - float(ts or 0)) / 3600000.0, txt[:30]))
    if not cands:
        return 1
    res = PQ.handle_pending(a, dev, db, max_n=n, dry_run=dry)
    print("\n回 %d / 试 %d / 跳过 %d" % (res["sent"], res["tried"], res["skipped"]))
    return 0


def main():
    # 🔴 2026-11-08 21:1x（修复 §79/§80 遗留 P1「daemon.out 中文乱码」）：
    #   core/log.py 早就写了 setup_stdout()，但**全仓库没有任何地方调用它**
    #   （grep 只有定义）→ 重定向到文件时 stdout 仍按控制台 cp936 写，
    #   `>> logs\daemon.out` 得到的是 GBK 字节，UTF-8 工具读出来全是「����」。
    #   实测：本次用 cmd 重定向启动后 daemon.out 整篇乱码，排障只能硬解。
    #   在 argparse 之前调一次（越早越好，连 argparse 的报错也能正确编码）。
    try:
        from core.log import setup_stdout
        setup_stdout()
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="soul1.0")
    ap.add_argument("cmd", nargs="?", default="check",
                    choices=["check", "screen", "once", "daemon", "watchdog",
                             "wake", "match", "clear", "pending", "bell"])
    ap.add_argument("n", nargs="?", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    # 🔴 2026-11-10（日志缺陷修复）：本文件建了 `log = get_logger("run")` 却一次不用
    #   → `logs/run.log` 长期 0 字节。每次启动的入口参数（daemon / clear / pending …）
    #   是复盘时判断「这个进程到底被谁、用什么参数拉起来的」最直接的证据。
    try:
        import os as _os
        log.info("run 启动：argv=%s pid=%s", sys.argv[1:], _os.getpid())
    except Exception:
        pass

    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "screen":
        return cmd_screen()
    if args.cmd == "once":
        return cmd_once(dry=args.dry)
    if args.cmd == "daemon":
        return cmd_daemon()
    if args.cmd == "watchdog":
        return cmd_watchdog()
    if args.cmd == "wake":
        return cmd_wake(args.n or 2)
    if args.cmd == "match":
        return cmd_match(args.n or 3)
    if args.cmd == "clear":
        return cmd_clear()
    if args.cmd == "pending":
        return cmd_pending(args.n or 5, dry=args.dry)
    if args.cmd == "bell":
        return cmd_bell(once=args.dry)
    return 2


if __name__ == "__main__":
    sys.exit(main())
