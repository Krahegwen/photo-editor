"""Apilado astro: port de proc.py/stack.py del flujo previo + alineado de estrellas.

Modos:
- luna:      centroide del disco brillante, recorte NxN y alineado subpíxel
             (phaseCorrelate), media sigma-clip. Port directo de proc.py.
- estrellas: detección DoG de estrellas (excluyendo el patrón fijo: vegetación,
             luces) y alineado INCREMENTAL entre frames consecutivos —
             astroalign por triángulos con fallback NN+RANSAC — componiendo
             similitudes ancladas al frame central. Media sigma-clip.
- media:     sin alinear, media sigma-clip (reducción de ruido, escena fija).
- max:       sin alinear, máximo por píxel (trails, composite de fuegos).
- hdr:       brackets ordenados por exposición, alineado por traslación y
             fusión de exposiciones (Mertens).

Por qué incremental: entre frames consecutivos el cielo se mueve ~2 px y el
matching es trivial y robusto; entre extremos de una sesión (rotación de campo
de varios grados, nubes, estrellas que entran/salen) el matching directo
falla. Verificado con las Perseidas 240812.

Los frames decodificados van como .npy uint16 a %LOCALAPPDATA%/stackwork
(nunca dentro de las carpetas del usuario) y se borran al terminar. El
resultado se guarda como TIFF16 LZW + JPG q95 en la carpeta; el acabado fino
(enfoque/saturación, el viejo finish.py) se hace abriendo el TIFF en Revelar.
"""
import shutil
import uuid
from pathlib import Path

import cv2
import numpy as np

try:
    import astroalign as _aa
except Exception:  # opcional: sin él queda el fallback NN+RANSAC
    _aa = None

from . import config, db, develop
from .export import _save_jpg, _save_tif16

MODES = ("luna", "estrellas", "media", "max", "hdr")
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
    d = cv2.GaussianBlur(gray, (0, 0), s) - cv2.GaussianBlur(gray, (0, 0), 3 * s)
    if excl is not None:
        d[excl > 0] = 0
    mad = float(np.median(np.abs(d))) + 1e-3
    peaks = (d == cv2.dilate(d, np.ones((5, 5), np.uint8))) & (d > 8.0 * mad)
    ys, xs = np.nonzero(peaks)
    if not len(xs):
        return np.empty((0, 2), np.float32)
    order = np.argsort(-d[ys, xs])[:cap]
    return np.stack([xs[order], ys[order]]).T.astype(np.float32)


def _pair_transform(
    prev_pts: np.ndarray, pts: np.ndarray
) -> tuple[np.ndarray, int, str]:
    """Similitud frame→frame anterior (movimiento pequeño). astroalign primero;
    fallback vecino-más-próximo + RANSAC. Escala fuera de [0.98, 1.02] = frame
    descartado: mejor perder uno que meter una transformación espuria."""
    if len(prev_pts) >= 10 and len(pts) >= 10 and _aa is not None:
        try:
            t, (s, _d) = _aa.find_transform(pts, prev_pts, max_control_points=120)
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


def _exposure_seconds(path: Path) -> float:
    import exifread

    try:
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False, stop_tag="EXIF ExposureTime")
        val = str(tags.get("EXIF ExposureTime", "")).strip()
        if "/" in val:
            a, b = val.split("/")
            return float(a) / float(b)
        return float(val) if val else 0.0
    except Exception:
        return 0.0


def _sigma_clip_stack(files: list[Path], H: int, W: int) -> np.ndarray:
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
                    """SELECT p.id, p.stem, p.ext, f.name AS folder
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

        first4, last4 = rows[0]["stem"][-4:], rows[-1]["stem"][-4:]
        base = f"apilado_{mode}_{first4}-{last4}"
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

        try:
            npys: list[Path] = []

            if mode == "estrellas":
                # patrón fijo con 5 frames repartidos (mediana difumina estrellas)
                job["progress"]["current"] = "patrón fijo"
                idxs = sorted({0, len(rows) // 4, len(rows) // 2, 3 * len(rows) // 4, len(rows) - 1})
                spread = [
                    _gray16f(develop.decode(_src(rows[i]), half=half))
                    for i in idxs
                    if _src(rows[i]).exists()
                ]
                excl = None
                if len(spread) >= 3:
                    excl = _exclusion_mask(
                        np.median(np.stack(spread), axis=0).astype(np.float32), half
                    )

                mid = len(rows) // 2
                ref_img = develop.decode(_src(rows[mid]), half=half)
                ref_shape = ref_img.shape[:2]
                ref_pts = _detect_stars(_gray16f(ref_img), excl, half)
                if len(ref_pts) < 20:
                    raise ValueError(
                        f"El frame de referencia ({rows[mid]['stem']}) tiene pocas "
                        f"estrellas ({len(ref_pts)})"
                    )
                p = work / f"{rows[mid]['stem']}.npy"
                np.save(p, ref_img.astype(np.uint16))
                npys.append(p)
                job["progress"]["done"] += 1
                matches: list[int] = []
                refinadas = 0
                metodo = {"astroalign": 0, "ransac": 0}

                for chain in (rows[mid + 1 :], rows[mid - 1 :: -1] if mid > 0 else []):
                    prev_pts = ref_pts
                    t_prev = np.eye(3, dtype=np.float32)
                    for r in chain:
                        job["progress"]["current"] = r["stem"]
                        try:
                            src_path = _src(r)
                            if not src_path.exists():
                                raise ValueError("no está en disco")
                            img = develop.decode(src_path, half=half)
                            pts = _detect_stars(_gray16f(img), excl, half)
                            M, n, kind = _pair_transform(prev_pts, pts)
                            t_total = _compose(t_prev, M)
                            t_total, n_ref = _refine_to_ref(ref_pts, pts, t_total)
                            if n_ref:
                                refinadas += 1
                            warped = cv2.warpAffine(
                                img, t_total[:2], (ref_shape[1], ref_shape[0]),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                            )
                            p = work / f"{r['stem']}.npy"
                            np.save(p, warped.astype(np.uint16))
                            npys.append(p)
                            prev_pts, t_prev = pts, t_total
                            matches.append(max(n, n_ref))
                            metodo[kind] += 1
                        except Exception as exc:
                            fallidos.append(f"{r['stem']}: {exc}")
                        job["progress"]["done"] += 1
                info["alineado"] = metodo | {
                    "matches_mediana": int(np.median(matches)) if matches else 0,
                    "refinadas_contra_ref": refinadas,
                    "referencia": rows[mid]["stem"],
                }

            else:
                acc_max = None
                hdr_frames: list[tuple[float, np.ndarray]] = []
                ref_crop_gray = None
                win = None
                for r in rows:
                    job["progress"]["current"] = r["stem"]
                    src_path = _src(r)
                    try:
                        if not src_path.exists():
                            raise ValueError("no está en disco")
                        img = develop.decode(src_path, half=half)

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
            info["fallidos"] = fallidos
            return info
        finally:
            shutil.rmtree(work, ignore_errors=True)

    return run
