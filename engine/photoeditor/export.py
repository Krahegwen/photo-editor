"""Exportación con los presets de la política de archivo de Diego.

- normal:    JPG q95 4:4:4, lado largo 4096, a la raíz de la carpeta.
- favorita:  TIFF 16 bits LZW + JPG q95 a resolución completa, en la carpeta
             Y duplicados en `999999 - FAVS`.
- redes:     JPG q90 sRGB, lado largo 2048, en `<carpeta>/_redes/`.
- impresion: JPG q100 a resolución completa con 300 dpi, en `<carpeta>/_impresion/`.

Nunca se sobreescribe un archivo existente salvo force=True (protege posibles
JPG de cámara u exportaciones previas). El render usa la receta si existe;
sin receta exporta el revelado base (WB de cámara).
"""
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import config, db, develop

FAVS_DIR = "999999 - FAVS"

PRESETS: dict[str, dict] = {
    "normal": {"long": 4096, "jpg_q": 95, "subsampling": 0, "tiff": False, "dest": "root"},
    "favorita": {"long": None, "jpg_q": 95, "subsampling": 0, "tiff": True, "dest": "favs"},
    "redes": {"long": 2048, "jpg_q": 90, "subsampling": 2, "tiff": False, "dest": "_redes"},
    "impresion": {
        "long": None, "jpg_q": 100, "subsampling": 0, "tiff": False,
        "dest": "_impresion", "dpi": 300,
    },
}

def _resize_long(img: np.ndarray, long_px: int | None) -> np.ndarray:
    if not long_px:
        return img
    h, w = img.shape[:2]
    sc = long_px / max(h, w)
    if sc >= 1:
        return img
    return cv2.resize(img, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)


def _save_jpg(img16: np.ndarray, dest: Path, q: int, subsampling: int, dpi: int | None) -> None:
    u8 = (img16.astype(np.float32) / 257.0 + 0.5).astype(np.uint8)
    im = Image.fromarray(u8)
    kwargs: dict = {"quality": q, "subsampling": subsampling}
    if dpi:
        kwargs["dpi"] = (dpi, dpi)
    im.save(dest, "JPEG", **kwargs)


def _save_tif16(img16: np.ndarray, dest: Path) -> None:
    cv2.imwrite(str(dest), img16[:, :, ::-1], [cv2.IMWRITE_TIFF_COMPRESSION, 5])


def _export_one(root: Path, row, preset_name: str, force: bool) -> dict:
    p = PRESETS[preset_name]
    folder = row["folder"]
    stem = row["stem"]
    src = root / folder / (stem + row["ext"])
    if not src.exists():
        return {"stem": stem, "ok": False, "error": "el archivo ya no está en disco"}

    if p["dest"] in ("_redes", "_impresion"):
        outdir = root / folder / p["dest"]
    else:
        outdir = root / folder
    outdir.mkdir(exist_ok=True)

    targets = [outdir / f"{stem}.jpg"]
    if p["tiff"]:
        targets.append(outdir / f"{stem}.tif")
    if not force:
        clash = [t.name for t in targets if t.exists()]
        if clash:
            return {"stem": stem, "ok": False, "error": f"ya existe: {', '.join(clash)}"}

    recipe = develop.load_recipe(develop.recipe_path(root, folder, stem))
    img16 = develop.render_full(src, recipe)
    img16 = _resize_long(img16, p["long"])

    written = []
    _save_jpg(img16, outdir / f"{stem}.jpg", p["jpg_q"], p["subsampling"], p.get("dpi"))
    written.append(f"{folder}/{(outdir / (stem + '.jpg')).name}" if p["dest"] in ("root", "favs")
                   else f"{folder}/{p['dest']}/{stem}.jpg")
    if p["tiff"]:
        _save_tif16(img16, outdir / f"{stem}.tif")
        written.append(f"{folder}/{stem}.tif")

    if p["dest"] == "favs" and folder != FAVS_DIR:
        favs = root / FAVS_DIR
        favs.mkdir(exist_ok=True)
        for t in targets:
            fav_t = favs / t.name
            if fav_t.exists() and not force:
                return {"stem": stem, "ok": False,
                        "error": f"exportado en {folder} pero ya existía en FAVS: {t.name}",
                        "written": written}
            shutil.copy2(t, fav_t)
            written.append(f"{FAVS_DIR}/{t.name}")

    return {"stem": stem, "ok": True, "written": written}


def job_fn(photo_ids: list[int], preset_name: str, force: bool = False):
    """Función de trabajo para la cola (jobs.submit)."""
    if preset_name not in PRESETS:
        raise ValueError(f"Preset desconocido: {preset_name}")

    def run(job: dict) -> dict:
        from . import scan

        from . import gpu
        from .parallel import prefetch, workers

        con = db.connect()
        touched: set[str] = set()
        results: list[dict] = []
        try:
            root = config.get_root()
            job["progress"]["total"] = len(photo_ids)
            rows = []
            for pid in photo_ids:
                row = con.execute(
                    """SELECT p.stem, p.ext, f.name AS folder FROM photos p
                       JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                    (pid,),
                ).fetchone()
                if row is None:
                    results.append(
                        {"stem": f"id {pid}", "ok": False, "error": "no está en el catálogo"}
                    )
                    job["progress"]["done"] += 1
                else:
                    rows.append(row)
            # revelados en paralelo (decode en hilos; la GPU, si la hay, serializa sola)
            for row, res in prefetch(
                rows, lambda r: _export_one(root, r, preset_name, force), window=min(3, workers())
            ):
                job["progress"]["current"] = row["stem"]
                if isinstance(res, Exception):
                    res = {"stem": row["stem"], "ok": False, "error": str(res)}
                results.append(res)
                if res.get("ok"):
                    touched.add(row["folder"])
                    if PRESETS[preset_name]["dest"] == "favs":
                        touched.add(FAVS_DIR)
                job["progress"]["done"] += 1
            gpu.release()
            # re-indexar las carpetas con archivos nuevos
            for name in touched:
                d = root / name
                if d.is_dir():
                    scan._scan_folder(con, d, name)
        finally:
            con.close()
        return {"preset": preset_name, "results": results}

    return run
