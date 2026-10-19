"""Planificador de gráficos: propone animaciones (emojis, tarjetas, imágenes de la librería) a partir de la transcripción.

El modelo solo ELIGE: la palabra gancho (por su índice, nunca un tiempo), el motivo y sus parámetros. Los tiempos los saca el código
de la palabra elegida, y `graphics_schedule` impone después las reglas de sincronía. Sin modelo hay un plan B con un diccionario
de palabras → emoji. Lo propuesto es siempre revisable en la línea de tiempo del editor.

Política de contenido: emojis de cosas, cifras e instituciones; nunca de colectivos (etnia, nacionalidad, religión): se filtran
los tonos de piel y las banderas salvo 🇪🇸, y el prompt lo prohíbe.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from app.services import graphics_schedule

MOTIFS = ("emoji", "keyword", "image", "counter", "strike")
EFFECTS = {"emoji": {"pop", "vaporize", "explode"}, "image": {"pop", "vaporize", "break", "explode"}}
ENTRIES = {"pop", "punch", "slide_left", "slide_right", "slide_top", "drop"}
STYLES = {"original", "card", "silhouette", "red"}
SECONDS_PER_BEAT = 6.0          # ≈ un gráfico cada 5–6 s (el programador exige ≥ 4 s entre grandes)
ALLOWED_FLAGS = {"🇪🇸"}


@dataclass
class Plan:
    beats: list[dict] = field(default_factory=list)
    source: str = "model"
    notes: list[str] = field(default_factory=list)


def max_beats(duration: float) -> int:
    return max(1, int(duration / SECONDS_PER_BEAT))


def _norm(word: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", text)


def emoji_allowed(emoji: str) -> bool:
    """Sin tonos de piel ni banderas (salvo la de España): no se dibujan colectivos."""
    if any(0x1F3FB <= ord(c) <= 0x1F3FF for c in emoji):
        return False
    indicators = [c for c in emoji if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    return not indicators or emoji in ALLOWED_FLAGS


# --- plan B: diccionario ------------------------------------------------------------------------------

# (prefijo de la palabra normalizada, emoji, efecto). Solo cosas, cifras e instituciones.
DICTIONARY: list[tuple[str, str, str]] = [
    ("pensionista", "🧓", "pop"), ("jubilad", "🧓", "pop"), ("jubila", "🧓", "pop"), ("pension", "🧓", "pop"),
    ("deuda", "💸", "pop"), ("deficit", "💸", "pop"), ("impuesto", "💸", "pop"),
    ("dinero", "💰", "pop"), ("euros", "💰", "pop"), ("salario", "💰", "pop"), ("sueldo", "💰", "pop"),
    ("peta", "💥", "explode"), ("colaps", "💥", "explode"), ("quiebra", "💥", "explode"), ("hundi", "💥", "explode"), ("bomba", "💣", "explode"),
    ("gobierno", "🏛️", "pop"), ("congreso", "🏛️", "pop"), ("ministr", "🏛️", "pop"),
    ("elecci", "🗳️", "pop"), ("votos", "🗳️", "pop"), ("votar", "🗳️", "pop"), ("urna", "🗳️", "pop"),
    ("informe", "📄", "pop"), ("estudio", "📄", "pop"), ("ley", "📜", "pop"),
    ("trabaj", "💼", "pop"), ("empleo", "💼", "pop"), ("paro", "📉", "pop"), ("crisis", "📉", "pop"), ("inflacion", "📈", "pop"),
    ("mentira", "🤥", "pop"), ("peligro", "🚨", "pop"), ("alerta", "🚨", "pop"), ("urgente", "🚨", "pop"),
    ("fuego", "🔥", "pop"), ("guerra", "💣", "pop"), ("casa", "🏠", "pop"), ("vivienda", "🏠", "pop"), ("alquiler", "🏠", "pop"),
]


def from_dictionary(words: list[dict], duration: float, *, limit: int | None = None) -> list[dict]:
    """Un emoji por concepto (el primero que aparece), con separación mínima, hasta `limit` gráficos."""
    limit = limit or max_beats(duration)
    out: list[dict] = []
    used: set[str] = set()
    last_at = -99.0
    for w in words:
        key = _norm(w["text"])
        if len(key) < 4 or w["start"] - last_at < 4.5:
            continue
        for prefix, emoji, effect in DICTIONARY:
            if key.startswith(prefix) and emoji not in used:
                out.append({"type": "emoji", "at": round(w["start"], 3), "emoji": emoji, **({"effect": effect} if effect != "pop" else {}),
                            "reason": f"«{w['text']}»"})
                used.add(emoji)
                last_at = w["start"]
                break
        if len(out) >= limit:
            break
    return out


# --- modelo ---------------------------------------------------------------------------------------------

PROMPT = """Eres el editor de motion graphics de un canal de YouTube Shorts. A partir de las palabras del clip (cada una con su índice y su
segundo) propón animaciones que refuercen lo que se dice y mantengan el interés. Responde SOLO un JSON: {"beats": [...]}.

Cada beat: {"word_index": <índice de la palabra gancho>, "motif": "emoji" | "keyword" | "image" | "counter" | "strike", ..., "reason": "<5-8 palabras>"}.
- emoji: {"emoji": "💥", "target": "<emoji opcional al que llega el principal, ej. 🐔→🗳️>", "effect": "pop" | "vaporize" | "explode"}.
- keyword: {"text": "<1-3 palabras CLAVE en mayúsculas, ej. DEUDA>"} (tarjeta de texto; úsala poco, para una cifra o una idea).
- image: {"asset_id": <id de la lista de imágenes>, "style": "original" | "card" | "silhouette" | "red", "entry": "pop" | "punch" | "drop" | "slide_left" | "slide_right" | "slide_top", "effect": "pop" | "vaporize" | "break" | "explode"}.
  Solo si el nombre de la imagen encaja con lo que se dice; nunca inventes un asset_id.
  Las imágenes «Mapa de X» son el mapa de ese país: úsalas con style "original" justo cuando se nombra el país (y «Mapa de Europa» cuando se habla de Europa en general).
- counter: {"from_value": 0, "to_value": <la cifra que se dice>, "prefix": "", "suffix": "<unidad, ej. ' M€', ' %', ' ml'>", "label": "<1-3 palabras>"}. Solo cuando se dice una cifra concreta; word_index = la palabra de la cifra; to_value es esa cifra tal cual se dice (sin inventar).
- strike: {"text": "<1-2 palabras>"}: tacha con un aspa algo que se niega o se rechaza (un nombre, una idea). Úsalo poco.
Reglas:
- Como máximo {MAX} beats, repartidos por todo el clip (≈ uno cada 5-6 s, nunca dos seguidos). El primero, pasados los 2,5 s.
- La acción cae EN la palabra gancho: elige la palabra del objeto o la idea (p. ej. «pensionistas», «petado», «deuda»), no una conjunción.
- Efectos con sentido: explode/vaporize/break para algo que se hunde, desaparece o se rompe; punch/drop para un golpe; pop para el resto.
- Solo emojis de COSAS, cifras e instituciones. NUNCA emojis de personas por su etnia, nacionalidad o religión, ni banderas (salvo 🇪🇸), ni burlas a personas reales.
- No repitas el mismo emoji. Sin explicaciones fuera del JSON."""


def _word_lines(words: list[dict]) -> str:
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(f"{i}({w['start']:.1f}){w['text']}")
        if w["text"].rstrip().endswith((".", "?", "!")) or len(cur) >= 14:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def default_llm(system: str, user: str) -> dict | None:
    from app.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, timeout=60)
        response = client.chat.completions.create(
            model=settings.openai_clip_model, temperature=0.5, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        data = json.loads(response.choices[0].message.content or "{}")
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - red, cuota o JSON roto: se cae al plan B y el usuario lo ve
        return None


def _pick(value, allowed, default=None):
    return value if value in allowed else default


def beat_from_model(raw: dict, words: list[dict], asset_ids: set[int]) -> dict | None:
    """Un beat del modelo → beat para el editor, o None si no vale. El tiempo sale de la palabra elegida, no del modelo."""
    if not isinstance(raw, dict):
        return None
    index = raw.get("word_index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(words):
        return None
    beat: dict = {"at": round(words[index]["start"], 3), "reason": str(raw.get("reason", ""))[:120]}
    motif = raw.get("motif")
    if motif == "emoji":
        emoji = str(raw.get("emoji", "")).strip()
        target = str(raw.get("target") or "").strip()
        if not graphics_schedule.is_emoji(emoji) or not emoji_allowed(emoji):
            return None
        beat.update(type="emoji", emoji=emoji)
        if target:
            if not graphics_schedule.is_emoji(target) or not emoji_allowed(target):
                return None
            beat["target"] = target
        else:
            effect = _pick(raw.get("effect"), EFFECTS["emoji"])
            if effect and effect != "pop":
                beat["effect"] = effect
    elif motif == "keyword":
        text = re.sub(r"\s+", " ", str(raw.get("text", ""))).strip().upper()[:40]
        if not text:
            return None
        beat.update(type="keyword", text=text)
    elif motif == "image":
        asset_id = raw.get("asset_id")
        if not isinstance(asset_id, int) or asset_id not in asset_ids:
            return None
        beat.update(type="image", asset_id=asset_id, style=_pick(raw.get("style"), STYLES, "card"))
        for key, allowed in (("entry", ENTRIES), ("effect", EFFECTS["image"])):
            value = _pick(raw.get(key), allowed)
            if value and value != "pop":
                beat[key] = value
    elif motif == "counter":
        values = []
        for key in ("from_value", "to_value"):
            v = raw.get(key, 0 if key == "from_value" else None)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not -1e9 <= v <= 1e9:
                return None
            values.append(float(v))
        beat.update(type="counter", from_value=values[0], to_value=values[1], prefix=str(raw.get("prefix") or "")[:8],
                    suffix=str(raw.get("suffix") or "")[:12], label=re.sub(r"\s+", " ", str(raw.get("label") or "")).strip()[:40])
        beat = {k: v for k, v in beat.items() if v != ""}
    elif motif == "strike":
        text = re.sub(r"\s+", " ", str(raw.get("text", ""))).strip().upper()[:40]
        if not text:
            return None
        beat.update(type="strike", text=text)
    else:
        return None
    return beat


def plan(*, words: list[dict], duration: float, hook: str, assets: list[dict], existing: list[dict], cortinilla_at: float | None,
         single_lane: bool, llm: Callable[[str, str], dict | None] | None = default_llm,
         maps: dict[str, int] | None = None, speakers: dict | None = None) -> Plan:
    """Propuesta ya programada: solo lo que cabe junto a lo que el usuario ya puso (que manda sobre lo propuesto)."""
    limit = max_beats(duration)
    asset_ids = {a["id"] for a in assets}
    source, notes, proposals = "model", [], []
    data = llm(PROMPT.replace("{MAX}", str(limit)), _user_prompt(words, duration, hook, assets)) if llm is not None else None
    raw = data.get("beats") if isinstance(data, dict) else None
    if isinstance(raw, list):
        proposals = [b for b in (beat_from_model(r, words, asset_ids) for r in raw[: limit * 2]) if b]
    if not proposals:
        source = "plan_b"
        notes.append("No se pudo usar el modelo (¿falta la clave de OpenAI?) o no propuso nada: propuesta básica por palabras clave.")
        proposals = from_dictionary(words, duration, limit=limit)
    proposals += _map_beats(words, maps or {}, proposals)
    proposals += speaker_beats(words, speakers or {})
    fixed = [{**b, "priority": 1000} for b in existing]           # lo del usuario manda: lo propuesto solo entra si cabe
    scheduled = graphics_schedule.schedule(fixed + [{**p, "priority": p.get("priority", graphics_schedule.PRIORITY_BY_TYPE.get(p["type"], 0))} for p in proposals],
                                           duration, cortinilla_at=cortinilla_at, single_lane=single_lane)
    keep = {_key(b) for b in existing}
    reasons = {_key(p): p.get("reason", "") for p in proposals}
    accepted = []
    for b in scheduled.beats:
        if _key(b) in keep:
            continue
        accepted.append({**{k: v for k, v in b.items() if k != "reason"}, "reason": reasons.get(_key(b), "")})
    dropped = len(proposals) - len(accepted)
    if dropped:
        notes.append(f"{dropped} propuesta{'s' if dropped != 1 else ''} no cabe{'n' if dropped != 1 else ''} (solapes, gancho o cortinilla).")
    return Plan(accepted[:limit], source, notes)


LOWER_THIRD_MIN_START = 2.6   # tras el gancho (los primeros 2,2 s)
LOWER_THIRD_MIN_TURN = 1.5    # el rótulo sale cuando el speaker lleva al menos esto hablando seguido
LOWER_THIRD_PRIORITY = 8      # identificar a quien habla pesa más que un contador


def speaker_beats(words: list[dict], speakers: dict) -> list[dict]:
    """Un rótulo de nombre y cargo cuando empieza a hablar en serio cada speaker con nombre (turno de al menos 1,5 s, tras el gancho)."""
    out: list[dict] = []
    seen: set[str] = set()
    run_start: float | None = None
    run_first = 0
    run_label: str | None = None
    for i, w in enumerate(words):
        label = w.get("speaker")
        if label != run_label:
            run_label, run_start, run_first = label, w["start"], i
        if not label or label in seen:
            continue
        card = speakers.get(label) or {}
        name = str(card.get("name") or "").strip()
        if not name:
            continue
        first = next((words[j] for j in range(run_first, i + 1) if words[j]["start"] >= LOWER_THIRD_MIN_START), None)
        if first is not None and w["end"] - (run_start or 0.0) >= LOWER_THIRD_MIN_TURN:
            seen.add(label)
            role = str(card.get("role") or "").strip()
            out.append({"type": "lower_third", "at": round(first["start"], 3), "name": name[:40], **({"role": role[:60]} if role else {}),
                        "priority": LOWER_THIRD_PRIORITY, "reason": f"«{name}» habla"})
    return out


MAX_MAP_BEATS = 4
MAP_MIN_START = 2.5          # el gancho ocupa los primeros 2,2 s: la primera mención posterior es la que lleva mapa


def _map_beats(words: list[dict], maps: dict[str, int], proposals: list[dict]) -> list[dict]:
    """Un mapa en la primera mención de cada país (los que el modelo no haya puesto ya), hasta MAX_MAP_BEATS."""
    from app.services import country_maps

    taken = {p.get("asset_id") for p in proposals if p["type"] == "image"}
    out: list[dict] = []
    for name, index in country_maps.mentions(words, MAP_MIN_START):
        asset_id = maps.get(name)
        if asset_id is None or asset_id in taken:
            continue
        out.append({"type": "image", "at": round(words[index]["start"], 3), "asset_id": asset_id, "style": "original",
                    "reason": f"«{words[index]['text'].strip('.,;:!?¿¡')}» → mapa de {name}"})
        if len(out) >= MAX_MAP_BEATS:
            break
    return out


def _key(beat: dict) -> tuple:
    return (beat.get("type"), round(float(beat.get("at", 0)), 3))


def _user_prompt(words: list[dict], duration: float, hook: str, assets: list[dict]) -> str:
    lib = "\n".join(f"- {a['id']}: {a['name']}" + (f" [{', '.join(a['tags'])}]" if a.get("tags") else "") for a in assets) or "(sin imágenes)"
    return f"Duración del clip: {duration:.1f} s\nGancho: {hook or '(ninguno)'}\n\nImágenes de la librería:\n{lib}\n\nPalabras (índice(segundo)palabra):\n{_word_lines(words)}"
