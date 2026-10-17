"""Silencios por RMS en ventanas de 50 ms (§3.3 del md). Tiempos en segundos.

silences.json: {"threshold_db": -45.0, "window": 0.05, "silences": [{"start": 1.0, "end": 1.5}]}
Sirve para colocar los cortes del clip sin pisar palabras (paso 5) y lo reutiliza el planner de F7.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
WINDOW = 0.05
THRESHOLD_DB = -45.0
MIN_SILENCE = 0.10  # dos ventanas seguidas: con 0,15 s se perdían pausas reales entre frases (≈0,3 s) cuyo nivel roza el umbral


def window_db(samples: np.ndarray) -> np.ndarray:
    """Nivel RMS en dBFS de cada ventana completa de 50 ms (la cola incompleta se descarta)."""
    size = int(SAMPLE_RATE * WINDOW)
    n = len(samples) // size
    if n == 0:
        return np.empty(0)
    frames = samples[: n * size].astype(np.float64).reshape(n, size) / 32768.0
    rms = np.sqrt((frames ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def silences_from_db(db: np.ndarray, threshold: float = THRESHOLD_DB, min_len: float = MIN_SILENCE) -> list[dict]:
    quiet = db < threshold
    out: list[dict] = []
    i, n = 0, len(quiet)
    while i < n:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < n and quiet[j]:
            j += 1
        start, end = round(i * WINDOW, 3), round(j * WINDOW, 3)
        if end - start >= min_len - 1e-9:
            out.append({"start": start, "end": end})
        i = j
    return out


def detect_silences(audio: Path) -> list[dict]:
    """Decodifica con ffmpeg a mono 16 kHz y mide por bloques, para no cargar horas de audio en memoria."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    size = int(SAMPLE_RATE * WINDOW)
    block = size * 2 * 4000  # 4000 ventanas (200 s) por lectura, en bytes
    db_parts: list[np.ndarray] = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        pending = b""
        while True:
            chunk = proc.stdout.read(block)
            if not chunk:
                break
            pending += chunk
            usable = (len(pending) // (size * 2)) * (size * 2)
            if usable:
                db_parts.append(window_db(np.frombuffer(pending[:usable], dtype=np.int16)))
                pending = pending[usable:]
        err = proc.stderr.read().decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg no pudo decodificar el audio: {err[-300:]}")
    db = np.concatenate(db_parts) if db_parts else np.empty(0)
    return silences_from_db(db)


def save_silences(silences: list[dict], path: Path) -> None:
    data = {"threshold_db": THRESHOLD_DB, "window": WINDOW, "silences": silences}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def load_silences(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["silences"]


# --- ajuste de cortes a silencios --------------------------------------------------------------

SNAP_WINDOW = 0.6   # el corte solo se mueve hasta 0,6 s
LEAD_PAD = 0.2      # silencio que se deja antes de la primera palabra / después de la última
EDGE_TOL = 0.05     # tolerancia por la cuantización de 50 ms de las ventanas


def snap_start(t: float, silences: list[dict]) -> float:
    """Mueve el inicio a un silencio que acabe justo antes de la primera palabra, dejando hasta 0,2 s de colchón.

    Nunca avanza el inicio (eso cortaría palabras): solo retrocede, y solo por dentro de un silencio.
    """
    if any(s["start"] <= t and s["end"] > t + EDGE_TOL for s in silences):
        return t  # ya está dentro de un silencio
    before = [s for s in silences if s["end"] <= t + EDGE_TOL and t - s["end"] <= SNAP_WINDOW]
    if not before:
        return t
    s = max(before, key=lambda s: s["end"])
    return round(max(0.0, min(t, max(s["start"], s["end"] - LEAD_PAD))), 3)


def snap_end(t: float, silences: list[dict], total: float | None = None) -> float:
    """Mueve el fin a un silencio que empiece justo después de la última palabra, dejando hasta 0,2 s de colchón."""
    if any(s["start"] < t - EDGE_TOL and s["end"] >= t for s in silences):
        return t
    after = [s for s in silences if s["start"] >= t - EDGE_TOL and s["start"] - t <= SNAP_WINDOW]
    if not after:
        return t
    s = min(after, key=lambda s: s["start"])
    out = max(t, min(s["end"], s["start"] + LEAD_PAD))
    return round(min(out, total) if total is not None else out, 3)


def can_cut_start(t: float, silences: list[dict]) -> bool:
    """¿Un inicio de clip en `t` acaba en silencio? (ya está dentro de uno, o `snap_start` puede retrasarlo a uno)"""
    return any(x["start"] <= t <= x["end"] for x in silences) or snap_start(t, silences) != t


def can_cut_end(t: float, silences: list[dict]) -> bool:
    return any(x["start"] <= t <= x["end"] for x in silences) or snap_end(t, silences) != t
