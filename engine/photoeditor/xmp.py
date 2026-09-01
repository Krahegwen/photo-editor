"""Sidecars .xmp — fuente de verdad del rating, compatible con Lightroom.

Lectura: la misma regex del flujo previo (atributo o elemento). Escritura:
si el sidecar existe (p. ej. creado por Lightroom con ajustes de revelado)
solo se toca el valor de xmp:Rating y se preserva todo lo demás; si no
existe, se crea uno mínimo que Lightroom lee sin quejarse.
"""
import re
from pathlib import Path

_RATING_ATTR = re.compile(r'(xmp:Rating=")(-?\d+)(")')
_RATING_ELEM = re.compile(r"(<xmp:Rating>)(-?\d+)(</xmp:Rating>)")
_DESCRIPTION = re.compile(r"(<rdf:Description\b)")

_MINIMAL = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="photo-editor">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmp:Rating="{rating}"/>
 </rdf:RDF>
</x:xmpmeta>
"""


def read_rating(xmp_path: Path) -> int | None:
    try:
        text = xmp_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _RATING_ATTR.search(text) or _RATING_ELEM.search(text)
    return int(m.group(2)) if m else None


_SUBJECT_BLOCK = re.compile(r"<dc:subject>.*?</dc:subject>", re.S)
_LI = re.compile(r"<rdf:li[^>]*>(.*?)</rdf:li>", re.S)
_DESC_SELFCLOSE = re.compile(r"(<rdf:Description\b[^>]*?)/>", re.S)

_MINIMAL_KW = """<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="photo-editor">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/">
   {block}
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def read_keywords(xmp_path: Path) -> list[str]:
    try:
        text = xmp_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    m = _SUBJECT_BLOCK.search(text)
    if not m:
        return []
    return [li.strip() for li in _LI.findall(m.group(0)) if li.strip()]


def write_keywords(xmp_path: Path, keywords: list[str], replace: bool = False) -> list[str]:
    """Escribe dc:subject (keywords de Lightroom) preservando el resto del
    sidecar. Por defecto AÑADE a las existentes; devuelve la lista final."""
    nuevos = [k.strip() for k in keywords if k and k.strip()]
    actuales = [] if replace else read_keywords(xmp_path)
    todos = list(dict.fromkeys(actuales + nuevos))
    lis = "".join(f"<rdf:li>{_esc(k)}</rdf:li>" for k in todos)
    block = f"<dc:subject><rdf:Bag>{lis}</rdf:Bag></dc:subject>"

    if not xmp_path.exists():
        out = _MINIMAL_KW.format(block=block)
    else:
        text = xmp_path.read_text(encoding="utf-8", errors="ignore")
        if _SUBJECT_BLOCK.search(text):
            out = _SUBJECT_BLOCK.sub(block, text, count=1)
        else:
            if "xmlns:dc=" not in text:
                new, n = _DESCRIPTION.subn(
                    lambda m: m.group(1) + ' xmlns:dc="http://purl.org/dc/elements/1.1/"',
                    text,
                    count=1,
                )
                if not n:
                    raise ValueError(f"Sidecar con estructura desconocida: {xmp_path.name}")
                text = new
            m = _DESC_SELFCLOSE.search(text)
            if m:
                out = text[: m.start()] + m.group(1) + f">{block}</rdf:Description>" + text[m.end() :]
            elif "</rdf:Description>" in text:
                out = text.replace("</rdf:Description>", f"{block}</rdf:Description>", 1)
            else:
                raise ValueError(f"Sidecar con estructura desconocida: {xmp_path.name}")

    tmp = xmp_path.with_name(xmp_path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(xmp_path)
    return todos


def write_rating(xmp_path: Path, rating: int) -> None:
    if xmp_path.exists():
        text = xmp_path.read_text(encoding="utf-8", errors="ignore")
        new, n = _RATING_ATTR.subn(lambda m: m.group(1) + str(rating) + m.group(3), text, count=1)
        if not n:
            new, n = _RATING_ELEM.subn(
                lambda m: m.group(1) + str(rating) + m.group(3), text, count=1
            )
        if not n:
            attr = f' xmp:Rating="{rating}"'
            if "xmlns:xmp=" not in text:
                attr = ' xmlns:xmp="http://ns.adobe.com/xap/1.0/"' + attr
            new, n = _DESCRIPTION.subn(lambda m: m.group(1) + attr, text, count=1)
        if not n:
            raise ValueError(f"Sidecar con estructura desconocida, no lo toco: {xmp_path.name}")
        out = new
    else:
        out = _MINIMAL.format(rating=rating)
    tmp = xmp_path.with_name(xmp_path.name + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(xmp_path)
