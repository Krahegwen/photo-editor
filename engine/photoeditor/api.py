"""API REST local. La UI Vue habla con esto; en F3 el servidor MCP también."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, db, previews, scan

app = FastAPI(title="photo-editor engine", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    folders: list[str] | None = None


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


@app.get("/api/photos")
def list_photos(folder_id: int):
    con = db.connect()
    try:
        rows = con.execute(
            """SELECT id, stem, ext, bytes, mtime, taken_at, rating
               FROM photos WHERE folder_id=? ORDER BY stem, ext""",
            (folder_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _photo_path(photo_id: int) -> tuple[Path, str, float]:
    con = db.connect()
    try:
        row = con.execute(
            """SELECT p.stem, p.ext, p.mtime, f.name AS folder
               FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
            (photo_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "Foto no encontrada en el catálogo")
    rel = f"{row['folder']}/{row['stem']}{row['ext']}"
    return config.get_root() / row["folder"] / (row["stem"] + row["ext"]), rel, row["mtime"]


@app.get("/api/preview/{photo_id}")
def preview(photo_id: int, s: int = 320):
    abs_path, rel, mtime = _photo_path(photo_id)
    if not abs_path.exists():
        raise HTTPException(404, f"El archivo ya no está en disco: {rel}")
    try:
        out = previews.get_preview(abs_path, rel, mtime, s)
    except Exception as exc:
        raise HTTPException(500, f"No pude generar la preview de {rel}: {exc}") from exc
    return FileResponse(
        out, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"}
    )


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
