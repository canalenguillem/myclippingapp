"""Handlers por tipo de job. Cada uno recibe un JobContext y el payload."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from . import queue


class Cancelled(Exception):
    pass


@dataclass
class JobContext:
    db: Session
    job_id: int
    user_id: int
    log_file: Path

    def log(self, message: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip("\n") + "\n")

    def progress(self, value: int) -> None:
        queue.set_progress(self.db, self.job_id, value)

    def check_cancelled(self) -> None:
        if queue.is_cancelled(self.db, self.job_id):
            raise Cancelled()


Handler = Callable[[JobContext, dict], None]


def demo(ctx: JobContext, payload: dict) -> None:
    """Job de prueba: cuenta segundos, escribe log y progreso. Sirve para validar la cola."""
    seconds = int(payload.get("seconds", 10))
    ctx.log(f"demo: {seconds}s")
    for i in range(seconds):
        ctx.check_cancelled()
        time.sleep(1)
        ctx.log(f"tick {i + 1}/{seconds}")
        ctx.progress(int((i + 1) * 100 / seconds))
    if payload.get("fail"):
        raise RuntimeError("fallo pedido en el payload")


def ingest(ctx: JobContext, payload: dict) -> None:
    """Descarga el vídeo, extrae el audio y lo transcribe una sola vez, por palabra."""
    from app.db.models import Project, User
    from app.services import storage, transcription, video_download

    project = ctx.db.get(Project, int(payload["project_id"]))
    if project is None or project.user_id != ctx.user_id:
        raise RuntimeError("Proyecto no encontrado")
    user = ctx.db.get(User, ctx.user_id)

    def fail(message: str) -> None:
        project.status, project.error = "failed", message[:2000]
        ctx.db.commit()

    try:
        folder = storage.project_dir(project.user_id, project.id)
        project.status, project.error = "downloading", None
        ctx.db.commit()

        ctx.log(f"Leyendo metadatos: {project.source_url}")
        info = video_download.probe(project.source_url, ctx.log)
        duration = float(info.get("duration") or 0)
        project.title = str(info.get("title") or project.source_url)[:512]
        project.duration = duration
        ctx.db.commit()
        if duration and duration > user.max_video_minutes * 60:
            raise video_download.DownloadError(
                f"El vídeo dura {duration / 60:.0f} min y tu límite es {user.max_video_minutes} min"
            )
        ctx.log(f"«{project.title}» · {duration / 60:.1f} min")
        ctx.check_cancelled()

        last = {"pct": -1}

        def on_progress(frac: float) -> None:
            pct = int(frac * 50)
            if pct != last["pct"]:
                last["pct"] = pct
                ctx.check_cancelled()
                ctx.progress(pct)

        video = video_download.download(project.source_url, folder, ctx.log, on_progress)
        project.video_path = storage.rel(video)
        ctx.db.commit()
        ctx.log(f"Vídeo descargado: {video.name} ({video.stat().st_size / 1e6:.0f} MB)")
        ctx.progress(50)

        audio = video_download.extract_audio(video, folder / "audio.mp3")
        ctx.check_cancelled()
        project.status = "transcribing"
        ctx.db.commit()
        ctx.log("Transcribiendo con AssemblyAI (puede tardar unos minutos)…")
        ctx.progress(55)
        data = transcription.transcribe_words(audio, payload.get("language", "auto"))
        words_file = folder / "words.json"
        transcription.save_words(data, words_file)
        ctx.log(f"{len(data['words'])} palabras · idioma {data['language']}")

        project.words_path = storage.rel(words_file)
        project.status = "transcribed"
        ctx.db.commit()
    except Cancelled:
        fail("Cancelado")
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise


HANDLERS: dict[str, Handler] = {"demo": demo, "ingest": ingest}
