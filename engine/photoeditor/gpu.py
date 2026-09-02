"""Aceleración opcional en GPU con CuPy.

Se activa sola si `import cupy` funciona y hay dispositivo CUDA; PHOTOED_GPU=0
la apaga. Todo lo que la usa (sigma-clip, detección DoG, pipeline tonal del
revelado) tiene su camino CPU equivalente y cae a él ante cualquier error
(falta de VRAM incluida), así que el repo funciona igual sin NVIDIA.

Instalación: `uv sync --extra gpu` (CuPy + librerías CUDA en wheels de pip,
sin CUDA Toolkit del sistema).
"""
import os
import warnings

# Con las librerías CUDA de pip (cuda-pathfinder) no hace falta CUDA_PATH.
warnings.filterwarnings("ignore", message="CUDA path could not be detected")

cp = None
ndi = None
AVAILABLE = False
REASON = ""

if os.environ.get("PHOTOED_GPU", "1") == "0":
    REASON = "desactivada (PHOTOED_GPU=0)"
else:
    try:
        import cupy as _cp
        import cupyx.scipy.ndimage as _ndi

        if _cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError("sin dispositivo CUDA")
        float((_cp.zeros(4, dtype=_cp.float32) + 1).sum())  # carga librerías
        cp, ndi = _cp, _ndi
        AVAILABLE = True
    except Exception as exc:  # sin cupy, sin driver, sin GPU…
        REASON = f"{type(exc).__name__}: {exc}"[:160]


# Interruptor en caliente (desde la web o el MCP): la GPU puede estar
# disponible pero apagada por el usuario sin reiniciar el motor.
enabled = True


def active() -> bool:
    return AVAILABLE and enabled


def set_enabled(value: bool) -> dict:
    global enabled
    enabled = bool(value)
    if not enabled:
        release()
    return info()


def info() -> dict:
    if not AVAILABLE:
        return {"disponible": False, "activa": False, "motivo": REASON or "cupy no instalado"}
    dev = cp.cuda.Device()
    free, total = dev.mem_info
    props = cp.cuda.runtime.getDeviceProperties(dev.id)
    name = props["name"]
    if isinstance(name, bytes):
        name = name.decode(errors="ignore")
    return {
        "disponible": True,
        "activa": enabled,
        "nombre": name,
        "vram_libre_mb": int(free // 2**20),
        "vram_total_mb": int(total // 2**20),
    }


def release() -> None:
    """Devuelve la VRAM del pool al sistema (para convivir con ComfyUI y cía)."""
    if AVAILABLE:
        try:
            cp.get_default_memory_pool().free_all_blocks()
        except Exception:
            pass
