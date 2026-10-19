"""Conexión de un canal de YouTube por OAuth con el `client_secret.json` del propio usuario.

- `parse_client_secret`: valida el JSON de Google Cloud (tipo web o installed) y solo admite los servidores de Google, para que un
  fichero manipulado no pueda hacer que el secreto se envíe a otro host.
- `sign_state` / `verify_state`: el `state` del flujo va firmado (HMAC) con usuario, canal, nonce y caducidad: un `state`
  manipulado o ajeno se rechaza (el repo viejo mandaba el id del canal en claro, inseguro en multiusuario).
- `GoogleClient`: intercambio del código por tokens y lectura del canal (httpx; se sustituye en los tests).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx

from app.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
ALLOWED_AUTH_HOSTS = {"accounts.google.com"}
ALLOWED_TOKEN_HOSTS = {"oauth2.googleapis.com", "accounts.google.com"}
STATE_TTL = 600
CALLBACK_PATH = "/api/youtube/callback"


class SecretError(ValueError):
    """Mensaje pensado para el usuario."""


class OAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClientSecret:
    client_id: str
    client_secret: str
    project_id: str
    auth_uri: str
    token_uri: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @property
    def hint(self) -> str:
        return f"{self.project_id or 'proyecto'} · …{self.client_id[-24:]}"


def parse_client_secret(raw: bytes | str) -> ClientSecret:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise SecretError("El fichero no es un JSON válido") from exc
    if not isinstance(data, dict):
        raise SecretError("El fichero no es un client_secret.json de Google")
    kind = next((k for k in ("web", "installed") if isinstance(data.get(k), dict)), None)
    if kind is None:
        raise SecretError("No parece un client_secret.json de Google Cloud (falta la sección «web» o «installed»)")
    c = data[kind]
    client_id, client_secret = str(c.get("client_id", "")), str(c.get("client_secret", ""))
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        raise SecretError("Faltan el client_id o el client_secret, o no son de Google")
    auth_uri = str(c.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth")
    token_uri = str(c.get("token_uri") or "https://oauth2.googleapis.com/token")
    if urlparse(auth_uri).scheme != "https" or urlparse(auth_uri).hostname not in ALLOWED_AUTH_HOSTS:
        raise SecretError("El auth_uri no es de Google: no se admite")
    if urlparse(token_uri).scheme != "https" or urlparse(token_uri).hostname not in ALLOWED_TOKEN_HOSTS:
        raise SecretError("El token_uri no es de Google: no se admite")
    return ClientSecret(client_id, client_secret, str(c.get("project_id", "")), auth_uri, token_uri)


def redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + CALLBACK_PATH


# --- state firmado ---------------------------------------------------------------------------------

def _key() -> bytes:
    secret = get_settings().jwt_secret
    if not secret:
        raise OAuthError("JWT_SECRET vacío: configúralo en .env")
    return hashlib.sha256(b"oauth-state:" + secret.encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign_state(user_id: int, channel_id: int, *, now: float | None = None) -> str:
    payload = f"{user_id}.{channel_id}.{secrets.token_urlsafe(8)}.{int((now if now is not None else time.time()) + STATE_TTL)}"
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
    return f"{_b64(payload.encode())}.{_b64(sig)}"


def verify_state(state: str, *, now: float | None = None) -> tuple[int, int]:
    """Devuelve (user_id, channel_id) o lanza OAuthError."""
    try:
        body, sig = state.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        payload = base64.urlsafe_b64decode(pad(body))
        expected = hmac.new(_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, base64.urlsafe_b64decode(pad(sig))):
            raise OAuthError("state manipulado")
        user_id, channel_id, _nonce, exp = payload.decode().split(".")
        if (now if now is not None else time.time()) > int(exp):
            raise OAuthError("El enlace de conexión caducó: vuelve a pulsar «Conectar»")
        return int(user_id), int(channel_id)
    except OAuthError:
        raise
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise OAuthError("state no válido") from exc


def build_auth_url(secret: ClientSecret, state: str) -> str:
    params = {
        "client_id": secret.client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "select_account consent", "include_granted_scopes": "true", "state": state,
    }
    return f"{secret.auth_uri}?{urlencode(params)}"


# --- Google ----------------------------------------------------------------------------------------

class GoogleClient:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))

    def exchange_code(self, secret: ClientSecret, code: str) -> dict:
        """Cambia el código por tokens. Devuelve {access_token, refresh_token, expires_at, scope}."""
        try:
            r = self.http.post(secret.token_uri, data={
                "code": code, "client_id": secret.client_id, "client_secret": secret.client_secret,
                "redirect_uri": redirect_uri(), "grant_type": "authorization_code",
            })
        except httpx.HTTPError as exc:
            raise OAuthError(f"No se pudo hablar con Google ({type(exc).__name__})") from exc
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200:
            raise OAuthError(f"Google rechazó el código: {body.get('error_description') or body.get('error') or r.status_code}")
        if not body.get("refresh_token"):
            raise OAuthError("Google no devolvió refresh_token: revoca el acceso de la app en tu cuenta de Google y vuelve a conectar")
        return {"access_token": body["access_token"], "refresh_token": body["refresh_token"], "scope": body.get("scope", ""),
                "expires_at": int(time.time()) + int(body.get("expires_in", 3600))}

    def channel_info(self, access_token: str) -> dict:
        """El canal de la cuenta conectada: {id, title, thumbnail}."""
        try:
            r = self.http.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                              headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise OAuthError(f"No se pudo leer el canal ({type(exc).__name__})") from exc
        if r.status_code != 200:
            raise OAuthError(f"YouTube no dejó leer el canal ({r.status_code})")
        items = r.json().get("items") or []
        if not items:
            raise OAuthError("Esa cuenta de Google no tiene un canal de YouTube")
        snippet = items[0].get("snippet", {})
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("default") or thumbs.get("medium") or {}).get("url")
        return {"id": items[0]["id"], "title": snippet.get("title", ""), "thumbnail": thumb}
