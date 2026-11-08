# -*- coding: utf-8 -*-
"""OCR 层：RapidOCR（CPU，无显存占用）。

定位：UI 树读不到的地方用它兜底。实测 Soul 聊天页的气泡是自绘的，
a11y 树里节点数为 0，只能靠截图 OCR 拿文字和位置。

复用现网已验证的模型档位：PP-OCRv5 mobile（v6tiny 已证伪，串号率高）。
"""
import io

from core.log import get_logger

log = get_logger("eyes.ocr")

_ENGINE = None
_VER = None


def engine():
    """懒加载 RapidOCR。首次约 1~2s，之后常驻内存。"""
    global _ENGINE, _VER
    if _ENGINE is not None:
        return _ENGINE
    from rapidocr import ModelType, OCRVersion, RapidOCR
    _VER = "v5mobile"
    params = {
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
    }
    _ENGINE = RapidOCR(params=params)
    log.info("RapidOCR 已加载 (%s)", _VER)
    return _ENGINE


class Item(object):
    """一条 OCR 结果。box 为 (x1, y1, x2, y2)，像素坐标。"""
    __slots__ = ("text", "score", "box")

    def __init__(self, text, score, box):
        self.text = text
        self.score = score
        self.box = box

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) // 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) // 2

    def __repr__(self):
        return "<%r @(%d,%d) %.2f>" % (self.text[:12], self.cx, self.cy, self.score)


def _to_np(png_bytes):
    import numpy as np
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return np.array(im), im.size


def read(png_bytes, min_score=0.5):
    """对一张 PNG 做 OCR，返回 Item 列表（按 y 再 x 排序）。"""
    arr, size = _to_np(png_bytes)
    res = engine()(arr)
    items = []
    if res is None:
        return items
    # rapidocr 3.x: res.boxes (N,4,2) / res.txts / res.scores
    boxes = getattr(res, "boxes", None)
    txts = getattr(res, "txts", None)
    scores = getattr(res, "scores", None)
    if boxes is None or txts is None:
        return items
    for i, t in enumerate(txts):
        try:
            sc = float(scores[i])
        except Exception:
            sc = 1.0
        if sc < min_score:
            continue
        b = boxes[i]
        xs = [float(p[0]) for p in b]
        ys = [float(p[1]) for p in b]
        items.append(Item(t, sc, (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    items.sort(key=lambda it: (it.cy, it.cx))
    return items


def lines(png_bytes, min_score=0.5, gap=12):
    """把同一行（y 接近）的 Item 合并成一行文本，便于阅读。"""
    items = read(png_bytes, min_score=min_score)
    out, cur, cy = [], [], None
    for it in items:
        if cy is None or abs(it.cy - cy) <= gap:
            cur.append(it)
            cy = it.cy if cy is None else (cy + it.cy) // 2
        else:
            out.append((cy, sorted(cur, key=lambda x: x.cx)))
            cur, cy = [it], it.cy
    if cur:
        out.append((cy, sorted(cur, key=lambda x: x.cx)))
    return out
