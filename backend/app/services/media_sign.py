"""URLs firmadas y con caducidad para <video>/<img>, que no pueden mandar cabeceras ni CSRF.

La firma cubre la ruta (relativa a MEDIA_DIR) y la caducidad. La autorización real ocurre al FIRMAR: solo los
endpoints que comprueban que el recurso es del usuario (`get_owned`) generan una URL.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import quote

from app.config import get_settings

DEFAULT_TTL = 3600


def _key() -> bytes:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET vacío: configúralo en .env")
    return hashlib.sha256(b"media:" + secret.encode()).digest()  # clave derivada: no se reutiliza la del JWT


def sign(rel: str, exp: int) -> str:
    return hmac.new(_key(), f"{rel}\n{exp}".encode(), hashlib.sha256).hexdigest()


def verify(rel: str, exp: int, sig: str) -> bool:
    return time.time() <= exp and hmac.compare_digest(sign(rel, exp), sig)


def signed_url(rel: str, ttl: int = DEFAULT_TTL) -> dict:
    exp = int(time.time()) + ttl
    return {"url": f"/api/media/{quote(rel)}?exp={exp}&sig={sign(rel, exp)}", "expires_in": ttl}
