"""Nombres de salida de apilados/timelapses: '<carpeta> - <tipo> <HHMM>-<HHMM>[ extra]'.

El intervalo sale del taken_at (EXIF) de la selección: p. ej.
'240812 - Estrellas - trails 0202-0227'. Si cruza medianoche se antepone el
día al fin (0250-13.0110); sin EXIF se cae al rango de stems (4 dígitos).
"""


def time_span(rows) -> str:
    times = sorted(r["taken_at"] for r in rows if r["taken_at"])
    if times:
        t0, t1 = times[0], times[-1]
        a = t0[11:16].replace(":", "")
        b = t1[11:16].replace(":", "")
        if t0[:10] != t1[:10]:
            b = f"{t1[8:10]}.{b}"
        return f"{a}-{b}"
    return f"{rows[0]['stem'][-4:]}-{rows[-1]['stem'][-4:]}"


def output_base(folder: str, kind: str, rows, extra: str = "") -> str:
    return f"{folder} - {kind} {time_span(rows)}{extra}"
