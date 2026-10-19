"""Revisión automática de un render (F9): comprobaciones baratas sobre el vídeo ya hecho y el plan que se mandó al motor.

Cada comprobación devuelve {"id", "level": "ok" | "warn" | "error", "message"}. Nunca tumban el render: solo informan.
Pendiente (necesita visión por ordenador): gráfico sobre una cara, estilo de subtítulo que no corresponde al hablante."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

DURATION_TOLERANCE = 0.35   # s de diferencia con lo esperado (clip + cortinillas)
PEAK_LIMIT_DB = -0.1        # por encima, el audio satura (pico > 0,98)
SILENT_DB = -50.0           # volumen medio por debajo del cual se considera sin audio
BLACK_SECONDS = 1.0         # un tramo de pantalla negra más largo que esto es un fallo
MIN_VISIBLE = 0.8           # un texto o gráfico visible menos que esto no se lee
BIG = {"keyword", "image", "counter", "strike", "lower_third"}


def _run(args: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return proc.stderr + proc.stdout


def probe_duration(video: Path) -> float | None:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)])
    try:
        return float(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def audio_levels(video: Path) -> tuple[float | None, float | None]:
    """(volumen medio, pico) en dB, o (None, None) si no hay audio."""
    out = _run(["ffmpeg", "-v", "info", "-nostats", "-i", str(video), "-vn", "-af", "volumedetect", "-f", "null", "-"])
    mean, peak = re.search(r"mean_volume:\s*(-?[\d.]+)\s*dB", out), re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", out)
    return (float(mean.group(1)), float(peak.group(1))) if mean and peak else (None, None)


def black_segments(video: Path) -> list[tuple[float, float]]:
    out = _run(["ffmpeg", "-v", "info", "-nostats", "-i", str(video), "-an", "-vf", "blackdetect=d=0.5:pic_th=0.98", "-f", "null", "-"], timeout=300)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", out)]


def check(video: Path, *, expected_duration: float, beats: list[dict], dropped: list[dict] | None = None) -> list[dict]:
    """`beats`: los gráficos ya programados (con `at`, `lead`, `duration`, `type`), en segundos del clip."""
    results: list[dict] = []

    def add(id_: str, level: str, message: str) -> None:
        results.append({"id": id_, "level": level, "message": message})

    actual = probe_duration(video)
    if actual is None:
        add("duration", "error", "No se pudo leer la duración del vídeo")
    elif abs(actual - expected_duration) > DURATION_TOLERANCE:
        add("duration", "error", f"Dura {actual:.1f} s y debería durar {expected_duration:.1f} s (clip + cortinillas)")
    else:
        add("duration", "ok", f"Duración correcta ({actual:.1f} s)")

    mean, peak = audio_levels(video)
    if mean is None:
        add("audio", "error", "El vídeo no tiene audio")
    elif mean < SILENT_DB:
        add("audio", "error", f"Audio casi mudo (volumen medio {mean:.0f} dB)")
    elif peak > PEAK_LIMIT_DB:
        add("audio", "warn", f"El audio llega a {peak:.1f} dB: puede saturar")
    else:
        add("audio", "ok", f"Audio correcto (pico {peak:.1f} dB)")

    long_black = [(a, b) for a, b in black_segments(video) if b - a >= BLACK_SECONDS]
    if long_black:
        add("black", "error", "Pantalla negra de " + ", ".join(f"{a:.1f}–{b:.1f} s" for a, b in long_black[:3]))
    else:
        add("black", "ok", "Sin tramos de pantalla negra")

    windows = [(max(0.0, b["at"] - b.get("lead", 0.0)), max(0.0, b["at"] - b.get("lead", 0.0)) + b.get("duration", 0.0), b) for b in beats]
    short = [b for s, e, b in windows if e - s < MIN_VISIBLE]
    if short:
        add("visible", "warn", f"{len(short)} gráfico(s) se ven menos de {MIN_VISIBLE} s: no da tiempo a leerlos")
    clash = [(a[2], b[2]) for i, a in enumerate(windows) for b in windows[i + 1:]
             if a[2]["type"] in BIG and b[2]["type"] in BIG and a[0] < b[1] and b[0] < a[1]]
    if clash:
        add("overlap", "error", f"{len(clash)} pareja(s) de gráficos grandes a la vez (a {clash[0][0]['at']:.1f} s)")
    if not short and not clash:
        add("graphics", "ok", "Gráficos sin solapes y con tiempo de lectura")
    if dropped:
        add("dropped", "warn", f"{len(dropped)} gráfico(s) descartado(s) por el programador (no entran): revisa la lista de gráficos")
    return results


def worst(results: list[dict]) -> str:
    levels = {r["level"] for r in results}
    return "error" if "error" in levels else "warn" if "warn" in levels else "ok"
