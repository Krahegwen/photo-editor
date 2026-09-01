"""Cola de trabajos del motor: un worker secuencial, registro en memoria.

Los trabajos largos (escaneo, métricas, exportación, cerrar carpeta) se
encolan aquí; la UI y el servidor MCP consultan el mismo registro vía
/api/jobs. El registro es efímero (memoria del proceso): si el motor se
reinicia se pierde el historial, nunca los efectos (archivos, DB).
"""
import queue
import threading
import time
import uuid
from collections import OrderedDict
from typing import Callable

MAX_KEPT = 60

_jobs: "OrderedDict[str, dict]" = OrderedDict()
_queue: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_started = False


def _worker() -> None:
    while True:
        jid = _queue.get()
        with _lock:
            job = _jobs.get(jid)
        if job is None:
            continue
        job["state"] = "running"
        job["started"] = time.time()
        fn = job.pop("_fn", None)
        try:
            job["result"] = fn(job) if fn else None
            job["state"] = "done"
        except Exception as exc:
            job["state"] = "error"
            job["error"] = str(exc)
        finally:
            job["finished"] = time.time()
            job["progress"]["current"] = None


def _trim() -> None:
    finished = [k for k, j in _jobs.items() if j["state"] in ("done", "error")]
    while len(_jobs) > MAX_KEPT and finished:
        _jobs.pop(finished.pop(0), None)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def submit(kind: str, title: str, fn: Callable[[dict], object]) -> dict:
    global _started
    with _lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
        job = {
            "id": uuid.uuid4().hex[:10],
            "kind": kind,
            "title": title,
            "state": "queued",
            "progress": {"done": 0, "total": 0, "current": None},
            "result": None,
            "error": None,
            "created": time.time(),
            "started": None,
            "finished": None,
            "_fn": fn,
        }
        _jobs[job["id"]] = job
        _trim()
    _queue.put(job["id"])
    return public(job)


def get(job_id: str) -> dict | None:
    j = _jobs.get(job_id)
    return public(j) if j else None


def recent(limit: int = 20) -> list[dict]:
    return [public(j) for j in reversed(_jobs.values())][:limit]


def active() -> list[dict]:
    return [public(j) for j in _jobs.values() if j["state"] in ("queued", "running")]
