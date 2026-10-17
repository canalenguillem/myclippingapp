"""Rutas de ficheros por usuario/proyecto. En la BD se guardan relativas a MEDIA_DIR."""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def media_root() -> Path:
    return get_settings().media_dir


def project_dir(user_id: int, project_id: int) -> Path:
    path = media_root() / f"u{user_id}" / f"p{project_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rel(path: Path) -> str:
    return path.resolve().relative_to(media_root().resolve()).as_posix()


def absolute(relative: str) -> Path:
    """Resuelve una ruta relativa de la BD y rechaza cualquiera que se salga de MEDIA_DIR."""
    root = media_root().resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError("Ruta fuera de MEDIA_DIR")
    return path
