# photo-editor

Editor fotográfico local para sustituir Lightroom/Photoshop en mi flujo real:
cribar, puntuar, revelar RAW (Sony ARW), apilar astro y exportar — con API REST
y, más adelante, servidor MCP para que Claude opere el mismo motor.

**Estado: F0 (cimientos)** — catálogo SQLite, previews con caché y rejilla en el
navegador. Fases siguientes: F1 cribado · F2 revelado · F3 MCP · F4 astro.

## Arquitectura

- `engine/` — Python 3.11 + FastAPI: escaneo incremental, previews (rawpy,
  JPEG incrustado del RAW), catálogo. Escucha en `127.0.0.1:8177`.
- `app/` — Vue 3 + Vite. En desarrollo, proxy de `/api` al engine.
- `launcher/` — arranca el engine (que sirve `app/dist` si existe) y abre el
  navegador.

Principios: la verdad vive en disco (RAW + sidecars `.xmp` compatibles con
Lightroom); SQLite es solo un índice reconstruible; la caché de previews va a
`%LOCALAPPDATA%\photo-editor\`, nunca dentro del archivo de fotos; los RAW no
se modifican jamás.

## Configuración

Raíz del archivo de fotos: variable de entorno `PHOTOED_ROOT`, o clave `root`
en `%LOCALAPPDATA%\photo-editor\config.json`. Puerto: `PHOTOED_PORT` (8177 por
defecto).

## Desarrollo

```bash
cd engine && uv sync && uv run python -m photoeditor   # API en :8177
cd app && corepack pnpm install && corepack pnpm dev   # UI en :5173
```

## Uso normal

```bash
corepack pnpm -C app build
powershell launcher/photo-editor.ps1
```
