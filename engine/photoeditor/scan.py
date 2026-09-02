"""Escaneo incremental del archivo fotográfico a SQLite.

Solo el primer nivel de cada carpeta de fecha; se saltan carpetas ocultas,
las que empiezan por "_" (trabajo temporal) y 999998* (herramientas).
"""
import re
import time
from pathlib import Path

import exifread

from . import config, db, xmp
from .formats import IMAGE_EXTS

_EXIF_DT = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) ")


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


def _has_images(d: Path) -> bool:
    try:
        return any(p.is_file() and p.suffix.lower() in IMAGE_EXTS for p in d.iterdir())
    except OSError:
        return False


def inspect_root(path: Path) -> dict:
    """Qué se indexaría en esa ruta: subcarpetas con fotos y fotos sueltas en
    la propia raíz (que pasan a ser una carpeta más, la de la raíz)."""
    subs = [d for d in folder_dirs(path) if _has_images(d)]
    sueltas = sum(1 for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    return {"subcarpetas": len(subs), "fotos_sueltas": sueltas, "ejemplos": [d.name for d in subs[:4]]}


def scan_targets(root: Path) -> list[tuple[Path, str]]:
    """(directorio, nombre en el catálogo): las subcarpetas de fecha y, si la
    raíz tiene fotos sueltas, la propia raíz como '.'."""
    targets = [(d, d.name) for d in folder_dirs(root)]
    if _has_images(root):
        targets.insert(0, (root, config.ROOT_FOLDER))
    return targets


def _scan_folder(con, folder: Path, name: str | None = None) -> None:
    name = name or folder.name
    con.execute("INSERT OR IGNORE INTO folders(name) VALUES(?)", (name,))
    fid = con.execute("SELECT id FROM folders WHERE name=?", (name,)).fetchone()[0]
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
               SET bytes=excluded.bytes, mtime=excluded.mtime, taken_at=excluded.taken_at,
                   sharp=NULL, clip_hi=NULL, clip_lo=NULL, bright=NULL, metrics_at=NULL""",
            (fid, f.stem, ext, st.st_size, st.st_mtime, _taken_at(f)),
        )
    for key, row in known.items():
        if key not in seen:
            con.execute("DELETE FROM photos WHERE id=?", (row["id"],))
    # Ratings desde sidecars en cada pasada: recogen también los borrados.
    con.execute("UPDATE photos SET rating=NULL WHERE folder_id=?", (fid,))
    for sc in folder.glob("*.xmp"):
        r = xmp.read_rating(sc)
        if r is not None and r > 0:  # 0 = sin puntuar, igual que Lightroom
            con.execute(
                "UPDATE photos SET rating=? WHERE folder_id=? AND stem=?", (r, fid, sc.stem)
            )
    con.execute(
        "UPDATE folders SET photo_count=(SELECT COUNT(DISTINCT stem) FROM photos WHERE folder_id=?),"
        " last_scan=? WHERE id=?",
        (fid, time.time(), fid),
    )
    con.commit()


def job_fn(only: list[str] | None):
    """Función de trabajo para la cola (jobs.submit)."""

    def run(job: dict) -> dict:
        con = db.connect()
        try:
            root = config.get_root()
            targets = scan_targets(root)
            if only:
                wanted = set(only)
                targets = [t for t in targets if t[1] in wanted]
            job["progress"]["total"] = len(targets)
            adoptadas: list[str] = []
            if not only:
                names = {n for _, n in targets}
                known = {r["name"]: r["id"] for r in con.execute("SELECT id, name FROM folders")}
                missing = [(n, fid) for n, fid in known.items() if n not in names]
                new_dirs = [d for d, n in targets if n not in known and n != config.ROOT_FOLDER]
                # Carpeta renombrada desde fuera (Explorador): si un directorio
                # nuevo tiene casi las mismas fotos que una carpeta desaparecida,
                # es la misma → se adopta el nombre y se conservan métricas e ids.
                for old_name, fid in missing:
                    stems = {
                        r["stem"]
                        for r in con.execute("SELECT stem FROM photos WHERE folder_id=?", (fid,))
                    }
                    if not stems:
                        continue
                    best, best_score = None, 0.0
                    for d in new_dirs:
                        on_disk = {p.stem for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS}
                        if not on_disk:
                            continue
                        score = len(stems & on_disk) / max(len(stems), len(on_disk))
                        if score > best_score:
                            best, best_score = d, score
                    if best is not None and best_score >= 0.8:
                        con.execute("UPDATE folders SET name=? WHERE id=?", (best.name, fid))
                        _migrate_preview_cache(con, fid, old_name, best.name)
                        new_dirs.remove(best)
                        adoptadas.append(f"{old_name} → {best.name}")
                        names.add(best.name)
                    else:
                        con.execute("DELETE FROM folders WHERE id=?", (fid,))
                con.commit()
            for d, n in targets:
                job["progress"]["current"] = config.display_name(n)
                _scan_folder(con, d, n)
                job["progress"]["done"] += 1
            out = {"carpetas": len(targets)}
            if adoptadas:
                out["renombradas_detectadas"] = adoptadas
            return out
        finally:
            con.close()

    return run


def _migrate_preview_cache(con, fid: int, old: str, new: str) -> None:
    """La caché de previews va por ruta relativa: al adoptar un renombrado se
    mueven las entradas para no regenerarlas."""
    from . import previews

    for p in con.execute("SELECT stem, ext, mtime FROM photos WHERE folder_id=?", (fid,)):
        for size in previews.SIZES:
            a = previews._cache_path(f"{old}/{p['stem']}{p['ext']}", p["mtime"], size)
            if a.exists():
                try:
                    a.replace(previews._cache_path(f"{new}/{p['stem']}{p['ext']}", p["mtime"], size))
                except OSError:
                    pass
