import hmac
import secrets
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_ph = PasswordHasher()
JWT_ALG = "HS256"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 dias


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise RuntimeError("JWT_SECRET vacio: configuralo en .env")
    return secret


def make_session_token(user_id: int, csrf: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "csrf": csrf, "iat": now, "exp": now + SESSION_TTL}, _secret(), JWT_ALG)


def read_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(cookie_value: str | None, header_value: str | None, token_csrf: str) -> bool:
    """Doble envio: la cabecera debe coincidir con la cookie Y con el valor firmado en el JWT."""
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value) and hmac.compare_digest(header_value, token_csrf)
