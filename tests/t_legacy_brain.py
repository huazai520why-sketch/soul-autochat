# -*- coding: utf-8 -*-
"""验证：能否在新目录直接调用旧的 brain_reply 出话（不依赖 daemon）。"""
import os
import sys
import time

BASE = r"E:\soul2.1"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "brain"))
os.chdir(BASE)

print("== import soul_brain ==")
t0 = time.time()
try:
    import soul_brain
except Exception as e:
    print("!! import 失败: %r" % e)
    import traceback
    traceback.print_exc()
    sys.exit(1)
print("   ok %.2fs  PERSONA=%d 字" % (time.time() - t0, len(soul_brain.PERSONA or "")))

print("\n== 出话测试（her_msg = 在干嘛呢） ==")
t0 = time.time()
try:
    r = soul_brain.brain_reply(hist="", her_msg="在干嘛呢", sid="probe_new_1")
except Exception as e:
    print("!! 调用异常: %r" % e)
    import traceback
    traceback.print_exc()
    sys.exit(2)
dt = time.time() - t0
print("   耗时 %.1fs" % dt)
print("   返回 %r" % (r,))

print("\n== 第二次（带一点历史） ==")
hist = "我: 今天上班累不累\n她: 还好 就是有点困"
t0 = time.time()
try:
    r2 = soul_brain.brain_reply(hist=hist, her_msg="你说人为什么要上班啊", sid="probe_new_1")
    print("   耗时 %.1fs  返回 %r" % (time.time() - t0, r2))
except Exception as e:
    print("!! 异常 %r" % e)
