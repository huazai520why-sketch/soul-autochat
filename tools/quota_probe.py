# -*- coding: utf-8 -*-
"""D2 取证探针: 停 daemon 后跑。导航到星球→点灵魂匹配卡→额度弹层出现→
dump_hierarchy 落盘→记录文本→用项目自身 _dismiss_quota 关闭→报告落点。
只读+关弹层, 不发任何消息。"""
import os, sys, time

os.chdir(r"E:\soul1.0")
sys.path.insert(0, r"E:\soul1.0")

from core.device import Device          # noqa: E402
from brain.act import Actor             # noqa: E402
from brain import nav                   # noqa: E402
from brain import match as M            # noqa: E402
from eyes.page import detect            # noqa: E402
from core.log import get_logger         # noqa: E402

log = get_logger("tools.quota_probe")

dev = Device.get()
a = Actor(dev)
nav.ensure_app(dev)
snap, pg = nav.to_tab(a, "星球")
print("STEP1 page=", pg, flush=True)
if pg != "planet":
    print("ABORT: not on planet", flush=True)
    sys.exit(2)

n, remain = M.match_entry(snap)
print("STEP2 entry=", (n.bounds if n is not None else None), "remain=", remain, flush=True)
if n is None:
    print("ABORT: no soul-match entry", flush=True)
    sys.exit(3)

before = snap.signature()
a.hand.tap_node(n, settle=2.0)
time.sleep(3.0)
s2 = a.snap(force=True)
print("STEP3 page=", detect(s2), "quota_out=", M.quota_out(s2), flush=True)

xml = dev.u2().dump_hierarchy()
with open(r"E:\soul1.0\logs\_quota_popup_dump.xml", "w", encoding="utf-8") as f:
    f.write(xml)
print("STEP4 dump saved bytes=", len(xml), flush=True)

texts = list(s2.texts())
print("STEP5 texts_head=", json_str := str(texts[:16])[:600], flush=True)

ok = M._dismiss_quota(a, s2)
print("STEP6 dismissed=", ok, flush=True)
time.sleep(1.0)
s3 = a.snap(force=True)
print("STEP7 final page=", detect(s3), "quota_still=", M.quota_out(s3), flush=True)
if M.quota_out(s3):
    a.hand.back(settle=1.2)
    s4 = a.snap(force=True)
    print("STEP8 after back page=", detect(s4), "quota_still=", M.quota_out(s4), flush=True)
print("PROBE DONE", flush=True)
