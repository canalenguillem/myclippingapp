"""Análisis del clip vertical: ¿lleva subtítulos quemados en la mitad de arriba?

Si los lleva, la banda de papel debe cubrir esas filas al 100 %; si no, va centrada en el corte. Se mira solo la
zona del plano corto (donde actúa la banda). Una fila «parece de subtítulo» si tiene píxeles de texto (blanco puro o
verde o amarillo) que aparecen y desaparecen con frecuencia: un fondo blanco estático, un logo fijo o un objeto que se mueve
no cumplen las dos condiciones a la vez.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

W, H = 270, 480          # fotogramas reducidos a 1/4 de 1080x1920
SCALE = 4
MAX_FRAMES = 150
MIN_FRAMES = 10
PRESENT = 0.02           # fracción de la fila con píxeles de texto para contar como «hay texto»
MIN_PERSISTENCE = 0.40   # en al menos el 40 % de los fotogramas (con 0,25 un brillo de la frente en un clip con zoom pasaba por texto)
MIN_CHANGE = 0.006       # cambio medio entre fotogramas consecutivos
MAX_GAP_ROWS = 2         # huecos entre filas candidatas que se unen (8 px reales)
MIN_ROWS, MAX_ROWS = 2, 30  # 8–120 px reales
LOWER_PART = 0.45        # los subtítulos quemados van en la parte BAJA del plano: no se buscan en el 45 % de arriba (ojos, frente)


class AnalysisError(RuntimeError):
    pass


def _frames(video: Path, duration: float, ffmpeg: str) -> np.ndarray:
    fps = max(0.5, min(5.0, MAX_FRAMES / max(duration, 1.0)))
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(video), "-vf", f"fps={fps:.3f},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AnalysisError(f"ffmpeg no pudo decodificar el clip para analizarlo: {proc.stderr.decode(errors='replace')[-300:]}")
    size = W * H * 3
    n = len(proc.stdout) // size
    return np.frombuffer(proc.stdout[: n * size], dtype=np.uint8).reshape(n, H, W, 3)


def detect_in_frames(frames: np.ndarray, top_ratio: float) -> dict | None:
    """`frames`: (n, 480, 270, 3) RGB. Devuelve {y0, y1, confidence} en px del lienzo 1080x1920, o None."""
    if len(frames) < MIN_FRAMES:
        return None
    top_rows = int(H * top_ratio)
    region = frames[:, :top_rows].astype(np.int16)
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    white = np.minimum(np.minimum(r, g), b) > 235
    green = (g > 200) & (r < 90) & (b < 90)
    yellow = (r > 200) & (g > 160) & (b < 110) & (r - b > 110)
    row_frac = (white | green | yellow).mean(axis=2)                      # (n, top_rows)
    persistence = (row_frac > PRESENT).mean(axis=0)
    change = np.abs(np.diff(row_frac, axis=0)).mean(axis=0)
    candidate = (persistence >= MIN_PERSISTENCE) & (change >= MIN_CHANGE)
    candidate[: int(top_rows * LOWER_PART)] = False      # la banda nunca se mueve a la cara por culpa de un brillo que cambia

    runs: list[tuple[int, int]] = []
    start = last = None
    for y in np.flatnonzero(candidate):
        if start is None:
            start = last = int(y)
        elif y - last <= MAX_GAP_ROWS + 1:
            last = int(y)
        else:
            runs.append((start, last))
            start = last = int(y)
    if start is not None:
        runs.append((start, last))
    runs = [(a, c) for a, c in runs if MIN_ROWS <= c - a + 1 <= MAX_ROWS]
    if not runs:
        return None
    a, c = max(runs, key=lambda run: float((persistence[run[0]: run[1] + 1] * change[run[0]: run[1] + 1]).sum()))
    return {
        "y0": int(a * SCALE),
        "y1": int(min(top_rows, c + 1) * SCALE),
        "confidence": round(float(persistence[a: c + 1].mean()), 2),
    }


def detect_burned_subtitles(video: Path, *, top_ratio: float, duration: float, ffmpeg: str = "ffmpeg") -> dict | None:
    return detect_in_frames(_frames(Path(video), duration, ffmpeg), top_ratio)
