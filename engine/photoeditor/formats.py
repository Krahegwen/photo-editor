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
