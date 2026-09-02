"""Configuración y rutas de datos locales.

Todo lo que genera la app (índice, caché, config) vive en %LOCALAPPDATA%,
nunca dentro de la carpeta de fotos: esa se sincroniza con la nube del usuario.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(
    os.environ.get("PHOTOED_HOME")
    or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "photo-editor"
)
CACHE_DIR = APP_DIR / "cache"
DB_PATH = APP_DIR / "catalog.db"
CONFIG_PATH = APP_DIR / "config.json"


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _file_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def get_root() -> Path:
    """Raíz del archivo fotográfico: PHOTOED_ROOT > config.json."""
    env = os.environ.get("PHOTOED_ROOT")
    root = Path(env) if env else Path(_file_config().get("root", ""))
    if not str(root).strip() or not root.is_dir():
        raise RuntimeError(
            f"Carpeta de fotos no configurada: define PHOTOED_ROOT o 'root' en {CONFIG_PATH}"
        )
    return root


def set_root(path: str) -> Path:
    """Guarda la raíz en config.json (la UI la elige) y refresca la caché."""
    p = Path(path).expanduser()
    if not str(path).strip() or not p.is_dir():
        raise ValueError(f"No existe la carpeta: {path}")
    cfg = _file_config()
    cfg["root"] = str(p)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    get_root.cache_clear()
    return p


# Nombre interno de la propia raíz cuando contiene fotos sueltas (además de,
# o en vez de, subcarpetas): `root / "."` sigue siendo la raíz.
ROOT_FOLDER = "."


def display_name(folder: str) -> str:
    """Nombre visible de una carpeta del catálogo ('.' se muestra como la raíz)."""
    if folder != ROOT_FOLDER:
        return folder
    try:
        return get_root().name or "raíz"
    except RuntimeError:
        return "raíz"
