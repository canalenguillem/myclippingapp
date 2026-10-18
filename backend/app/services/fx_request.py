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
    }
    hook = (hook or "").strip()
    if hook:
        request["hook"] = {"text": hook[:120], "duration": HOOK_SECONDS}
    if band:
        request["band"] = {"y0": int(band["y0"]), "y1": int(band["y1"])}
    return request
