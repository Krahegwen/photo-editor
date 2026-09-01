"""Servidor MCP de photo-editor para Claude Desktop / Claude Code.

Cliente fino sobre la API REST del motor local (PHOTOED_URL, por defecto
127.0.0.1:8177): las mismas operaciones que usa la UI, sin duplicar lógica.
El motor debe estar arrancado (launcher/photo-editor.ps1).

Las fotos se refieren por sus 4 dígitos ("8881") o por el stem completo
("_DSC8881"); las carpetas por nombre exacto o subcadena única ("eclipse").
"""
import io
import os
import time

import httpx
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .formats import is_raw

BASE = os.environ.get("PHOTOED_URL", "http://127.0.0.1:8177")

mcp = MCPServer(
    "photo-editor",
    instructions=(
        "Editor fotográfico local de Diego (archivo CAMERA, Sony A7 III). "
        "Flujo: escanear → listar/ver → sugerir_descartes → puntuar (1★=descarte, "
        "≥4★=revelar) → borrar_fotos (siempre enseñando antes la lista) → "
        "aplicar_receta → exportar → cerrar_carpeta (dry-run primero). "
        "Los borrados van a la papelera de Windows."
    ),
)


def _req(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        r = httpx.request(method, f"{BASE}{path}", timeout=120, **kwargs)
    except httpx.ConnectError as exc:
        raise ToolError(
            f"El motor de photo-editor no responde en {BASE}. "
            "Arráncalo con launcher/photo-editor.ps1 (o python -m photoeditor en engine/)."
        ) from exc
    if r.status_code >= 400:
        raise ToolError(f"{r.status_code}: {r.text}")
    return r


def _get(path: str, **params) -> dict | list:
    return _req("GET", path, params=params or None).json()


def _post(path: str, payload: dict) -> dict:
    return _req("POST", path, json=payload).json()


def _folder(nombre: str) -> dict:
    folders = _get("/api/folders")
    exact = [f for f in folders if f["name"].lower() == nombre.lower()]
    if exact:
        return exact[0]
    subs = [f for f in folders if nombre.lower() in f["name"].lower()]
    if len(subs) == 1:
        return subs[0]
    if not subs:
        raise ToolError(f"No encuentro ninguna carpeta que contenga '{nombre}'")
    raise ToolError(
        "Nombre ambiguo, coincide con: " + ", ".join(f["name"] for f in subs[:8])
    )


def _photos(folder_id: int) -> list[dict]:
    return _get("/api/photos", folder_id=folder_id)


def _match(photos: list[dict], ref: str) -> dict:
    ref = ref.strip()
    cand = [p for p in photos if p["stem"] == ref] or [
        p for p in photos if p["stem"].endswith(ref)
    ]
    if not cand:
        raise ToolError(f"No encuentro la foto '{ref}' en esa carpeta")
    stems = {p["stem"] for p in cand}
    if len(stems) > 1:
        raise ToolError(f"'{ref}' es ambiguo: {sorted(stems)[:8]}")
    raws = [p for p in cand if is_raw(p["ext"])]
    return (raws or cand)[0]


def _compact(p: dict) -> dict:
    out = {"foto": p["stem"], "ext": p["ext"], "rating": p["rating"]}
    if p.get("flags"):
        out["sospechas"] = p["flags"]
    if p.get("has_recipe"):
        out["receta"] = True
    if p.get("taken_at"):
        out["hora"] = p["taken_at"][11:]
    return out


# ------------------------------------------------------------------ tools


@mcp.tool()
def estado() -> dict:
    """Estado del motor: raíz, tamaño del catálogo y trabajos activos o recientes."""
    h = _get("/api/health")
    h["trabajos"] = _get("/api/jobs", limit=6)
    return h


@mcp.tool()
def listar_carpetas() -> list[dict]:
    """Lista las carpetas del archivo (orden descendente, FAVS arriba) con su nº de fotos."""
    return [
        {"carpeta": f["name"], "fotos": f["photo_count"]} for f in _get("/api/folders")
    ]


@mcp.tool()
def listar_fotos(carpeta: str, min_rating: int = 0, solo_sospechosas: bool = False) -> dict:
    """Fotos de una carpeta. min_rating filtra por estrellas (4 = las que van a revelado);
    solo_sospechosas deja solo las marcadas por las métricas (vacía/borrosa/quemada)."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    if min_rating:
        ps = [p for p in ps if (p["rating"] or 0) >= min_rating]
    if solo_sospechosas:
        ps = [p for p in ps if p["flags"]]
    return {"carpeta": f["name"], "total": len(ps), "fotos": [_compact(p) for p in ps]}


@mcp.tool()
def ver_foto(carpeta: str, foto: str, grande: bool = False) -> Image:
    """Devuelve la preview de una foto (por sus 4 dígitos o stem). grande=True pide 1600px."""
    f = _folder(carpeta)
    p = _match(_photos(f["id"]), foto)
    size = 1600 if grande else 320
    data = _req("GET", f"/api/preview/{p['id']}", params={"s": size}).content
    return Image(data=data, format="jpeg")


@mcp.tool()
def hoja_contactos(carpeta: str, pagina: int = 1, min_rating: int = 0,
                   solo_sospechosas: bool = False) -> Image:
    """Hoja de contactos 3x4 (12 fotos por página) con número y estado de cada foto."""
    from PIL import Image as PILImage
    from PIL import ImageDraw

    f = _folder(carpeta)
    ps = _photos(f["id"])
    if min_rating:
        ps = [p for p in ps if (p["rating"] or 0) >= min_rating]
    if solo_sospechosas:
        ps = [p for p in ps if p["flags"]]
    total_pages = max(1, -(-len(ps) // 12))
    page = ps[(pagina - 1) * 12 : pagina * 12]
    if not page:
        raise ToolError(f"Página vacía (hay {total_pages} páginas, {len(ps)} fotos)")

    TW, TH, LBL = 320, 214, 26
    cols, rows = 3, -(-len(page) // 3)
    sheet = PILImage.new("RGB", (cols * TW + 8 * (cols + 1), rows * (TH + LBL) + 8 * (rows + 1) + 24), (18, 20, 26))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 4), f"{f['name']} — página {pagina}/{total_pages}", fill=(232, 234, 240))
    for i, p in enumerate(page):
        try:
            data = _req("GET", f"/api/preview/{p['id']}", params={"s": 320}).content
            th = PILImage.open(io.BytesIO(data)).convert("RGB")
            th.thumbnail((TW, TH))
        except Exception:
            th = PILImage.new("RGB", (TW, TH), (40, 40, 48))
        c, r = i % cols, i // cols
        x = 8 + c * (TW + 8)
        y = 24 + 8 + r * (TH + LBL + 8)
        sheet.paste(th, (x + (TW - th.width) // 2, y + (TH - th.height) // 2))
        label = p["stem"][-4:]
        if p["rating"]:
            label += "  ✕1★" if p["rating"] == 1 else "  " + "★" * p["rating"]
        if p["flags"]:
            label += "  [" + ",".join(p["flags"]) + "]"
        draw.text((x + 2, y + TH + 4), label, fill=(224, 163, 65))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return Image(data=buf.getvalue(), format="jpeg")


@mcp.tool()
def puntuar(carpeta: str, fotos: list[str], estrellas: int) -> dict:
    """Escribe estrellas (0-5) en los sidecars .xmp (compatibles con Lightroom).
    Convención de Diego: 1★ = candidata a borrar; ≥4★ = va a revelado."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    items = [{"photo_id": _match(ps, ref)["id"], "rating": estrellas} for ref in fotos]
    res = _post("/api/rating", {"items": items})
    ok = sum(1 for r in res["results"] if r["ok"])
    return {"puntuadas": ok, "errores": [r for r in res["results"] if not r["ok"]]}


@mcp.tool()
def sugerir_descartes(carpeta: str) -> dict:
    """Analiza la nitidez/histograma de la carpeta (si hace falta) y devuelve las
    candidatas a descarte con su motivo. No puntúa nada por sí solo."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    if any(p["metrics_at"] is None for p in ps):
        job = _post("/api/metrics", {"folder_id": f["id"]})
        deadline = time.time() + 110
        while time.time() < deadline:
            time.sleep(2)
            j = _get(f"/api/jobs/{job['id']}")
            if j["state"] in ("done", "error"):
                break
        else:
            return {"aviso": "El análisis sigue en marcha; vuelve a llamar en un rato",
                    "job_id": job["id"]}
        ps = _photos(f["id"])
    flagged = [p for p in ps if p["flags"]]
    return {
        "carpeta": f["name"],
        "analizadas": len(ps),
        "sospechosas": [
            {"foto": p["stem"], "motivos": p["flags"], "rating": p["rating"]} for p in flagged
        ],
    }


@mcp.tool()
def borrar_fotos(carpeta: str, fotos: list[str], confirmado: bool = False) -> dict:
    """Envía fotos a la papelera de Windows (con sus sidecars). Con confirmado=False
    solo devuelve la lista de lo que se borraría: enséñasela a Diego y repite con
    confirmado=True cuando él dé el visto bueno explícito."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    matched = [_match(ps, ref) for ref in fotos]
    if not confirmado:
        return {
            "aviso": "DRY-RUN: nada borrado. Confirma con Diego y repite con confirmado=true.",
            "se_borrarian": [f"{p['stem']}{p['ext']}" for p in matched],
        }
    res = _post("/api/delete", {"photo_ids": [p["id"] for p in matched]})
    return {"a_papelera": res["trashed"], "errores": res["errors"]}


@mcp.tool()
def receta(carpeta: str, foto: str) -> dict:
    """Lee la receta de revelado de una foto (sidecar .pe.json) y los valores neutros."""
    f = _folder(carpeta)
    p = _match(_photos(f["id"]), foto)
    return _get(f"/api/develop/{p['id']}")


@mcp.tool()
def aplicar_receta(carpeta: str, fotos: list[str], ajustes: dict) -> dict:
    """Aplica ajustes de revelado a una o varias fotos (no destructivo, sidecar
    .pe.json). Claves: temp, tint (-100..100), exposure (EV -3..3), contrast,
    highlights, shadows, blacks, saturation, vibrance (-100..100), sharpen (0..100),
    rot90 (0-3), angle (-15..15), crop {x,y,w,h} normalizado."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    ids = [_match(ps, ref)["id"] for ref in fotos]
    geometry = any(k in ajustes for k in ("crop", "rot90", "angle"))
    res = _post(
        "/api/develop/copy",
        {"recipe": ajustes, "to_photo_ids": ids, "include_geometry": geometry},
    )
    ok = sum(1 for r in res["results"] if r["ok"])
    return {"aplicadas": ok, "errores": [r for r in res["results"] if not r["ok"]]}


@mcp.tool()
def exportar(carpeta: str, preset: str, fotos: list[str] | None = None,
             min_rating: int = 0, force: bool = False) -> dict:
    """Exporta fotos con un preset: 'normal' (4K JPG q95), 'favorita' (TIFF16+JPG
    full-res, duplicada a FAVS), 'redes' (2048), 'impresion' (q100 300dpi).
    Sin lista de fotos, exporta las de min_rating (p. ej. 4 = las marcadas para
    revelado). Devuelve el trabajo encolado; consulta con estado_trabajo."""
    f = _folder(carpeta)
    ps = _photos(f["id"])
    if fotos:
        ids = [_match(ps, ref)["id"] for ref in fotos]
    else:
        ids = [p["id"] for p in ps if (p["rating"] or 0) >= max(1, min_rating)]
        if not ids:
            raise ToolError("Ninguna foto cumple el filtro; pasa una lista o baja min_rating")
    return _post("/api/export", {"photo_ids": ids, "preset": preset, "force": force})


@mcp.tool()
def cerrar_carpeta(carpeta: str, ejecutar: bool = False) -> dict:
    """Aplica la política de archivo de Diego a una carpeta. Con ejecutar=False
    devuelve el informe dry-run (qué RAW se borrarían y por qué, qué queda
    pendiente, qué TIFF no están en FAVS). Enséñale el informe a Diego y solo
    con su visto bueno repite con ejecutar=True."""
    f = _folder(carpeta)
    return _post("/api/close_folder", {"folder_id": f["id"], "execute": ejecutar})


@mcp.tool()
def apilar(carpeta: str, modo: str, desde: str | None = None, hasta: str | None = None,
           fotos: list[str] | None = None, escala: str = "auto",
           crop_px: int = 1200, force: bool = False) -> dict:
    """Apila fotos de una carpeta como trabajo encolado. Modos: 'luna' (recorta el
    disco y alinea subpíxel), 'estrellas' (alineado de campo estelar con rotación),
    'media' (sigma-clip sin alinear), 'max' (máximo por píxel: trails y composites
    de fuegos), 'hdr' (fusión de brackets por exposición). Selección por lista de
    fotos o por rango desde/hasta (4 dígitos, p. ej. 8636 a 8727). El resultado
    queda como apilado_<modo>_<rango>.tif/jpg en la carpeta, editable en Revelar."""
    f = _folder(carpeta)
    todos = _photos(f["id"])
    ps = [p for p in todos if is_raw(p["ext"])] or todos
    if fotos:
        ids = [_match(ps, ref)["id"] for ref in fotos]
    elif desde and hasta:
        d, h = desde.strip()[-4:], hasta.strip()[-4:]
        ids = [
            p["id"] for p in ps if p["stem"][-4:].isdigit() and d <= p["stem"][-4:] <= h
        ]
    else:
        raise ToolError("Indica una lista de fotos o un rango desde/hasta")
    if len(ids) < 2:
        raise ToolError(f"Solo {len(ids)} fotos en la selección — hacen falta al menos 2")
    return _post(
        "/api/stack",
        {"photo_ids": ids, "mode": modo, "crop_px": crop_px, "escala": escala, "force": force},
    )


@mcp.tool()
def escanear(carpeta: str | None = None) -> dict:
    """Re-indexa el archivo completo (o una carpeta) tras cambios en disco."""
    payload = {"folders": [_folder(carpeta)["name"]]} if carpeta else {}
    return _post("/api/scan", payload)


@mcp.tool()
def estado_trabajo(job_id: str) -> dict:
    """Progreso y resultado de un trabajo encolado (escaneo, métricas, export, cierre)."""
    return _get(f"/api/jobs/{job_id}")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
