"""Cerrar carpeta: aplica la política de archivo, siempre con dry-run previo.

Política (CLAUDE.md de CAMERA, fijada 28-08-2026): tras procesar una carpeta
quedan solo los JPG finales; el RAW se borra una vez revelado (hay JPG con su
stem) o si es descarte 1★; el TIFF de 16 bits solo existe para favoritas y
debe estar duplicado en 999999 - FAVS.
"""
from . import config, db, scan, trash
from .formats import is_raw

FAVS_DIR = "999999 - FAVS"


def analyze(folder_id: int) -> dict:
    con = db.connect()
    try:
        folder = con.execute("SELECT id, name FROM folders WHERE id=?", (folder_id,)).fetchone()
        if folder is None:
            raise ValueError("Carpeta no encontrada en el catálogo")
        rows = con.execute(
            "SELECT id, stem, ext, rating FROM photos WHERE folder_id=?", (folder_id,)
        ).fetchall()
    finally:
        con.close()

    root = config.get_root()
    by_stem: dict[str, dict] = {}
    for r in rows:
        by_stem.setdefault(r["stem"], {})[r["ext"]] = r

    borrar, pendientes, tiff_sin_favs = [], [], []
    finales = 0
    for stem in sorted(by_stem):
        exts = by_stem[stem]
        raw = next((exts[e] for e in exts if is_raw(e)), None)
        jpg = exts.get(".jpg") or exts.get(".jpeg")
        tif = exts.get(".tif") or exts.get(".tiff")
        if jpg is not None:
            finales += 1
        if raw is not None:
            if raw["rating"] == 1:
                borrar.append({"stem": stem, "id": raw["id"], "motivo": "descarte 1★"})
            elif jpg is not None:
                borrar.append({"stem": stem, "id": raw["id"], "motivo": "revelado (hay JPG final)"})
            else:
                pendientes.append(stem)
        if tif is not None and folder["name"] != FAVS_DIR:
            if not (root / FAVS_DIR / f"{stem}.tif").exists():
                tiff_sin_favs.append(stem)

    return {
        "folder_id": folder_id,
        "folder": folder["name"],
        "borrar": borrar,
        "pendientes": pendientes,
        "tiff_sin_favs": tiff_sin_favs,
        "finales": finales,
        "total_fotos": len(rows),
    }


def job_fn(folder_id: int):
    def run(job: dict) -> dict:
        report = analyze(folder_id)
        ids = [b["id"] for b in report["borrar"]]
        job["progress"]["total"] = len(ids)
        con = db.connect()
        trashed: list[str] = []
        errors: list[str] = []
        try:
            root = config.get_root()
            for pid in ids:
                row = con.execute(
                    """SELECT p.id, p.stem, p.ext, p.folder_id, f.name AS folder
                       FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                    (pid,),
                ).fetchone()
                if row is not None:
                    job["progress"]["current"] = row["stem"]
                    try:
                        trashed += trash.trash_photo(con, root, row)
                    except Exception as exc:
                        errors.append(f"{row['stem']}: {exc}")
                job["progress"]["done"] += 1
            d = root / report["folder"]
            if d.is_dir():
                scan._scan_folder(con, d, report["folder"])
        finally:
            con.close()
        trash.audit("cerrar_carpeta", trashed)
        report["trashed"] = trashed
        report["errors"] = errors
        return report

    return run
