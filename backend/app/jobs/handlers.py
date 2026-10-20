"""Handlers por tipo de job. Cada uno recibe un JobContext y el payload."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from . import queue
from .context import Cancelled, JobContext  # noqa: F401  (se reexportan: otros módulos los importan de aquí)


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
    from app.db.models import Project, ProjectStatus, User
    from app.services import speakers as speakers_service
    from app.services import silences as silences_service
    from app.services import seo as seo_service
    from app.services import source as source_service
    from app.services import storage, transcription, video_download

    project = ctx.db.get(Project, int(payload["project_id"]))
    if project is None or project.user_id != ctx.user_id:
        raise RuntimeError("Proyecto no encontrado")
    user = ctx.db.get(User, ctx.user_id)

    def fail(message: str) -> None:
        # Un re-transcribir fallido no invalida lo que ya había: se vuelve al estado anterior con el error a la vista.
        project.status = previous_status if transcribe_only else ProjectStatus.FAILED
        project.error = message[:2000]
        ctx.db.commit()

    transcribe_only = bool(payload.get("transcribe_only"))
    previous_status = project.status

    def measure_silences(folder) -> None:
        ctx.log("Midiendo silencios…")
        found = silences_service.detect_silences(folder / "audio.mp3")
        silences_file = folder / "silences.json"
        silences_service.save_silences(found, silences_file)
        project.silences_path = storage.rel(silences_file)
        ctx.db.commit()
        ctx.log(f"{len(found)} silencios")

    def transcribe(folder) -> None:
        ctx.log("Transcribiendo con AssemblyAI y diarización (puede tardar unos minutos)…")
        ctx.progress(55)
        data = transcription.transcribe_words(
            folder / "audio.mp3", payload.get("language", "auto"), payload.get("speakers_expected")
        )
        words_file = folder / "words.json"
        transcription.save_words(data, words_file)
        labels = transcription.speaker_labels(data)
        project.speakers = speakers_service.merge_speakers(project.speakers, labels)
        project.words_path = storage.rel(words_file)
        ctx.db.commit()
        ctx.log(f"{len(data['words'])} palabras · idioma {data['language']} · speakers {', '.join(labels)}")

    try:
        folder = storage.project_dir(project.user_id, project.id)
        if transcribe_only:
            if not project.video_path:
                raise RuntimeError("El proyecto no tiene vídeo descargado: no se puede re-transcribir")
            if not (folder / "audio.mp3").exists():
                source = source_service.ensure_source(project, ctx.log)
                ctx.db.commit()
                video_download.extract_audio(source, folder / "audio.mp3")
            project.status, project.error = ProjectStatus.TRANSCRIBING, None
            ctx.db.commit()
            if not project.silences_path:  # proyectos importados antes de F4
                measure_silences(folder)
            transcribe(folder)
            project.status = previous_status if previous_status in (ProjectStatus.READY, ProjectStatus.DETECTING) else ProjectStatus.DETECTING
            ctx.db.commit()
            return
        project.status, project.error = ProjectStatus.DOWNLOADING, None
        ctx.db.commit()

        ctx.log(f"Leyendo metadatos: {project.source_url}")
        info = video_download.probe(project.source_url, ctx.log)
        duration = float(info.get("duration") or 0)
        project.title = str(info.get("title") or project.source_url)[:512]
        project.duration = duration
        project.source_handle = project.source_handle or seo_service.handle_from_info(info)
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
        measure_silences(folder)
        project.status = ProjectStatus.TRANSCRIBING
        ctx.db.commit()
        transcribe(folder)
        project.status = ProjectStatus.DETECTING
        ctx.db.commit()
        queue.enqueue(ctx.db, ctx.user_id, "detect", {"project_id": project.id})
        ctx.log("Detección de clips encolada")
    except Cancelled:
        fail("Cancelado")
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise


def detect(ctx: JobContext, payload: dict) -> None:
    """Pide al LLM los mejores momentos, ajusta los cortes a silencios y guarda los clips."""
    from app.db.models import Project, ProjectStatus
    from app.services import clip_detector, clips as clips_service, silences as silences_service
    from app.services import storage, transcription

    project = ctx.db.get(Project, int(payload["project_id"]))
    if project is None or project.user_id != ctx.user_id:
        raise RuntimeError("Proyecto no encontrado")
    previous = project.status

    def fail(message: str) -> None:
        # Un re-detectar fallido sobre un proyecto ya listo no lo invalida: vuelve a `ready` con el error a la vista.
        project.status = ProjectStatus.READY if previous is ProjectStatus.READY else ProjectStatus.FAILED
        project.error = message[:2000]
        ctx.db.commit()

    try:
        if not project.words_path:
            raise RuntimeError("El proyecto no tiene transcripción")
        project.status, project.error = ProjectStatus.DETECTING, None
        ctx.db.commit()
        data = transcription.load_words(storage.absolute(project.words_path))
        silences = (silences_service.load_silences(storage.absolute(project.silences_path))
                    if project.silences_path else [])

        def progress(fraction: float) -> None:
            ctx.check_cancelled()
            ctx.progress(int(fraction * 90))

        candidates = clip_detector.detect_clips(
            data, parts=payload.get("parts"), clips_per_part=int(payload.get("clips_per_part", 5)),
            target_dur=int(payload.get("target_dur", 40)), silences=silences, log=ctx.log, progress=progress,
        )
        total = project.duration
        for c in candidates:
            c.start = silences_service.snap_start(c.start, silences)
            c.end = silences_service.snap_end(c.end, silences, total)
        inserted, skipped = clips_service.replace_detected_clips(ctx.db, project, candidates)
        ctx.log(f"{inserted} clips guardados" + (f" ({skipped} descartados por solaparse con clips ya trabajados)" if skipped else ""))
        project.status = ProjectStatus.READY
        ctx.db.commit()
    except Cancelled:
        fail("Cancelado")
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise


from .render import render  # noqa: E402  (al final: render importa este paquete)
from .upload import upload  # noqa: E402

HANDLERS: dict[str, Handler] = {"demo": demo, "ingest": ingest, "detect": detect, "render": render, "upload": upload}
