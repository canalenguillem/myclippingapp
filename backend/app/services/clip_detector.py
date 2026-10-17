"""Detección de clips con un LLM, sobre las palabras del words.json (tiempos en SEGUNDOS).

Porta `clip_detector` del repo viejo con cuatro cambios: parte de palabras (no de un .vtt), pide también
`hook`, `emphasis_words` y `parts`, acota cada clip a límites de frase y valida la respuesta del modelo.
Los timestamps que devuelve el LLM no se aceptan tal cual: se ajustan a inicio/fin de frase.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from app.config import get_settings

SENTENCE_END = re.compile(r"[.!?…]+[\"'»”’)\]]*$")


class DetectionError(RuntimeError):
    pass


@dataclass
class Cue:
    start: float
    end: float
    text: str
    speaker: str | None
    lo: int  # índice de la primera palabra en words.json
    hi: int  # índice de la última palabra (incluida)


@dataclass
class ClipCandidate:
    start: float
    end: float
    title: str
    reason: str
    score: int
    transcript: str = ""
    hook: str = ""
    emphasis: list[dict] = field(default_factory=list)  # [{"start": seg_absolutos, "text": palabra}]
    parts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {**self.__dict__, "start": round(self.start, 2), "end": round(self.end, 2),
                "duration": round(self.end - self.start, 2)}


# --- frases -------------------------------------------------------------------------------------

def _split_long(words: list[dict], lo: int, max_words: int, max_seconds: float) -> list[tuple[int, int]]:
    """Parte una frase desmesurada por su pausa más larga (no por un contador), recursivamente."""
    n = len(words)
    if (n <= max_words and words[-1]["end"] - words[0]["start"] <= max_seconds) or n < 8:
        return [(lo, lo + n - 1)]
    gaps = [(words[k + 1]["start"] - words[k]["end"], -k) for k in range(3, n - 4)]
    k = -max(gaps)[1]  # a igualdad de pausa, la más temprana
    return _split_long(words[:k + 1], lo, max_words, max_seconds) + _split_long(words[k + 1:], lo + k + 1, max_words, max_seconds)


def build_cues(words: list[dict], max_gap: float = 0.8, max_words: int = 60, max_seconds: float = 25.0) -> list[Cue]:
    """Agrupa palabras en frases: corta tras puntuación final, pausa larga o cambio de speaker.

    No se usan los `segments` de AssemblyAI: en un monólogo es una sola utterance de minutos. Tampoco se
    corta por longitud mientras no sea absurda: un clip que acaba donde un contador partió la frase termina a
    mitad de idea. Solo si una frase pasa de `max_words`/`max_seconds` se parte, por su pausa más larga.
    """
    spans: list[tuple[int, int]] = []
    lo = 0
    for i, w in enumerate(words):
        if i > lo:
            prev = words[i - 1]
            if w["start"] - prev["end"] > max_gap or w.get("speaker") != prev.get("speaker"):
                spans.append((lo, i - 1))
                lo = i
        if SENTENCE_END.search(w["text"]):
            spans.append((lo, i))
            lo = i + 1
    if lo < len(words):
        spans.append((lo, len(words) - 1))

    cues: list[Cue] = []
    for a, b in spans:
        for x, y in _split_long(words[a:b + 1], a, max_words, max_seconds):
            chunk = words[x:y + 1]
            cues.append(Cue(chunk[0]["start"], chunk[-1]["end"], " ".join(w["text"] for w in chunk),
                            chunk[0].get("speaker"), x, y))
    return cues


def _transcript_block(cues: list[Cue], with_speakers: bool) -> str:
    lines = []
    for n, c in enumerate(cues):
        tag = f"[{c.speaker}] " if with_speakers and c.speaker else ""
        lines.append(f"[{n}] {c.start:.1f}-{c.end:.1f}s: {tag}{c.text}")
    return "\n".join(lines)


# --- prompt y validación ------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres un editor experto en clips virales para TikTok, Reels y Shorts. "
    "Recibes la transcripcion de un video con marcas de tiempo (en segundos) y "
    "debes seleccionar los momentos con mayor potencial viral: ganchos, "
    "revelaciones, giros, frases impactantes o emocionales, o segmentos "
    "autoconclusivos. Cada clip debe empezar y terminar en pausas naturales. "
    "Construye cada clip como un ARCO COMPLETO (preambulo/contexto -> desarrollo -> "
    "desenlace), no solo la frase punchline: incluye el contexto previo y el cierre "
    "para que dure lo pedido y se entienda solo."
)


def _user_prompt(block: str, count: int, target: int, min_dur: int, max_dur: int) -> str:
    return (
        f"Este es UN SEGMENTO de la transcripcion (indice, tiempo en segundos, texto):\n\n{block}\n\n"
        f"Selecciona hasta {count} clips con potencial viral de ESTE segmento. Reglas:\n"
        f"- DURACION (IMPORTANTE): cada clip DEBE durar entre {min_dur} y {max_dur} segundos, idealmente ~{target}s. "
        f"Si el momento potente es corto, EXTIENDE los limites (hacia atras para incluir el planteamiento y hacia delante "
        f"para incluir la reaccion/desenlace). NO devuelvas clips mas cortos de {min_dur}s.\n"
        "- 'start' y 'end' en segundos (numeros), alineados al inicio y al final de las frases del segmento.\n"
        "- Cada clip debe ser autoconclusivo y engancharse desde el primer segundo.\n"
        "- 'hook': titular de maximo 6 palabras que enganche en los primeros segundos.\n"
        "- 'emphasis_words': de 2 a 4 palabras del clip, copiadas tal cual de la transcripcion, que se dicen con mas fuerza "
        "(cifras, nombres propios, la palabra clave de una revelacion). Nada de articulos, preposiciones ni pronombres.\n"
        "- 'parts': de 2 a 4 frases, una por cada parte tematica del clip, en orden.\n"
        "- 'hook' y 'parts' en el mismo idioma que la transcripcion.\n"
        "- Ordena de mayor a menor potencial.\n\n"
        "Responde SOLO con JSON valido de esta forma:\n"
        '{"clips": [{"start": number, "end": number, "title": "gancho corto", "reason": "por que funciona", '
        '"score": number_0_100, "hook": "max 6 palabras", "emphasis_words": ["palabra", "palabra"], '
        '"parts": ["frase", "frase"]}]}'
    )


class _LlmClip(BaseModel):
    start: float
    end: float
    title: str = ""
    reason: str = ""
    score: int = 0
    hook: str = ""
    emphasis_words: list[str] = []
    parts: list[str] = []

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> int:
        try:
            return max(0, min(100, int(float(v))))
        except (TypeError, ValueError):
            return 0

    @field_validator("hook", mode="after")
    @classmethod
    def _hook(cls, v: str) -> str:
        return " ".join(v.split()[:6])

    @field_validator("emphasis_words", mode="after")
    @classmethod
    def _emphasis(cls, v: list[str]) -> list[str]:
        return [w.strip() for w in v if isinstance(w, str) and w.strip()][:4]

    @field_validator("parts", mode="after")
    @classmethod
    def _parts(cls, v: list[str]) -> list[str]:
        return [p.strip() for p in v if isinstance(p, str) and p.strip()][:4]


def parse_response(content: str) -> list[_LlmClip]:
    """Acepta solo los clips bien formados; uno roto no tira los demás."""
    data = json.loads(content or "{}")
    out = []
    for item in data.get("clips", []):
        try:
            clip = _LlmClip.model_validate(item)
        except ValidationError:
            continue
        if math.isfinite(clip.start) and math.isfinite(clip.end) and clip.end > clip.start:
            out.append(clip)
    return out


# --- ajuste de límites --------------------------------------------------------------------------

SILENCE_REACH = 8.0  # hasta cuántos segundos se desplaza un límite para dar con un final de frase y/o un silencio


def _ends_sentence(cue: Cue) -> bool:
    return bool(SENTENCE_END.search(cue.text))


def _nearest(target: float, cands: list[tuple[float, bool]], ok: Callable[[float], bool] | None) -> float:
    """Elige el límite más cercano a `target`, por prioridad y dentro del alcance:
    1) final/inicio de frase CON silencio; 2) de frase, sin silencio; 3) pausa interna con silencio;
    4) el más cercano sin más. Acabar a mitad de frase es peor que cortar sin silencio."""
    near = [(t, sentence) for t, sentence in cands if abs(t - target) <= SILENCE_REACH]
    pools = []
    if ok is not None:
        pools.append([t for t, sentence in near if sentence and ok(t)])
    pools.append([t for t, sentence in near if sentence])
    if ok is not None:
        pools.append([t for t, _ in near if ok(t)])
    for pool in pools:
        if pool:
            return min(pool, key=lambda x: abs(x - target))
    return min((t for t, _ in cands), key=lambda x: abs(x - target))


def snap_to_cues(start: float, end: float, cues: list[Cue], silences: list[dict] | None = None) -> tuple[float, float]:
    """Inicio al arranque de una frase y fin al final de una frase, con preferencia por los que tienen silencio al
    lado (el corte no pisa una palabra). Ver `_nearest` para el orden de prioridad."""
    ok_start = ok_end = None
    if silences:
        from app.services import silences as sl

        ok_start, ok_end = (lambda t: sl.can_cut_start(t, silences)), (lambda t: sl.can_cut_end(t, silences))
    starts = [(c.start, k == 0 or _ends_sentence(cues[k - 1])) for k, c in enumerate(cues)]
    ends = [(c.end, _ends_sentence(c)) for c in cues]
    s, e = _nearest(start, starts, ok_start), _nearest(end, ends, ok_end)
    return (s, e) if e > s else (start, end)


def trim_to_max(start: float, end: float, cues: list[Cue], max_dur: float, end_ok: Callable[[float], bool] | None = None) -> tuple[float, float]:
    """Si pasa de la duración máxima, el fin retrocede al último final de frase que cabe; entre los que no distan más
    de SILENCE_REACH s de ese, se prefiere uno de frase con silencio, y si no, de frase."""
    if end - start <= max_dur:
        return start, end
    fits = [c for c in cues if start < c.end <= start + max_dur]
    if not fits:
        return start, end
    best = max(fits, key=lambda c: c.end)
    near = [c for c in fits if best.end - c.end <= SILENCE_REACH]
    for pool in ([c for c in near if _ends_sentence(c) and end_ok(c.end)] if end_ok else [], [c for c in near if _ends_sentence(c)]):
        if pool:
            return start, max(pool, key=lambda c: c.end).end
    return start, best.end


def extend_to_target(start: float, end: float, cues: list[Cue], target: float, max_dur: float, total_end: float) -> tuple[float, float]:
    """Si el clip es más corto que `target`, extiende a límites de frase: primero hacia delante, luego hacia atrás."""
    if end - start >= target:
        return start, end
    for c in cues:
        if c.end > end and (c.end - start) <= max_dur and c.end <= total_end + 0.01:
            end = c.end
            if end - start >= target:
                return start, end
    for c in reversed(cues):
        if c.start < start and (end - c.start) <= max_dur:
            start = c.start
            if end - start >= target:
                break
    return max(0.0, start), end


def _norm(word: str) -> str:
    stripped = unicodedata.normalize("NFD", word.lower())
    return re.sub(r"[^\w]", "", "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn"))


def map_emphasis(emphasis_words: list[str], words: list[dict], start: float, end: float) -> list[dict]:
    """Localiza cada énfasis dentro del clip y devuelve su tiempo ABSOLUTO en segundos.

    El modelo a veces devuelve una frase («Tribunal Constitucional») en vez de una palabra: se busca la secuencia
    entera y el énfasis cae en su palabra más larga; si la secuencia no está, se prueba solo con esa palabra.
    Se guarda por tiempo y texto (no por índice) para que sobreviva a un recorte distinto del clip.
    """
    inside = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    keys = [_norm(w["text"]) for w in inside]
    used: set[int] = set()
    found: list[dict] = []

    def free(i: int) -> bool:
        return i not in used and keys[i] != ""

    for target in emphasis_words:
        tokens = [t for t in (_norm(t) for t in target.split()) if t]
        if not tokens:
            continue
        hit = None
        for i in range(len(keys) - len(tokens) + 1):
            if keys[i:i + len(tokens)] == tokens and all(free(i + k) for k in range(len(tokens))):
                hit = i + max(range(len(tokens)), key=lambda k: len(tokens[k]))  # palabra más larga de la frase
                break
        if hit is None and len(tokens) > 1:
            for token in sorted(set(tokens), key=lambda t: -len(t)):  # de la más larga a la más corta
                hit = next((i for i, k in enumerate(keys) if k == token and free(i)), None)
                if hit is not None:
                    break
        if hit is None:
            continue
        used.add(hit)
        found.append({"start": float(inside[hit]["start"]), "text": inside[hit]["text"].strip(".,;:!?¿¡\"'«»")})
    return sorted(found, key=lambda e: e["start"])


def _dedupe(clips: list[ClipCandidate]) -> list[ClipCandidate]:
    """Los clips que se pisan (frecuente en los bordes entre partes) se quedan con el de mejor score."""
    kept: list[ClipCandidate] = []
    for c in sorted(clips, key=lambda c: -c.score):
        if any(min(c.end, k.end) - max(c.start, k.start) > 0.5 * min(c.end - c.start, k.end - k.start) for k in kept):
            continue
        kept.append(c)
    return sorted(kept, key=lambda c: c.start)


def resolve_parts(total_seconds: float, parts: int | None) -> int:
    """Sin valor explícito: ~1 parte por cada 15 min de vídeo."""
    return parts if parts and parts > 0 else max(1, round(total_seconds / 60 / 15))


# --- detector -----------------------------------------------------------------------------------

def detect_clips(
    transcript: dict,
    *,
    client: Any = None,
    parts: int | None = None,
    clips_per_part: int = 5,
    target_dur: int = 40,
    model: str | None = None,
    silences: list[dict] | None = None,
    log: Callable[[str], None] = lambda msg: None,
    progress: Callable[[float], None] = lambda fraction: None,
) -> list[ClipCandidate]:
    words = transcript.get("words") or []
    if not words:
        raise DetectionError("La transcripción no tiene palabras")
    cues = build_cues(words)
    if client is None:
        from openai import OpenAI

        key = get_settings().openai_api_key
        if not key:
            raise DetectionError("Falta OPENAI_API_KEY en .env")
        client = OpenAI(api_key=key)
    model = model or get_settings().openai_clip_model

    total_end = cues[-1].end
    min_dur, max_dur = max(5, target_dur - 10), target_dur + 15
    with_speakers = len({c.speaker for c in cues}) > 1
    n_parts = resolve_parts(total_end, parts)
    chunk_size = math.ceil(len(cues) / n_parts)

    end_ok = None
    if silences:
        from app.services import silences as sl

        end_ok = lambda t: sl.can_cut_end(t, silences)  # noqa: E731
    found: list[ClipCandidate] = []
    errors: list[str] = []
    chunks = [cues[i:i + chunk_size] for i in range(0, len(cues), chunk_size)]
    for n, chunk in enumerate(chunks, 1):
        progress((n - 1) / len(chunks))  # puede lanzar para cancelar
        prompt = _user_prompt(_transcript_block(chunk, with_speakers), clips_per_part, target_dur, min_dur, max_dur)
        try:
            response = client.chat.completions.create(
                model=model, temperature=0.4, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            )
            items = parse_response(response.choices[0].message.content)
        except Exception as exc:  # noqa: BLE001 - una parte que falla no tumba las demás
            errors.append(f"{type(exc).__name__}: {exc}")
            log(f"Parte {n}/{len(chunks)} falló: {errors[-1]}")
            continue
        log(f"Parte {n}/{len(chunks)}: {len(items)} clips propuestos")
        for item in items:
            start, end = snap_to_cues(max(0.0, item.start), min(total_end, item.end), cues, silences)
            start, end = trim_to_max(start, end, cues, max_dur, end_ok)
            if end - start < min_dur:
                start, end = extend_to_target(start, end, cues, target_dur, max_dur, total_end)
            if end - start < 3:
                continue
            inside = " ".join(w["text"] for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05)
            found.append(ClipCandidate(
                start=start, end=end, title=item.title.strip()[:120], reason=item.reason.strip()[:300],
                score=item.score, transcript=inside[:2000], hook=item.hook,
                emphasis=map_emphasis(item.emphasis_words, words, start, end), parts=item.parts,
            ))
    progress(1.0)
    if not found and errors and len(errors) == len(chunks):
        raise DetectionError(f"El modelo falló en todas las partes: {errors[0]}")
    return _dedupe(found)
