"""Ejecuta ffmpeg con progreso (0..1) y cancelación. Lo comparten el vertical, el fallback ASS y los retoques."""
from __future__ import annotations

import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path


class FfmpegError(RuntimeError):
    """ffmpeg terminó con error; el mensaje lleva las últimas líneas de su salida."""


def run_ffmpeg(
    args: list[str],
    *,
    duration: float,
    cleanup: list[Path] | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> None:
    """`args` es la orden completa (con `-progress pipe:1 -nostats -v error`). `cancel_check` se llama a menudo y puede
    lanzar para cancelar: ffmpeg se mata y se borran los ficheros de `cleanup`."""
    cleanup = cleanup or []
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: deque[str] = deque(maxlen=12)  # lo que no es progreso: los mensajes de error de ffmpeg
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    done = min(1.0, max(0.0, int(line.split("=", 1)[1]) / 1e6 / duration))
                except (ValueError, ZeroDivisionError):
                    continue
                if on_progress:
                    on_progress(done)
            elif "=" not in line and line:
                tail.append(line)
            if cancel_check:
                cancel_check()
        proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        for f in cleanup:
            f.unlink(missing_ok=True)
        raise
    if proc.returncode != 0:
        for f in cleanup:
            f.unlink(missing_ok=True)
        raise FfmpegError(" | ".join(tail)[-600:])
    if on_progress:
        on_progress(1.0)


def progress_args(ffmpeg: str = "ffmpeg") -> list[str]:
    return [ffmpeg, "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
