"""Clip vertical con pantalla partida: plano corto arriba y la escena completa abajo.

Port de `make_vertical_clip` del repo viejo, solo para el diseño `split` (el único que se renderiza en F5).
El corte y la composición salen en una sola pasada de ffmpeg. La salida va pensada para HyperFrames:
30 fps constantes y un fotograma clave por segundo (con intervalos largos «causa fallos al buscar y
congelaciones», ver fx_worker/spike/RESULTADOS.md).
"""
from __future__ import annotations

import os
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path

CANVAS_W, CANVAS_H = 1080, 1920
DRAFT_W, DRAFT_H = 540, 960
FPS = 30

FOCUS_X = {"left": "0", "center": "(iw-ow)/2", "right": "iw-ow"}


class VerticalError(RuntimeError):
    pass


def canvas_for(draft: bool) -> tuple[int, int]:
    return (DRAFT_W, DRAFT_H) if draft else (CANVAS_W, CANVAS_H)


def build_filter(top_ratio: float = 0.5, focus: str = "center", zoom: float = 1.0,
                 width: int = CANVAS_W, height: int = CANVAS_H) -> str:
    """Arriba: recorte enfocado (encuadre + zoom) que rellena el hueco. Abajo: la escena completa, sin recortar y
    con barras negras si hace falta, para no perder a nadie. Termina en 30 fps constantes."""
    if focus not in FOCUS_X:
        raise VerticalError(f"Encuadre no válido: {focus!r}")
    top_h = int(height * top_ratio)
    top_h -= top_h % 2  # alto par para el codec
    bottom_h = height - top_h
    zoom = max(1.0, float(zoom))
    scaled_w, scaled_h = int(width * zoom), int(top_h * zoom)
    return (
        f"[0:v]split=2[top][botsrc];"
        f"[top]scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
        f"crop={width}:{top_h}:{FOCUS_X[focus]}:(ih-oh)/2,setsar=1[toppad];"
        f"[botsrc]scale={width}:{bottom_h}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{bottom_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[bot];"
        f"[toppad][bot]vstack=inputs=2,fps={FPS}[v]"
    )


def make_vertical_clip(
    video: Path,
    start: float,
    end: float,
    out_path: Path,
    *,
    top_ratio: float = 0.5,
    focus: str = "center",
    zoom: float = 1.0,
    draft: bool = False,
    ffmpeg: str = "ffmpeg",
    on_progress: Callable[[float], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> Path:
    """Corta [start, end] (segundos del vídeo fuente) y lo compone en vertical.

    `draft` produce 540x960 con compresión rápida. `on_progress` recibe 0..1. `cancel_check` se llama a menudo y
    puede lanzar para cancelar: ffmpeg se mata y no queda ningún fichero a medias."""
    if not Path(video).is_file():
        raise VerticalError(f"No existe el vídeo de origen: {video}")
    if not (start >= 0 and end > start):
        raise VerticalError("El fin debe ser posterior al inicio (y el inicio no negativo)")
    if not 0.2 <= top_ratio <= 0.9:
        raise VerticalError("top_ratio debe estar entre 0,2 y 0,9")
    duration = round(end - start, 3)
    width, height = canvas_for(draft)
    quality = ["-crf", "28", "-preset", "veryfast"] if draft else ["-crf", "20", "-preset", "medium"]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_name(out_path.stem + ".part" + out_path.suffix)
    cmd = [
        ffmpeg, "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{duration:.3f}",
        "-filter_complex", build_filter(top_ratio, focus, zoom, width, height),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", *quality, "-pix_fmt", "yuv420p",
        "-g", str(FPS), "-keyint_min", str(FPS), "-sc_threshold", "0",  # fotograma clave cada segundo
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        str(part),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: deque[str] = deque(maxlen=12)  # lo que no es progreso: los mensajes de error de ffmpeg
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    done = min(1.0, max(0.0, int(line.split("=", 1)[1]) / 1e6 / duration))
                except ValueError:
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
        part.unlink(missing_ok=True)
        raise
    if proc.returncode != 0 or not part.exists():
        part.unlink(missing_ok=True)
        raise VerticalError("ffmpeg falló al generar el clip vertical: " + " | ".join(tail)[-600:])
    os.replace(part, out_path)
    if on_progress:
        on_progress(1.0)
    return out_path
