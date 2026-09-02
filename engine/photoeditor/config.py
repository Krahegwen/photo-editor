"""Configuración y rutas de datos locales.

Todo lo que genera la app (índice, caché, config) vive en %LOCALAPPDATA%,
nunca dentro de la carpeta de fotos: esa se sincroniza con la nube del usuario.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

def _local_appdata() -> Path:
    """%LOCALAPPDATA% real del usuario.

    - Si el proceso no lo trae (tareas programadas, servicios), se deriva del
      perfil para no acabar en un directorio de datos fantasma.
    - Si viene VIRTUALIZADO (procesos lanzados desde una app empaquetada MSIX,
      p. ej. Claude Desktop: '...\\Packages\\<app>\\LocalCache\\Local'), se
      des-virtualiza: si no, el motor arrancado desde ahí y el arrancado desde
      el escritorio verían catálogos distintos."""
    env = os.environ.get("LOCALAPPDATA")
    if os.name != "nt":
        return Path(env) if env else Path.home() / ".local" / "share"
    if env:
        p = Path(env)
        parts = [x.lower() for x in p.parts]
        if "packages" in parts and "localcache" in parts:
            return Path.home() / "AppData" / "Local"
        return p
    return Path.home() / "AppData" / "Local"


APP_DIR = Path(os.environ.get("PHOTOED_HOME") or _local_appdata() / "photo-editor")
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
    raw = os.environ.get("PHOTOED_ROOT") or str(_file_config().get("root", ""))
    # Path("") es "." (el cwd) y existe siempre: una raíz vacía NO es una raíz
    if not raw.strip() or raw.strip() == ".":
        raise RuntimeError(
            f"Carpeta de fotos no configurada: define PHOTOED_ROOT o 'root' en {CONFIG_PATH}"
        )
    root = Path(raw).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError(f"La carpeta de fotos no existe o no es absoluta: {raw}")
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
