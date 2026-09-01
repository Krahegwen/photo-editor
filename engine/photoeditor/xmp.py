"""Sidecars .xmp — fuente de verdad del rating, compatible con Lightroom.

Lightroom escribe xmp:Rating como atributo o como elemento; la misma regex
que ya usaba el flujo previo cubre ambos casos.
"""
import re
from pathlib import Path

_RATING_RE = re.compile(r'xmp:Rating(?:="|>)(-?\d+)')


def read_rating(xmp_path: Path) -> int | None:
    try:
        text = xmp_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _RATING_RE.search(text)
    return int(m.group(1)) if m else None
