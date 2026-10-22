"""Seguimiento por plano. Un clip de una tele o de una llamada cambia de composición con cada corte: lo que vale para un plano
(dónde está la cara) no vale para el siguiente. Aquí se parte el clip en planos (cortes de ffmpeg), se detectan las caras de cada
uno (CPU, `pipeline/faces.py`) y se decide qué hacer con el recorte vertical:

- «face»: hay una cara principal (o varias que caben juntas en el recorte) → el recorte se centra en ella durante el plano.
- «wide»: no hay ninguna cara grande, o las caras importantes no caben juntas y el hablante no es ninguna de ellas (plano general
  de un plató con pantallas) → se enseña el cuadro entero (mismo mecanismo que las pantallas compartidas).
- «snap»: varias caras grandes que no caben (webcams de una llamada) y el hablante del worker de ASD es una de ellas → se le sigue, pegándose a la cara real más cercana.
- «keep»: sin datos suficientes → se deja el seguimiento normal."""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

from . import faces as faces_mod

FPS = 2.0
WIDTH = 960               # ancho al que se analizan los fotogramas
MIN_FACE = 0.08           # una cara de menos de esta fracción del alto del cuadro no cuenta (miniaturas, pantallas lejanas)
PROMINENT = 0.5           # «importante» = al menos esta fracción de la cara más grande
SNAP = 0.25               # el hablante del ASD se pega a la cara grande más cercana si está a menos de esto (del ancho del cuadro)
SPEAKER_SIZE = 0.8        # el hablante del ASD solo cuenta si su cara es al menos esta fracción de la más grande (no una cara pequeña de fondo)
FIT = 0.92                # las caras importantes caben si su extensión es ≤ FIT × el ancho del recorte
MIN_SHOT = 0.8            # un plano más corto que esto se une al anterior
SCENE = 0.2               # umbral de corte de ffmpeg


class ShotError(RuntimeError):
    pass


def window_fraction(width: int, height: int, top_ratio: float) -> float:
    """Fracción del ancho del cuadro que cabe en la parte de arriba del vertical (recorte 9:16 de 1080 × alto de la parte de arriba)."""
    top_h = int(1920 * top_ratio) // 2 * 2
    return min(1.0, 1080.0 / (top_h * width / height))


def cuts(video: Path, start: float, end: float, ffmpeg: str = "ffmpeg") -> list[float]:
    """Instantes de corte de plano, relativos a `start`."""
    cmd = [ffmpeg, "-v", "info", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video), "-an",
           "-vf", f"select=gt(scene\\,{SCENE}),showinfo", "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300).stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShotError(f"No se pudieron buscar los cortes: {exc}") from exc
    return sorted(float(t) for t in re.findall(r"pts_time:([0-9.]+)", out))


def _probe(video: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, timeout=60).stdout.strip().split(",")
    try:
        return int(out[0]), int(out[1])
    except (ValueError, IndexError) as exc:
        raise ShotError("No se pudo leer el tamaño del vídeo") from exc


def frames(video: Path, start: float, end: float, ffmpeg: str = "ffmpeg") -> Iterator[tuple[float, np.ndarray]]:
    """(instante relativo, fotograma RGB) a FPS por segundo, de uno en uno (sin cargar todo en memoria)."""
    w, h = _probe(video)
    out_w, out_h = WIDTH, int(round(h * WIDTH / w / 2) * 2)
    cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video), "-an",
           "-vf", f"fps={FPS},scale={out_w}:{out_h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = out_w * out_h * 3
    try:
        k = 0
        while True:
            raw = proc.stdout.read(size)
            if len(raw) < size:
                break
            yield k / FPS, np.frombuffer(raw, dtype=np.uint8).reshape(out_h, out_w, 3)
            k += 1
    finally:
        proc.kill()
        proc.wait()


def classify(found: list[dict], window: float) -> tuple[str, dict]:
    """Decisión de un fotograma a partir de sus caras. -> ("wide"|"face"|"multi", datos)."""
    relevant = [f for f in found if f["h"] >= MIN_FACE]
    if not relevant:
        return "wide", {}
    top = max(f["h"] for f in relevant)
    prominent = [f for f in relevant if f["h"] >= PROMINENT * top]
    left = min(f["x"] for f in prominent)
    right = max(f["x"] + f["w"] for f in prominent)
    if right - left <= FIT * window:
        return "face", {"x": (left + right) / 2}
    return "multi", {"boxes": [(f["x"], f["x"] + f["w"], f["h"] / top) for f in prominent]}


def _clusters(values: list[float], gap: float = 0.08) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= gap:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def decide(samples: list[tuple[str, dict]], asd_xs: list[float]) -> dict:
    """Decisión de un plano a partir de las de sus fotogramas (voto por mayoría) y de las posiciones del hablante del ASD en él."""
    if not samples:
        return {"kind": "keep"}
    kind = Counter(k for k, _ in samples).most_common(1)[0][0]
    chosen = [d for k, d in samples if k == kind]
    if kind == "wide":
        return {"kind": "wide"}
    if kind == "face":
        return {"kind": "face", "x": round(float(np.median([d["x"] for d in chosen])), 4)}
    # varias caras que no caben juntas: si el hablante del ASD es una de las caras GRANDES (webcams de una llamada), se le sigue
    # pegándose a la cara real más cercana; si es una cara pequeña de fondo (plató con pantallas), se enseña el plano entero
    centers_per_frame = [[(a + b) / 2 for a, b, rel in d["boxes"] if rel >= SPEAKER_SIZE] for d in chosen]
    flat = [c for cs in centers_per_frame for c in cs]
    centers = [round(float(np.median(cl)), 4) for cl in _clusters(flat) if len(cl) * 2 >= len(chosen)]
    if not centers or not asd_xs:
        return {"kind": "wide"}
    ok = sum(1 for x in asd_xs if min(abs(x - c) for c in centers) <= SNAP)
    return {"kind": "snap", "centers": centers} if ok >= 0.8 * len(asd_xs) else {"kind": "wide"}


def plan(video: Path, start: float, end: float, *, window: float, asd_at: Callable[[float], float | None] | None = None,
         detect: Callable[[np.ndarray], list[dict]] | None = None, ffmpeg: str = "ffmpeg") -> list[dict]:
    """Planos del clip [start, end] con su decisión: [{start, end, kind, x?}], tiempos relativos a `start`, contiguos."""
    detect = detect or faces_mod.detect
    duration = end - start
    bounds = [0.0]
    for c in cuts(video, start, end, ffmpeg):
        if c - bounds[-1] >= MIN_SHOT and duration - c >= MIN_SHOT:
            bounds.append(c)
    bounds.append(duration)
    per_shot: list[list[tuple[str, dict]]] = [[] for _ in range(len(bounds) - 1)]
    fallback: list[list[tuple[str, dict]]] = [[] for _ in range(len(bounds) - 1)]
    for t, frame in frames(video, start, end, ffmpeg):
        i = next((k for k in range(len(bounds) - 1) if bounds[k] <= t < bounds[k + 1]), len(bounds) - 2)
        verdict = classify(detect(frame), window)
        fallback[i].append(verdict)
        if bounds[i] + 0.15 <= t <= bounds[i + 1] - 0.15:          # los fotogramas pegados al corte pueden ser mezcla de dos planos
            per_shot[i].append(verdict)
    out = []
    for i in range(len(bounds) - 1):
        steps = max(1, int((bounds[i + 1] - bounds[i]) / 0.5))
        asd_xs = [x for k in range(steps) if asd_at and (x := asd_at(bounds[i] + (k + 0.5) * (bounds[i + 1] - bounds[i]) / steps)) is not None]
        out.append({"start": round(bounds[i], 3), "end": round(bounds[i + 1], 3), **decide(per_shot[i] or fallback[i], asd_xs)})
    return out
