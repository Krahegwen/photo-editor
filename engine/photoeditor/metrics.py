"""Métricas de cribado por carpeta: nitidez y recortes de histograma.

Port de la idea de analyze.py del flujo previo (varianza del Laplaciano),
generalizada: los umbrales absolutos no valen entre escenas, así que las
sospechas se marcan comparando con la mediana de la carpeta (ver api._annotate).
Se mide sobre la preview de 1600 reescalada a ~1024 para que la escala del
Laplaciano sea comparable entre fotos.
"""
import time

import cv2
import numpy as np

from . import config, db, previews


def _measure(preview_path) -> dict | None:
    im = cv2.imread(str(preview_path), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    h, w = im.shape
    if w > 1024:
        im = cv2.resize(im, (1024, max(1, int(h * 1024 / w))), interpolation=cv2.INTER_AREA)
    return {
        "sharp": float(cv2.Laplacian(im.astype(np.float32), cv2.CV_32F).var()),
        "clip_hi": float((im >= 250).mean()),
        "clip_lo": float((im <= 5).mean()),
        "bright": float(im.mean()),
    }


def job_fn(folder_id: int):
    """Función de trabajo para la cola (jobs.submit)."""

    def run(job: dict) -> dict:
        con = db.connect()
        try:
            root = config.get_root()
            rows = con.execute(
                """SELECT p.id, p.stem, p.ext, p.mtime, f.name AS folder FROM photos p
                   JOIN folders f ON f.id = p.folder_id
                   WHERE p.folder_id=? AND p.metrics_at IS NULL""",
                (folder_id,),
            ).fetchall()
            job["progress"]["total"] = len(rows)
            for r in rows:
                job["progress"]["current"] = r["stem"]
                abs_path = root / r["folder"] / (r["stem"] + r["ext"])
                rel = f"{r['folder']}/{r['stem']}{r['ext']}"
                m = None
                try:
                    if abs_path.exists():
                        pv = previews.get_preview(abs_path, rel, r["mtime"], 1600)
                        m = _measure(pv)
                except Exception:
                    m = None
                if m:
                    con.execute(
                        "UPDATE photos SET sharp=?, clip_hi=?, clip_lo=?, bright=?, metrics_at=?"
                        " WHERE id=?",
                        (m["sharp"], m["clip_hi"], m["clip_lo"], m["bright"], time.time(), r["id"]),
                    )
                else:
                    con.execute("UPDATE photos SET metrics_at=? WHERE id=?", (time.time(), r["id"]))
                con.commit()
                job["progress"]["done"] += 1
            return {"medidas": len(rows)}
        finally:
            con.close()

    return run
