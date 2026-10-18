"""Traduce una frase libre («el guante da un golpe y explota») a las piezas que el motor de render sabe hacer.

No genera código de animación: solo ELIGE entre entradas, efectos y estilos conocidos (el render sigue siendo
determinista). Primero un traductor por palabras clave en español, que funciona sin red; si no reconoce nada y hay clave de
OpenAI, se le pregunta al modelo con un JSON cerrado. Lo que devuelva el modelo se valida contra la lista de piezas.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable

ENTRIES = {"pop", "punch", "slide_left", "slide_right", "slide_top", "drop"}
EFFECTS = {"pop", "vaporize", "break", "explode"}
STYLES = {"original", "card", "silhouette", "red"}

LABELS = {
    "punch": "entra de un golpe", "drop": "cae desde arriba", "slide_left": "entra por la izquierda", "slide_right": "entra por la derecha",
    "slide_top": "baja desde arriba", "vaporize": "se vaporiza", "break": "se parte en dos", "explode": "explota",
    "card": "tarjeta de papel", "silhouette": "silueta", "red": "rojo de marca",
}

_ENTRY = [  # el orden manda: «un golpe desde la izquierda» es un golpe
    ("punch", r"golpe|golpea|golpear|golpeando|punetazo|puno\b|pega\b|pegar|asesta|embiste|puñetazo"),
    ("drop", r"\bcae\b|caer|cayendo|se deja caer|aterriza|se desploma"),
    ("slide_left", r"(desde|por|de) la izquierda|de izquierda"),
    ("slide_right", r"(desde|por|de) la derecha|de derecha"),
    ("slide_top", r"desde arriba|baja desde|por arriba"),
]
_EFFECT = [
    ("explode", r"explot|explosi|estall|revient|bomba|boom|vuela en pedazos|salta por los aires"),
    ("vaporize", r"vaporiz|desintegr|se deshace|polvo|se esfuma|evapor|desvanece en"),
    ("break", r"rompe|rompi|se parte|parte en dos|partir|quiebra|trocea|se hace pedazos"),
]
_STYLE = [("card", r"tarjeta|papel"), ("silhouette", r"silueta|sombra"), ("red", r"\brojo\b|en rojo")]


def _norm(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def _first(patterns: list[tuple[str, str]], text: str) -> str | None:
    for name, pattern in patterns:
        if re.search(_norm(pattern), text):
            return name
    return None


def understood(result: dict) -> str:
    parts = [LABELS[k] for k in (result.get("entry"), result.get("effect"), result.get("style")) if k in LABELS]
    return " · ".join(parts) if parts else "nada reconocido"


def from_keywords(text: str) -> dict:
    t = _norm(text)
    return {"entry": _first(_ENTRY, t), "effect": _first(_EFFECT, t), "style": _first(_STYLE, t)}


PROMPT = (
    "Traduce la frase del usuario a piezas de animación para un gráfico de vídeo. Responde SOLO un JSON con las claves "
    '"entry" (uno de: pop, punch, slide_left, slide_right, slide_top, drop), "effect" (uno de: pop, vaporize, break, explode) y '
    '"style" (uno de: original, card, silhouette, red). Usa null en lo que la frase no diga. punch = entra golpeando; drop = cae; '
    "vaporize = se deshace en polvo; break = se parte en dos; explode = explota en pedazos."
)


def default_llm(text: str) -> dict | None:
    """Pregunta al modelo de OpenAI. None si no hay clave o falla (el llamante cae al resultado de las palabras clave)."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, timeout=20)
        response = client.chat.completions.create(
            model=settings.openai_clip_model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": text[:300]}],
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception:  # noqa: BLE001 - la red o el modelo pueden fallar de muchas formas; el usuario sigue con los selectores
        return None


def _clean(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    pick = lambda key, allowed: raw.get(key) if raw.get(key) in allowed else None  # noqa: E731
    return {"entry": pick("entry", ENTRIES), "effect": pick("effect", EFFECTS), "style": pick("style", STYLES)}


def interpret(text: str, *, llm: Callable[[str], dict | None] | None = default_llm) -> dict:
    """{entry, effect, style, source, understood}. Los valores son siempre piezas válidas o None."""
    text = (text or "").strip()
    result = {**from_keywords(text), "source": "keywords"}
    if text and not any(result[k] for k in ("entry", "effect", "style")) and llm is not None:
        guess = _clean(llm(text))
        if any(guess.values()):
            result = {**guess, "source": "llm"}
    if not any(result.get(k) for k in ("entry", "effect", "style")):
        result["source"] = "none"
    result["understood"] = understood(result)
    return result
