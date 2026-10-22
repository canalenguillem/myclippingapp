"""Pantallas compartidas (un tuit, una web, un documento) dentro del vídeo original: tramos en los que una parte del cuadro es una
página clara con texto, y dónde está. Con eso el render puede mostrar esa región entera en vez de recortar al hablante.

Heurística barata (CPU): a 2 fotogramas por segundo y 320×180, una «página» es una zona con mucha luminosidad y poco color
(fondo blanco o casi blanco). Se busca la franja de columnas contigua más ancha con esa propiedad y, dentro de ella, las filas.
Pendiente: modo oscuro, vídeos incrustados y fondos de color (ahí haría falta OCR; ver status.md)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

FPS = 2.0
W, H = 320, 180
BRIGHT = 185             # luminosidad mínima (0–255) de un píxel «de página»
MAX_SAT = 40             # diferencia máxima entre canales: poco color
COL_FRACTION = 0.55      # una columna es de página si ese porcentaje de sus píxeles lo es
MIN_WIDTH = 0.40         # la franja de página ocupa al menos esta parte del ancho del cuadro (un fondo blanco estrecho no es una pantalla)
MIN_INK = 0.02           # …y su mediana de «tinta» (píxeles oscuros sin color: texto) no baja de esta fracción: una pared blanca no tiene texto
MIN_HEIGHT = 0.45        # …y esta parte del alto
MIN_RUN = 0.03           # una franja de página de menos ancho que esto es ruido
MERGE_GAP = 0.30         # franjas separadas por menos de esto (del ancho) forman una sola pantalla
MIN_SECONDS = 2.0        # un tramo más corto no da tiempo a leerlo
MAX_GAP = 1.0            # huecos de menos de esto dentro de un tramo se rellenan
PAD = 0.01


class ScreenError(RuntimeError):
    pass


def read_frames(video: Path, start: float, end: float, ffmpeg: str = "ffmpeg") -> np.ndarray:
    """Fotogramas RGB (n, H, W, 3) del tramo [start, end] a FPS por segundo."""
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video), "-an",
           "-vf", f"fps={FPS},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScreenError(f"No se pudo leer el vídeo: {exc}") from exc
    if proc.returncode != 0:
        raise ScreenError(f"ffmpeg falló al leer el vídeo: {proc.stderr.decode(errors='replace')[-200:]}")
    data = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = data.size // (W * H * 3)
    return data[: n * W * H * 3].reshape(n, H, W, 3)


def page_box(frame: np.ndarray) -> tuple[float, float, float, float] | None:
    """(x, y, w, h) en fracciones del cuadro de la región de «página» más ancha de un fotograma, o None."""
    rgb = frame.astype(np.int16)
    lum = rgb.mean(axis=2)
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    mask = (lum >= BRIGHT) & (sat <= MAX_SAT)
    cols = mask.mean(axis=0) >= COL_FRACTION
    runs: list[tuple[int, int]] = []
    run_start = None
    for x in range(W + 1):
        on = x < W and bool(cols[x])
        if on and run_start is None:
            run_start = x
        elif not on and run_start is not None:
            if (x - run_start) / W >= MIN_RUN:
                runs.append((run_start, x))
            run_start = None
    if not runs:
        return None
    # la franja más ancha, ampliada con las vecinas separadas por poco (un vídeo oscuro incrustado entre dos márgenes blancos)
    seed = max(range(len(runs)), key=lambda i: runs[i][1] - runs[i][0])
    lo = hi = seed
    while lo > 0 and runs[lo][0] - runs[lo - 1][1] <= MERGE_GAP * W:
        lo -= 1
    while hi < len(runs) - 1 and runs[hi + 1][0] - runs[hi][1] <= MERGE_GAP * W:
        hi += 1
    group = runs[lo:hi + 1]
    x0, x1 = group[0][0], group[-1][1]
    if (x1 - x0) / W < MIN_WIDTH:
        return None
    page_cols = np.zeros(W, dtype=bool)
    for a_, b_ in group:
        page_cols[a_:b_] = True
    rows = mask[:, page_cols].mean(axis=1) >= 0.35
    ys = np.flatnonzero(rows)
    if ys.size == 0 or (ys[-1] - ys[0] + 1) / H < MIN_HEIGHT:
        return None
    return x0 / W, ys[0] / H, (x1 - x0) / W, (ys[-1] - ys[0] + 1) / H


def segments_from_boxes(boxes: list[tuple[float, float, float, float] | None]) -> list[dict]:
    """Agrupa los fotogramas seguidos con página (rellenando huecos cortos) en tramos de ≥ MIN_SECONDS. Tiempos relativos al inicio."""
    gap = int(MAX_GAP * FPS)
    flags = [b is not None for b in boxes]
    i, runs = 0, []
    while i < len(flags):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(flags) and (flags[j + 1] or any(flags[j + 1: j + 2 + gap])):
            j += 1
        while j > i and not flags[j]:
            j -= 1
        runs.append((i, j))
        i = j + 1
    out = []
    for a, b in runs:
        if (b - a + 1) / FPS < MIN_SECONDS:
            continue
        found = [boxes[k] for k in range(a, b + 1) if boxes[k] is not None]
        x, y, w, h = (float(np.median([f[n] for f in found])) for n in range(4))
        x, y = max(0.0, x - PAD), max(0.0, y - PAD)
        w, h = min(1.0 - x, w + 2 * PAD), min(1.0 - y, h + 2 * PAD)
        out.append({"start": round(a / FPS, 2), "end": round((b + 1) / FPS, 2), "x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
    return out


def ink_fraction(frame: np.ndarray, box: tuple[float, float, float, float]) -> float:
    """Fracción de píxeles «de texto» (oscuros y sin color) dentro de la región: una página con texto la tiene alta; un fondo liso, ~0."""
    x, y, w, h = box
    sub = frame[int(y * H):max(int(y * H) + 1, int((y + h) * H)), int(x * W):max(int(x * W) + 1, int((x + w) * W))].astype(np.int16)
    lum = sub.mean(axis=2)
    sat = sub.max(axis=2) - sub.min(axis=2)
    return float(((lum < 120) & (sat < 60)).mean())


def detect(video: Path, start: float, end: float, *, ffmpeg: str = "ffmpeg") -> list[dict]:
    """Tramos con una pantalla compartida entre `start` y `end` (segundos del vídeo original). Cada uno: {start, end, x, y, w, h}
    con start/end absolutos en segundos y la caja en fracciones del cuadro."""
    frames = read_frames(video, start, end, ffmpeg)
    boxes = [page_box(f) for f in frames]
    out = []
    for seg in segments_from_boxes(boxes):
        a, b = int(seg["start"] * FPS), min(len(frames), int(seg["end"] * FPS))
        box = (seg["x"], seg["y"], seg["w"], seg["h"])
        if not b > a or float(np.median([ink_fraction(frames[k], box) for k in range(a, b)])) < MIN_INK:
            continue                                   # sin texto: un fondo blanco, no una pantalla
        out.append({**seg, "start": round(start + seg["start"], 2), "end": round(min(end, start + seg["end"]), 2)})
    return out
