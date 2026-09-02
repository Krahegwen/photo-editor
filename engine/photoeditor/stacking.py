"""Apilado astro: port de proc.py/stack.py del flujo previo + alineado de estrellas.

Modos:
- luna:      centroide del disco brillante, recorte NxN y alineado subpíxel
             (phaseCorrelate), media sigma-clip. Port directo de proc.py.
- estrellas: detección DoG de estrellas (excluyendo el patrón fijo: vegetación,
             luces) y alineado INCREMENTAL entre frames consecutivos —
             astroalign por triángulos con fallback NN+RANSAC — componiendo
             similitudes ancladas al frame central. Media sigma-clip.
- media:     sin alinear, media sigma-clip (reducción de ruido, escena fija).
- max:       sin alinear, máximo por píxel (composite de fuegos, trails crudos).
- trails:    máximo por píxel + RELLENO DE HUECOS: el movimiento del cielo
             entre frames consecutivos (misma detección/matching que estrellas)
             se interpola en fracciones y el frame anterior se funde desplazado,
             de modo que el trazo cubre el intervalo entre disparos. El suelo
             (patrón fijo) queda excluido para no emborronarlo.
- hdr:       brackets ordenados por exposición, alineado por traslación y
             fusión de exposiciones (Mertens).

Salida: '<carpeta> - <tipo> <HHMM>-<HHMM>.tif/jpg' (ver naming.py).

Por qué incremental: entre frames consecutivos el cielo se mueve ~2 px y el
matching es trivial y robusto; entre extremos de una sesión (rotación de campo
de varios grados, nubes, estrellas que entran/salen) el matching directo
falla. Verificado con las Perseidas 240812.

Los frames decodificados van como .npy uint16 a %LOCALAPPDATA%/stackwork
(nunca dentro de las carpetas del usuario) y se borran al terminar. El
resultado se guarda como TIFF16 LZW + JPG q95 en la carpeta; el acabado fino
(enfoque/saturación, el viejo finish.py) se hace abriendo el TIFF en Revelar.
"""
import math
import shutil
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    import astroalign as _aa
except Exception:  # opcional: sin él queda el fallback NN+RANSAC
    _aa = None

from . import config, db, develop, gpu, naming
from .export import _save_jpg, _save_tif16
from .parallel import prefetch, workers

MODES = ("luna", "estrellas", "media", "max", "trails", "hdr")
_LABEL = {
    "luna": "apilado luna",
    "estrellas": "apilado estrellas",
    "media": "apilado media",
    "max": "apilado max",
    "trails": "trails",
    "hdr": "hdr",
}
_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ------------------------------------------------------------------ utilidades


def _gray8(img16: np.ndarray) -> np.ndarray:
    return cv2.cvtColor((img16 >> 8).astype(np.uint8), cv2.COLOR_RGB2GRAY)


def _grayf(img16: np.ndarray) -> np.ndarray:
    return _gray8(img16).astype(np.float32)


def _gray16f(img16: np.ndarray) -> np.ndarray:
    """Luminancia float32 en rango 0..65535 (sin cuantizar a 8 bits)."""
    return img16.astype(np.float32) @ _LUMA


def _moon_centroid(img16: np.ndarray) -> tuple[float, float]:
    g = _gray8(img16)
    small = cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    gb = cv2.GaussianBlur(small, (5, 5), 0)
    th = max(float(gb.max()) * 0.35, 25.0)
    n, _lab, stats, cent = cv2.connectedComponentsWithStats((gb > th).astype(np.uint8), 8)
    if n < 2:
        raise ValueError("no encuentro el disco (¿frame vacío?)")
    i = 1 + int(np.argmax(stats[1:, 4]))
    cx, cy = cent[i]
    return float(cx) * 4, float(cy) * 4


def _crop_at(img: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
    H, W = img.shape[:2]
    size = min(size, H, W)
    x0 = int(round(cx)) - size // 2
    y0 = int(round(cy)) - size // 2
    x0 = max(0, min(W - size, x0))
    y0 = max(0, min(H - size, y0))
    return np.ascontiguousarray(img[y0 : y0 + size, x0 : x0 + size])


# ------------------------------------------------------ estrellas: detección


def _exclusion_mask(fixed_bg: np.ndarray, half: bool) -> np.ndarray:
    """Zonas fijas brillantes (vegetación iluminada, farolas): fuera del matching."""
    excl = (fixed_bg > np.percentile(fixed_bg, 97)).astype(np.uint8)
    k = 31 if half else 61
    return cv2.dilate(excl, np.ones((k, k), np.uint8))


def _detect_stars(
    gray: np.ndarray, excl: np.ndarray | None, half: bool, cap: int = 300
) -> np.ndarray:
    """Paso-banda DoG (mata nubes/gradientes), umbral robusto por MAD y máximos
    locales. Devuelve (x, y) ordenadas por respuesta. Verificado: ~90 % de
    repetibilidad entre frames consecutivos en las Perseidas urbanas."""
    s = 1.0 if half else 2.0
    if gpu.active():
        try:
            return _detect_stars_gpu(gray, excl, s, cap)
        except Exception:
            gpu.release()  # VRAM u otro: camino CPU
    d = cv2.GaussianBlur(gray, (0, 0), s) - cv2.GaussianBlur(gray, (0, 0), 3 * s)
    if excl is not None and excl.shape == d.shape:
        d[excl > 0] = 0
    mad = float(np.median(np.abs(d))) + 1e-3
    peaks = (d == cv2.dilate(d, np.ones((5, 5), np.uint8))) & (d > 8.0 * mad)
    ys, xs = np.nonzero(peaks)
    if not len(xs):
        return np.empty((0, 2), np.float32)
    order = np.argsort(-d[ys, xs])[:cap]
    return np.stack([xs[order], ys[order]]).T.astype(np.float32)


def _quick_votes(a: np.ndarray, b: np.ndarray, max_shift: float = 500.0) -> int:
    """Votación rápida de traslación dominante entre dos nubes de puntos.
    Sirve de puerta barata antes de astroalign: cuando NO hay solape coherente,
    astroalign quema 30-60 s agotando triángulos antes de rendirse."""
    if len(a) < 10 or len(b) < 10:
        return 0
    diffs = (b[:, None, :] - a[None, :, :]).reshape(-1, 2)
    m = (np.abs(diffs) < max_shift).all(axis=1)
    d = diffs[m]
    if len(d) < 10:
        return 0
    bins = int(2 * max_shift // 6)
    H, _, _ = np.histogram2d(
        d[:, 0], d[:, 1], bins=bins, range=[[-max_shift, max_shift], [-max_shift, max_shift]]
    )
    return int(H.max())


def _detect_stars_gpu(
    gray: np.ndarray, excl: np.ndarray | None, s: float, cap: int
) -> np.ndarray:
    """Misma detección que la CPU, en CuPy (gaussian_filter con truncate=3
    para parecerse al kernel de OpenCV)."""
    cp, ndi = gpu.cp, gpu.ndi
    g = cp.asarray(gray, dtype=cp.float32)
    d = ndi.gaussian_filter(g, s, truncate=3.0) - ndi.gaussian_filter(g, 3 * s, truncate=3.0)
    if excl is not None and excl.shape == d.shape:
        d[cp.asarray(excl) > 0] = 0
    mad = float(cp.median(cp.abs(d))) + 1e-3
    peaks = (d == ndi.maximum_filter(d, size=5)) & (d > 8.0 * mad)
    ys, xs = cp.nonzero(peaks)
    if int(xs.size) == 0:
        return np.empty((0, 2), np.float32)
    order = cp.argsort(-d[ys, xs])[:cap]
    return cp.asnumpy(cp.stack([xs[order], ys[order]]).T).astype(np.float32)


def _pair_transform(
    prev_pts: np.ndarray, pts: np.ndarray
) -> tuple[np.ndarray, int, str]:
    """Similitud frame→frame anterior (movimiento pequeño). astroalign primero
    (con puerta rápida); fallback vecino-más-próximo + RANSAC. Escala fuera de
    [0.98, 1.02] = frame descartado: mejor perder uno que meter una
    transformación espuria."""
    if (
        len(prev_pts) >= 10
        and len(pts) >= 10
        and _aa is not None
        and _quick_votes(prev_pts, pts) >= 12
    ):
        try:
            t, (s, _d) = _aa.find_transform(pts, prev_pts, max_control_points=80)
            if 0.98 <= float(t.scale) <= 1.02:
                return t.params[:2].astype(np.float32), len(s), "astroalign"
        except Exception:
            pass
    src, dst = [], []
    for i, p in enumerate(pts):
        d2 = np.sum((prev_pts - p) ** 2, axis=1)
        j = int(np.argmin(d2))
        if d2[j] < 144.0:  # radio 12 px: consecutivos se mueven ~2 px
            src.append(pts[i])
            dst.append(prev_pts[j])
    if len(src) >= 8:
        M, inl = cv2.estimateAffinePartial2D(
            np.float32(src), np.float32(dst), method=cv2.RANSAC, ransacReprojThreshold=2.0
        )
        if M is not None:
            sc = float(np.sqrt(abs(np.linalg.det(M[:, :2]))))
            if 0.98 <= sc <= 1.02:
                return M.astype(np.float32), int(inl.sum()), "ransac"
    raise ValueError("no alineable con el frame anterior")


def _compose(t_prev: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Compone (3x3) la transformación frame→prev con prev→ref."""
    mh = np.vstack([m, [0, 0, 1]]).astype(np.float32)
    return t_prev @ mh


def _refine_to_ref(
    ref_pts: np.ndarray, pts: np.ndarray, t_guess: np.ndarray, radius: float = 10.0
) -> tuple[np.ndarray, int]:
    """Ajuste ABSOLUTO contra la referencia usando la cadena como guía: proyecta
    las estrellas con t_guess, casa por vecino próximo y re-estima la similitud
    directa frame→ref. Elimina la deriva acumulada de la composición (sin esto,
    ~0.2 px de sesgo por par se convierten en trazas de ~8 px en el apilado)."""
    ones = np.ones((len(pts), 1), np.float32)
    proj = (t_guess[:2] @ np.hstack([pts, ones]).T).T
    src, dst = [], []
    for i, p in enumerate(proj):
        d2 = np.sum((ref_pts - p) ** 2, axis=1)
        j = int(np.argmin(d2))
        if d2[j] < radius * radius:
            src.append(pts[i])
            dst.append(ref_pts[j])
    if len(src) < 15:
        return t_guess, 0
    M, inl = cv2.estimateAffinePartial2D(
        np.float32(src), np.float32(dst), method=cv2.RANSAC, ransacReprojThreshold=2.0
    )
    if M is None:
        return t_guess, 0
    sc = float(np.sqrt(abs(np.linalg.det(M[:, :2]))))
    if not 0.98 <= sc <= 1.02:
        return t_guess, 0
    return np.vstack([M, [0, 0, 1]]).astype(np.float32), int(inl.sum())


# ------------------------------------------------------------------ apoyo


def _exposure_params(path: Path) -> tuple[float, float, float]:
    """(segundos, ISO, f) desde EXIF; 0.0 donde falte."""
    import exifread

    try:
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except Exception:
        return 0.0, 0.0, 0.0

    def ratio(name: str) -> float:
        v = str(tags.get(name, "")).strip()
        try:
            if "/" in v:
                a, b = v.split("/")
                return float(a) / float(b)
            return float(v) if v else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    return ratio("EXIF ExposureTime"), ratio("EXIF ISOSpeedRatings"), ratio("EXIF FNumber")


def _exposure_seconds(path: Path) -> float:
    return _exposure_params(path)[0]


def _ev_linear(path: Path) -> float:
    """Exposición fotométrica relativa t·ISO/f² (0 si el EXIF no da para más)."""
    t, iso, f = _exposure_params(path)
    if t <= 0 or f <= 0:
        return 0.0
    return t * (iso or 100.0) / (f * f)


def _gap_steps(t_prev: str | None, t_cur: str | None, expo: float) -> int:
    """Posiciones intermedias para que el trazo del frame anterior cubra el
    hueco hasta este: ceil(intervalo/exposición), entre 1 y 8. Sin datos, 2."""
    try:
        dt = (
            datetime.strptime(t_cur, "%Y-%m-%d %H:%M:%S")
            - datetime.strptime(t_prev, "%Y-%m-%d %H:%M:%S")
        ).total_seconds()
    except (TypeError, ValueError):
        return 2
    if dt <= 0 or expo <= 0:
        return 2
    return int(max(1, min(8, math.ceil(dt / expo))))


def _apply_gain(img16: np.ndarray, gain: float) -> np.ndarray:
    """Iguala la exposición en LINEAL (deshace la gamma 2.222, aplica ganancia,
    vuelve). Con ganancia ~1 no toca nada."""
    if abs(gain - 1.0) < 0.05:
        return img16
    lin = (img16.astype(np.float32) / 65535.0) ** 2.222
    out = np.clip(lin * gain, 0, None) ** (1 / 2.222)
    return (np.clip(out, 0, 1) * 65535 + 0.5).astype(np.uint16)


def _sigma_clip_gpu(files: list[Path], H: int, W: int) -> np.ndarray:
    """Sigma-clip en CuPy: los frames suben en uint16 (mitad de transferencia)
    y se convierten en la GPU; rodajas de ~400 MB de VRAM."""
    cp = gpu.cp
    mms = [np.load(f, mmap_mode="r") for f in files]
    res = np.zeros((H, W, 3), np.float32)
    n = len(mms)
    SL = max(8, int(400_000_000 / max(1, W * 3 * 4 * n)))
    for y in range(0, H, SL):
        sl = cp.stack([cp.asarray(np.ascontiguousarray(m[y : y + SL])) for m in mms]).astype(
            cp.float32
        )
        mu = sl.mean(0)
        sd = sl.std(0) + 1e-3
        for _ in range(2):
            mask = cp.abs(sl - mu) < 2.5 * sd
            c = mask.sum(0).clip(1)
            mu = cp.where(mask, sl, 0).sum(0) / c
            sd = cp.sqrt(cp.where(mask, (sl - mu) ** 2, 0).sum(0) / c) + 1e-3
        res[y : y + SL] = cp.asnumpy(mu)
        del sl, mask, mu, sd, c
    return res


def _sigma_clip_stack(files: list[Path], H: int, W: int) -> np.ndarray:
    if gpu.active():
        try:
            return _sigma_clip_gpu(files, H, W)
        except Exception:
            gpu.release()  # sin VRAM suficiente u otro: camino CPU
    mms = [np.load(f, mmap_mode="r") for f in files]
    res = np.zeros((H, W, 3), np.float32)
    n = len(mms)
    SL = max(8, int(80_000_000 / max(1, W * 3 * 4 * n)))
    for y in range(0, H, SL):
        sl = np.stack([m[y : y + SL].astype(np.float32) for m in mms])
        mu = sl.mean(0)
        sd = sl.std(0) + 1e-3
        for _ in range(2):
            mask = np.abs(sl - mu) < 2.5 * sd
            s = np.where(mask, sl, 0).sum(0)
            c = mask.sum(0).clip(1)
            mu = s / c
            sd = np.sqrt(np.where(mask, (sl - mu) ** 2, 0).sum(0) / c) + 1e-3
        res[y : y + SL] = mu
    return res


# ------------------------------------------------------------------ trabajo


def job_fn(photo_ids: list[int], mode: str, crop_px: int = 1200,
           escala: str = "auto", force: bool = False):
    if mode not in MODES:
        raise ValueError(f"Modo desconocido: {mode} (usa {', '.join(MODES)})")
    if len(photo_ids) < 2:
        raise ValueError("Hacen falta al menos 2 fotos para apilar")

    def run(job: dict) -> dict:
        from . import scan

        con = db.connect()
        try:
            rows = [
                con.execute(
                    """SELECT p.id, p.stem, p.ext, p.taken_at, f.name AS folder
                       FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                    (pid,),
                ).fetchone()
                for pid in photo_ids
            ]
        finally:
            con.close()
        rows = [r for r in rows if r is not None]
        folders = {r["folder"] for r in rows}
        if len(folders) != 1:
            raise ValueError(f"Las fotos deben ser de una sola carpeta (hay {len(folders)})")
        folder = rows[0]["folder"]
        rows.sort(key=lambda r: r["stem"])
        root = config.get_root()
        outdir = root / folder

        base = naming.output_base(folder, _LABEL[mode], rows)
        out_tif, out_jpg = outdir / f"{base}.tif", outdir / f"{base}.jpg"
        if not force and (out_tif.exists() or out_jpg.exists()):
            raise ValueError(f"Ya existe {base}.tif/jpg — usa force para sobreescribir")

        half = (escala == "media") or (escala == "auto" and mode in ("estrellas", "media", "hdr"))
        job["progress"]["total"] = len(rows) + 1

        work = config.APP_DIR / "stackwork" / uuid.uuid4().hex[:8]
        work.mkdir(parents=True, exist_ok=True)
        fallidos: list[str] = []
        info: dict = {"modo": mode, "escala": "media" if half else "completa"}

        def _src(r) -> Path:
            return root / folder / (r["stem"] + r["ext"])

        # normalización de exposición (no en max: el máximo mezcla a propósito;
        # no en hdr: Mertens necesita las diferencias)
        gains: dict[str, float] = {}
        expo_s: dict[str, float] = {}
        exp_info: dict | None = None
        if mode in ("luna", "estrellas", "media", "trails"):
            evs: dict[str, float] = {}
            for r in rows:
                p = _src(r)
                if not p.exists():
                    continue
                t, iso, fn = _exposure_params(p)
                expo_s[r["stem"]] = t
                evs[r["stem"]] = t * (iso or 100.0) / (fn * fn) if (t > 0 and fn > 0) else 0.0
            valid = [v for v in evs.values() if v > 0]
            if valid:
                ref_ev = float(np.median(valid))
                gains = {s: (ref_ev / v if v > 0 else 1.0) for s, v in evs.items()}
                gmax = max((max(g, 1 / g) for g in gains.values() if g > 0), default=1.0)
                exp_info = {
                    "normalizadas": sum(1 for g in gains.values() if abs(g - 1) >= 0.05),
                    "ratio_max": round(gmax, 2),
                }

        def _fixed_mask():
            """Patrón fijo (vegetación, luces) con 5 frames repartidos: la
            mediana sin alinear difumina las estrellas y conserva lo quieto.
            Solo la forma mayoritaria: mezclar vertical y horizontal
            (reencuadres con giro de cámara) rompería la mediana."""
            job["progress"]["current"] = "patrón fijo"
            idxs = sorted({0, len(rows) // 4, len(rows) // 2, 3 * len(rows) // 4, len(rows) - 1})
            idxs = [i for i in idxs if _src(rows[i]).exists()]
            with ThreadPoolExecutor(max_workers=workers()) as ex:
                spread = list(
                    ex.map(lambda i: _gray16f(develop.decode(_src(rows[i]), half=half)), idxs)
                )
            if len(spread) < 3:
                return None
            dom = Counter(g.shape for g in spread).most_common(1)[0][0]
            same = [g for g in spread if g.shape == dom]
            if len(same) < 3:
                return None
            return _exclusion_mask(np.median(np.stack(same), axis=0).astype(np.float32), half)

        def _decode_norm(r):
            """Decodifica (en hilos vía prefetch) y ecualiza exposición."""
            if not _src(r).exists():
                raise ValueError("no está en disco")
            img = develop.decode(_src(r), half=half)
            return _apply_gain(img, gains.get(r["stem"], 1.0))

        try:
            npys: list[Path] = []

            if mode == "estrellas":
                excl = _fixed_mask()

                def _pass(seg_rows):
                    """Cadena anclada al medio del segmento + refinamiento absoluto.
                    Devuelve (npys, ref_pts, ref_shape, pendientes, metodo, matches)."""
                    seg_npys: list[Path] = []
                    pend: list[tuple] = []
                    matches: list[int] = []
                    metodo = {"astroalign": 0, "ransac": 0}
                    m0 = len(seg_rows) // 2
                    ref_row = seg_rows[m0]
                    if not _src(ref_row).exists():
                        raise ValueError(f"la referencia {ref_row['stem']} no está en disco")
                    ref_img = _decode_norm(ref_row)
                    rshape = ref_img.shape[:2]
                    rpts = _detect_stars(_gray16f(ref_img), excl, half)
                    if len(rpts) < 20:
                        raise ValueError(
                            f"la referencia {ref_row['stem']} tiene pocas estrellas ({len(rpts)})"
                        )
                    p = work / f"{ref_row['stem']}.npy"
                    np.save(p, ref_img.astype(np.uint16))
                    seg_npys.append(p)
                    job["progress"]["done"] += 1
                    for chain in (seg_rows[m0 + 1 :], seg_rows[m0 - 1 :: -1] if m0 > 0 else []):
                        prev_pts, t_prev = rpts, np.eye(3, dtype=np.float32)
                        for r, img in prefetch(chain, _decode_norm):
                            job["progress"]["current"] = r["stem"]
                            try:
                                if isinstance(img, Exception):
                                    raise img
                                pts = _detect_stars(_gray16f(img), excl, half)
                                M, n, kind = _pair_transform(prev_pts, pts)
                                t_total = _compose(t_prev, M)
                                t_total, n_ref = _refine_to_ref(rpts, pts, t_total)
                                warped = cv2.warpAffine(
                                    img, t_total[:2], (rshape[1], rshape[0]),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                )
                                p = work / f"{r['stem']}.npy"
                                np.save(p, warped.astype(np.uint16))
                                seg_npys.append(p)
                                prev_pts, t_prev = pts, t_total
                                matches.append(max(n, n_ref))
                                metodo[kind] += 1
                            except Exception as exc:
                                pend.append((r, str(exc)))
                            job["progress"]["done"] += 1
                    return seg_npys, rpts, rshape, pend, metodo, matches

                # pasada 1: cadena principal
                npys, ref_pts_a, ref_shape_a, pend, metodo, matches = _pass(rows)

                # pasada 2: los caídos reintentan DIRECTOS contra la referencia
                # (astroalign aguanta reencuadres grandes mientras haya solape)
                recuperadas = 0
                still: list = []
                if pend:
                    job["progress"]["total"] += len(pend)
                    for r, img in prefetch([p[0] for p in pend], _decode_norm):
                        job["progress"]["current"] = f"{r['stem']} (directo)"
                        try:
                            if isinstance(img, Exception):
                                raise img
                            pts = _detect_stars(_gray16f(img), excl, half)
                            M, _n, _kind = _pair_transform(ref_pts_a, pts)
                            t_total = np.vstack([M, [0, 0, 1]]).astype(np.float32)
                            t_total, _n_ref = _refine_to_ref(ref_pts_a, pts, t_total)
                            warped = cv2.warpAffine(
                                img, t_total[:2], (ref_shape_a[1], ref_shape_a[0]),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                            )
                            p = work / f"{r['stem']}.npy"
                            np.save(p, warped.astype(np.uint16))
                            npys.append(p)
                            recuperadas += 1
                        except Exception:
                            still.append(r)
                        job["progress"]["done"] += 1

                # pasada 3: si quedan ≥3, probablemente es OTRO ENCUADRE:
                # se apila aparte con su propio rango
                seg_b = None
                if len(still) >= 3:
                    still.sort(key=lambda r: r["stem"])
                    job["progress"]["total"] += len(still)
                    try:
                        npys_b, _rp, _rs, pend_b, _mb, _matb = _pass(still)
                        for r, why in pend_b:
                            fallidos.append(f"{r['stem']}: {why}")
                        if len(npys_b) >= 3:
                            sample_b = np.load(npys_b[0], mmap_mode="r")
                            res_b = _sigma_clip_stack(
                                npys_b, sample_b.shape[0], sample_b.shape[1]
                            )
                            out_b = np.clip(res_b, 0, 65535).astype(np.uint16)
                            fb, lb = still[0]["stem"][-4:], still[-1]["stem"][-4:]
                            base_b = naming.output_base(folder, _LABEL[mode], still)
                            tif_b, jpg_b = outdir / f"{base_b}.tif", outdir / f"{base_b}.jpg"
                            if force or not (tif_b.exists() or jpg_b.exists()):
                                _save_tif16(out_b, tif_b)
                                _save_jpg(out_b, jpg_b, q=95, subsampling=0, dpi=None)
                                seg_b = {
                                    "rango": f"{fb}-{lb}",
                                    "frames": len(npys_b),
                                    "salida": [f"{folder}/{base_b}.tif", f"{folder}/{base_b}.jpg"],
                                }
                            else:
                                seg_b = {"rango": f"{fb}-{lb}", "frames": len(npys_b),
                                         "error": f"ya existe {base_b} (usa force)"}
                        else:
                            for pth in npys_b:
                                fallidos.append(f"{pth.stem}: encuadre distinto con <3 frames")
                    except ValueError as exc:
                        for r in still:
                            fallidos.append(f"{r['stem']}: posible otro encuadre ({exc})")
                elif still:
                    for r in still:
                        fallidos.append(
                            f"{r['stem']}: no alinea ni con cadena ni directo "
                            "(¿otro encuadre? mínimo 3 frames para apilarlo aparte)"
                        )

                info["alineado"] = metodo | {
                    "matches_mediana": int(np.median(matches)) if matches else 0,
                    "recuperadas_directas": recuperadas,
                    "referencia": rows[len(rows) // 2]["stem"],
                }
                if seg_b is not None:
                    info["encuadres"] = 2
                    info["segmento_b"] = seg_b

            elif mode == "trails":
                excl = _fixed_mask()
                acc = None
                prev_img = prev_pts = prev_row = None
                rellenos = 0
                sin_relleno: list[str] = []
                ident = np.float32([[1, 0, 0], [0, 1, 0]])
                for r, img in prefetch(rows, _decode_norm):
                    job["progress"]["current"] = r["stem"]
                    try:
                        if isinstance(img, Exception):
                            raise img
                        pts = _detect_stars(_gray16f(img), excl, half)
                        if acc is None:
                            acc = img.copy()
                        else:
                            if img.shape != acc.shape:
                                raise ValueError("forma distinta (¿reencuadre con giro?)")
                            acc = np.maximum(acc, img)
                            # relleno del hueco: el frame anterior avanza hacia
                            # este en fracciones del movimiento del cielo
                            try:
                                M, _n, _k = _pair_transform(prev_pts, pts)  # este → anterior
                                m_fwd = cv2.invertAffineTransform(M)  # anterior → este
                                steps = _gap_steps(
                                    prev_row["taken_at"], r["taken_at"],
                                    expo_s.get(prev_row["stem"], 0.0),
                                )
                                H, W = acc.shape[:2]
                                for k in range(1, steps + 1):
                                    f = k / (steps + 1)
                                    mf = ((1 - f) * ident + f * m_fwd).astype(np.float32)
                                    w = cv2.warpAffine(
                                        prev_img, mf, (W, H),
                                        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                    )
                                    if excl is not None and excl.shape == w.shape[:2]:
                                        w[excl > 0] = 0
                                    acc = np.maximum(acc, w)
                                rellenos += 1
                            except Exception as exc:
                                sin_relleno.append(f"{r['stem']}: {exc}")
                        prev_img, prev_pts, prev_row = img, pts, r
                    except Exception as exc:
                        fallidos.append(f"{r['stem']}: {exc}")
                    job["progress"]["done"] += 1
                if acc is None:
                    raise ValueError("Ningún frame válido")
                out16 = acc.astype(np.uint16)
                info["frames"] = len(rows) - len(fallidos)
                info["huecos"] = {"rellenados": rellenos, "sin_rellenar": len(sin_relleno)}
                if sin_relleno:
                    info["huecos"]["detalle"] = sin_relleno[:6]

            else:
                acc_max = None
                hdr_frames: list[tuple[float, np.ndarray]] = []
                ref_crop_gray = None
                win = None
                for r, img in prefetch(rows, _decode_norm):
                    job["progress"]["current"] = r["stem"]
                    src_path = _src(r)
                    try:
                        if isinstance(img, Exception):
                            raise img

                        if mode == "luna":
                            cx, cy = _moon_centroid(img)
                            crop = _crop_at(img, cx, cy, crop_px)
                            g = _grayf(crop)
                            if ref_crop_gray is None:
                                ref_crop_gray = g
                                win = cv2.createHanningWindow(g.shape[::-1], cv2.CV_32F)
                            else:
                                (dx, dy), _ = cv2.phaseCorrelate(g, ref_crop_gray, win)
                                if abs(dx) > 60 or abs(dy) > 60:
                                    raise ValueError(
                                        f"desplazamiento sospechoso ({dx:.0f},{dy:.0f})"
                                    )
                                M = np.float32([[1, 0, dx], [0, 1, dy]])
                                crop = cv2.warpAffine(
                                    crop, M, (crop.shape[1], crop.shape[0]),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT,
                                )
                            p = work / f"{r['stem']}.npy"
                            np.save(p, crop.astype(np.uint16))
                            npys.append(p)

                        elif mode == "media":
                            p = work / f"{r['stem']}.npy"
                            np.save(p, img.astype(np.uint16))
                            npys.append(p)

                        elif mode == "max":
                            acc_max = img.copy() if acc_max is None else np.maximum(acc_max, img)

                        elif mode == "hdr":
                            if len(hdr_frames) >= 12:
                                raise ValueError("máximo 12 frames para HDR")
                            hdr_frames.append((_exposure_seconds(src_path), img))
                    except Exception as exc:
                        fallidos.append(f"{r['stem']}: {exc}")
                    job["progress"]["done"] += 1

            job["progress"]["current"] = "apilando"
            if mode in ("luna", "estrellas", "media"):
                if len(npys) < 2:
                    raise ValueError(
                        f"Solo {len(npys)} frames válidos — {'; '.join(fallidos[:4])}"
                    )
                sample = np.load(npys[0], mmap_mode="r")
                res = _sigma_clip_stack(npys, sample.shape[0], sample.shape[1])
                out16 = np.clip(res, 0, 65535).astype(np.uint16)
                info["frames"] = len(npys)
            elif mode == "max":
                if acc_max is None:
                    raise ValueError("Ningún frame válido")
                out16 = acc_max.astype(np.uint16)
                info["frames"] = len(rows) - len(fallidos)
            elif mode == "trails":
                pass  # out16 ya calculado en su bucle
            else:  # hdr
                if len(hdr_frames) < 2:
                    raise ValueError("Hacen falta al menos 2 exposiciones válidas para HDR")
                hdr_frames.sort(key=lambda t: t[0])
                info["exposiciones"] = [round(t[0], 4) for t in hdr_frames]
                mid_img = hdr_frames[len(hdr_frames) // 2][1]
                gref = _grayf(mid_img)
                win = cv2.createHanningWindow(gref.shape[::-1], cv2.CV_32F)
                aligned = []
                for _sec, im in hdr_frames:
                    g = _grayf(im)
                    (dx, dy), _ = cv2.phaseCorrelate(g, gref, win)
                    M = np.float32([[1, 0, dx], [0, 1, dy]])
                    aligned.append(
                        cv2.warpAffine(
                            im, M, (im.shape[1], im.shape[0]),
                            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT,
                        ).astype(np.float32)
                        / 65535.0
                    )
                merger = cv2.createMergeMertens()
                try:
                    fused = merger.process(aligned)
                except cv2.error:
                    fused = merger.process(
                        [(a * 255).astype(np.uint8) for a in aligned]
                    ).astype(np.float32)
                    fused = fused / 255.0 if fused.max() > 2 else fused
                out16 = (np.clip(fused, 0, 1) * 65535 + 0.5).astype(np.uint16)
                info["frames"] = len(aligned)

            _save_tif16(out16, out_tif)
            _save_jpg(out16, out_jpg, q=95, subsampling=0, dpi=None)
            job["progress"]["done"] += 1

            con = db.connect()
            try:
                scan._scan_folder(con, outdir)
            finally:
                con.close()

            info["salida"] = [f"{folder}/{base}.tif", f"{folder}/{base}.jpg"]
            if exp_info is not None:
                info["exposiciones"] = exp_info
            info["fallidos"] = fallidos
            return info
        finally:
            shutil.rmtree(work, ignore_errors=True)
            gpu.release()

    return run
