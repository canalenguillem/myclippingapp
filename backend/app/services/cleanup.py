"""Liberar disco: todo lo pesado (vídeo original, audio y renders) se puede regenerar descargando el vídeo de nuevo y volviendo
a renderizar, así que solo se conserva lo que no: `words.json`, `silences.json` y la BD (clips, gráficos, SEO, speakers…)."""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Project, RenderState
from app.jobs import queue
from app.services import storage

KEEP = {"words.json", "silences.json"}      # lo que cuesta dinero o tiempo regenerar (AssemblyAI) o es pequeño y útil


@dataclass
class Usage:
    total: int
    heavy: int
    last_activity: float | None       # mtime más reciente de cualquier fichero del proyecto (segundos epoch)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


def usage(folder: Path) -> Usage:
    if not folder.is_dir():
        return Usage(0, 0, None)
    total = heavy = 0
    newest = 0.0
    for f in folder.rglob("*"):
        if not f.is_file():
            continue
        size = f.stat().st_size
        total += size
        newest = max(newest, f.stat().st_mtime)
        if not (f.parent == folder and f.name in KEEP):
            heavy += size
    return Usage(total, heavy, newest or None)


def free_project(db: Session, project: Project) -> int:
    """Borra lo pesado del proyecto y deja los clips sin render (el vídeo se descarga solo al volver a renderizar).
    No toca nada si hay un job en cola o en marcha. Devuelve los bytes liberados."""
    if queue.active_job(db, project.user_id, project.id):
        return 0
    folder = storage.project_dir(project.user_id, project.id)
    before = usage(folder).total
    for item in list(folder.iterdir()):
        if item.name in KEEP:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    for clip in db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == project.user_id)).all():
        clip.draft_path = clip.rendered_path = clip.thumbnail_path = clip.analysis_path = None
        if clip.render_state is not RenderState.RENDERING:
            clip.render_state = RenderState.NONE
    db.commit()
    return max(0, before - usage(folder).total)


def cleanup_old(db: Session, retention_days: int, *, now: float | None = None) -> tuple[int, int]:
    """Libera los proyectos sin actividad (ficheros nuevos: descargas, renders) en `retention_days`. (proyectos, bytes)."""
    if retention_days <= 0:
        return 0, 0
    limit = (now if now is not None else time.time()) - retention_days * 86400
    projects = freed = 0
    for project in db.scalars(select(Project)).all():
        u = usage(storage.project_dir(project.user_id, project.id))
        if u.heavy == 0 or u.last_activity is None or u.last_activity > limit:
            continue
        got = free_project(db, project)
        if got:
            projects += 1
            freed += got
    return projects, freed


def disk() -> tuple[int, int]:
    """(libres, totales) en bytes del disco donde está MEDIA_DIR."""
    stat = shutil.disk_usage(storage.media_root())
    return stat.free, stat.total


def utc_iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None
