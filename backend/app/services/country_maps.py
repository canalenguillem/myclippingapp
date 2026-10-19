"""Mapas de países como imágenes PNG transparentes (para gráficos y para el objeto que orbita en la cortinilla).

Salen de `app/data/countries-50m.json` (world-atlas / Natural Earth): el país en el rojo de marca con su contorno crema y,
muy atenuados, los vecinos, para que se reconozca por la forma. Solo Pillow, sin dependencias nuevas."""
from __future__ import annotations

import io
import json
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

DATA = Path(__file__).resolve().parent.parent / "data" / "countries-50m.json"
FILL, OUTLINE, NEIGHBOR = (218, 46, 9, 255), (243, 238, 226, 255), (243, 238, 226, 46)
SIZE = 640  # lado mayor del PNG
PAD = 0.06

# nombre en español → nombre en world-atlas
NAMES = {
    "Albania": "Albania", "Alemania": "Germany", "Andorra": "Andorra", "Armenia": "Armenia", "Austria": "Austria",
    "Azerbaiyán": "Azerbaijan", "Bélgica": "Belgium", "Bielorrusia": "Belarus", "Bosnia y Herzegovina": "Bosnia and Herz.",
    "Bulgaria": "Bulgaria", "Chipre": "Cyprus", "Croacia": "Croatia", "Dinamarca": "Denmark", "Eslovaquia": "Slovakia",
    "Eslovenia": "Slovenia", "España": "Spain", "Estonia": "Estonia", "Finlandia": "Finland", "Francia": "France",
    "Georgia": "Georgia", "Grecia": "Greece", "Hungría": "Hungary", "Irlanda": "Ireland", "Islandia": "Iceland",
    "Italia": "Italy", "Kosovo": "Kosovo", "Letonia": "Latvia", "Liechtenstein": "Liechtenstein", "Lituania": "Lithuania",
    "Luxemburgo": "Luxembourg", "Macedonia del Norte": "Macedonia", "Malta": "Malta", "Moldavia": "Moldova",
    "Montenegro": "Montenegro", "Noruega": "Norway", "Países Bajos": "Netherlands", "Polonia": "Poland", "Portugal": "Portugal",
    "Reino Unido": "United Kingdom", "República Checa": "Czechia", "Rumanía": "Romania", "Rusia": "Russia", "Serbia": "Serbia",
    "Suecia": "Sweden", "Suiza": "Switzerland", "Turquía": "Turkey", "Ucrania": "Ukraine",
    # fuera de Europa, los que salen a menudo en política y economía
    "Argelia": "Algeria", "Argentina": "Argentina", "Brasil": "Brazil", "Canadá": "Canada", "China": "China", "Colombia": "Colombia",
    "Cuba": "Cuba", "Egipto": "Egypt", "Estados Unidos": "United States of America", "India": "India", "Irán": "Iran", "Irak": "Iraq",
    "Israel": "Israel", "Japón": "Japan", "Marruecos": "Morocco", "México": "Mexico", "Palestina": "Palestine", "Perú": "Peru",
    "Siria": "Syria", "Venezuela": "Venezuela", "Chile": "Chile", "Libia": "Libya", "Mauritania": "Mauritania", "Túnez": "Tunisia",
}
EUROPE = list(NAMES)[:list(NAMES).index("Argelia")]
CONTINENT = "Europa"  # no es un país: todos los europeos en rojo (menos los del Cáucaso, Turquía y Chipre, que quedan tenues)
NOT_IN_CONTINENT = {"Armenia", "Azerbaiyán", "Georgia", "Turquía", "Chipre"}
CONTINENT_VIEW = (-25.0, 34.0, 45.0, 72.0)  # lon0, lat0, lon1, lat1

# recuadro (lon0, lat0, lon1, lat1) que se queda de cada país: sin islas lejanas ni territorios de ultramar
REGION = {
    "France": (-6, 41, 10, 52), "Spain": (-10, 35.5, 5, 44.5), "Portugal": (-10, 36.5, -6, 42.5), "Norway": (4, 57, 32, 72),
    "Denmark": (7, 54, 16, 58), "Netherlands": (3, 50, 8, 54), "United States of America": (-125, 24, -66, 50),
    "Russia": (19, 41, 180, 82), "Canada": (-141, 41, -52, 84), "United Kingdom": (-9, 49, 2, 61), "Greece": (19, 34, 30, 42),
    "Italy": (6, 36, 19, 47.5), "Turkey": (25, 35, 45, 43), "Chile": (-76, -56, -66, -17), "China": (73, 18, 135, 54),
}


class CountryError(ValueError):
    pass


@lru_cache(maxsize=1)
def _atlas() -> tuple[dict, list[list[tuple[float, float]]]]:
    topo = json.loads(DATA.read_text(encoding="utf-8"))
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs: list[list[tuple[float, float]]] = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return topo, arcs


def _ring(indexes: list[int], arcs) -> list[tuple[float, float]]:
    ring: list[tuple[float, float]] = []
    for i in indexes:
        pts = arcs[i] if i >= 0 else arcs[~i][::-1]
        ring.extend(pts if not ring else pts[1:])
    # polígonos que cruzan el antimeridiano (Rusia, Fiyi): se desenvuelve la longitud para que el anillo sea continuo
    out = [ring[0]]
    shift = 0.0
    for (px, _), (x, y) in zip(ring, ring[1:]):
        if x - px > 180:
            shift -= 360
        elif px - x > 180:
            shift += 360
        out.append((x + shift, y))
    return out


def _polygons(geometry: dict, arcs) -> list[list[list[tuple[float, float]]]]:
    """Cada polígono como lista de anillos (el primero, exterior)."""
    polys = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
    return [[_ring(r, arcs) for r in poly] for poly in polys]


def _centroid(ring) -> tuple[float, float]:
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def _bbox_area(ring) -> float:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def names() -> set[str]:
    """Todo lo que se puede pedir: países y el continente."""
    return set(NAMES) | {CONTINENT}


def available() -> list[dict]:
    """Países que ofrece la librería, en español: [{name, group}]."""
    return [{"name": CONTINENT, "group": "Europa"}] + [{"name": es, "group": "Europa" if es in EUROPE else "Otros"} for es in sorted(NAMES)]


def render(country_es: str) -> bytes:
    """PNG transparente del país (nombre en español de `NAMES`)."""
    topo, arcs = _atlas()
    geoms = topo["objects"]["countries"]["geometries"]
    if country_es == CONTINENT:
        wanted = {NAMES[n] for n in EUROPE if n not in NOT_IN_CONTINENT}
        targets = [g for g in geoms if g["properties"]["name"] in wanted]
        polys = [p for g in targets for p in _polygons(g, arcs)]
        lon0, lat0, lon1, lat1 = CONTINENT_VIEW
    else:
        en = NAMES.get(country_es)
        if en is None:
            raise CountryError(f"País desconocido: {country_es!r}")
        target = next((g for g in geoms if g["properties"]["name"] == en), None)
        if target is None:
            raise CountryError(f"No hay datos para {country_es!r}")
        targets = [target]
        polys = _polygons(target, arcs)
        if en in REGION:
            x0, y0, x1, y1 = REGION[en]
            polys = [p for p in polys if x0 <= _centroid(p[0])[0] <= x1 and y0 <= _centroid(p[0])[1] <= y1] or polys
        else:
            biggest = max(polys, key=lambda p: _bbox_area(p[0]))
            cx, cy = _centroid(biggest[0])
            polys = [p for p in polys if abs(_centroid(p[0])[0] - cx) < 25 and abs(_centroid(p[0])[1] - cy) < 25]
        pts = [pt for p in polys for pt in p[0]]
        lon0, lon1 = min(p[0] for p in pts), max(p[0] for p in pts)
        lat0, lat1 = min(p[1] for p in pts), max(p[1] for p in pts)
    k = math.cos(math.radians((lat0 + lat1) / 2))  # equirrectangular corregida por la latitud media
    w_deg, h_deg = max((lon1 - lon0) * k, 1e-6), max(lat1 - lat0, 1e-6)
    scale = SIZE * (1 - 2 * PAD) / max(w_deg, h_deg)
    width, height = int(w_deg * scale + SIZE * 2 * PAD), int(h_deg * scale + SIZE * 2 * PAD)
    off = SIZE * PAD

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        return (lon - lon0) * k * scale + off, (lat1 - lat) * scale + off

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    margin = 0.15  # grados extra para pintar a los vecinos que asoman en el encuadre
    for g in geoms:
        if any(g is t for t in targets):
            continue
        for poly in _polygons(g, arcs):
            ring = poly[0]
            if not any(lon0 - margin <= p[0] <= lon1 + margin and lat0 - margin <= p[1] <= lat1 + margin for p in ring[::4] + ring[-1:]):
                continue
            draw.polygon([to_px(*p) for p in ring], fill=NEIGHBOR)
    for poly in polys:
        draw.polygon([to_px(*p) for p in poly[0]], fill=FILL, outline=OUTLINE)
        for hole in poly[1:]:
            draw.polygon([to_px(*p) for p in hole], fill=(0, 0, 0, 0))
        ring = [to_px(*p) for p in poly[0]]
        draw.line(ring + ring[:1], fill=OUTLINE, width=3, joint="curve")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
