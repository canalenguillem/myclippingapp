"""Programador determinista de gráficos (§4.2 del md). El planner (LLM) o el usuario PROPONEN beats; este módulo hace
cumplir las reglas de sincronía y devuelve solo los que caben, con la ventana ya ajustada.

Tiempos en segundos del CLIP (sin cortinillas; el mapa de tiempos de `fx_worker` las desplaza después).
Beat de entrada:  {"type", "at", ...parámetros del motivo, "lead"?, "duration"?, "priority"?}
Beat de salida:   el mismo con `lead` y `duration` ya ajustados, listo para el contrato de `fx_worker`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

LEAD_MIN, LEAD_MAX, LEAD_DEFAULT = 0.3, 0.8, 0.5   # el elemento entra 0,3–0,8 s antes de la palabra
DURATION_MIN, DURATION_MAX = 2.0, 4.0              # cada elemento vive 2–4 s
EPS = 1e-6                                          # tolerancia de coma flotante en las comparaciones de tiempos
MIN_VISIBLE = 1.5                                  # una ventana recortada por una cortinilla o el final no baja de esto
MIN_BIG_GAP = 4.0                                  # entre el inicio de dos gráficos grandes (≈ 1 cada 4–5 s)
HOOK_SECONDS = 2.2                                 # el gancho ocupa los primeros segundos (igual que fx_request)

# Motivos y su tamaño: nunca dos grandes a la vez. Cada motivo nuevo se da de alta aquí (y en el contrato de fx_worker).
BIG = {"keyword", "image", "counter", "strike", "lower_third", "puppets"}
SMALL = {"emoji"}
DURATION_BY_TYPE = {"keyword": 2.5, "emoji": 2.5, "image": 3.0, "counter": 3.0, "strike": 2.5, "lower_third": 3.0, "puppets": 3.0}
PRIORITY_BY_TYPE = {"keyword": 5, "emoji": 3, "image": 6, "counter": 7, "strike": 6, "lower_third": 4, "puppets": 6}
LEAD_BY_TYPE = {"emoji": 0.8, "counter": 0.8, "puppets": 0.8}   # la cifra necesita tiempo para rodar hasta la palabra
MOVING_ENTRIES = {"punch", "slide_left", "slide_right", "slide_top", "drop"}   # entradas con recorrido: necesitan tiempo para llegar
MOVING_LEAD = 0.7                       # una escena con saltos necesita tiempo para llegar a la palabra
REQUIRED_FIELD = {"keyword": "text", "emoji": "emoji", "image": "asset_id", "counter": "to_value", "strike": "text", "lower_third": "name", "puppets": "asset_ids"}


_EMOJI_CATEGORIES = {"So", "Sk", "Cf", "Mn"}


def is_emoji(text: str) -> bool:
    """Igual que el contrato de fx_worker (`^[\\p{So}\\p{Sk}\\p{Cf}\\p{Mn}]+$`): símbolos, modificadores, ZWJ y selectores de variante;
    sin letras, cifras, espacios ni signos ASCII (así nada de HTML y un emoji «raro» no tumba el render del servicio)."""
    return 0 < len(text) <= 16 and all(unicodedata.category(c) in _EMOJI_CATEGORIES and ord(c) > 0x7F for c in text)


@dataclass
class Scheduled:
    beats: list[dict]
    dropped: list[dict]  # [{"beat": {...}, "reason": "..."}]


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def schedule(beats: list[dict] | None, clip_duration: float, *, cortinilla_at: float | None = None, single_lane: bool = False) -> Scheduled:
    """`single_lane`: en pantalla completa todos los gráficos comparten el hueco difuminado de abajo, así que nunca hay dos a la vez."""
    dropped: list[dict] = []
    candidates: list[dict] = []

    def drop(beat: dict, reason: str) -> None:
        dropped.append({"beat": beat, "reason": reason})

    for beat in beats or []:
        if not isinstance(beat, dict):
            continue
        kind = beat.get("type")
        if kind not in BIG and kind not in SMALL:
            drop(beat, f"motivo desconocido: {kind!r}")
            continue
        if kind == "emoji" and not (is_emoji(str(beat.get("emoji", ""))) and (beat.get("target") in (None, "") or is_emoji(str(beat["target"])))):
            drop(beat, "emoji no válido")
            continue
        field = REQUIRED_FIELD.get(kind)
        # la imagen llega como `asset_id` (lo guardado) o ya resuelta como `image` (la ruta que se manda a fx_worker)
        if kind == "puppets" and not (beat.get("asset_ids") or beat.get("images")):
            drop(beat, "faltan las caras")
            continue
        if kind != "puppets" and field and not (str(beat.get(field, "")).strip() or (kind == "image" and beat.get("image"))):
            drop(beat, "falta el texto" if field == "text" else "falta la imagen" if field == "asset_id" else f"falta el campo «{field}»")
            continue
        at = _num(beat.get("at"), -1.0)
        if not 0.0 <= at <= clip_duration:
            drop(beat, "la palabra gancho cae fuera del clip")
            continue
        default_lead = MOVING_LEAD if beat.get("entry") in MOVING_ENTRIES else LEAD_BY_TYPE.get(kind, LEAD_DEFAULT)
        lead = min(LEAD_MAX, max(LEAD_MIN, _num(beat.get("lead"), default_lead)))
        length = min(DURATION_MAX, max(DURATION_MIN, _num(beat.get("duration"), DURATION_BY_TYPE.get(kind, 2.5))))
        start = max(0.0, at - lead)
        end = min(clip_duration, start + length)
        if kind in BIG and start < HOOK_SECONDS:  # el gancho ya ocupa la pantalla: entra cuando acaba
            start = HOOK_SECONDS
            if at - start < LEAD_MIN - EPS:
                drop(beat, "choca con el gancho")
                continue
            end = min(clip_duration, start + length)
        if cortinilla_at is not None and start < cortinilla_at < end:
            if at >= cortinilla_at:        # la palabra viene tras la cortinilla: entra al reanudarse el clip
                start = cortinilla_at
                if at - start < LEAD_MIN - EPS:
                    drop(beat, "la palabra cae pegada a la cortinilla de inicio")
                    continue
                end = min(clip_duration, start + length)
            else:                          # la palabra viene antes: sale antes de que entre la cortinilla
                end = cortinilla_at
        if end - start < MIN_VISIBLE - EPS:
            drop(beat, "no cabe una ventana visible de 1,5 s")
            continue
        out = {k: v for k, v in beat.items() if k not in ("priority",)}
        out.update(at=round(at, 3), lead=round(at - start, 3), duration=round(end - start, 3))
        candidates.append({"beat": out, "start": start, "end": end, "big": kind in BIG,
                           "priority": _num(beat.get("priority"), PRIORITY_BY_TYPE.get(kind, 0))})

    accepted: list[dict] = []
    for c in sorted(candidates, key=lambda c: (-c["priority"], c["beat"]["at"])):
        if single_lane:
            clash = next((a for a in accepted if a["start"] < c["end"] and c["start"] < a["end"]), None)
        elif c["big"]:
            clash = next((a for a in accepted if a["big"] and abs(a["start"] - c["start"]) < MIN_BIG_GAP), None)
        else:
            clash = next((a for a in accepted if a["beat"]["type"] == c["beat"]["type"] and a["start"] < c["end"] and c["start"] < a["end"]), None)
        if clash:
            drop(c["beat"], "solapa con otro gráfico más prioritario" if c["big"] or single_lane else "solapa con otro gráfico del mismo tipo")
            continue
        accepted.append(c)
    accepted.sort(key=lambda c: c["beat"]["at"])
    return Scheduled([a["beat"] for a in accepted], dropped)
