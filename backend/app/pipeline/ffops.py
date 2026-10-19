"""Retoques sueltos con ffmpeg: miniatura y reducción del borrador."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .ffmpeg_run import FfmpegError, progress_args, run_ffmpeg


class FfopsError(RuntimeError):
    pass


def make_thumbnail(video: Path, out_path: Path, *, at: float, width: int = 540, ffmpeg: str = "ffmpeg") -> Path:
    """Un fotograma del vídeo en `at` segundos, escalado a `width` de ancho."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    try:
        run_ffmpeg([ffmpeg, "-y", "-v", "error", "-nostats", "-ss", f"{max(0.0, at):.3f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(part)], duration=1.0, cleanup=[part])
    except FfmpegError as exc:
        raise FfopsError(f"No se pudo sacar la miniatura: {exc}") from exc
    if not part.exists():
        raise FfopsError("No se generó la miniatura")
    os.replace(part, out_path)
    return out_path


def downscale(video: Path, out_path: Path, *, width: int, height: int, duration: float, ffmpeg: str = "ffmpeg",
              on_progress: Callable[[float], None] | None = None,
              cancel_check: Callable[[], None] | None = None) -> Path:
    """Reduce un vídeo (p. ej. el render de HyperFrames, siempre 1080x1920) al tamaño del borrador."""
    out_path = Path(out_path)
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    cmd = [*progress_args(ffmpeg), "-i", str(video), "-vf", f"scale={width}:{height}", "-c:v", "libx264", "-crf", "28",
           "-preset", "veryfast", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-movflags", "+faststart",
           "-c:a", "copy", str(part)]
    try:
        run_ffmpeg(cmd, duration=duration, cleanup=[part], on_progress=on_progress, cancel_check=cancel_check)
    except FfmpegError as exc:
        raise FfopsError(f"No se pudo reducir el borrador: {exc}") from exc
    if not part.exists():
        raise FfopsError("No se generó el borrador reducido")
    os.replace(part, out_path)
    return out_path


def cut_for_analysis(video: Path, start: float, end: float, out_path: Path, *, ffmpeg: str = "ffmpeg",
                     cancel_check: Callable[[], None] | None = None) -> Path:
    """Tramo [start, end] a 25 fps y 720 px de alto, sin recomponer: lo que se manda al worker de ASD."""
    out_path = Path(out_path)
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    duration = round(end - start, 3)
    cmd = [*progress_args(ffmpeg), "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{duration:.3f}",
           "-vf", "scale=-2:'min(720,ih)',fps=25", "-c:v", "libx264", "-crf", "26", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-ar", "16000", "-ac", "1", str(part)]
    try:
        run_ffmpeg(cmd, duration=duration, cleanup=[part], cancel_check=cancel_check)
    except FfmpegError as exc:
        raise FfopsError(f"No se pudo preparar el tramo para el análisis: {exc}") from exc
    if not part.exists():
        raise FfopsError("No se generó el tramo de análisis")
    os.replace(part, out_path)
    return out_path
