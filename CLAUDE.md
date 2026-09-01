# photo-editor — instrucciones del proyecto

App local que sustituye Lightroom/Photoshop para el flujo del usuario (cribar →
puntuar → revelar ARW → apilar astro → exportar). Plan por fases: F0 cimientos ✔,
F1 cribado ✔, F2 revelado ✔, F3 MCP+jobs ✔, F4 astro ✔, F5 extras (1ª tanda ✔:
curvas, mejor-de-ráfaga, timelapse, keywords, galería; quedan Tunnel/móvil,
lensfun, dark frames según uso).

Notas F5: curva master en la receta (PCHIP, LUT 4096); timelapse con el ffmpeg
embebido de imageio-ffmpeg; keywords dc:subject conviviendo con xmp:Rating en
el mismo sidecar; galería en %LOCALAPPDATA%/photo-editor/galleries (NUNCA
publicar sin orden explícita de Diego — el job devuelve el comando wrangler).
Modo `trails` = máximo + relleno de huecos entre disparos (el frame anterior
avanza en fracciones del movimiento del cielo medido con astroalign; el patrón
fijo queda excluido). `max` sigue siendo el máximo crudo (fuegos).

Nombres de salida (`naming.py`, regla de Diego): '<carpeta> - <tipo>
<HHMM>-<HHMM>[ extra]' con el intervalo horario real de la selección — p. ej.
'240812 - Estrellas - trails 0202-0217.tif', '… - timelapse 0202-0217 24fps.mp4'.
Renombrar carpetas: POST /api/folders/{id}/rename (✎ en la cabecera, doble
clic en el título, tool MCP renombrar_carpeta) — renombra en disco y en el
índice y migra la caché de previews; rechaza si hay jobs corriendo.

Notas F4: `stacking.py` — modos luna (port de proc.py: centroide+phaseCorrelate),
estrellas (detector DoG propio + astroalign con puerta rápida de votación y
fallback NN+RANSAC; cadena incremental anclada al frame central + refinamiento
absoluto contra la referencia), media, max, hdr (Mertens). Exposición
normalizada en lineal (t·ISO/f², mediana como referencia) en luna/estrellas/
media; reencuadres: pasada directa de recuperación y segmentación automática
(≥3 frames → apilado aparte con su rango). Temporales .npy uint16 en
%LOCALAPPDATA%/stackwork, borrados al acabar. Salida apilado_<modo>_<rango>.tif
(16b LZW) + .jpg; el acabado (viejo finish.py) se hace en Revelar.

Formatos: `formats.py` centraliza RAW_EXTS (arw, dng, rw2, cr2/cr3, nef, raf,
orf, pef, srw…) — probado con los samples DNG/RW2 de `260901- SAMPLE`. Ojo:
CR3 puede venir sin EXIF vía exifread (contenedor ISO-BMFF).

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
