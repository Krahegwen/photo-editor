"""Envío seguro a la papelera + log de auditoría.

Compartido por el borrado de la API y por cerrar-carpeta. Nunca borrado duro.
"""
import json
import time
from pathlib import Path

from send2trash import send2trash

from . import config


def audit(action: str, items: list[str]) -> None:
    if not items:
        return
    line = json.dumps(
        {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "items": items},
        ensure_ascii=False,
    )
    with open(config.APP_DIR / "deletions.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def trash_stem(con, root: Path, folder_id: int, folder: str, stem: str) -> list[str]:
    """Papelera para la foto ENTERA: todas sus versiones (RAW, JPG, TIF…) y
    sus sidecars. Es lo que significa descartar una foto en la rejilla."""
    trashed: list[str] = []
    rows = con.execute(
        "SELECT id, ext FROM photos WHERE folder_id=? AND stem=?", (folder_id, stem)
    ).fetchall()
    for r in rows:
        f = root / folder / (stem + r["ext"])
        if f.exists():
            send2trash(str(f))
        trashed.append(f"{folder}/{stem}{r['ext']}")
        con.execute("DELETE FROM photos WHERE id=?", (r["id"],))
    for suffix in (".xmp", ".pe.json"):
        sc = root / folder / (stem + suffix)
        if sc.exists():
            send2trash(str(sc))
            trashed.append(f"{folder}/{sc.name}")
    con.commit()
    return trashed


def trash_photo(con, root: Path, row) -> list[str]:
    """Papelera para el archivo de la foto y, si nadie más comparte el stem,
    sus sidecars .xmp y .pe.json. Borra la fila y devuelve lo enviado."""
    rel = f"{row['folder']}/{row['stem']}{row['ext']}"
    fpath = root / row["folder"] / (row["stem"] + row["ext"])
    if fpath.exists():
        send2trash(str(fpath))
    trashed = [rel]
    others = con.execute(
        "SELECT COUNT(*) FROM photos WHERE folder_id=? AND stem=? AND id<>?",
        (row["folder_id"], row["stem"], row["id"]),
    ).fetchone()[0]
    if others == 0:
        for suffix in (".xmp", ".pe.json"):
            sc = root / row["folder"] / (row["stem"] + suffix)
            if sc.exists():
                send2trash(str(sc))
                trashed.append(f"{row['folder']}/{sc.name}")
    con.execute("DELETE FROM photos WHERE id=?", (row["id"],))
    con.commit()
    return trashed
