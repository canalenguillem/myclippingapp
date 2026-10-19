"""Canales de YouTube del usuario: cada uno con su propio `client_secret.json` (cambiable) y su conexión OAuth."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.config import get_settings
from app.db import get_db
from app.db.models import User, YouTubeChannel
from app.services import crypto, youtube_oauth

router = APIRouter(prefix="/api/channels", tags=["channels"])
callback_router = APIRouter(prefix="/api/youtube", tags=["channels"])
google = youtube_oauth.GoogleClient()
MAX_SECRET_BYTES = 20_000
MAX_CHANNELS = 10


class ChannelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    language: str = Field(default="es", pattern=r"^[a-z]{2}$")
    default_privacy: Literal["private", "unlisted", "public"] = "private"
    seo_rules: str = Field(default="", max_length=2000)


class ChannelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    default_privacy: Literal["private", "unlisted", "public"] | None = None
    seo_rules: str | None = Field(default=None, max_length=2000)


class ChannelOut(BaseModel):
    id: int
    name: str
    language: str
    default_privacy: str
    seo_rules: str
    has_secret: bool
    secret_hint: str | None
    linked: bool
    yt_title: str | None
    yt_thumbnail: str | None
    yt_channel_id: str | None
    linked_at: datetime | None
    redirect_uri: str  # el que hay que registrar en Google Cloud


def _hint(ch: YouTubeChannel) -> str | None:
    if not ch.client_secret_enc:
        return None
    try:
        return youtube_oauth.ClientSecret(**crypto.decrypt_json(ch.client_secret_enc)).hint
    except (crypto.CryptoError, TypeError, ValueError):
        return "ilegible (¿cambió la clave de cifrado?): sube el JSON otra vez"


def _out(ch: YouTubeChannel) -> ChannelOut:
    return ChannelOut(id=ch.id, name=ch.name, language=ch.language, default_privacy=ch.default_privacy, seo_rules=ch.seo_rules,
                      has_secret=bool(ch.client_secret_enc), secret_hint=_hint(ch), linked=bool(ch.token_enc), yt_title=ch.yt_title,
                      yt_thumbnail=ch.yt_thumbnail, yt_channel_id=ch.yt_channel_id, linked_at=ch.linked_at, redirect_uri=youtube_oauth.redirect_uri())


def _unlink(ch: YouTubeChannel) -> None:
    ch.token_enc, ch.yt_channel_id, ch.yt_title, ch.yt_thumbnail, ch.linked_at = None, None, None, None, None


@router.get("", response_model=list[ChannelOut])
def list_channels(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(c) for c in db.scalars(select(YouTubeChannel).where(YouTubeChannel.user_id == user.id).order_by(YouTubeChannel.id)).all()]


@router.post("", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if len(db.scalars(select(YouTubeChannel.id).where(YouTubeChannel.user_id == user.id)).all()) >= MAX_CHANNELS:
        raise HTTPException(409, f"Máximo {MAX_CHANNELS} canales")
    ch = YouTubeChannel(user_id=user.id, name=body.name.strip(), language=body.language, default_privacy=body.default_privacy, seo_rules=body.seo_rules)
    db.add(ch)
    db.commit()
    return _out(ch)


@router.patch("/{channel_id}", response_model=ChannelOut)
def patch_channel(channel_id: int, body: ChannelPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(ch, field, value.strip() if field == "name" else value)
    db.commit()
    return _out(ch)


@router.delete("/{channel_id}", status_code=204)
def delete_channel(channel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    db.delete(ch)
    db.commit()


@router.put("/{channel_id}/client-secret", response_model=ChannelOut)
async def put_client_secret(channel_id: int, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Sube o REEMPLAZA el client_secret.json del canal. Con otro JSON, el token anterior ya no vale: hay que volver a conectar."""
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    data = await file.read(MAX_SECRET_BYTES + 1)
    if len(data) > MAX_SECRET_BYTES:
        raise HTTPException(422, "El fichero es demasiado grande para ser un client_secret.json")
    try:
        secret = youtube_oauth.parse_client_secret(data)
    except youtube_oauth.SecretError as exc:
        raise HTTPException(422, str(exc)) from exc
    ch.client_secret_enc = crypto.encrypt_json(secret.to_dict())
    _unlink(ch)
    db.commit()
    return _out(ch)


@router.delete("/{channel_id}/client-secret", response_model=ChannelOut)
def delete_client_secret(channel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    ch.client_secret_enc = None
    _unlink(ch)
    db.commit()
    return _out(ch)


@router.get("/{channel_id}/oauth/start")
def oauth_start(channel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """URL de Google para conectar el canal (el navegador va a ella). Pide siempre elegir cuenta y dar el permiso."""
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    if not ch.client_secret_enc:
        raise HTTPException(409, "Sube primero el client_secret.json de este canal")
    try:
        secret = youtube_oauth.ClientSecret(**crypto.decrypt_json(ch.client_secret_enc))
    except (crypto.CryptoError, TypeError, ValueError) as exc:
        raise HTTPException(409, "No se puede leer el client_secret guardado: súbelo otra vez") from exc
    return {"url": youtube_oauth.build_auth_url(secret, youtube_oauth.sign_state(user.id, ch.id)), "redirect_uri": youtube_oauth.redirect_uri()}


@router.post("/{channel_id}/refresh", response_model=ChannelOut)
def refresh_channel(channel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Vuelve a leer de YouTube el nombre y el avatar del canal conectado (p. ej. tras renombrarlo). Renueva el acceso si hace falta."""
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    if not ch.token_enc or not ch.client_secret_enc:
        raise HTTPException(409, "El canal no está conectado")
    try:
        secret = youtube_oauth.ClientSecret(**crypto.decrypt_json(ch.client_secret_enc))
        token = crypto.decrypt_json(ch.token_enc)
        if int(token.get("expires_at", 0)) < time.time() + 60:
            token = google.refresh(secret, token)
            ch.token_enc = crypto.encrypt_json(token)
        info = google.channel_info(token["access_token"])
    except (youtube_oauth.OAuthError, crypto.CryptoError, TypeError, ValueError, KeyError) as exc:
        raise HTTPException(502, str(exc)) from exc
    ch.yt_channel_id, ch.yt_title, ch.yt_thumbnail = info["id"], info["title"], info["thumbnail"]
    db.commit()
    return _out(ch)


@router.delete("/{channel_id}/token", response_model=ChannelOut)
def disconnect(channel_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch = get_owned(db, YouTubeChannel, channel_id, user)
    _unlink(ch)
    db.commit()
    return _out(ch)


def _back(**params) -> RedirectResponse:
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return RedirectResponse(f"{get_settings().public_base_url.rstrip('/')}/channels?{query}", status_code=303)


@callback_router.get("/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    """Vuelta de Google. El `state` firmado fija a qué canal y usuario pertenece; uno manipulado o ajeno se rechaza."""
    try:
        user_id, channel_id = youtube_oauth.verify_state(state or "")
    except youtube_oauth.OAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    if user_id != user.id:
        raise HTTPException(400, "El enlace de conexión es de otro usuario")
    ch = db.get(YouTubeChannel, channel_id)
    if ch is None or ch.user_id != user.id:
        raise HTTPException(404, "Canal no encontrado")
    if error or not code:
        return _back(error="Google no concedió el permiso" if error == "access_denied" else (error or "Falta el código de Google"))
    try:
        secret = youtube_oauth.ClientSecret(**crypto.decrypt_json(ch.client_secret_enc or ""))
        token = google.exchange_code(secret, code)
        info = google.channel_info(token["access_token"])
    except (youtube_oauth.OAuthError, crypto.CryptoError, TypeError, ValueError) as exc:
        return _back(error=str(exc))
    ch.token_enc = crypto.encrypt_json(token)
    ch.yt_channel_id, ch.yt_title, ch.yt_thumbnail, ch.linked_at = info["id"], info["title"], info["thumbnail"], datetime.utcnow()
    db.commit()
    return _back(linked=ch.id)
