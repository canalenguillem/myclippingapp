"""Transcripción por palabra con AssemblyAI y diarización. Tiempos en SEGUNDOS (la API los da en ms).

words.json v2:
  {"version": 2, "revision": 1, "language": "es", "text": "...",
   "words":    [{"text", "start", "end", "confidence", "speaker"}],
   "segments": [{"start", "end", "speaker", "text"}]}
`revision` sube en cada edición manual (palabras o speakers) y sirve para detectar escrituras concurrentes.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

import assemblyai as aai

from app.config import get_settings

WORDS_VERSION = 2


class TranscriptionError(RuntimeError):
    pass


def _sec(ms: float) -> float:
    return round(ms / 1000, 3)


def _speaker_at(utterances: list[dict], start: float, end: float) -> str | None:
    """Speaker de la utterance que más se solapa con [start, end]."""
    best, best_overlap = None, 0.0
    for u in utterances:
        overlap = min(end, u["end"]) - max(start, u["start"])
        if overlap > best_overlap:
            best, best_overlap = u["speaker"], overlap
    return best


def _segments_from_words(words: list[dict]) -> list[dict]:
    """Agrupa palabras consecutivas del mismo speaker (respaldo cuando no hay utterances)."""
    segments: list[dict] = []
    for w in words:
        if segments and segments[-1]["speaker"] == w["speaker"]:
            seg = segments[-1]
            seg["end"] = w["end"]
            seg["text"] += " " + w["text"]
        else:
            segments.append({"start": w["start"], "end": w["end"], "speaker": w["speaker"], "text": w["text"]})
    return segments


def build_transcript(tx: Any, language: str = "auto") -> dict:
    """Convierte la respuesta del SDK (palabras y utterances en ms) al words.json v2."""
    raw_words = list(getattr(tx, "words", None) or [])
    if not raw_words:
        raise TranscriptionError("La transcripción salió vacía (¿vídeo sin voz?)")

    utterances = [
        {"start": _sec(u.start), "end": _sec(u.end), "speaker": str(u.speaker), "text": u.text}
        for u in (getattr(tx, "utterances", None) or [])
    ]
    words = []
    for w in raw_words:
        start, end = _sec(w.start), _sec(w.end)
        speaker = getattr(w, "speaker", None) or _speaker_at(utterances, start, end) or "A"
        words.append({"text": w.text, "start": start, "end": end,
                      "confidence": round(w.confidence, 3), "speaker": str(speaker)})

    json_response = getattr(tx, "json_response", None) or {}
    return {
        "version": WORDS_VERSION,
        "revision": 1,
        "language": json_response.get("language_code") or language,
        "text": getattr(tx, "text", None) or " ".join(w["text"] for w in words),
        "words": words,
        "segments": utterances or _segments_from_words(words),
    }


def transcribe_words(audio: Path, language: str = "auto", speakers_expected: int | None = None) -> dict:
    key = get_settings().aai_api_key
    if not key:
        raise TranscriptionError("Falta AAI_API_KEY en .env")
    aai.settings.api_key = key
    options: dict[str, Any] = {"speaker_labels": True}
    if speakers_expected:
        options["speakers_expected"] = speakers_expected
    if language == "auto":
        options["language_detection"] = True
    else:
        options["language_code"] = language
    tx = aai.Transcriber().transcribe(str(audio), config=aai.TranscriptionConfig(**options))
    if tx.status == aai.TranscriptStatus.error:
        raise TranscriptionError(f"AssemblyAI: {tx.error}")
    return build_transcript(tx, language)


def has_speakers(data: dict) -> bool:
    """False en los words.json v1 (importados antes de la diarización): no traen `speaker`."""
    words = data.get("words") or []
    return bool(words) and all("speaker" in w for w in words)


def speaker_labels(data: dict) -> list[str]:
    return sorted({w["speaker"] for w in data.get("words", []) if "speaker" in w})


def save_words(data: dict, path: Path) -> None:
    """Escritura atómica: nunca queda un words.json a medias si el proceso muere."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_words(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RevisionConflict(RuntimeError):
    """El words.json cambió desde que el cliente lo leyó."""


def update_words(path: Path, expected_revision: int, mutate) -> int:
    """Lee, comprueba la revisión, aplica `mutate(data)` y guarda de forma atómica; devuelve la nueva revisión.

    El flock serializa las ediciones: sin él, dos peticiones con la misma revisión podrían pasar la comprobación
    a la vez y la segunda pisaría a la primera.
    """
    with open(path.with_name(path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load_words(path)
        if data.get("revision", 1) != expected_revision:
            raise RevisionConflict(f"revisión {expected_revision}, actual {data.get('revision', 1)}")
        mutate(data)
        data["revision"] = data.get("revision", 1) + 1
        save_words(data, path)
        return data["revision"]


def rebuild_text(data: dict) -> None:
    data["text"] = " ".join(w["text"] for w in data["words"])


def refresh_segments(data: dict, regroup: bool) -> None:
    """Tras editar. `regroup=True` (cambió algún speaker): se reagrupan por turnos de speaker.
    `regroup=False` (solo texto): se conservan los límites de cada segmento y se rehace su texto."""
    if regroup:
        data["segments"] = _segments_from_words([{**w, "speaker": w.get("speaker", "A")} for w in data["words"]])
        return
    for seg in data.get("segments", []):
        seg["text"] = " ".join(w["text"] for w in data["words"] if w["start"] >= seg["start"] - 0.001 and w["end"] <= seg["end"] + 0.001)
