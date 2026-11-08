# -*- coding: utf-8 -*-
"""设备接入层：adb 路径探测 / serial 自动识别 / root 校验 / 截图 / u2 连接。

设计约束（来自现网踩坑）：
- MuMu 重建后 `emulator-5554` 会消失、只剩 `127.0.0.1:16384`，必须自动探测，不能写死。
- `adb devices` 输出在 Windows 上带 \\r，解析前必须去掉，否则 `device$` 永远匹配不上。
- 截图只认「本次真的拿到新 PNG」：校验 PNG magic，不只看字节数。
- 上层任何模块都不许自己拼 adb 命令，一律走这里，方便换通道。
"""
import re
import shutil
import subprocess
import time
from pathlib import Path

from .log import get_logger
from .paths import ADB_CANDIDATES

log = get_logger("core.device")

# ---- 设备快慢感知（2026-11-02：提速也要看实际情况，卡的时候必须放慢）----
DUMP_MS = [0]          # 最近一次 UI dump 耗时（ms），由 eyes.uitree 写入

# ---- 动作代数（2026-11-08 A2 帧复用的兜底守卫）----
# 每执行一次「会改变屏幕」的动作就 +1。eyes.uitree.Screen 在 dump 时记下当时的
# 代数，复用时先比对：代数变了 = 中间发生过动作 = 这一帧一定过期，必须重取。
#
# 为什么不能只靠 Actor._after 的 force=True：现网存在绕过 Actor 直接调 u2 的路径
# （hands/pic.py 的 press、brain/search.py 的 send_keys/clear_text），
# 那些动作不会走 _after。有了这个全局代数，**任何**动作都会让缓存作废，
# 不需要在每个调用点手工记得 invalidate。
ACTION_GEN = [0]


def note_action():
    """记一次屏幕动作，让所有缓存的 UI 帧作废。"""
    ACTION_GEN[0] += 1


def action_gen():
    return ACTION_GEN[0]


def note_dump(ms):
    """记录一次 dump 耗时，供手感节流判断设备当前快慢。"""
    try:
        DUMP_MS[0] = int(ms)
    except Exception:
        pass


def slow_factor():
    """设备越卡，动作后的等待越长（防止"点了没反应→再点→变双击"）。"""
    ms = DUMP_MS[0]
    if ms >= 2000:
        return 2.5
    if ms >= 800:
        return 1.5
    return 1.0

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _find_adb():
    for p in ADB_CANDIDATES:
        if Path(p).exists():
            return p
    w = shutil.which("adb")
    if w:
        return w
    raise RuntimeError("找不到 adb，检查 MuMu 安装目录或 PATH")


def u2_version():
    """3.7.x 起 uiautomator2 不再暴露 __version__，改从包元数据取。"""
    try:
        from importlib.metadata import version
        return version("uiautomator2")
    except Exception:
        try:
            import uiautomator2 as m
            return getattr(m, "__version__", "?")
        except Exception:
            return "?"


class Device:
    """单个模拟器实例。所有设备操作入口。"""

    _inst = None

    def __init__(self, serial=None):
        self.adb = _find_adb()
        self.serial = serial or self.probe_serial()
        self._u2 = None

    # ---------- 单例 ----------
    @classmethod
    def get(cls, serial=None):
        if cls._inst is None:
            cls._inst = cls(serial=serial)
        return cls._inst

    # ---------- 底层 ----------
    def run(self, args, timeout=30):
        """直接跑 adb 参数列表，返回 (rc, stdout_bytes, stderr_bytes)。"""
        cmd = [self.adb] + (["-s", self.serial] if self.serial else []) + list(args)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
            rc, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            log.warning("adb 超时 %.1fs: %s", time.time() - t0, " ".join(args[:3]))
            return 124, b"", b"timeout"
        return rc, out, err

    def sh(self, cmd, timeout=30):
        """adb shell <cmd>，返回 bytes。"""
        rc, out, _ = self.run(["shell", cmd], timeout=timeout)
        return out

    def text(self, cmd, timeout=30):
        """adb shell <cmd>，返回去空白后的字符串（容错 utf-8）。"""
        return self.sh(cmd, timeout=timeout).decode("utf-8", "ignore").strip()

    # ---------- 探测 ----------
    @staticmethod
    def _list_devices(adb):
        try:
            p = subprocess.run([adb, "devices"], capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            raise RuntimeError("adb devices 超时")
        cands = []
        for line in p.stdout.decode("utf-8", "ignore").replace("\r", "").split("\n"):
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1].strip() == "device":
                cands.append(parts[0].strip())
        return cands, p.stdout

    @staticmethod
    def probe_serial(prefer="127.0.0.1:16384"):
        """找设备 serial。

        🔴 必须自动重连（2026-11-02 实测）：
          副机上 adb server 会跟着 SSH 会话一起退出，下次进来 `adb devices` 是空的，
          每个脚本都报「没有可用设备」。所以这里发现目标 serial 不在时，
          先 `adb connect` 一次再重查 —— 否则整套脚本没法用。
        """
        adb = _find_adb()
        cands, raw = Device._list_devices(adb)

        if prefer not in cands:
            try:
                subprocess.run([adb, "connect", prefer], capture_output=True, timeout=20)
            except Exception as e:
                log.warning("adb connect %s 失败: %r", prefer, e)
            time.sleep(1.2)
            cands, raw = Device._list_devices(adb)

        if not cands:
            raise RuntimeError("没有可用设备：%r" % raw[:200])
        # 优先 MuMu 的 127.0.0.1:port（emulator-5554 可能是残留通道）
        if prefer in cands:
            return prefer
        cands.sort(key=lambda s: (0 if s.startswith("127.0.0.1:") else 1, s))
        return cands[0]

    def root_ok(self):
        """MuMu userdebug 镜像 adbd 本身就是 root，不需要 su。"""
        out = self.text("id")
        return "uid=0" in out

    def ensure_root(self, wait=6.0):
        """确保 adbd 是 root；不是就 `adb root` 重启 adbd 再等。

        为什么必须自动做（2026-11-02 实测）：
          模拟器重启后 adbd 退回 `uid=2000(shell)`，读不了 /data/data/<pkg>/databases，
          数据层直接报「设备上没有 IM-SDK 库」，必回链路整条断掉。
        注意：`adb root` 会重启 adbd，u2 连接随之失效，所以成功后要把 u2 缓存清掉。
        """
        if self.root_ok():
            return True
        log.warning("adbd 不是 root（%s）→ adb root", self.text("id")[:40])
        self.run(["root"], timeout=30)
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(1.5)
            self.reset_u2()
            if self.root_ok():
                log.info("已切到 root（用时 %.1fs）", time.time() - t0)
                return True
        log.warning("adb root 失败，仍是：%s", self.text("id")[:40])
        return False

    def wm_size(self):
        out = self.text("wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError("wm size 解析失败: %r" % out)
        return int(m.group(1)), int(m.group(2))

    def current_app(self):
        """当前前台 Activity：返回 (package, activity)。"""
        out = self.text("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
        pkg, act = "", ""
        m = re.search(r"([\w\.]+)/([\w\.\$]+)", out)
        if m:
            pkg, act = m.group(1), m.group(2)
        return pkg, act

    # ---------- 截图 ----------
    def screencap(self, timeout=30):
        """exec-out 取 PNG 原始字节。校验 magic，坏图直接抛错（不返回半张图）。"""
        rc, raw, err = self.run(["exec-out", "screencap", "-p"], timeout=timeout)
        if not raw:
            raise RuntimeError("screencap 空输出 rc=%s err=%r" % (rc, err[:120]))
        if not raw.startswith(PNG_MAGIC):
            # Windows adb 偶发 CRLF 污染（\n -> \r\n），保守修复后复检
            fixed = raw.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n")
            if fixed.startswith(PNG_MAGIC):
                log.warning("截图疑似 CRLF 污染，已修复 (%d -> %d bytes)", len(raw), len(fixed))
                raw = fixed
            else:
                raise RuntimeError("截图不是 PNG，前 16 字节=%r" % raw[:16])
        return raw

    def screencap_to(self, path, timeout=30):
        """截图落盘，返回 (path, bytes, seconds)。同一文件必须整包覆盖。"""
        t0 = time.time()
        raw = self.screencap(timeout=timeout)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return p, len(raw), time.time() - t0

    # ---------- u2 ----------
    def u2(self, timeout=60):
        """uiautomator2 连接（懒加载）。失败抛 RuntimeError，由上层决定是否降级 adb。"""
        if self._u2 is not None:
            return self._u2
        try:
            import uiautomator2 as u2mod
        except ImportError as e:
            raise RuntimeError("未安装 uiautomator2: %s" % e)
        t0 = time.time()
        try:
            try:
                d = u2mod.connect(self.serial, timeout=timeout)
            except TypeError:
                # 老版本 uiautomator2 的 connect() 没有 timeout 参数
                d = u2mod.connect(self.serial)
            d.info  # 触发一次通信，确认真的可用
        except Exception as e:
            raise RuntimeError("u2 连接失败(%s): %r" % (self.serial, e))
        log.info("u2 已连接 %s (%.1fs) ver=%s", self.serial, time.time() - t0, u2_version())
        self._u2 = d
        return d

    def u2_alive(self):
        try:
            self.u2()
            return True
        except Exception:
            return False

    def reset_u2(self):
        """丢掉缓存的 u2 连接，下次 u2() 重新连。

        什么时候需要（2026-11-02 实测）：
        u2 的 device 端 server 会莫名退出，表现为
        `http.client.RemoteDisconnected: Remote end closed connection`，
        之后所有 dump 都失败。adbd 本身还是好的，重连即可恢复。
        """
        old = self._u2
        self._u2 = None
        try:
            if old is not None:
                old._server = None      # 让 u2 丢掉内部 http 连接
        except Exception:
            pass
        log.warning("u2 连接已重置")

    def __repr__(self):
        return "<Device %s adb=%s>" % (self.serial, self.adb)
