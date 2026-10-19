"""Cliente del worker de ASD (detección de quién habla, TalkNet en GPU).

Se le sube el tramo del clip y devuelve a qué altura del plano está cada cara y quién habla en cada momento.
Cualquier fallo (sin URL, worker apagado, error) devuelve None: el render cae a las posiciones de los speakers."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import get_settings


def configured() -> bool:
    return bool(get_settings().asd_worker_url.strip())


def fetch_segments(video: Path, cache: Path | None = None) -> dict | None:
    if cache and cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # caché corrupta: se recalcula
    url = get_settings().asd_worker_url.strip().rstrip("/")
    if not url or not video.is_file():
        return None
    try:
        with video.open("rb") as fh:
            resp = httpx.post(f"{url}/asd", files={"file": (video.name, fh, "video/mp4")},
                              timeout=httpx.Timeout(1800.0, connect=5.0))
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, OSError, ValueError):
        return None
    if cache:
        try:
            cache.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
    return data
