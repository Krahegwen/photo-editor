"""Timelapse desde una secuencia de fotos (previews 1600, look de cámara).

Usa el ffmpeg embebido de imageio-ffmpeg (sin tocar el PATH del sistema).
Los frames se copian numerados a %LOCALAPPDATA%/stackwork y se borran al
terminar. Salida '<carpeta> - timelapse <HHMM>-<HHMM> <fps>fps.mp4' en la
carpeta (H.264 CRF 18, 1920x1080 con pillarbox para verticales).
"""
import shutil
import subprocess
import uuid
from pathlib import Path

from . import config, db, naming, previews


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        raise ValueError("No hay ffmpeg disponible (ni imageio-ffmpeg ni en el PATH)")


def job_fn(photo_ids: list[int], fps: int = 24, force: bool = False):
    if len(photo_ids) < 10:
        raise ValueError("Un timelapse necesita al menos 10 fotos")
    if not 2 <= fps <= 60:
        raise ValueError("fps fuera de rango (2-60)")

    def run(job: dict) -> dict:
        ffmpeg = _ffmpeg_exe()
        con = db.connect()
        try:
            rows = [
                con.execute(
                    """SELECT p.id, p.stem, p.ext, p.mtime, p.taken_at, f.name AS folder
                       FROM photos p JOIN folders f ON f.id = p.folder_id WHERE p.id=?""",
                    (pid,),
                ).fetchone()
                for pid in photo_ids
            ]
        finally:
            con.close()
        rows = [r for r in rows if r is not None]
        folders = {r["folder"] for r in rows}
        if len(folders) != 1:
            raise ValueError("Las fotos deben ser de una sola carpeta")
        folder = rows[0]["folder"]
        rows.sort(key=lambda r: r["stem"])
        root = config.get_root()

        out = root / folder / (naming.output_base(folder, "timelapse", rows, f" {fps}fps") + ".mp4")
        if out.exists() and not force:
            raise ValueError(f"Ya existe {out.name} — usa force para sobreescribir")

        job["progress"]["total"] = len(rows) + 1
        work = config.APP_DIR / "stackwork" / uuid.uuid4().hex[:8]
        work.mkdir(parents=True, exist_ok=True)
        try:
            n = 0
            fallidos: list[str] = []
            for r in rows:
                job["progress"]["current"] = r["stem"]
                try:
                    abs_path = root / folder / (r["stem"] + r["ext"])
                    rel = f"{folder}/{r['stem']}{r['ext']}"
                    pv = previews.get_preview(abs_path, rel, r["mtime"], 1600)
                    n += 1
                    shutil.copyfile(pv, work / f"{n:05d}.jpg")
                except Exception as exc:
                    fallidos.append(f"{r['stem']}: {exc}")
                job["progress"]["done"] += 1
            if n < 10:
                raise ValueError(f"Solo {n} frames válidos")

            job["progress"]["current"] = "codificando"
            cmd = [
                ffmpeg, "-y", "-framerate", str(fps),
                "-i", str(work / "%05d.jpg"),
                "-vf",
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", str(out),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if proc.returncode != 0:
                raise ValueError(f"ffmpeg falló: {proc.stderr[-400:]}")
            job["progress"]["done"] += 1
            return {
                "salida": f"{folder}/{out.name}",
                "frames": n,
                "fps": fps,
                "duracion_s": round(n / fps, 1),
                "fallidos": fallidos,
            }
        finally:
            shutil.rmtree(work, ignore_errors=True)

    return run
