"""Revelado no destructivo.

La receta vive en un sidecar JSON (`<stem>.pe.json`) junto a la foto — el RAW
jamás se toca. El pipeline trabaja en float32 0..1 sobre la salida rawpy con
los mismos parámetros de decodificación del flujo previo (WB de cámara,
gamma 2.222/4.5, sRGB), así el punto de partida es el look ya conocido.

Para la edición interactiva se usa un proxy (half_size + reescalado a ~1536 px)
cacheado en memoria; el render a resolución completa solo ocurre al exportar.
Las curvas de tono son heurísticas propias v1 (no las de Adobe): se afinan con
el uso.
"""
import json
import threading
from pathlib import Path

import cv2
import numpy as np
import rawpy

try:  # al cargar, no en la primera curva: importar scipy cuesta ~1.4 s
    from scipy.interpolate import PchipInterpolator as _Pchip
except Exception:  # sin scipy, interpolación lineal
    _Pchip = None

from . import gpu

DEFAULTS: dict = {
    "temp": 0,          # -100..100  azul ↔ ámbar (sobre el WB de cámara)
    "tint": 0,          # -100..100  verde ↔ magenta
    "exposure": 0.0,    # EV -3..+3
    "contrast": 0,      # -100..100
    "highlights": 0,    # -100..100
    "shadows": 0,       # -100..100
    "blacks": 0,        # -100..100  (+ hunde negros, - los levanta)
    "saturation": 0,    # -100..100
    "vibrance": 0,      # -100..100
    "sharpen": 0,       # 0..100     (unsharp como finish.py)
    "rot90": 0,         # 0..3 giros de 90° en sentido antihorario
    "angle": 0.0,       # -15..15    enderezar
    "crop": None,       # {x,y,w,h} normalizado 0..1 sobre el encuadre girado
    "curve": None,      # curva de tonos master: [[x,y],...] 0..1, o None
}

PROXY_PX = 1536
_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)

_cache_lock = threading.Lock()
_proxy_cache: dict[int, tuple[float, np.ndarray]] = {}


# ------------------------------------------------------------------ receta


def recipe_path(root: Path, folder: str, stem: str) -> Path:
    return root / folder / f"{stem}.pe.json"


def load_recipe(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    out = dict(DEFAULTS)
    out.update({k: data[k] for k in data if k in DEFAULTS})
    return out


def normalize(recipe: dict | None) -> dict:
    out = dict(DEFAULTS)
    if recipe:
        out.update({k: recipe[k] for k in recipe if k in DEFAULTS})
    return out


def save_recipe(path: Path, recipe: dict) -> None:
    data = {"version": 1} | normalize(recipe)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ decode


def decode(path: Path, half: bool) -> np.ndarray:
    """RGB uint16. RAW (ARW/DNG/RW2/…) vía rawpy; JPG/TIFF vía cv2."""
    from .formats import is_raw

    if is_raw(path.suffix):
        kwargs = dict(
            use_camera_wb=True,
            no_auto_bright=True,
            gamma=(2.222, 4.5),
            output_color=rawpy.ColorSpace.sRGB,
            output_bps=16,
            half_size=half,
        )
        if not half:
            kwargs["demosaic_algorithm"] = rawpy.DemosaicAlgorithm.AHD
        with rawpy.imread(str(path)) as raw:
            return raw.postprocess(**kwargs)
    arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ValueError(f"No pude leer {path.name}")
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    arr = arr[:, :, ::-1]  # BGR → RGB
    if arr.dtype == np.uint8:
        return arr.astype(np.uint16) * 257
    return arr.astype(np.uint16)


def get_proxy(photo_id: int, path: Path, mtime: float) -> np.ndarray:
    """float32 0..1, lado largo ~PROXY_PX, cacheado (máx. 2 fotos)."""
    with _cache_lock:
        hit = _proxy_cache.get(photo_id)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    img = decode(path, half=True).astype(np.float32) / 65535.0
    h, w = img.shape[:2]
    sc = PROXY_PX / max(h, w)
    if sc < 1:
        img = cv2.resize(img, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)
    with _cache_lock:
        while len(_proxy_cache) >= 2:
            _proxy_cache.pop(next(iter(_proxy_cache)))
        _proxy_cache[photo_id] = (mtime, img)
    return img


# ------------------------------------------------------------------ pipeline


def _blur_cpu(a: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(a, (0, 0), sigma)


def _blur_gpu(a, sigma: float):
    return gpu.ndi.gaussian_filter(a, (sigma, sigma, 0), truncate=3.0)


def _rgb2hsv_cv(xp, rgb):
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def _hsv2rgb_cv(xp, h, s, v):
    return cv2.cvtColor(np.ascontiguousarray(np.stack([h, s, v], -1)), cv2.COLOR_HSV2RGB)


def _rgb2hsv_xp(xp, rgb):
    """HSV estándar (H en grados 0..360, S y V en 0..1), la misma convención
    que cv2 para float32, escrito sobre el módulo de arrays (numpy o cupy)."""
    r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    d = mx - mn
    dd = xp.maximum(d, 1e-12)
    h = (
        xp.where(
            mx == r_,
            ((g_ - b_) / dd) % 6.0,
            xp.where(mx == g_, (b_ - r_) / dd + 2.0, (r_ - g_) / dd + 4.0),
        )
        * 60.0
    )
    h = xp.where(d > 0, h, 0.0)
    s = xp.where(mx > 0, d / xp.maximum(mx, 1e-12), 0.0)
    return h, s, mx


def _hsv2rgb_xp(xp, h, s, v):
    c = v * s
    hp = (h / 60.0) % 6.0
    x = c * (1 - xp.abs(hp % 2.0 - 1))
    m = v - c
    i = xp.minimum(xp.floor(hp).astype(xp.int32), 5)
    z = xp.zeros_like(c)
    # seis sectores explícitos: cupy.select solo admite escalares en default
    sect = [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5]
    r_ = xp.select(sect, [c, x, z, z, x, c], 0.0)
    g_ = xp.select(sect, [x, c, c, x, z, z], 0.0)
    b_ = xp.select(sect, [z, z, x, c, c, x], 0.0)
    return xp.stack([r_ + m, g_ + m, b_ + m], axis=-1)


def apply_recipe(img: np.ndarray, recipe: dict, skip_crop: bool = False) -> np.ndarray:
    """img float32 RGB 0..1 (no se muta); devuelve el resultado procesado.

    Geometría en CPU (cv2); la parte tonal corre en la GPU si está disponible
    y la imagen pasa de ~1 MP (preview y exportación), con el mismo código
    sobre numpy o cupy y caída a CPU ante cualquier fallo."""
    r = normalize(recipe)
    out = _geometry(img, r, skip_crop)
    if gpu.AVAILABLE and out.size >= 3_000_000:
        try:
            cp = gpu.cp
            res = _tonal(
                cp.asarray(np.ascontiguousarray(out), dtype=cp.float32),
                r, cp, _blur_gpu, _rgb2hsv_xp, _hsv2rgb_xp,
            )
            return cp.asnumpy(res)
        except Exception:
            gpu.release()
    return _tonal(np.ascontiguousarray(out), r, np, _blur_cpu, _rgb2hsv_cv, _hsv2rgb_cv)


def _geometry(img: np.ndarray, r: dict, skip_crop: bool) -> np.ndarray:
    out = img
    k = int(r["rot90"]) % 4
    if k:
        out = np.ascontiguousarray(np.rot90(out, k))
    ang = float(r["angle"])
    if abs(ang) > 0.05:
        h, w = out.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        out = cv2.warpAffine(
            np.ascontiguousarray(out), M, (w, h),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
        )
    c = r["crop"]
    if c and not skip_crop:
        h, w = out.shape[:2]
        x0 = max(0, min(w - 8, int(c["x"] * w)))
        y0 = max(0, min(h - 8, int(c["y"] * h)))
        x1 = min(w, x0 + max(8, int(c["w"] * w)))
        y1 = min(h, y0 + max(8, int(c["h"] * h)))
        out = out[y0:y1, x0:x1]
    return out


def _tonal(out, r: dict, xp, blur, rgb2hsv, hsv2rgb):
    """Parte tonal del revelado sobre el módulo de arrays `xp` (numpy o cupy)."""
    # --- WB + exposición en lineal
    lin = xp.clip(out, 0, 1) ** 2.2
    t, ti, ev = r["temp"] / 100, r["tint"] / 100, float(r["exposure"])
    if t or ti:
        lin = lin * xp.asarray([1 + 0.4 * t, 1 - 0.25 * ti, 1 - 0.4 * t], dtype=xp.float32)
    if ev:
        lin = lin * (2.0 ** ev)
    out = xp.clip(lin, 0, None) ** (1 / 2.2)
    out = xp.clip(out, 0, 1)

    # --- negros
    b = r["blacks"] / 100
    if b > 0:
        k2 = 0.10 * b
        out = xp.clip((out - k2) / (1 - k2), 0, 1)
    elif b < 0:
        k2 = 0.10 * -b
        out = out * (1 - k2) + k2

    # --- altas luces / sombras con máscara de luminancia
    hl, sh = r["highlights"] / 100, r["shadows"] / 100
    if hl or sh:
        L = out @ xp.asarray(_LUMA)
        if hl:
            m = xp.clip((L - 0.55) / 0.45, 0, 1)[..., None]
            out = out * (1 + 0.55 * hl * m)
        if sh:
            m = xp.clip(1 - L / 0.45, 0, 1)[..., None]
            out = out + 0.55 * sh * m * (1 - out)
        out = xp.clip(out, 0, 1)

    # --- contraste
    ct = r["contrast"] / 100
    if ct:
        out = xp.clip((out - 0.5) * (1 + 0.8 * ct) + 0.5, 0, 1)

    # --- curva de tonos (master RGB; PCHIP monótona, LUT de 4096 para no
    #     introducir bandeados en los TIFF de 16 bits)
    cv_pts = r.get("curve")
    if cv_pts and len(cv_pts) >= 2:
        try:
            pts = sorted((float(p[0]), float(p[1])) for p in cv_pts)
            fx: list[float] = []
            fy: list[float] = []
            for x, y in pts:
                if not fx or x > fx[-1] + 1e-4:
                    fx.append(min(max(x, 0.0), 1.0))
                    fy.append(min(max(y, 0.0), 1.0))
            if fx[0] > 0:
                fx.insert(0, 0.0)
                fy.insert(0, fy[0])
            if fx[-1] < 1:
                fx.append(1.0)
                fy.append(fy[-1])
            grid = np.linspace(0, 1, 4096, dtype=np.float32)
            if _Pchip is not None:
                lut = _Pchip(fx, fy)(grid).astype(np.float32)
            else:
                lut = np.interp(grid, np.float32(fx), np.float32(fy)).astype(np.float32)
            lut = xp.asarray(np.clip(lut, 0, 1))
            out = lut[xp.clip(out * 4095.0, 0, 4095).astype(xp.int32)]
        except Exception:
            pass  # curva malformada: mejor ignorarla que romper el revelado

    # --- saturación / vibrance
    s, v = r["saturation"] / 100, r["vibrance"] / 100
    if s or v:
        h, S, V = rgb2hsv(xp, out)
        if v:
            S = S * (1 + v * (1 - S))
        if s:
            S = S * (1 + s)
        out = hsv2rgb(xp, h, xp.clip(S, 0, 1), V)

    # --- enfoque (unsharp doble suave, como finish.py)
    sp = r["sharpen"] / 100
    if sp:
        out = xp.clip(out + 0.9 * sp * (out - blur(out, 2.0)), 0, 1)

    return xp.clip(out, 0, 1)


def histogram(img: np.ndarray) -> dict:
    L = img @ _LUMA
    hist, _ = np.histogram(L, bins=128, range=(0.0, 1.0))
    peak = max(1, int(hist.max()))
    return {
        "luma": [round(float(x) / peak, 4) for x in hist],
        "clip_hi": round(float((L >= 0.995).mean()), 4),
        "clip_lo": round(float((L <= 0.005).mean()), 4),
    }


def encode_jpeg(img: np.ndarray, quality: int = 88) -> bytes:
    u8 = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", u8[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Fallo codificando JPEG")
    return buf.tobytes()


def render_full(path: Path, recipe: dict | None) -> np.ndarray:
    """Render a resolución completa → uint16 RGB (para exportación)."""
    img = decode(path, half=False).astype(np.float32) / 65535.0
    out = apply_recipe(img, normalize(recipe))
    return (np.clip(out, 0, 1) * 65535 + 0.5).astype(np.uint16)
