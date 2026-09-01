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


def apply_recipe(img: np.ndarray, recipe: dict, skip_crop: bool = False) -> np.ndarray:
    """img float32 RGB 0..1 (no se muta); devuelve el resultado procesado."""
    r = normalize(recipe)
    out = img

    # --- geometría
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

    # --- WB + exposición en lineal
    lin = np.clip(out, 0, 1) ** 2.2
    t, ti, ev = r["temp"] / 100, r["tint"] / 100, float(r["exposure"])
    if t or ti:
        lin = lin * np.array([1 + 0.4 * t, 1 - 0.25 * ti, 1 - 0.4 * t], np.float32)
    if ev:
        lin = lin * (2.0 ** ev)
    out = np.clip(lin, 0, None) ** (1 / 2.2)
    out = np.clip(out, 0, 1)

    # --- negros
    b = r["blacks"] / 100
    if b > 0:
        k2 = 0.10 * b
        out = np.clip((out - k2) / (1 - k2), 0, 1)
    elif b < 0:
        k2 = 0.10 * -b
        out = out * (1 - k2) + k2

    # --- altas luces / sombras con máscara de luminancia
    hl, sh = r["highlights"] / 100, r["shadows"] / 100
    if hl or sh:
        L = out @ _LUMA
        if hl:
            m = np.clip((L - 0.55) / 0.45, 0, 1)[..., None]
            out = out * (1 + 0.55 * hl * m)
        if sh:
            m = np.clip(1 - L / 0.45, 0, 1)[..., None]
            out = out + 0.55 * sh * m * (1 - out)
        out = np.clip(out, 0, 1)

    # --- contraste
    ct = r["contrast"] / 100
    if ct:
        out = np.clip((out - 0.5) * (1 + 0.8 * ct) + 0.5, 0, 1)

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
            try:
                from scipy.interpolate import PchipInterpolator

                lut = PchipInterpolator(fx, fy)(grid).astype(np.float32)
            except Exception:
                lut = np.interp(grid, np.float32(fx), np.float32(fy)).astype(np.float32)
            lut = np.clip(lut, 0, 1)
            out = lut[np.clip(out * 4095.0, 0, 4095).astype(np.int32)]
        except Exception:
            pass  # curva malformada: mejor ignorarla que romper el revelado

    # --- saturación / vibrance
    s, v = r["saturation"] / 100, r["vibrance"] / 100
    if s or v:
        hsv = cv2.cvtColor(np.ascontiguousarray(out), cv2.COLOR_RGB2HSV)
        S = hsv[..., 1]
        if v:
            S = S * (1 + v * (1 - S))
        if s:
            S = S * (1 + s)
        hsv[..., 1] = np.clip(S, 0, 1)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    # --- enfoque (unsharp doble suave, como finish.py)
    sp = r["sharpen"] / 100
    if sp:
        blur = cv2.GaussianBlur(out, (0, 0), 2.0)
        out = np.clip(out + 0.9 * sp * (out - blur), 0, 1)

    return np.clip(out, 0, 1)


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
