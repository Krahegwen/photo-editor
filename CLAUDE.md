# photo-editor — instrucciones del proyecto

App local que sustituye Lightroom/Photoshop para el flujo del usuario (cribar →
puntuar → revelar ARW → apilar astro → exportar). Plan por fases: F0 cimientos ✔,
F1 cribado ✔, F2 revelado ✔, F3 MCP+jobs ✔, F4 astro ✔, F5 extras (1ª tanda ✔:
curvas, mejor-de-ráfaga, timelapse, keywords, galería; 2ª tanda ✔: nombres con
intervalo, modo trails, renombrar carpetas, móvil en red local; quedan Tunnel,
lensfun y dark frames según uso).

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
orf, pef, srw…) — probado con los samples DNG/RW2 de la carpeta de pruebas
(`000000 - SAMPLE TEST`; se llamó `260901- SAMPLE` hasta que Diego la renombró
para que quedara al final del orden descendente). Ojo:
CR3 puede venir sin EXIF vía exifread (contenedor ISO-BMFF).

Notas F3: cola secuencial en `jobs.py` (registro en memoria, /api/jobs);
escaneo/métricas/export/cerrar-carpeta son jobs. `mcp_server.py` = cliente
httpx sobre la API (mcp 2.x: MCPServer, ToolError; NO FastMCP). El motor corre
desacoplado; tras cambiar código del engine hay que reiniciar ese proceso (ver
§ Arranque y datos: el PID no es la verdad, lo es /api/health). `borrar_fotos` y
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

Raíz del archivo: `config.set_root` (config.json) + /api/root (GET inspecciona
cualquier ruta, POST cambia y escanea, /browse abre tkinter en subproceso);
RootDialog.vue sale solo si health.ok es false. Una raíz con fotos sueltas se
indexa como carpeta `config.ROOT_FOLDER` ('.') y se muestra por su basename
(`display_name`); al re-escanear carpetas SIEMPRE pasar el nombre del
catálogo a `_scan_folder(con, dir, name)`.

Una foto = un nombre base (regla de Diego): el catálogo guarda una fila por
archivo, pero /api/photos agrupa por stem (`_group_versions`): el archivo
principal (RAW > TIFF > PNG > JPG, `formats.rank`) da id/preview/revelado y
el resto son `files`/`formats`. Contadores por stems distintos; métricas solo
sobre la principal; descartar (1★ → papelera) manda TODAS las versiones y
sidecars (`trash.trash_stem`). Cerrar carpeta sigue borrando solo el RAW.

## Arranque y datos (MSIX: leer antes de tocar nada)

Claude Desktop es una app empaquetada (MSIX) y Windows **virtualiza
`AppData\Local`** para sus procesos hijos: lo que se escriba desde una sesión de
Claude acaba en `AppData\Local\Packages\<app>\LocalCache\Local\`, y el motor
que arranca Diego desde el escritorio usa el directorio real. Sin cuidado, los
dos ven **catálogos distintos**. Y la trampa: **la variable de entorno se lee
normal** — la redirección la hace el sistema de ficheros, así que
`config._local_appdata()`, que mira `%LOCALAPPDATA%` buscando `Packages` y
`LocalCache`, **no siempre se dispara**. Para comprobar si dos rutas son el
mismo fichero: `fsutil file queryfileid <ruta>`.

Reglas:

1. **El motor de Diego se arranca con `launcher\engine-task.ps1`**, que registra
   la tarea programada `photo-editor-engine` (`-AlIniciarSesion` para que
   arranque al iniciar sesión, `-Quitar` para eliminarla). La tarea llama a
   `photo-editor.ps1 -SoloMotor` y corre **fuera del contenedor**. Nunca
   arrancarlo con Start-Process desde una sesión de Claude.
   `mcp_server._start_engine` prefiere esa tarea y **cae a un proceso suelto si
   no existe**: si no está registrada, el motor acaba dentro del contenedor sin
   avisar. Comprobarlo con `schtasks /Query /TN photo-editor-engine`.
2. **Para leer o escribir el directorio real desde dentro**, pasar por una tarea
   programada. `launcher\migrar-datos.ps1` es el ejemplo: copia
   virtualizado → real. El scratchpad y `%TEMP%` también están virtualizados, así
   que el script que lance la tarea debe vivir en el repo y el log en
   `C:\Users\Public`.
3. **Verificar con `/api/health`** (`app_dir`, `folders`, `lan`), no con rutas ni
   con el PID. `.venv\Scripts\python.exe` es un stub que lanza un hijo: el hijo
   es el que escucha, y puede morirse dejando vivo al padre. En Windows dos
   motores pueden escuchar en el 8177 a la vez y las peticiones se reparten.
4. **El MCP en Claude Desktop**: `launcher\mcp-desktop.ps1` registra la entrada y
   la repone cada 2 s durante 20 min, porque Desktop **reescribe**
   `claude_desktop_config.json` con su copia en memoria al guardar preferencias
   y ya se llevó la entrada una vez. Hay que cerrar Desktop del todo (bandeja →
   Salir) y volver a abrirlo. La ruta real del fichero es
   `...\Packages\<app>\LocalCache\Roaming\Claude\claude_desktop_config.json`.
5. **`launcher\firewall.ps1` lo ejecuta el usuario, nunca el asistente.** Y ojo:
   `health.lan.abierto` **no** dice que el cortafuegos esté abierto, solo que el
   motor escucha en `0.0.0.0`.
6. **Los `.ps1` son ASCII puro a propósito**: PowerShell 5.1 lee un `.ps1` sin
   BOM como ANSI y un guión largo rompe el parser en silencio.

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

## Rendimiento (CPU y GPU opcional)

- `parallel.prefetch` decodifica por delante en hilos (LibRaw suelta el GIL):
  apilados, timelapse, galería y export en lote. PHOTOED_THREADS lo ajusta
  (por defecto mitad de hilos lógicos, tope 4).
- `gpu.py`: aceleración opcional con CuPy (`uv sync --extra gpu`: CuPy +
  librerías CUDA en wheels de pip, sin CUDA Toolkit). Cubre sigma-clip,
  detección DoG y la parte tonal del revelado (geometría sigue en cv2/CPU).
  Todo cae a CPU ante cualquier error; PHOTOED_GPU=0 la apaga. El repo es
  público: el camino CPU es el de referencia y debe seguir funcionando.
- GOTCHA CuPy: `cupy.select` solo admite un **escalar** en `default` (numpy
  acepta arrays). Es el tipo de diferencia que revienta solo en el camino GPU,
  que es el que no se prueba por defecto.
- Timelapse usa h264_nvenc si el ffmpeg lo trae y funciona; si no, libx264.
- /api/health informa de gpu, threads y lan (host, urls para el móvil).
- Red local: host por PHOTOED_HOST o "host" en config.json (Diego: 0.0.0.0);
  por defecto 127.0.0.1 porque la API no tiene auth. Cortafuegos: solo con
  launcher/firewall.ps1 ejecutado por el usuario (nunca desde Claude). El 📱
  de la cabecera da URL + QR (/api/qr.png).

## Comandos

- Engine: `uv sync` / `uv run python -m photoeditor` (desde `engine/`; en esta
  máquina uv se invoca como `python -m uv`).
- App: `corepack pnpm install|dev|build` (desde `app/`).
- Verificación rápida: `GET http://127.0.0.1:8177/api/health`.
