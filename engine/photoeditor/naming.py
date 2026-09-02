"""Nombres de salida de apilados/timelapses: '<carpeta> <HHhMM>-<HHhMM> <tipo>'.

El intervalo sale del taken_at (EXIF) de la selección y se escribe con la
'h' para que no se confunda con un rango de números de foto:
'240812 - Estrellas 02h02-02h17 trails'. Si cruza medianoche se antepone
el día al fin (23h50-14d00h20); sin EXIF se cae al rango de stems.
"""


def time_span(rows) -> str:
    times = sorted(r["taken_at"] for r in rows if r["taken_at"])
    if times:
        t0, t1 = times[0], times[-1]
        a = f"{t0[11:13]}h{t0[14:16]}"
        b = f"{t1[11:13]}h{t1[14:16]}"
        if t0[:10] != t1[:10]:
            b = f"{t1[8:10]}d{b}"
        return f"{a}-{b}"
    return f"{rows[0]['stem'][-4:]}-{rows[-1]['stem'][-4:]}"


def output_base(folder: str, kind: str, rows, extra: str = "") -> str:
    from . import config  # la raíz ('.') se nombra por su carpeta real

    return f"{config.display_name(folder)} {time_span(rows)} {kind}{extra}"
