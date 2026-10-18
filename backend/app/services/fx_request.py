"""Construye la petición del servicio de render (fx_worker) a partir de un clip. Funciones puras, sin E/S."""
from __future__ import annotations

import re

SPEAKER_LABEL = re.compile(r"^[A-Za-z0-9]{1,8}$")
HOOK_SECONDS = 2.2
MAX_WORDS = 5000
QUALITY = {"draft": "draft", "final": "standard"}  # calidad del motor de render para cada tipo de render


def clip_words(words: list[dict], start: float, end: float) -> list[dict]:
    """Palabras del clip con tiempos RELATIVOS a su inicio (t = 0), en segundos."""
    duration = end - start
    out: list[dict] = []
    for w in words:
        if w["start"] < start - 0.05 or w["end"] > end + 0.05:
            continue
        text = str(w["text"]).strip()[:80]
        if not text:
            continue
        s = round(max(0.0, w["start"] - start), 3)
        e = round(min(duration, max(s, w["end"] - start)), 3)
        item = {"text": text, "start": s, "end": e}
        label = w.get("speaker")
        if label and SPEAKER_LABEL.match(str(label)):
            item["speaker"] = str(label)
        out.append(item)
    return out[:MAX_WORDS]


DEFAULT_COLOR = "#DA2E09"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _clamp(value, lo: float, hi: float, default: float) -> float:
    try:
        return round(min(hi, max(lo, float(value))), 3)
    except (TypeError, ValueError):
        return default


def _text(value, limit: int, default: str = "") -> str:
    return str(value).strip()[:limit] if value not in (None, "") else default


def _color(config: dict, colors: dict) -> str:
    for candidate in (config.get("color"), (colors or {}).get("primary")):
        if isinstance(candidate, str) and _HEX.match(candidate):
            return candidate.upper()
    return DEFAULT_COLOR


def cortinilla_params(config: dict | None, colors: dict | None, *, at: float, orbit: str | None) -> dict:
    """Cortinilla de inicio para el servicio. `config` es `BrandTemplate.cortinilla`; los valores se acotan al contrato."""
    config = config or {}
    out = {"at": round(at, 3), "duration": _clamp(config.get("duration"), 1.0, 10.0, 3.6), "color": _color(config, colors or {}),
           "title": _text(config.get("title"), 40), "kicker": _text(config.get("kicker"), 60)}
    if orbit:
        out["orbit"] = orbit
    return out


def outro_params(config: dict | None, colors: dict | None) -> dict:
    """Cortinilla final (siempre). Sin plantilla sale con los valores por defecto: color de marca y botones."""
    config = config or {}
    return {"duration": _clamp(config.get("outro_duration"), 1.0, 10.0, 2.5), "color": _color(config, colors or {}),
            "handle": _text(config.get("handle"), 40), "text": _text(config.get("outro_text"), 80),
            "like": _text(config.get("like"), 20, "ME GUSTA"), "subscribe": _text(config.get("subscribe"), 20, "SUSCRÍBETE")}


def build_fx_request(
    *,
    video: str,
    output: str,
    quality: str,
    duration: float,
    top_ratio: float,
    words: list[dict],
    speakers: dict,
    hook: str,
    preset: str,
    band: dict | None,
    cortinilla: dict | None = None,
    outro: dict | None = None,
    sfx: bool = True,
) -> dict:
    """`video` y `output` son rutas relativas a MEDIA_DIR. Los speakers solo llevan los campos del contrato."""
    request: dict = {
        "video": video,
        "output": output,
        "quality": QUALITY[quality],
        "fps": 30,
        "duration": round(duration, 3),
        "layout": {"mode": "split", "top_ratio": round(top_ratio, 3)},
        "words": words,
        "speakers": {
            label: {
                "name": str(card.get("name", ""))[:80],
                "role": str(card.get("role", ""))[:120],
                "caption_style": card.get("caption_style", "sans_upper"),
                "is_source": bool(card.get("is_source", False)),
            }
            for label, card in (speakers or {}).items()
            if SPEAKER_LABEL.match(str(label))
        },
        "preset": preset,
        "sfx": bool(sfx),
    }
    if cortinilla:
        request["cortinilla"] = cortinilla
    if outro:
        request["outro"] = outro
    hook = (hook or "").strip()
    if hook:
        request["hook"] = {"text": hook[:120], "duration": HOOK_SECONDS}
    if band:
        request["band"] = {"y0": int(band["y0"]), "y1": int(band["y1"])}
    return request
