"""Image preparation for Gemma: orientation fix, resize, region-of-interest crop."""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageDraw, ImageOps

MAX_SIDE = 896


def _open(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def _jpeg(im: Image.Image, q=88) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=q)
    return buf.getvalue()


def prepare(data: bytes, max_side: int = MAX_SIDE) -> bytes:
    im = _open(data)
    im.thumbnail((max_side, max_side))
    return _jpeg(im)


def crop_roi(data: bytes, roi: list[float], min_side: int = 512) -> bytes:
    """roi = [x0, y0, x1, y1] as fractions (0-1). Upscales small crops so the
    model sees detail."""
    im = _open(data)
    w, h = im.size
    x0, y0, x1, y1 = roi
    box = (int(max(0, min(x0, x1)) * w), int(max(0, min(y0, y1)) * h),
           int(min(1, max(x0, x1)) * w), int(min(1, max(y0, y1)) * h))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        raise ValueError("region too small")
    c = im.crop(box)
    s = min_side / min(c.size)
    if s > 1:
        c = c.resize((int(c.width * s), int(c.height * s)), Image.LANCZOS)
    c.thumbnail((MAX_SIDE, MAX_SIDE))
    return _jpeg(c)


def draw_roi(data: bytes, roi: Optional[list[float]]) -> bytes:
    """Full image with the region outlined, so Gemma sees context and focus."""
    im = _open(data)
    if roi:
        w, h = im.size
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = roi
        d.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], outline=(255, 0, 0), width=max(3, w // 200))
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return _jpeg(im)
