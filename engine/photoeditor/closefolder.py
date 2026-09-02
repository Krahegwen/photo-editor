"""Cerrar carpeta: aplica la política de archivo, siempre con dry-run previo.

Política (CLAUDE.md de CAMERA, fijada 28-08-2026): tras procesar una carpeta
quedan solo los JPG finales; el RAW se borra una vez revelado (hay JPG con su
stem) o si es descarte 1★; el TIFF de 16 bits solo existe para favoritas y
debe estar duplicado en 999999 - FAVS.

Favoritas: las 5★ pasan a FAVS con el nombre '<carpeta> <HHhMM>' (regla de
Diego: carpeta + hora del disparo, porque en FAVS se renombran). El informe
dry-run propone la lista con el nombre destino; el usuario desmarca o cambia
nombres en el diálogo. Un manifiesto (favs.json en %LOCALAPPDATA%) recuerda
qué fotos se copiaron ya y con qué nombre, para no proponerlas dos veces.
"""
import json
import re
import shutil

from . import config, db, export, scan, trash
from .formats import is_raw, rank

FAVS_DIR = "999999 - FAVS"
MANIFEST = config.APP_DIR / "favs.json"
_BAD = re.compile(r'[\\/:*?"<>|]+')


def _manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def _fav_name(folder_label: str, taken_at: str | None, stem: str) -> str:
    if taken_at and len(taken_at) >= 16:
        return f"{folder_label} {taken_at[11:13]}h{taken_at[14:16]}"
    return f"{folder_label} {stem}"


def _safe(name: str) -> str:
    return _BAD.sub("", name).strip().rstrip(".") or "favorita"


def analyze(folder_id: int) -> dict:
    con = db.connect()
    try:
        folder = con.execute("SELECT id, name FROM folders WHERE id=?", (folder_id,)).fetchone()
        if folder is None:
            raise ValueError("Carpeta no encontrada en el catálogo")
        rows = con.execute(
            "SELECT id, stem, ext, rating, taken_at FROM photos WHERE folder_id=?", (folder_id,)
        ).fetchall()
    finally:
        con.close()

    root = config.get_root()
    fname = folder["name"]
    label = config.display_name(fname)
    by_stem: dict[str, dict] = {}
    for r in rows:
        by_stem.setdefault(r["stem"], {})[r["ext"]] = r

    borrar, pendientes, tiff_sin_favs, favoritas = [], [], [], []
    finales = 0
    manifest = _manifest()
    favs_dir = root / FAVS_DIR
    existing = {p.stem.lower() for p in favs_dir.iterdir() if p.is_file()} if favs_dir.is_dir() else set()

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
        if tif is not None and fname != FAVS_DIR:
            if not (root / FAVS_DIR / f"{stem}.tif").exists():
                tiff_sin_favs.append(stem)

        rating = next((r["rating"] for r in exts.values() if r["rating"] is not None), None)
        if rating == 5 and fname != FAVS_DIR:
            principal = min(exts.values(), key=lambda r: rank(r["ext"]))
            key = f"{fname}/{stem}"
            en_manifiesto = manifest.get(key)
            ya = bool(en_manifiesto) or (favs_dir / f"{stem}.jpg").exists() or (favs_dir / f"{stem}.tif").exists()
            favoritas.append({
                "id": principal["id"],
                "stem": stem,
                "ext": principal["ext"],
                "taken_at": principal["taken_at"],
                "nombre": en_manifiesto or _fav_name(label, principal["taken_at"], stem),
                "tiene_jpg": jpg is not None,
                "tiene_tif": tif is not None,
                "revelar": jpg is None and tif is None,
                "ya_en_favs": ya,
            })

    # nombres únicos entre las candidatas nuevas y frente a lo que ya hay en FAVS
    seen = set(existing)
    for fv in favoritas:
        if fv["ya_en_favs"]:
            continue
        base, n = fv["nombre"], 2
        while fv["nombre"].lower() in seen:
            fv["nombre"] = f"{base}-{n}"
            n += 1
        seen.add(fv["nombre"].lower())

    return {
        "folder_id": folder_id,
        "folder": fname,
        "borrar": borrar,
        "pendientes": pendientes,
        "tiff_sin_favs": tiff_sin_favs,
        "favoritas": favoritas,
        "finales": finales,
        "total_fotos": len(by_stem),
    }


def job_fn(folder_id: int, favs: list[dict] | None = None):
    """favs: [{"id": photo_id, "nombre": nombre_en_favs}] confirmados en el diálogo."""
    favs = favs or []

    def run(job: dict) -> dict:
        report = analyze(folder_id)
        ids = [b["id"] for b in report["borrar"]]
        job["progress"]["total"] = len(favs) + len(ids)
        con = db.connect()
        trashed: list[str] = []
        errors: list[str] = []
        copiadas: list[dict] = []
        fav_err: list[str] = []
        try:
            root = config.get_root()
            folder = report["folder"]
            favs_dir = root / FAVS_DIR
            manifest = _manifest()

            # 1) favoritas → FAVS (antes de tocar ningún RAW)
            for fv in favs:
                name = _safe(str(fv.get("nombre", "")))
                job["progress"]["current"] = name
                try:
                    row = con.execute(
                        """SELECT p.stem, p.folder_id, f.name AS folder FROM photos p
                           JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                        (int(fv["id"]),),
                    ).fetchone()
                    if row is None:
                        raise ValueError("no está en el catálogo")
                    stem = row["stem"]
                    versions = {
                        r["ext"]: r
                        for r in con.execute(
                            "SELECT id, ext FROM photos WHERE folder_id=? AND stem=?",
                            (row["folder_id"], stem),
                        )
                    }
                    jpg = versions.get(".jpg") or versions.get(".jpeg")
                    tif = versions.get(".tif") or versions.get(".tiff")
                    favs_dir.mkdir(exist_ok=True)
                    written: list[str] = []
                    if jpg is None and tif is None:
                        # sin final aún: revelar con su receta (preset favorita =
                        # TIFF16 + JPG en la carpeta) y copiar a FAVS con el nombre nuevo
                        raw_ext = next((e for e in versions if is_raw(e)), None)
                        if raw_ext is None:
                            raise ValueError("no tiene RAW ni final")
                        raw_row = {"stem": stem, "ext": raw_ext, "folder": folder}
                        res = export._export_one(root, raw_row, "favorita", False, favs_name=name)
                        if not res.get("ok"):
                            raise ValueError(res.get("error", "no se pudo revelar"))
                        written = res.get("written", [])
                    else:
                        for r in (jpg, tif):
                            if r is None:
                                continue
                            src = root / folder / (stem + r["ext"])
                            dst = favs_dir / (name + r["ext"])
                            if dst.exists():
                                raise ValueError(f"ya existe en FAVS: {dst.name}")
                            shutil.copy2(src, dst)
                            written.append(f"{FAVS_DIR}/{dst.name}")
                    manifest[f"{folder}/{stem}"] = name
                    copiadas.append({"stem": stem, "nombre": name, "archivos": written})
                except Exception as exc:
                    fav_err.append(f"{name}: {exc}")
                job["progress"]["done"] += 1
            if copiadas:
                _save_manifest(manifest)

            # 2) RAW a la papelera según la política (lo que mostró el dry-run)
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

            d = root / folder
            if d.is_dir():
                scan._scan_folder(con, d, folder)
            if copiadas and favs_dir.is_dir():
                scan._scan_folder(con, favs_dir, FAVS_DIR)
        finally:
            con.close()
        trash.audit("cerrar_carpeta", trashed)
        report["trashed"] = trashed
        report["errors"] = errors
        report["favs_copiadas"] = copiadas
        report["favs_errores"] = fav_err
        return report

    return run
