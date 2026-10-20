"""El vídeo original de un proyecto: si se borró para liberar espacio, se descarga de nuevo (lo único que no se puede regenerar
sin él son los renders; la transcripción y los clips viven en la BD y en `words.json`)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.db.models import Project
from app.services import storage, video_download


def available(project: Project) -> bool:
    if not project.video_path:
        return False
    try:
        return storage.absolute(project.video_path).is_file()
    except ValueError:
        return False


def ensure_source(project: Project, log: Callable[[str], None], on_progress: Callable[[float], None] = lambda f: None) -> Path:
    """Ruta del vídeo original; lo descarga de nuevo si falta en el disco. No hace commit: lo hace quien llama."""
    if not project.video_path:
        raise video_download.DownloadError("El proyecto aún no tiene vídeo")
    path = storage.absolute(project.video_path)
    if path.is_file():
        return path
    log("El vídeo original se borró para liberar espacio: descargándolo de nuevo…")
    video = video_download.download(project.source_url, storage.project_dir(project.user_id, project.id), log, on_progress)
    project.video_path = storage.rel(video)
    log(f"Vídeo descargado: {video.name} ({video.stat().st_size / 1e6:.0f} MB)")
    return video
