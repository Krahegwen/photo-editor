"""Escaneo incremental del archivo fotográfico a SQLite.

Solo el primer nivel de cada carpeta de fecha; se saltan carpetas ocultas,
las que empiezan por "_" (trabajo temporal) y 999998* (herramientas).
"""
import re
import threading
import time
from pathlib import Path

import exifread

from . import config, db, xmp

IMAGE_EXTS = {".arw", ".jpg", ".jpeg", ".tif", ".tiff", ".png"}
_EXIF_DT = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) ")

_lock = threading.Lock()
state: dict = {
    "running": False,
    "folder": None,
    "done": 0,
    "total": 0,
    "error": None,
    "finished_at": None,
}


def _taken_at(path: Path) -> str | None:
    try:
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False, stop_tag="EXIF DateTimeOriginal")
        val = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        return _EXIF_DT.sub(r"\1-\2-\3 ", str(val)) if val else None
    except Exception:
        return None


def folder_dirs(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and not p.name.startswith((".", "_", "999998")):
            out.append(p)
    return out


def _scan_folder(con, folder: Path) -> None:
    con.execute("INSERT OR IGNORE INTO folders(name) VALUES(?)", (folder.name,))
    fid = con.execute("SELECT id FROM folders WHERE name=?", (folder.name,)).fetchone()[0]
    known = {
        (r["stem"], r["ext"]): r
        for r in con.execute(
            "SELECT id, stem, ext, bytes, mtime FROM photos WHERE folder_id=?", (fid,)
        )
    }
    seen = set()
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext not in IMAGE_EXTS:
            continue
        st = f.stat()
        key = (f.stem, ext)
        seen.add(key)
        prev = known.get(key)
        if prev is not None and prev["bytes"] == st.st_size and abs(prev["mtime"] - st.st_mtime) < 1:
            continue
        con.execute(
            """INSERT INTO photos(folder_id, stem, ext, bytes, mtime, taken_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(folder_id, stem, ext) DO UPDATE
               SET bytes=excluded.bytes, mtime=excluded.mtime, taken_at=excluded.taken_at""",
            (fid, f.stem, ext, st.st_size, st.st_mtime, _taken_at(f)),
        )
    for key, row in known.items():
        if key not in seen:
            con.execute("DELETE FROM photos WHERE id=?", (row["id"],))
    # Ratings desde sidecars en cada pasada: recogen también los borrados.
    con.execute("UPDATE photos SET rating=NULL WHERE folder_id=?", (fid,))
    for sc in folder.glob("*.xmp"):
        r = xmp.read_rating(sc)
        if r is not None:
            con.execute(
                "UPDATE photos SET rating=? WHERE folder_id=? AND stem=?", (r, fid, sc.stem)
            )
    con.execute(
        "UPDATE folders SET photo_count=(SELECT COUNT(*) FROM photos WHERE folder_id=?),"
        " last_scan=? WHERE id=?",
        (fid, time.time(), fid),
    )
    con.commit()


def _scan_thread(only: list[str] | None) -> None:
    con = db.connect()
    try:
        root = config.get_root()
        dirs = folder_dirs(root)
        if only:
            wanted = set(only)
            dirs = [d for d in dirs if d.name in wanted]
        state["total"] = len(dirs)
        if not only:
            names = {d.name for d in dirs}
            for r in con.execute("SELECT id, name FROM folders").fetchall():
                if r["name"] not in names:
                    con.execute("DELETE FROM folders WHERE id=?", (r["id"],))
            con.commit()
        for d in dirs:
            state["folder"] = d.name
            _scan_folder(con, d)
            state["done"] += 1
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        state.update(running=False, folder=None, finished_at=time.time())
        con.close()


def run_scan(only: list[str] | None = None) -> bool:
    with _lock:
        if state["running"]:
            return False
        state.update(running=True, folder=None, done=0, total=0, error=None, finished_at=None)
    threading.Thread(target=_scan_thread, args=(only,), daemon=True).start()
    return True
