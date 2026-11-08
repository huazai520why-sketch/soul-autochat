# -*- coding: utf-8 -*-
"""奇遇铃现场取证：铃出现时把「各种能用的信号」同时抓下来，看哪条最快最准。

背景（2026-11-02）：
  铃是自绘弹窗，UI 树里没有「立即私聊」按钮，只能截图 + OCR 定位（2.5s）。
  用户在问「能不能通过 root / 库监控，别只靠截图」。
  已排除：数据库 —— 57 个库全扫，没有任何 bell/love/encounter 表。
  待验证：① 窗口栈（`dumpsys window`）铃是不是独立 Window
          ② logcat 里有没有铃事件
          ③ UI 树里除了「同城奇遇/关闭弹窗」还有没有别的特征节点

用法：
    python tests/t_bell_forensic.py            # 轮询 180s，发现就抓
    python tests/t_bell_forensic.py 600        # 轮询 600s
输出：logs/bell_<时间戳>/  下 5 个文件
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.device import Device  # noqa: E402
from core.paths import LOGS  # noqa: E402

TOTAL = int(sys.argv[1]) if len(sys.argv) > 1 else 180
POLL = 0.8


def window_lines(dev):
    out = dev.text("dumpsys window windows | grep -E 'Window #|mCurrentFocus'", timeout=20)
    return [ln.strip() for ln in out.replace("\r", "").split("\n") if ln.strip()]


def soul_windows(lines):
    return [ln for ln in lines if "cn.soulapp.android" in ln]


def main():
    dev = Device.get()
    base = soul_windows(window_lines(dev))
    print("基线：Soul 窗口 %d 个" % len(base))
    for b in base:
        print("   %s" % b[:110])
    print("\n开始轮询（每 %.1fs，共 %ds）…" % (POLL, TOTAL))

    t0 = time.time()
    while time.time() - t0 < TOTAL:
        try:
            lines = window_lines(dev)
            cur = soul_windows(lines)
            if len(cur) != len(base):
                stamp = time.strftime("%H%M%S")
                d = LOGS / ("bell_" + stamp)
                d.mkdir(parents=True, exist_ok=True)
                print("\n[%s] ⚡ 窗口数变化 %d -> %d，抓现场 -> %s"
                      % (time.strftime("%H:%M:%S"), len(base), len(cur), d.name))
                # ① 窗口栈
                (d / "windows.txt").write_text("\n".join(lines), encoding="utf-8")
                # ② UI 树（原始 XML）
                try:
                    xml = dev.u2().dump_hierarchy(compressed=False)
                    (d / "tree.xml").write_text(xml, encoding="utf-8")
                except Exception as e:
                    print("   tree 失败 %r" % e)
                # ③ 截图
                try:
                    png = dev.screencap()
                    (d / "shot.png").write_bytes(png)
                except Exception as e:
                    print("   shot 失败 %r" % e)
                # ④ logcat 尾部
                try:
                    (d / "logcat.txt").write_text(dev.text("logcat -d -t 800", timeout=40),
                                                  encoding="utf-8", errors="replace")
                except Exception as e:
                    print("   logcat 失败 %r" % e)
                # ⑤ 当前焦点
                try:
                    (d / "focus.txt").write_text(dev.text(
                        "dumpsys window | grep -i mCurrentFocus", timeout=20), encoding="utf-8")
                except Exception:
                    pass
                print("   抓完，新窗口列表：")
                for c in cur:
                    print("     %s" % c[:110])
                print("   -> 分析完再看下一轮（基线更新）")
                base = cur
        except Exception as e:
            print("轮询异常: %r" % e)
        time.sleep(POLL)

    print("\n轮询结束（%ds），没发现窗口变化" % TOTAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
