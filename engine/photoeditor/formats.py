"""Extensiones soportadas por el motor.

RAW = todo lo que decodifica LibRaw/rawpy con thumb incrustado razonable.
Probado con: ARW (Sony), DNG (Canon/Leica/Sony), RW2 (Panasonic).
"""

RAW_EXTS = {
    ".arw",  # Sony
    ".dng",  # Adobe/universal (Leica, drones, móviles…)
    ".rw2",  # Panasonic
    ".cr2",  # Canon
    ".cr3",  # Canon (ISO-BMFF: el EXIF vía exifread puede venir vacío)
    ".nef",  # Nikon
    ".nrw",  # Nikon
    ".raf",  # Fujifilm
    ".orf",  # Olympus/OM
    ".pef",  # Pentax
    ".srw",  # Samsung
}

FLAT_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}

IMAGE_EXTS = RAW_EXTS | FLAT_EXTS


def is_raw(ext: str) -> bool:
    return ext.lower() in RAW_EXTS


# Una foto = un nombre base; sus archivos son versiones. La "principal" (la que
# se previsualiza, revela y mide) es el RAW si lo hay, luego TIFF, PNG, JPG.
_RANK = {".tif": 1, ".tiff": 1, ".png": 2, ".jpg": 3, ".jpeg": 3}


def rank(ext: str) -> int:
    e = ext.lower()
    if e in RAW_EXTS:
        return 0
    return _RANK.get(e, 4)
