"""Cortinilla de inicio: dónde cae y cómo se desplazan los tiempos que vienen detrás.

Todo en segundos (float) relativos al inicio del clip, salvo que se diga otra cosa. La cortinilla se INSERTA: pausa
el clip, así que lo que viene después se retrasa su duración. Ese desplazamiento se calcula solo aquí (`TimeMap`).
La cortinilla final no mueve nada: va al final del vídeo, tras el último fotograma.
"""
from __future__ import annotations

from dataclasses import dataclass

INTRO_SECONDS = 4.0      # intro del clip antes de la cortinilla de inicio, por defecto
CORTINILLA_SECONDS = 3.6
FINAL_SECONDS = 2.5
END_MARGIN = 1.0         # la cortinilla de inicio no cae en el último segundo del clip: ahí entra la final
SENTENCE_END = (".", "?", "!", "…")


@dataclass(frozen=True)
class TimeMap:
    """Una inserción: a partir de `at` (segundos del clip) el vídeo se detiene `seconds` segundos."""

    at: float | None = None
    seconds: float = 0.0

    def to_out(self, t: float) -> float:
        """Segundo del vídeo final en que suena/se ve el segundo `t` del clip."""
        return t + self.seconds if self.at is not None and t >= self.at else t

    def total(self, clip_duration: float) -> float:
        """Duración del vídeo sin contar la cortinilla final."""
        return clip_duration + (self.seconds if self.at is not None else 0.0)


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith(SENTENCE_END)


def candidates(words: list[dict], silences: list[dict], duration: float, *, sentence_only: bool = True) -> list[float]:
    """Puntos válidos para insertar: el centro de cada silencio que no pisa palabras y cierra una frase completa."""
    out: list[float] = []
    for s in silences:
        lo, hi = max(0.0, s["start"]), min(duration, s["end"])
        if hi - lo <= 0:
            continue
        at = round((lo + hi) / 2, 3)
        if at > duration - END_MARGIN:
            continue
        if any(w["start"] < at < w["end"] for w in words):  # silencio detectado donde la transcripción aún tiene una palabra
            continue
        before = [w for w in words if w["end"] <= at + 1e-6]
        if sentence_only and (not before or not _ends_sentence(before[-1]["text"])):
            continue
        out.append(at)
    return out


def default_position(words: list[dict], silences: list[dict], duration: float, intro: float = INTRO_SECONDS) -> float | None:
    """Primer silencio tras frase completa pasada la intro; si no hay, el primer silencio cualquiera; si no, None."""
    for sentence_only in (True, False):
        for at in candidates(words, silences, duration, sentence_only=sentence_only):
            if at >= intro:
                return at
    return None


def snap_position(at: float, words: list[dict], silences: list[dict], duration: float) -> float | None:
    """Punto válido más cercano a `at` (frase completa antes que silencio cualquiera), o None si no hay ninguno."""
    for sentence_only in (True, False):
        found = candidates(words, silences, duration, sentence_only=sentence_only)
        if found:
            return min(found, key=lambda c: abs(c - at))
    return None


def rebase_silences(silences: list[dict], clip_start: float, clip_end: float) -> list[dict]:
    """Silencios del vídeo entero (segundos absolutos) → los que tocan el clip, relativos a su inicio."""
    return [
        {"start": max(s["start"], clip_start) - clip_start, "end": min(s["end"], clip_end) - clip_start}
        for s in silences if s["end"] > clip_start and s["start"] < clip_end
    ]


def resolve_position(requested: float | None, words: list[dict], silences: list[dict], duration: float) -> float | None:
    """Dónde entra de verdad la cortinilla de inicio: la posición pedida llevada al punto válido más cercano, o la
    automática si no se pidió ninguna. None si el clip no tiene ningún silencio válido."""
    if requested is not None:
        return snap_position(requested, words, silences, duration)
    return default_position(words, silences, duration)
