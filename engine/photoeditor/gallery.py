"""Galería estática a partir de una selección: HTML autocontenido + JPGs.

Se genera en %LOCALAPPDATA%/photo-editor/galleries/<slug>/ (nunca dentro de
la carpeta de fotos). Cada foto se revela con su receta a 2048 px. Publicarla
es decisión del usuario, p. ej.:
    npx wrangler pages deploy <ruta> --project-name=<slug>
"""
import json
import re
import shutil

from . import config, db, develop, gpu
from .export import _resize_long, _save_jpg
from .parallel import prefetch, workers

_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title>
<style>
:root{--bg:#12141a;--panel:#1b1e26;--line:#2f3542;--txt:#e8eaf0;--dim:#9aa2b4;--acc:#e0a341}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
header{padding:26px 20px 10px;max-width:1200px;margin:0 auto}
h1{margin:0;font-size:22px;letter-spacing:.3px}h1 span{color:var(--acc)}
.sub{color:var(--dim);font-size:13px;margin-top:4px}
.grid{max-width:1200px;margin:14px auto 60px;padding:0 20px;display:grid;
gap:10px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.grid a{display:block;border-radius:8px;overflow:hidden;border:1px solid var(--line)}
.grid a:hover{border-color:var(--acc)}
.grid img{display:block;width:100%;height:200px;object-fit:cover;background:#000}
#lb{position:fixed;inset:0;background:rgba(8,9,12,.96);display:none;
align-items:center;justify-content:center;flex-direction:column;gap:10px;z-index:9}
#lb.on{display:flex}
#lb img{max-width:96vw;max-height:88vh;object-fit:contain}
#lb .cap{color:var(--dim);font-size:13px}
#lb button{position:absolute;top:50%;transform:translateY(-50%);background:var(--panel);
color:var(--txt);border:1px solid var(--line);border-radius:8px;font-size:26px;
padding:8px 14px;cursor:pointer}
#lb button:hover{border-color:var(--acc)}
#prev{left:14px}#next{right:14px}
#close{position:absolute;top:14px;right:14px;transform:none;font-size:18px}
</style></head><body>
<header><h1>__TITULO__<span> · __COUNT__ fotos</span></h1>
<div class="sub">__SUB__</div></header>
<div class="grid" id="g"></div>
<div id="lb"><button id="prev">‹</button><img id="lbimg" alt="">
<button id="next">›</button><button id="close">✕</button><div class="cap" id="cap"></div></div>
<script>
const FOTOS=__ITEMS__;
const g=document.getElementById('g');
FOTOS.forEach((f,i)=>{const a=document.createElement('a');a.href='#';
const im=document.createElement('img');im.loading='lazy';im.src='thumb/'+f.file;im.alt=f.cap;
a.appendChild(im);a.onclick=e=>{e.preventDefault();open(i)};g.appendChild(a)});
let cur=0;const lb=document.getElementById('lb'),lbimg=document.getElementById('lbimg'),
cap=document.getElementById('cap');
function open(i){cur=i;lbimg.src='img/'+FOTOS[i].file;cap.textContent=FOTOS[i].cap;
lb.classList.add('on')}
function move(d){open((cur+d+FOTOS.length)%FOTOS.length)}
document.getElementById('prev').onclick=()=>move(-1);
document.getElementById('next').onclick=()=>move(1);
document.getElementById('close').onclick=()=>lb.classList.remove('on');
lb.onclick=e=>{if(e.target===lb)lb.classList.remove('on')};
addEventListener('keydown',e=>{if(!lb.classList.contains('on'))return;
if(e.key==='Escape')lb.classList.remove('on');
if(e.key==='ArrowLeft')move(-1);if(e.key==='ArrowRight')move(1)});
</script></body></html>
"""


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or "galeria"


def job_fn(photo_ids: list[int], titulo: str):
    if len(photo_ids) < 1:
        raise ValueError("La selección está vacía")

    def run(job: dict) -> dict:
        con = db.connect()
        try:
            rows = [
                con.execute(
                    """SELECT p.id, p.stem, p.ext, f.name AS folder
                       FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                    (pid,),
                ).fetchone()
                for pid in photo_ids
            ]
        finally:
            con.close()
        rows = [r for r in rows if r is not None]
        rows.sort(key=lambda r: (r["folder"], r["stem"]))
        root = config.get_root()

        slug = _slug(titulo)
        out = config.APP_DIR / "galleries" / slug
        if out.exists():
            shutil.rmtree(out)
        (out / "img").mkdir(parents=True)
        (out / "thumb").mkdir()

        job["progress"]["total"] = len(rows) + 1
        items: list[dict] = []
        fallidos: list[str] = []

        def _render(ir) -> dict:
            i, r = ir
            src = root / r["folder"] / (r["stem"] + r["ext"])
            if not src.exists():
                raise ValueError("no está en disco")
            recipe = develop.load_recipe(develop.recipe_path(root, r["folder"], r["stem"]))
            img16 = develop.render_full(src, recipe)
            big = _resize_long(img16, 2048)
            name = f"{i:03d}.jpg"
            _save_jpg(big, out / "img" / name, q=90, subsampling=0, dpi=None)
            _save_jpg(_resize_long(big, 480), out / "thumb" / name, q=82,
                      subsampling=2, dpi=None)
            return {"file": name, "cap": r["stem"]}

        # revelados en paralelo (decode en hilos; la GPU, si la hay, serializa sola)
        for (i, r), res in prefetch(list(enumerate(rows, 1)), _render, window=min(3, workers())):
            job["progress"]["current"] = r["stem"]
            if isinstance(res, Exception):
                fallidos.append(f"{r['stem']}: {res}")
            else:
                items.append(res)
            job["progress"]["done"] += 1
        gpu.release()

        if not items:
            raise ValueError(f"Ninguna foto renderizada — {'; '.join(fallidos[:4])}")

        job["progress"]["current"] = "index.html"
        html = (
            _HTML.replace("__TITULO__", titulo)
            .replace("__COUNT__", str(len(items)))
            .replace("__SUB__", "")
            .replace("__ITEMS__", json.dumps(items, ensure_ascii=False))
        )
        (out / "index.html").write_text(html, encoding="utf-8")
        job["progress"]["done"] += 1

        return {
            "ruta": str(out),
            "fotos": len(items),
            "fallidos": fallidos,
            "publicar": f'npx wrangler pages deploy "{out}" --project-name={slug}',
        }

    return run
