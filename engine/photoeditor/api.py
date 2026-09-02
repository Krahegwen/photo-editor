"""API REST local. La UI Vue habla con esto; en F3 el servidor MCP también."""
import base64
import datetime as dt
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    __version__,
    closefolder,
    config,
    db,
    develop,
    export,
    gallery,
    gpu,
    jobs,
    metrics,
    parallel,
    previews,
    scan,
    stacking,
    timelapse,
    trash,
    xmp,
)
from .formats import is_raw


def _warmup_gpu() -> None:
    """Compila los kernels de CuPy al arrancar (unos segundos, en segundo
    plano) para que la primera preview/apilado no los pague."""
    if not gpu.AVAILABLE:
        return
    try:
        import numpy as _np

        rng = _np.random.default_rng(0)
        img = rng.random((1024, 1024, 3), dtype=_np.float32)
        develop.apply_recipe(
            img,
            {"temp": 5, "tint": 3, "exposure": 0.3, "contrast": 10, "highlights": -10,
             "shadows": 10, "blacks": 5, "saturation": 10, "vibrance": 10, "sharpen": 20,
             "curve": [[0, 0], [0.5, 0.55], [1, 1]]},
        )
        stacking._detect_stars(rng.random((1024, 1024), dtype=_np.float32) * 1000, None, True)
        gpu.release()
    except Exception:
        pass


threading.Thread(target=_warmup_gpu, name="gpu-warmup", daemon=True).start()

app = FastAPI(title="photo-editor engine", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BURST_GAP_S = 2.5  # hueco máximo entre disparos para considerarlos ráfaga
BURST_MIN = 3


class ScanRequest(BaseModel):
    folders: list[str] | None = None


class RatingItem(BaseModel):
    photo_id: int
    rating: int  # 0..5; 0 = quitar puntuación


class RatingRequest(BaseModel):
    items: list[RatingItem]


class MetricsRequest(BaseModel):
    folder_id: int


class DeleteRequest(BaseModel):
    photo_ids: list[int]


class RecipeRequest(BaseModel):
    recipe: dict


class PreviewRequest(BaseModel):
    photo_id: int
    recipe: dict
    skip_crop: bool = False


class CopyRecipeRequest(BaseModel):
    recipe: dict
    to_photo_ids: list[int]
    include_geometry: bool = False


class ExportRequest(BaseModel):
    photo_ids: list[int]
    preset: str
    force: bool = False


class CloseFolderRequest(BaseModel):
    folder_id: int
    execute: bool = False


class StackRequest(BaseModel):
    photo_ids: list[int]
    mode: str
    crop_px: int = 1200
    escala: str = "auto"
    force: bool = False


class TimelapseRequest(BaseModel):
    photo_ids: list[int]
    fps: int = 24
    force: bool = False


class KeywordsItem(BaseModel):
    photo_id: int
    keywords: list[str]
    replace: bool = False


class KeywordsRequest(BaseModel):
    items: list[KeywordsItem]


class GalleryRequest(BaseModel):
    folder_id: int | None = None
    photo_ids: list[int] | None = None
    min_rating: int = 4
    titulo: str | None = None


# ---------------------------------------------------------------- estado


@app.get("/api/health")
def health():
    try:
        root, root_error = str(config.get_root()), None
    except RuntimeError as exc:
        root, root_error = None, str(exc)
    con = db.connect()
    try:
        folders = con.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
        photos = con.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    finally:
        con.close()
    return {
        "ok": root_error is None,
        "root": root,
        "gpu": gpu.info(),
        "threads": parallel.workers(),
        "root_error": root_error,
        "folders": folders,
        "photos": photos,
        "version": __version__,
    }


# ---------------------------------------------------------------- catálogo


@app.get("/api/folders")
def list_folders():
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT id, name, photo_count, last_scan FROM folders ORDER BY name DESC"
        ).fetchall()
    finally:
        con.close()
    try:
        root = config.get_root()
    except RuntimeError:
        root = None
    out = []
    for r in rows:
        d = dict(r)
        # renombrada/movida desde fuera (Explorador): la UI avisa y ofrece escanear
        d["exists"] = bool(root and (root / r["name"]).is_dir())
        out.append(d)
    return out


class GpuRequest(BaseModel):
    enabled: bool


@app.post("/api/gpu")
def set_gpu(req: GpuRequest):
    """Interruptor GPU/CPU en caliente (afecta a los trabajos que empiecen)."""
    return gpu.set_enabled(req.enabled)


class RenameFolderRequest(BaseModel):
    name: str


_BAD_NAME_CHARS = set('\\/:*?"<>|')


@app.post("/api/folders/{folder_id}/rename")
def rename_folder(folder_id: int, req: RenameFolderRequest):
    """Renombra la carpeta en disco y en el índice; migra la caché de previews
    (su clave es la ruta relativa) para no regenerarla."""
    new = req.name.strip().rstrip(".")
    if not new or (_BAD_NAME_CHARS & set(new)):
        raise HTTPException(400, 'Nombre no válido (sin \\ / : * ? " < > |)')
    if new.startswith((".", "_", "999998")):
        raise HTTPException(400, "Los nombres que empiezan por . _ o 999998 se ignoran al escanear")
    if jobs.active():
        raise HTTPException(409, "Espera a que termine la cola de trabajos antes de renombrar")
    root = config.get_root()
    con = db.connect()
    try:
        row = con.execute("SELECT id, name FROM folders WHERE id=?", (folder_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Carpeta no encontrada")
        old = row["name"]
        if new == old:
            return {"ok": True, "name": old, "previews_migradas": 0}
        src, dst = root / old, root / new
        if not src.is_dir():
            raise HTTPException(404, f"La carpeta {old} no está en disco")
        if dst.exists() and dst.resolve() != src.resolve():
            raise HTTPException(409, f"Ya existe {new}")
        photos = con.execute(
            "SELECT stem, ext, mtime FROM photos WHERE folder_id=?", (folder_id,)
        ).fetchall()
        try:
            src.rename(dst)
        except OSError as exc:
            raise HTTPException(500, f"No se pudo renombrar en disco: {exc}") from exc
        con.execute("UPDATE folders SET name=? WHERE id=?", (new, folder_id))
        con.commit()
    finally:
        con.close()
    moved = 0
    for p in photos:
        for size in previews.SIZES:
            a = previews._cache_path(f"{old}/{p['stem']}{p['ext']}", p["mtime"], size)
            if a.exists():
                a.replace(previews._cache_path(f"{new}/{p['stem']}{p['ext']}", p["mtime"], size))
                moved += 1
    return {"ok": True, "name": new, "previews_migradas": moved}


def _parse_dt(text: str | None) -> dt.datetime | None:
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _annotate(rows: list[dict]) -> list[dict]:
    """Añade flags de sospecha (vs. mediana de la carpeta) y ráfagas."""
    sharps = sorted(
        r["sharp"] for r in rows if r["sharp"] is not None and (r["bright"] or 0) > 10
    )
    med = sharps[len(sharps) // 2] if sharps else None

    gid, prev = 0, None
    sizes: dict[int, int] = {}
    for r in rows:
        t = _parse_dt(r["taken_at"])
        if t is None or prev is None or (t - prev).total_seconds() > BURST_GAP_S:
            gid += 1
        r["_burst"] = gid
        sizes[gid] = sizes.get(gid, 0) + 1
        prev = t

    for r in rows:
        flags = []
        if r["metrics_at"] is not None and r["sharp"] is not None:
            b = r["bright"] or 0
            if b < 6 and (r["clip_lo"] or 0) > 0.85:
                flags.append("vacía")
            elif med and b > 10 and r["sharp"] < 0.30 * med:
                flags.append("borrosa")
            if (r["clip_hi"] or 0) > 0.15:
                flags.append("quemada")
        r["flags"] = flags
        r["best_of_burst"] = False

    by_gid: dict[int, list[dict]] = {}
    for r in rows:
        by_gid.setdefault(r["_burst"], []).append(r)
    for r in rows:
        n = sizes[r.pop("_burst")]
        r["burst_n"] = n if n >= BURST_MIN else None
    # la más nítida de cada ráfaga, como guía de cribado
    for members in by_gid.values():
        if len(members) >= BURST_MIN:
            with_sharp = [m for m in members if m["sharp"] is not None]
            if with_sharp:
                max(with_sharp, key=lambda m: m["sharp"])["best_of_burst"] = True
    return rows


@app.get("/api/photos")
def list_photos(folder_id: int):
    con = db.connect()
    try:
        rows = [
            dict(r)
            for r in con.execute(
                """SELECT id, stem, ext, bytes, mtime, taken_at, rating,
                          sharp, clip_hi, clip_lo, bright, metrics_at
                   FROM photos WHERE folder_id=? ORDER BY stem, ext""",
                (folder_id,),
            ).fetchall()
        ]
        for r in rows:
            r["has_recipe"] = False
        try:
            fname = con.execute("SELECT name FROM folders WHERE id=?", (folder_id,)).fetchone()
            if fname:
                fdir = config.get_root() / fname["name"]
                for r in rows:
                    r["has_recipe"] = (fdir / f"{r['stem']}.pe.json").exists()
        except RuntimeError:
            pass
        return _annotate(rows)
    finally:
        con.close()


def _photo_row(con, photo_id: int):
    row = con.execute(
        """SELECT p.id, p.stem, p.ext, p.bytes, p.mtime, p.folder_id, f.name AS folder
           FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
        (photo_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Foto no encontrada en el catálogo")
    if not (config.get_root() / row["folder"]).is_dir():
        raise HTTPException(
            409,
            f"La carpeta '{row['folder']}' ya no está en disco (¿renombrada desde el "
            "Explorador?). Escanea el archivo para sincronizar el catálogo.",
        )
    return row


# ---------------------------------------------------------------- previews / exif


@app.get("/api/preview/{photo_id}")
def preview(photo_id: int, s: int = 320):
    con = db.connect()
    try:
        row = _photo_row(con, photo_id)
    finally:
        con.close()
    rel = f"{row['folder']}/{row['stem']}{row['ext']}"
    abs_path = config.get_root() / row["folder"] / (row["stem"] + row["ext"])
    if not abs_path.exists():
        raise HTTPException(404, f"El archivo ya no está en disco: {rel}")
    try:
        out = previews.get_preview(abs_path, rel, row["mtime"], s)
    except Exception as exc:
        raise HTTPException(500, f"No pude generar la preview de {rel}: {exc}") from exc
    return FileResponse(
        out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )


def _fmt_ratio(text: str | None, prefix: str = "", suffix: str = "") -> str | None:
    if not text:
        return None
    try:
        if "/" in text:
            a, b = text.split("/")
            val = float(a) / float(b)
        else:
            val = float(text)
        return f"{prefix}{val:g}{suffix}"
    except (ValueError, ZeroDivisionError):
        return f"{prefix}{text}{suffix}"


@app.get("/api/exif/{photo_id}")
def exif(photo_id: int):
    import exifread

    con = db.connect()
    try:
        row = _photo_row(con, photo_id)
    finally:
        con.close()
    abs_path = config.get_root() / row["folder"] / (row["stem"] + row["ext"])
    if not abs_path.exists():
        raise HTTPException(404, "El archivo ya no está en disco")
    try:
        with open(abs_path, "rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except Exception:
        tags = {}

    def g(*names):
        for n in names:
            if n in tags:
                return str(tags[n])
        return None

    return {
        "archivo": f"{row['stem']}{row['ext']}",
        "camara": g("Image Model"),
        "objetivo": g("EXIF LensModel"),
        "expo": g("EXIF ExposureTime"),
        "f": _fmt_ratio(g("EXIF FNumber"), prefix="f/"),
        "iso": g("EXIF ISOSpeedRatings"),
        "focal": _fmt_ratio(g("EXIF FocalLength"), suffix=" mm"),
        "fecha": g("EXIF DateTimeOriginal"),
        "dimensiones": (
            f"{g('EXIF ExifImageWidth')}×{g('EXIF ExifImageLength')}"
            if g("EXIF ExifImageWidth")
            else None
        ),
        "peso_mb": round(row["bytes"] / 1e6, 1),
    }


# ---------------------------------------------------------------- rating


@app.post("/api/rating")
def set_rating(req: RatingRequest):
    root = config.get_root()
    con = db.connect()
    results = []
    try:
        for it in req.items:
            if not 0 <= it.rating <= 5:
                results.append(
                    {"photo_id": it.photo_id, "ok": False, "error": "rating fuera de 0..5"}
                )
                continue
            try:
                row = _photo_row(con, it.photo_id)
                sidecar = root / row["folder"] / (row["stem"] + ".xmp")
                xmp.write_rating(sidecar, it.rating)
                con.execute(
                    "UPDATE photos SET rating=? WHERE folder_id=? AND stem=?",
                    (it.rating if it.rating > 0 else None, row["folder_id"], row["stem"]),
                )
                con.commit()
                results.append({"photo_id": it.photo_id, "ok": True})
            except HTTPException as exc:
                results.append({"photo_id": it.photo_id, "ok": False, "error": exc.detail})
            except Exception as exc:
                results.append({"photo_id": it.photo_id, "ok": False, "error": str(exc)})
    finally:
        con.close()
    return {"results": results}


# ---------------------------------------------------------------- métricas


@app.post("/api/metrics", status_code=202)
def start_metrics(req: MetricsRequest):
    con = db.connect()
    try:
        row = con.execute("SELECT name FROM folders WHERE id=?", (req.folder_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Carpeta no encontrada")
    return jobs.submit("metrics", f"Nitidez · {row['name']}", metrics.job_fn(req.folder_id))


# ---------------------------------------------------------------- borrado


@app.post("/api/delete")
def delete_photos(req: DeleteRequest):
    root = config.get_root()
    con = db.connect()
    trashed, errors = [], []
    touched: set[int] = set()
    try:
        for pid in req.photo_ids:
            try:
                row = _photo_row(con, pid)
            except HTTPException:
                errors.append(f"id {pid}: no está en el catálogo")
                continue
            try:
                trashed += trash.trash_photo(con, root, row)
                touched.add(row["folder_id"])
            except Exception as exc:
                errors.append(f"{row['folder']}/{row['stem']}{row['ext']}: {exc}")
        for fid in touched:
            con.execute(
                "UPDATE folders SET photo_count="
                "(SELECT COUNT(*) FROM photos WHERE folder_id=?) WHERE id=?",
                (fid, fid),
            )
        con.commit()
    finally:
        con.close()
    trash.audit("papelera", trashed)
    return {"trashed": trashed, "errors": errors}


# ---------------------------------------------------------------- revelado


@app.post("/api/develop/preview")
def develop_preview(req: PreviewRequest):
    t0 = time.time()
    con = db.connect()
    try:
        row = _photo_row(con, req.photo_id)
    finally:
        con.close()
    abs_path = config.get_root() / row["folder"] / (row["stem"] + row["ext"])
    if not abs_path.exists():
        raise HTTPException(404, "El archivo ya no está en disco")
    try:
        proxy = develop.get_proxy(req.photo_id, abs_path, row["mtime"])
        out = develop.apply_recipe(proxy, req.recipe, skip_crop=req.skip_crop)
        jpeg = develop.encode_jpeg(out)
        hist = develop.histogram(out)
    except Exception as exc:
        raise HTTPException(500, f"Fallo revelando: {exc}") from exc
    return {
        "jpeg_b64": base64.b64encode(jpeg).decode("ascii"),
        "hist": hist,
        "w": out.shape[1],
        "h": out.shape[0],
        "ms": int((time.time() - t0) * 1000),
    }


@app.post("/api/develop/copy")
def copy_recipe(req: CopyRecipeRequest):
    recipe = develop.normalize(req.recipe)
    if not req.include_geometry:
        for k in ("crop", "rot90", "angle"):
            recipe[k] = develop.DEFAULTS[k]
    con = db.connect()
    results = []
    try:
        root = config.get_root()
        for pid in req.to_photo_ids:
            try:
                row = _photo_row(con, pid)
                develop.save_recipe(
                    develop.recipe_path(root, row["folder"], row["stem"]), recipe
                )
                results.append({"photo_id": pid, "ok": True})
            except HTTPException as exc:
                results.append({"photo_id": pid, "ok": False, "error": exc.detail})
            except Exception as exc:
                results.append({"photo_id": pid, "ok": False, "error": str(exc)})
    finally:
        con.close()
    return {"results": results}


def _recipe_file(photo_id: int) -> Path:
    con = db.connect()
    try:
        row = _photo_row(con, photo_id)
    finally:
        con.close()
    return develop.recipe_path(config.get_root(), row["folder"], row["stem"])


@app.get("/api/develop/{photo_id}")
def get_recipe(photo_id: int):
    return {"recipe": develop.load_recipe(_recipe_file(photo_id)), "defaults": develop.DEFAULTS}


@app.put("/api/develop/{photo_id}")
def put_recipe(photo_id: int, req: RecipeRequest):
    develop.save_recipe(_recipe_file(photo_id), req.recipe)
    return {"ok": True}


@app.delete("/api/develop/{photo_id}")
def delete_recipe(photo_id: int):
    path = _recipe_file(photo_id)
    if path.exists():
        path.unlink()
    return {"ok": True}


# ---------------------------------------------------------------- exportación


@app.post("/api/export", status_code=202)
def start_export(req: ExportRequest):
    if req.preset not in export.PRESETS:
        raise HTTPException(400, f"Preset desconocido: {req.preset}")
    return jobs.submit(
        "export",
        f"Exportar {len(req.photo_ids)} · {req.preset}",
        export.job_fn(req.photo_ids, req.preset, req.force),
    )


# ---------------------------------------------------------------- cerrar carpeta


@app.post("/api/close_folder")
def close_folder(req: CloseFolderRequest):
    try:
        report = closefolder.analyze(req.folder_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not req.execute:
        return {"report": report, "job": None}
    job = jobs.submit(
        "close", f"Cerrar {report['folder']}", closefolder.job_fn(req.folder_id)
    )
    return {"report": report, "job": job}


# ---------------------------------------------------------------- apilado


@app.post("/api/stack", status_code=202)
def start_stack(req: StackRequest):
    try:
        fn = stacking.job_fn(req.photo_ids, req.mode, req.crop_px, req.escala, req.force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return jobs.submit("stack", f"Apilar {len(req.photo_ids)} · {req.mode}", fn)


# ---------------------------------------------------------------- timelapse


@app.post("/api/timelapse", status_code=202)
def start_timelapse(req: TimelapseRequest):
    try:
        fn = timelapse.job_fn(req.photo_ids, req.fps, req.force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return jobs.submit(
        "timelapse", f"Timelapse {len(req.photo_ids)}f · {req.fps}fps", fn
    )


# ---------------------------------------------------------------- keywords


@app.post("/api/keywords")
def set_keywords(req: KeywordsRequest):
    root = config.get_root()
    con = db.connect()
    results = []
    try:
        for it in req.items:
            try:
                row = _photo_row(con, it.photo_id)
                sidecar = root / row["folder"] / (row["stem"] + ".xmp")
                final = xmp.write_keywords(sidecar, it.keywords, it.replace)
                results.append({"photo_id": it.photo_id, "ok": True, "keywords": final})
            except HTTPException as exc:
                results.append({"photo_id": it.photo_id, "ok": False, "error": exc.detail})
            except Exception as exc:
                results.append({"photo_id": it.photo_id, "ok": False, "error": str(exc)})
    finally:
        con.close()
    return {"results": results}


# ---------------------------------------------------------------- galería


@app.post("/api/gallery", status_code=202)
def start_gallery(req: GalleryRequest):
    con = db.connect()
    try:
        if req.photo_ids:
            ids = req.photo_ids
            titulo = req.titulo or "galeria"
        elif req.folder_id is not None:
            folder = con.execute(
                "SELECT name FROM folders WHERE id=?", (req.folder_id,)
            ).fetchone()
            if folder is None:
                raise HTTPException(404, "Carpeta no encontrada")
            rows = con.execute(
                """SELECT id, stem, ext FROM photos
                   WHERE folder_id=? AND rating>=? ORDER BY stem, ext""",
                (req.folder_id, max(1, req.min_rating)),
            ).fetchall()
            by_stem: dict[str, list] = {}
            for r in rows:
                by_stem.setdefault(r["stem"], []).append(r)
            ids = []
            for stem in sorted(by_stem):
                group = by_stem[stem]
                raws = [r for r in group if is_raw(r["ext"])]
                ids.append((raws or group)[0]["id"])
            titulo = req.titulo or folder["name"]
        else:
            raise HTTPException(400, "Indica folder_id o photo_ids")
    finally:
        con.close()
    if not ids:
        raise HTTPException(400, "Ninguna foto cumple el filtro")
    try:
        fn = gallery.job_fn(ids, titulo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return jobs.submit("gallery", f"Galería · {titulo} ({len(ids)})", fn)


# ---------------------------------------------------------------- trabajos


@app.get("/api/jobs")
def list_jobs(limit: int = 20):
    return jobs.recent(limit)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "Trabajo no encontrado (el historial es del proceso actual)")
    return j


# ---------------------------------------------------------------- escaneo


@app.post("/api/scan", status_code=202)
def start_scan(req: ScanRequest | None = None):
    only = req.folders if req else None
    title = f"Escanear {len(only)} carpetas" if only else "Escanear archivo"
    return jobs.submit("scan", title, scan.job_fn(only))


_dist = Path(__file__).resolve().parents[2] / "app" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="app")
