"""Cifrado de secretos en la BD (client_secret y tokens de YouTube) con Fernet. La clave va en `APP_ENCRYPTION_KEY` (.env)."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().app_encryption_key
    if not key:
        raise CryptoError("APP_ENCRYPTION_KEY está vacía: configúrala en .env")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CryptoError("APP_ENCRYPTION_KEY no es una clave Fernet válida") from exc


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("No se pudo descifrar (¿cambió APP_ENCRYPTION_KEY?)") from exc


def encrypt_json(data: dict) -> str:
    return encrypt(json.dumps(data, separators=(",", ":")))


def decrypt_json(token: str) -> dict:
    return json.loads(decrypt(token))
