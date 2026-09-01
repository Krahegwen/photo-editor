# photo-editor

Editor fotográfico local para sustituir Lightroom/Photoshop en mi flujo real:
cribar, puntuar, revelar RAW (Sony ARW), apilar astro y exportar — con API REST
y, más adelante, servidor MCP para que Claude opere el mismo motor.

**Estado: F0–F4 completadas** — catálogo, cribado (rating XMP, métricas de
nitidez, borrado a papelera), revelado no destructivo con exportación por
presets, cola de trabajos, servidor MCP y apilador astro (luna, estrellas,
media sigma-clip, máximo para trails/fuegos, HDR Mertens).

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

## MCP (Claude Desktop / Claude Code)

`engine/photoeditor/mcp_server.py` expone las mismas operaciones que la UI
como tools MCP (stdio), hablando con la API del motor (`PHOTOED_URL`, por
defecto `127.0.0.1:8177`). Config para Claude Desktop:

```json
"photo-editor": {
  "command": "<repo>\\engine\\.venv\\Scripts\\python.exe",
  "args": ["-m", "photoeditor.mcp_server"]
}
```

Tools: estado, listar_carpetas, listar_fotos, ver_foto, hoja_contactos,
puntuar, sugerir_descartes, borrar_fotos (dry-run salvo confirmado), receta,
aplicar_receta, exportar, cerrar_carpeta (dry-run salvo ejecutar), escanear,
estado_trabajo. Los trabajos largos van a una cola secuencial (`/api/jobs`)
compartida entre la UI y el MCP.

## Desarrollo

```bash
cd engine && uv sync && uv run python -m photoeditor   # API en :8177
cd app && corepack pnpm install && corepack pnpm dev   # UI en :5173
```

## Rendimiento: CPU por defecto, GPU opcional

El camino de referencia es CPU y funciona en cualquier máquina; la
decodificación RAW va en hilos (`PHOTOED_THREADS`, por defecto la mitad de
los lógicos, tope 4). Con una NVIDIA se puede activar CuPy para el apilado
sigma-clip, la detección de estrellas y la parte tonal del revelado —
todo cae a CPU solo ante cualquier fallo:

```
cd engine && uv sync --extra gpu   # CuPy + librerías CUDA en wheels de pip (sin CUDA Toolkit)
```

`PHOTOED_GPU=0` la desactiva; `GET /api/health` dice si está activa. El
timelapse usa NVENC cuando el ffmpeg embebido y el driver lo permiten.

## Uso normal

```bash
corepack pnpm -C app build
powershell launcher/photo-editor.ps1
```
