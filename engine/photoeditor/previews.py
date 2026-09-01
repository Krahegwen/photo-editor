"""Previews con caché persistente (port de extract2.py del flujo previo).

Tamaños: 320 (rejilla) y 1600 (lupa) salen del JPEG incrustado del ARW —
rápido, sin demosaico. 3000 (≈50 %) usa revelado half_size y 6000 (1:1)
revelado completo, con los mismos parámetros de decodificación del flujo
previo para que el look sea consistente. La caché va por tamaño y se
invalida sola al cambiar el mtime del original.
"""
import hashlib
import io
from pathlib import Path
from uuid import uuid4

import rawpy
from PIL import Image, ImageOps

from . import config

SIZES = (320, 1600, 3000, 6000)


def _cache_path(rel: str, mtime: float, size: int) -> Path:
    key = hashlib.sha1(f"{rel}|{int(mtime)}|{size}".encode("utf-8")).hexdigest()
    p = config.CACHE_DIR / key[:2] / f"{key[2:26]}.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_image(path: Path, size: int) -> Image.Image:
    if path.suffix.lower() == ".arw":
        with rawpy.imread(str(path)) as raw:
            th = None
            if size <= 1600:
                try:
                    th = raw.extract_thumb()
                except Exception:
                    th = None
            if th is not None and th.format == rawpy.ThumbFormat.JPEG:
                return ImageOps.exif_transpose(Image.open(io.BytesIO(th.data)))
            if th is not None:
                return Image.fromarray(th.data)
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                gamma=(2.222, 4.5),
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=8,
                half_size=size <= 3000,
            )
            return Image.fromarray(rgb)
    try:
        return ImageOps.exif_transpose(Image.open(path))
    except Exception:
        import cv2  # TIFF de 16 bits u otros que PIL no traga

        arr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if arr is None:
            raise
        return Image.fromarray(arr[:, :, ::-1])


def get_preview(abs_path: Path, rel: str, mtime: float, size: int) -> Path:
    if size not in SIZES:
        size = min(SIZES, key=lambda s: abs(s - size))
    out = _cache_path(rel, mtime, size)
    if out.exists():
        return out
    im = _load_image(abs_path, size).convert("RGB")
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    tmp = out.with_name(f"{out.stem}.{uuid4().hex[:8]}.tmp")
    im.save(tmp, "JPEG", quality=85 if size <= 1600 else 90)
    tmp.replace(out)
    return out
