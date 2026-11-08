# -*- coding: utf-8 -*-
"""数据库实时监控：新消息一进来就打断当前流程，不让对方久等。

🔴 用户 2026-11-02：
   「有消息打断当前流程 回消息 新消息进来不要让别人久等 数据库实时监控」

为什么需要独立线程（而不是每轮开头查一次库）：
   一轮主循环可能跑 60~90 秒（清红点 2~3 个人 + 搜索），
   如果只在轮首查库，这 90 秒里进来的新消息要等下一轮才知道 ——
   实测最坏情况一轮 240s，对方要等 4 分钟。

实现原理（尽量省开销）：
   ① 后台线程每 1.5s 用 `stat` 看 IM 库（db + wal）的 mtime/size 指纹 —— 一次 ~80ms
   ② 指纹变了 → 置 dirty 标志（**不立刻 pull 库**，pull 一次要 2~3s，太贵）
   ③ 主流程在**安全点**检查 dirty：清红点每回完一个人、匹配发完开场白、
      唤醒每人之间 → 命中就提前退出，让主循环立刻回去刷新库 + 处理新消息

为什么不用「直接查未读数」：
   设备上没有 sqlite3 命令，查未读只能 pull 库（2~3s）；
   而 stat 只要 80ms，可以高频做。判断「有没有新东西」用 stat 足够，
   真正的未读判定留给主循环 pull 之后做。
"""
import os
import threading
import time

from core.log import get_logger

log = get_logger("data.watch")

POLL_S = 1.5          # stat 间隔
MAX_IDLE_S = 3.0      # 连续异常后最长等待，防死循环


class Watcher(object):
    """后台 stat 监控 IM 库变化。"""

    def __init__(self, dev, db_path=None):
        self.dev = dev
        self.db_path = db_path
        # 2026-11-04 P0-2: 按目录取指纹，不绑单个库文件名。
        #   库名随账号 token 变，绑名字 => 切号后 watcher 一直在看旧账号的库，
        #   新消息打断失效（实测 02:46 切号后 12 分钟才因重启恢复）。
        self.dir_path = os.path.dirname(db_path) if db_path else None
        self.dirty = False          # 有新写入（可能=新消息）
        self.changed_at = 0.0
        self._stop = False
        self._last = ""
        self._err = 0
        self._th = None
        self._self_until = 0.0   # 自己刚发过消息的时间护栏（见 mark_self_write）

    # ---------- 指纹 ----------
    def set_path(self, db_path):
        """切号/重新登录取到新的库路径时调一次（跟着换，别继续看旧库）。"""
        if not db_path:
            return False
        changed = (str(db_path) != str(self.db_path or ""))
        self.db_path = db_path
        self.dir_path = os.path.dirname(str(db_path))
        if changed:
            self._last = ""
            log.info("数据库监控已跟随到新库：%s", os.path.basename(str(db_path)))
        return changed

    def _sig(self):
        """目录内所有 IM 库（db + wal）的 (名字:mtime:size) 指纹。

        2026-11-04：原来只 stat 一个写死的库文件名，切号后立刻失明。
        现在按目录 glob，两个账号的库都在视野里 —— 实测同为 ~50ms（4 个文件），
        但不再依赖「当前账号是哪个」。
        """
        d = self.dir_path or (os.path.dirname(self.db_path) if self.db_path else "")
        if not d:
            return ""
        # toybox sh 会展开 glob；-shm 不监控（App 每秒都在写，纯噪声）
        cmd = ("stat -c '%n %Y:%s' " + d + "/*-DATA.db "
               + d + "/*-DATA.db-wal")
        # 🔴 两个坑（2026-11-02 实测）：
        #   ① stat 的格式串里有 %Y/%s，不能走 Python 的 % 格式化
        #      （会报 "unsupported format character 'Y'"）→ 用字符串拼接
        #   ② **必须同时监控 -wal**：IM 库是 WAL 模式，写入只更新 -wal，
        #      主库 mtime 会滞后（实测主库比 wal 旧 4 秒）→ 只看主库会漏消息
        #   ③ 不能用 `2>/dev/null ||`：u2 的 shell 不解析这些，整条会没输出
        try:
            # 🔴 必须走自己的 adb 通道（dev.text），不能用 u2.shell：
            #    u2 3.7.1 的 shell() 返回 ShellResponse 对象，当字符串用永远是空
            #    （第一版踩这个坑，监控形同虚设还查不出来）。dev.text 实测 40~50ms。
            return (self.dev.text(cmd, timeout=15) or "").replace("\r", "").strip()
        except Exception as e:
            log.warning("stat 异常: %r", e)
            return ""

    # ---------- 线程 ----------
    def _run(self):
        log.info("数据库监控启动（每 %.1fs 看目录 %s）", POLL_S, self.dir_path or self.db_path)
        while not self._stop:
            try:
                sig = self._sig()
                if sig and self._last and sig != self._last:
                    if time.time() < self._self_until:
                        # 这是我自己发消息造成的写入，不算「别人来了新消息」，
                        # 只更新指纹、不置 dirty（否则每回一个人就被自己中断）
                        self._last = sig
                        continue
                    self.dirty = True
                    self.changed_at = time.time()
                    log.info("⚡ 库有变化（可能在进新消息）")
                if sig:
                    self._last = sig
                    self._err = 0
                else:
                    self._err += 1
                    if self._err in (1, 10):
                        log.warning("监控指纹为空（stat 无输出，第 %d 次）", self._err)
            except Exception as e:
                self._err += 1
                if self._err in (1, 10):
                    log.warning("监控异常第 %d 次: %r", self._err, e)
            time.sleep(min(MAX_IDLE_S, POLL_S * (1 + self._err // 5)))

    def start(self):
        if self._th is not None:
            return
        self._th = threading.Thread(target=self._run, name="dbwatch", daemon=True)
        self._th.start()

    def mark_self_write(self, seconds=5.0):
        """我刚发了一条消息 → 接下来几秒的库变化是我自己写的，不算新消息。

        🔴 实测（2026-11-02）：不抑制的话，每次发送都会触发 dirty，
          清红点刚发完第一条就被自己的写入中断，后面的人永远轮不到。

        🔴 2026-11-02 二修：**顺带清掉此刻已置的 dirty**。
          原因：进会话那一下 App 会写库（标记已读），等我们灌字前调本函数时
          dirty 已经是 True 了；只封未来的变化不够 —— 唤醒循环一检查就
          「检测到新消息」中断，唤醒永远只能发 1 个人（实测连续复现）。
          清掉是安全的：漏掉的也只是一次「可能变了」的提示，下一轮 cycle
          开头照样 force 刷库，真正的新消息不会丢。

        🔴 2026-11-03 修复：原来是**绝对赋值**，match/wake 开头设 40s、
        发送结尾又设 6s，把 40s 覆盖成 6s —— 自己发送后的写库又触发抢占。
        改为取最大值（只延长、不缩短）。
        """
        self._self_until = max(self._self_until, time.time() + seconds)
        self.dirty = False
        self.changed_at = 0.0

    def stop(self):
        self._stop = True

    # ---------- 对外 ----------
    def take(self):
        """取走 dirty 标志（读一次即清），返回是否有新变化。"""
        if not self.dirty:
            return False
        self.dirty = False
        return True

    def peek(self):
        return bool(self.dirty)


# 全局单例：daemon 启动时挂一个，各处直接调 W.urgent()
_W = None


def attach(dev, db_path=None):
    global _W
    if _W is None:
        _W = Watcher(dev, db_path)
        _W.start()
    return _W


def get():
    return _W


def set_path(db_path):
    """外部（每轮 open_account 之后）调一次：让监控跟着当前账号的库走。

    2026-11-04 P0-2：8h 强制切号**不重启 daemon**，而库文件名随账号 token 变。
    光靠「目录级指纹」已经能看见新库，但日志里看不出到底跟没跟上；
    这里显式跟随一次，切号后第一轮就会打印「已跟随到新库」。
    """
    if _W is not None:
        return _W.set_path(db_path)
    return False


def urgent():
    """有没有「可能来了新消息」的信号（不清除）。"""
    return bool(_W is not None and _W.peek())


def mark_self_write(seconds=5.0):
    """外部（发消息后）调一次，告诉监控「这几秒的变化是我自己写的」。"""
    if _W is not None:
        _W.mark_self_write(seconds)


def consume():
    """消费掉信号（判断要处理新消息时调）。"""
    return bool(_W is not None and _W.take())
