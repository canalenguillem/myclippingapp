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


CUT_EASE = 0.04   # en un corte de plano el recorte salta (el plano ya cambia de golpe): sin deslizarse de una posición a otra


def _ease_of(point: tuple, default: float) -> float:
    return float(point[2]) if len(point) > 2 else default


def x_fraction_expr(track: list[tuple], ease: float = EASE) -> str:
    """Expresión de ffmpeg (variable `t`) con la posición 0..1: x0 + Σ (x_i − x_{i−1})·smoothstep((t − t_i)/ease_i).
    Cada punto es (t, x) o (t, x, ease)."""
    expr = f"{track[0][1]:.4f}"
    for prev_pt, pt in zip(track, track[1:]):
        t_i, x_i, prev = pt[0], pt[1], prev_pt[1]
        delta = x_i - prev
        u = f"clip((t-{t_i:.3f})/{_ease_of(pt, ease):.3f},0,1)"
        expr += f"{delta:+.4f}*({u}*{u}*(3-2*{u}))"
    return expr


def x_expr(track: list[tuple], ease: float = EASE) -> str:
    """Valor del `x` de `crop`: (iw-ow)·posición."""
    return f"(iw-ow)*({x_fraction_expr(track, ease)})"


def position_at(track: list[tuple], t: float, ease: float = EASE) -> float:
    """Misma curva en Python (para tests, la vista previa y el análisis por planos)."""
    pos = track[0][1]
    for prev_pt, pt in zip(track, track[1:]):
        u = min(1.0, max(0.0, (t - pt[0]) / _ease_of(pt, ease)))
        pos += (pt[1] - prev_pt[1]) * (u * u * (3 - 2 * u))
    return pos


def apply_shots(track: list[tuple], shots: list[dict], *, max_steps: int = MAX_STEPS) -> list[tuple]:
    """Seguimiento por plano sobre el recorrido base: en un plano «face» el recorte se queda en la cara; en un plano «snap» cada
    posición del hablante se pega a la cara grande más cercana; «wide» y «keep» conservan el recorrido base. En cada corte de plano
    el recorte salta (CUT_EASE) en vez de deslizarse."""
    out: list[tuple] = []
    for shot in shots:
        a, b = float(shot["start"]), float(shot["end"])
        base_here = position_at(track, a + 0.01)
        kind = shot.get("kind")
        if kind == "face":
            out.append((a, float(shot["x"]), CUT_EASE))
            continue
        centers = shot.get("centers") or []
        snap = (lambda x: min(centers, key=lambda c: abs(c - x))) if kind == "snap" and centers else (lambda x: x)
        out.append((a, snap(base_here), CUT_EASE))
        for pt in track:
            if a + 0.05 < pt[0] < b - 0.05:
                out.append((pt[0], snap(pt[1]), _ease_of(pt, EASE)))
    out = [(0.0, out[0][1], CUT_EASE)] + out if out and out[0][0] > 0 else out
    merged: list[tuple] = []
    for p in out:                                      # sin pasos repetidos
        if merged and abs(p[1] - merged[-1][1]) < 1e-4:
            continue
        merged.append(p)
    return merged[:max_steps] or list(track)
