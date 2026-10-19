"""`Project.speakers`: ficha de cada interlocutor. La clave es la etiqueta de AssemblyAI ("A", "B"…)."""
from __future__ import annotations

CAPTION_STYLES = ("sans_upper", "serif_italic")


def default_speaker() -> dict:
    return {"name": "", "role": "", "caption_style": "sans_upper", "is_source": False, "focus_x": 0.5}


def merge_speakers(existing: dict | None, labels: list[str]) -> dict:
    """Una ficha por etiqueta presente. Conserva lo que el usuario ya rellenó y no borra
    fichas de etiquetas que desaparecen (re-transcribir puede cambiar la diarización)."""
    merged = {k: dict(v) for k, v in (existing or {}).items()}
    for label in labels:
        merged.setdefault(label, default_speaker())
    return merged
