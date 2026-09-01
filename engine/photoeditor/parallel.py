"""Decodificación por delante en hilos.

LibRaw suelta el GIL, así que 4 hilos decodifican ~2× más rápido que uno
(medido: 1.030 → 486 ms por frame de 24 MP). `prefetch` mantiene una ventana
acotada de resultados por delante para no disparar la memoria: con 4 frames
de 24 MP en vuelo son ~600 MB.

PHOTOED_THREADS fija el número de hilos (por defecto, la mitad de los
lógicos, tope 4: LibRaw ya paraleliza algo por dentro).
"""
import os
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def workers() -> int:
    env = os.environ.get("PHOTOED_THREADS", "")
    if env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, min(4, (os.cpu_count() or 4) // 2))


def prefetch(
    items: Iterable[T], fn: Callable[[T], R], window: int | None = None
) -> Iterator[tuple[T, R | Exception]]:
    """Genera (item, fn(item) | excepción) EN ORDEN, calculando `window`
    elementos por delante en hilos. Las excepciones se devuelven, no se
    lanzan: el consumidor decide qué hacer con cada frame."""
    window = window or workers()
    it = iter(items)
    with ThreadPoolExecutor(max_workers=window) as ex:
        pending: list = []

        def fill() -> None:
            while len(pending) < window:
                try:
                    item = next(it)
                except StopIteration:
                    return
                pending.append((item, ex.submit(fn, item)))

        fill()
        while pending:
            item, fut = pending.pop(0)
            fill()
            try:
                res: R | Exception = fut.result()
            except Exception as exc:
                res = exc
            yield item, res
