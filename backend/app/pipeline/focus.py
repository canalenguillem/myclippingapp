"""Encuadre que sigue al hablante (mesas de debate): una posición horizontal por tramo de voz.

`build_track` convierte las palabras del clip (con `speaker`, segundos relativos al clip) en una lista
`[(t, x)]` con `x` en 0..1 (0 = borde izquierdo del plano, 1 = derecho). `x_expr` la pasa a una expresión de ffmpeg
con transiciones suaves para el filtro `crop`."""
from __future__ import annotations

DEFAULT_X = 0.5
MIN_HOLD = 1.0   # un tramo más corto (interjección) no mueve el plano
EASE = 0.25      # segundos que dura el movimiento de un hablante a otro
MAX_STEPS = 60   # tope para que la expresión de ffmpeg no crezca sin límite


def speaker_x(speakers: dict | None, label: str | None) -> float:
    card = (speakers or {}).get(label or "") or {}
    try:
        return min(1.0, max(0.0, float(card.get("focus_x", DEFAULT_X))))
    except (TypeError, ValueError):
        return DEFAULT_X


def build_track(words: list[dict], speakers: dict | None, *, min_hold: float = MIN_HOLD) -> list[tuple[float, float]]:
    """Tramos de voz seguidos del mismo hablante; los más cortos que `min_hold` se funden con el anterior.
    En los silencios se mantiene la última posición. Siempre empieza en t=0."""
    runs: list[list] = []  # [inicio, fin, x]
    for w in words:
        if w.get("speaker") is None:
            continue
        x = speaker_x(speakers, w["speaker"])
        if runs and runs[-1][2] == x:
            runs[-1][1] = float(w["end"])
        else:
            runs.append([float(w["start"]), float(w["end"]), x])
    return _track_from_runs(runs, min_hold)


def track_from_asd(data: dict, *, min_hold: float = MIN_HOLD) -> list[tuple[float, float]]:
    """Recorrido a partir de la respuesta del worker de ASD (TalkNet): `speakers[].center_norm` y `segments`
    (`speaker` −1 = nadie claro: se mantiene el plano). Tiempos relativos al clip enviado."""
    centers = {int(s["id"]): float(s["center_norm"][0]) for s in data.get("speakers") or []}
    runs: list[list] = []
    for seg in data.get("segments") or []:
        x = centers.get(int(seg.get("speaker", -1)))
        if x is None:
            continue
        x = min(1.0, max(0.0, x))
        if runs and runs[-1][2] == x:
            runs[-1][1] = float(seg["end"])
        else:
            runs.append([float(seg["start"]), float(seg["end"]), x])
    return _track_from_runs(runs, min_hold)


def _track_from_runs(runs: list[list], min_hold: float) -> list[tuple[float, float]]:
    merged: list[list] = []
    for run in runs:
        if merged and run[1] - run[0] < min_hold and merged[-1][0] != run[0]:
            merged[-1][1] = run[1]  # interjección: el plano se queda con quien hablaba
            continue
        if merged and merged[-1][2] == run[2]:
            merged[-1][1] = run[1]
            continue
        merged.append(run)
    if not merged:
        return [(0.0, DEFAULT_X)]
    track = [(0.0, merged[0][2])]
    for start, _end, x in merged[1:]:
        if x != track[-1][1]:
            track.append((round(start, 3), x))
    return track[:MAX_STEPS]


def x_fraction_expr(track: list[tuple[float, float]], ease: float = EASE) -> str:
    """Expresión de ffmpeg (variable `t`) con la posición 0..1: x0 + Σ (x_i − x_{i−1})·smoothstep((t − t_i)/ease)."""
    expr = f"{track[0][1]:.4f}"
    for (_, prev), (t_i, x_i) in zip(track, track[1:]):
        delta = x_i - prev
        u = f"clip((t-{t_i:.3f})/{ease:.3f},0,1)"
        expr += f"{delta:+.4f}*({u}*{u}*(3-2*{u}))"
    return expr


def x_expr(track: list[tuple[float, float]], ease: float = EASE) -> str:
    """Valor del `x` de `crop`: (iw-ow)·posición."""
    return f"(iw-ow)*({x_fraction_expr(track, ease)})"


def position_at(track: list[tuple[float, float]], t: float, ease: float = EASE) -> float:
    """Misma curva en Python (para tests y la vista previa)."""
    pos = track[0][1]
    for (_, prev), (t_i, x_i) in zip(track, track[1:]):
        u = min(1.0, max(0.0, (t - t_i) / ease))
        pos += (x_i - prev) * (u * u * (3 - 2 * u))
    return pos
