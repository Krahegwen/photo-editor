"""API REST local. La UI Vue habla con esto; en F3 el servidor MCP también."""
import datetime as dt
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, db, metrics, previews, scan, xmp

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
        return [dict(r) for r in rows]
    finally:
        con.close()


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
        n = sizes[r.pop("_burst")]
        r["burst_n"] = n if n >= BURST_MIN else None
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
    if not metrics.run(req.folder_id):
        raise HTTPException(409, "Ya hay un análisis en marcha")
    return {"started": True}


@app.get("/api/metrics/status")
def metrics_status():
    return metrics.state


# ---------------------------------------------------------------- borrado


def _audit(action: str, items: list[str]) -> None:
    line = json.dumps(
        {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "items": items},
        ensure_ascii=False,
    )
    with open(config.APP_DIR / "deletions.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


@app.post("/api/delete")
def delete_photos(req: DeleteRequest):
    from send2trash import send2trash

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
            rel = f"{row['folder']}/{row['stem']}{row['ext']}"
            try:
                fpath = root / row["folder"] / (row["stem"] + row["ext"])
                if fpath.exists():
                    send2trash(str(fpath))
                # el sidecar solo se va si ninguna otra foto comparte el stem
                others = con.execute(
                    "SELECT COUNT(*) FROM photos WHERE folder_id=? AND stem=? AND id<>?",
                    (row["folder_id"], row["stem"], pid),
                ).fetchone()[0]
                sidecar = root / row["folder"] / (row["stem"] + ".xmp")
                if others == 0 and sidecar.exists():
                    send2trash(str(sidecar))
                con.execute("DELETE FROM photos WHERE id=?", (pid,))
                con.commit()
                touched.add(row["folder_id"])
                trashed.append(rel)
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
        for fid in touched:
            con.execute(
                "UPDATE folders SET photo_count="
                "(SELECT COUNT(*) FROM photos WHERE folder_id=?) WHERE id=?",
                (fid, fid),
            )
        con.commit()
    finally:
        con.close()
    if trashed:
        _audit("papelera", trashed)
    return {"trashed": trashed, "errors": errors}


# ---------------------------------------------------------------- escaneo


@app.post("/api/scan", status_code=202)
def start_scan(req: ScanRequest | None = None):
    if not scan.run_scan(req.folders if req else None):
        raise HTTPException(409, "Ya hay un escaneo en marcha")
    return {"started": True}


@app.get("/api/scan/status")
def scan_status():
    return scan.state


_dist = Path(__file__).resolve().parents[2] / "app" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="app")
