# -*- coding: utf-8 -*-
import io
import sys
sys.path.insert(0, r"E:\soul2.1\brain")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import soul_rules as R
print("LEN", len(R.PERSONA))
print(R.PERSONA[:3000])
