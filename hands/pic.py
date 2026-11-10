# -*- coding: utf-8 -*-
"""手：发图片。

实测路径（2026-11-02，900x1600）：
    会话页「更多」(846,1531)
      -> 面板第 1 格「图片」(135,1050)
      -> SoulAlbumActivity 相册（图片是 FrameLayout desc='图片' / '图片第N个未选中'）
      -> 点某张 -> SoulAlbumPreviewActivity 预览页
      -> 右下「发送」TextView res=tvSend (820,1558)

前置：图片必须先 push 到模拟器（/sdcard/Pictures/），见 push_photos()。

⚠️ 键盘会影响：键盘弹着时底部工具栏被顶到 y≈868，「更多」点不中 → 先按 back 收键盘。
"""
import os
import subprocess
import time

from core.log import get_logger

log = get_logger("hands.pic")

MORE_DESC = "更多"
TAB_PIC = "图片"
SEND_RES = "tvSend"


def _keyboard_open(snap):
    """工具栏被顶到 1450 以上就是键盘弹着。"""
    for n in snap.nodes:
        if n.desc == MORE_DESC:
            return n.center[1] < 1450
    return False


def ensure_no_keyboard(actor):
    """收起键盘（键盘弹着会点不中底部工具栏）。"""
    snap = actor.snap()
    if _keyboard_open(snap):
        log.info("键盘弹着 -> back 收起")
        from core.device import note_action
        note_action()          # A2：绕过 Hand 的裸 u2 调用，手工让帧缓存作废
        # 2026-11-10 收口到 Hand.back 护栏版（关键盘会吞 back，退出前台仍自愈拉起）
        actor.hand.back(settle=0.0, force=True)
        time.sleep(1.2)
        return True
    return False


def open_album(actor):
    """会话页 -> 更多 -> 图片 -> 相册 -> **点一下「相机胶卷」刷新**。返回 (snap, ok)。

    🔴 必须点「相机胶卷」（用户 2026-11-02 提醒）：
      不点的话相册显示的是缓存的旧列表（实测只有 14 张旧图），
      刚 push 进来的照片看不到，会误发成模拟器里的老图。
    """
    ensure_no_keyboard(actor)

    snap = actor.snap()
    more = None
    for n in snap.nodes:
        if n.desc == MORE_DESC:
            more = n
            break
    if more is None:
        log.warning("找不到「更多」按钮")
        return snap, False
    actor.hand.tap_node(more, settle=1.8)

    s = actor.snap(force=True)
    pic = s.hit(text=TAB_PIC)
    if pic is None:
        log.warning("更多面板里没有「图片」")
        return s, False
    actor.hand.tap_node(pic, settle=2.5)

    s2 = actor.snap(force=True)
    ok = "SoulAlbumActivity" in (actor.dev.current_app()[1] or "")
    if not ok:
        log.warning("没进相册（fg=%s）", actor.dev.current_app()[1])
        return s2, False

    # 点「相机胶卷」把列表拉起来（否则是空/旧列表）
    f = s2.hit(text="相机胶卷")
    if f is not None:
        log.info("点「相机胶卷」刷新列表")
        actor.hand.tap_node(f, settle=2.2)
        s2 = actor.snap(force=True)
    else:
        log.info("没有「相机胶卷」入口，直接用当前列表")

    log.info("相册页 ok=%s 图片数=%d", ok, len(photos(s2)))
    return s2, ok


def photos(snap):
    """相册里的图片格子（按屏幕顺序：先上后下、先左后右）。"""
    out = [n for n in snap.nodes if n.clickable and (n.desc or "").startswith("图片")]
    out.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
    return out


def send(actor, dev, index=1, settle=2.0):
    """在相册里选第 index 张（1 起）并发出去。返回 (ok, 说明)。

    调用前须已在相册页（open_album 成功）。
    ⚠️ photos() 只认 desc='图片' 的格子 —— 第一格「拍摄」的 desc 是空的，
       所以 index=1 就是**第一张照片**，不会点到相机（用户 2026-11-02 提醒过）。
    ⚠️ 设备卡时点击会丢（点了不跳预览页），必须重试。
    """
    snap = actor.snap(force=True)
    ps = photos(snap)
    if not ps:
        return False, "相册里没有图片"
    if index < 1 or index > len(ps):
        return False, "序号越界（相册只有 %d 张）" % len(ps)

    n = ps[index - 1]
    fg = ""
    for attempt in (1, 2):
        log.info("选第 %d 张 %s（第 %d 次）", index, n.bounds, attempt)
        actor.hand.tap_node(n, settle=2.0)
        s = actor.snap(force=True)
        fg = dev.current_app()[1] or ""
        if "PreviewActivity" in fg:
            break
        log.warning("第 %d 次没进预览页（fg=%s），重点一次", attempt, fg.split(".")[-1])
        time.sleep(1.2)
        snap = actor.snap(force=True)
        ps = photos(snap)
        if index <= len(ps):
            n = ps[index - 1]
    else:
        return False, "点了两次都没进预览页（fg=%s）" % fg.split(".")[-1]

    s = actor.snap(force=True)
    btn = s.hit(res=SEND_RES) or s.hit(text="发送")
    if btn is None:
        return False, "预览页找不到发送按钮"
    log.info("点发送 %s", btn.bounds)
    actor.hand.tap_node(btn, settle=settle)

    # 回到会话页即成功
    s2, pg = actor.wait_page(("chat",), timeout=8.0)
    if pg != "chat":
        return False, "发图后没回到会话页（%s）" % pg
    return True, "已发送"


def send_from_chat(actor, dev, index=1):
    """一步到位：会话页 -> 发第 index 张图。返回 (ok, 说明)。"""
    snap, ok = open_album(actor)
    if not ok:
        return False, "打不开相册"
    return send(actor, dev, index=index)


# ---------------- 图片准备 ----------------
PHOTO_DIR_DEV = "/sdcard/Pictures"


def push_photos(dev, local_files, prefix="soul"):
    """把本地图片推到模拟器。返回推上去的设备路径列表。"""
    out = []
    try:
        dev.sh("mkdir -p %s" % PHOTO_DIR_DEV, timeout=20)
    except Exception:
        pass
    for i, f in enumerate(local_files, 1):
        if not os.path.exists(f):
            log.warning("本地图片不存在: %s", f)
            continue
        dst = "%s/%s%d.jpg" % (PHOTO_DIR_DEV, prefix, i)
        rc, o, e = dev.run(["push", f, dst], timeout=120)
        if rc == 0:
            out.append(dst)
            log.info("已推送 %s -> %s", os.path.basename(f), dst)
        else:
            log.warning("推送失败 %s: %r", f, e[:80])
    # 让系统相册重新扫描
    try:
        dev.sh('am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
               '-d file://%s' % PHOTO_DIR_DEV, timeout=20)
    except Exception:
        pass
    return out
