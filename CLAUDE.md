# photo-editor — instrucciones del proyecto

App local que sustituye Lightroom/Photoshop para el flujo del usuario (cribar →
puntuar → revelar ARW → apilar astro → exportar). Plan por fases: F0 cimientos ✔,
F1 cribado ✔, F2 revelado ✔, F3 MCP+jobs ✔, F4 astro ✔, F5 extras (según uso).

Notas F4: `stacking.py` — modos luna (port de proc.py: centroide+phaseCorrelate),
estrellas (detección propia + estimateAffinePartial2D RANSAC; NO astroalign),
media, max, hdr (Mertens). Temporales .npy uint16 en %LOCALAPPDATA%/stackwork,
borrados al acabar. Salida apilado_<modo>_<rango>.tif (16b LZW) + .jpg en la
carpeta; el acabado (viejo finish.py) se hace abriendo el TIFF en Revelar.

Notas F3: cola secuencial en `jobs.py` (registro en memoria, /api/jobs);
escaneo/métricas/export/cerrar-carpeta son jobs. `mcp_server.py` = cliente
httpx sobre la API (mcp 2.x: MCPServer, ToolError; NO FastMCP). El motor corre
desacoplado (launcher escribe el PID en %LOCALAPPDATA%\photo-editor\engine.pid);
tras cambiar código del engine hay que reiniciar ese proceso. `borrar_fotos` y
`cerrar_carpeta` vía MCP son dry-run salvo confirmación explícita de Diego.

Notas F2: receta JSON en sidecar `<stem>.pe.json` (compartida por stem);
pipeline en `develop.py` con curvas heurísticas v1 — se afinan con feedback
de Diego, no son las de Adobe. Exportación en `export.py` con los presets de
su política de archivo; nunca sobreescribe sin force.

## Arquitectura

- `engine/` (Python 3.11, gestionado con uv): FastAPI en `127.0.0.1:8177`.
  Módulos en `photoeditor/`: `scan` (índice SQLite incremental), `previews`
  (JPEG incrustado del ARW + caché por tamaño), `xmp` (ratings en sidecars),
  `api` (REST; sirve `app/dist` si existe).
- `app/` (Vue 3 + Vite; pnpm pineado por corepack): SPA en español; dev en
  :5173 con proxy `/api`.
- Datos generados en `%LOCALAPPDATA%\photo-editor\` (catalog.db, cache/,
  config.json con la raíz de fotos).

## Reglas de oro

- Fuente de verdad = archivos + sidecars `.xmp` (compatibles con Lightroom);
  SQLite es un índice reconstruible con un escaneo.
- El ARW nunca se modifica; las ediciones serán recetas no destructivas.
- NUNCA escribir cachés/DB/temporales dentro de la carpeta de fotos: se
  sincroniza con la nube del usuario.
- Borrar fotos siempre a papelera (send2trash) y con confirmación previa.
- El motor de imagen porta los scripts probados de `999998_herramientas` del
  archivo fotográfico (ver su README): no reinventar el pipeline.
- UI y textos en español.

## Comandos

- Engine: `uv sync` / `uv run python -m photoeditor` (desde `engine/`; en esta
  máquina uv se invoca como `python -m uv`).
- App: `corepack pnpm install|dev|build` (desde `app/`).
- Verificación rápida: `GET http://127.0.0.1:8177/api/health`.
