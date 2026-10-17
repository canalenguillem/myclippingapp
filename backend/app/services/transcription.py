"""Transcripción por palabra con AssemblyAI. Tiempos en SEGUNDOS (la API los da en ms)."""
from __future__ import annotations

import json
from pathlib import Path

import assemblyai as aai

from app.config import get_settings


class TranscriptionError(RuntimeError):
    pass


def transcribe_words(audio: Path, language: str = "auto") -> dict:
    """Devuelve {"language", "text", "words": [{"text","start","end","confidence"}]}."""
    key = get_settings().aai_api_key
    if not key:
        raise TranscriptionError("Falta AAI_API_KEY en .env")
    aai.settings.api_key = key
    if language == "auto":
        cfg = aai.TranscriptionConfig(language_detection=True)
    else:
        cfg = aai.TranscriptionConfig(language_code=language)
    tx = aai.Transcriber().transcribe(str(audio), config=cfg)
    if tx.status == aai.TranscriptStatus.error:
        raise TranscriptionError(f"AssemblyAI: {tx.error}")
    words = [
        {"text": w.text, "start": round(w.start / 1000, 3), "end": round(w.end / 1000, 3),
         "confidence": round(w.confidence, 3)}
        for w in (tx.words or [])
    ]
    if not words:
        raise TranscriptionError("La transcripción salió vacía (¿vídeo sin voz?)")
    lang = (getattr(tx, "json_response", None) or {}).get("language_code") or language
    return {"language": lang, "text": tx.text or "", "words": words}


def save_words(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_words(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
