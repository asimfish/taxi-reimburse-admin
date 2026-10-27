import hashlib
import json
import threading
from pathlib import Path

from PIL import Image, ImageOps

_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def _load_image(path):
    if Path(path).suffix.lower() in (".heic", ".heif"):
        from pillow_heif import register_heif_opener

        register_heif_opener()
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    # 超长截图按宽度缩放，OCR 速度与精度都更稳定
    if img.width > 1600:
        img = img.resize((1600, round(img.height * 1600 / img.width)))
    return img


def ocr_boxes(path, cache_dir=None):
    """返回 [{text, x, y, h, score}]，坐标为图片像素（缩放后）。"""
    data = Path(path).read_bytes()
    key = hashlib.sha256(data).hexdigest()
    cache = Path(cache_dir) / f"{key}.json" if cache_dir else None
    if cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    import numpy as np

    img = _load_image(path)
    with _lock:
        res, _ = _get_engine()(np.asarray(img))
    boxes = []
    for box, text, score in res or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append({"text": text.strip(), "x": round(min(xs)), "x1": round(max(xs)), "y": round(sum(ys) / 4), "h": round(max(ys) - min(ys)), "score": round(float(score), 3)})
    out = {"width": img.width, "height": img.height, "boxes": boxes}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def group_rows(boxes):
    """按纵坐标把文字框合成行，返回 [{y, text, parts}]。"""
    rows = []
    for b in sorted(boxes, key=lambda b: b["y"]):
        tol = max(12, b["h"] * 0.6)
        if rows and abs(rows[-1]["y"] - b["y"]) <= tol:
            rows[-1]["parts"].append(b)
        else:
            rows.append({"y": b["y"], "parts": [b]})
    for r in rows:
        r["parts"].sort(key=lambda b: b["x"])
        r["text"] = " ".join(p["text"] for p in r["parts"])
    return rows
