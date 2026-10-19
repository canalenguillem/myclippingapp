"""Subida de un vídeo a YouTube con el token del canal (subida reanudable por trozos).

`YouTubeUploader` es lo único que habla con la API; los tests usan uno falso. Si el acceso caducó se renueva con el
refresh_token y el token nuevo se devuelve para guardarlo.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.services.youtube_oauth import SCOPES, ClientSecret

CHUNK = 8 * 1024 * 1024
CATEGORY_ID = "22"  # «Personas y blogs»


class UploadError(RuntimeError):
    """Mensaje pensado para el usuario."""


@dataclass
class UploadResult:
    video_id: str
    token: dict          # token vigente tras la subida (puede haberse renovado)


def map_http_error(status: int, body: bytes | str) -> str:
    """Traduce un error de la API de YouTube a algo que el usuario pueda entender."""
    try:
        data = json.loads(body)
        reasons = [e.get("reason", "") for e in data.get("error", {}).get("errors", [])]
        message = data.get("error", {}).get("message", "")
    except (ValueError, TypeError, AttributeError):
        reasons, message = [], ""
    for reason, text in (
        ("quotaExceeded", "Se agotó la cuota diaria de la API de YouTube de tu proyecto de Google (unas 6 subidas al día): inténtalo mañana"),
        ("uploadLimitExceeded", "Este canal alcanzó su límite de subidas de hoy: inténtalo más tarde"),
        ("youtubeSignupRequired", "La cuenta de Google conectada no tiene un canal de YouTube"),
        ("forbidden", "YouTube no permite subir con este acceso: reconecta el canal"),
        ("invalidTitle", "YouTube rechazó el título: cámbialo"),
        ("invalidDescription", "YouTube rechazó la descripción: cámbiala"),
        ("invalidTags", "YouTube rechazó las etiquetas: simplifícalas"),
        ("videoTooLong", "El vídeo es demasiado largo para este canal"),
    ):
        if reason in reasons:
            return text
    if status == 401:
        return "El acceso del canal caducó o fue revocado: vuelve a conectarlo en Canales"
    return f"YouTube respondió {status}" + (f": {message}" if message else "")


class YouTubeUploader:
    def upload(
        self, *, secret: ClientSecret, token: dict, video: Path, title: str, description: str, tags: list[str], language: str,
        privacy: str, publish_at: datetime | None, on_progress: Callable[[float], None] | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> UploadResult:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        creds = Credentials(
            token=token.get("access_token"), refresh_token=token.get("refresh_token"), token_uri=secret.token_uri,
            client_id=secret.client_id, client_secret=secret.client_secret, scopes=SCOPES,
        )
        creds.expiry = datetime.fromtimestamp(int(token.get("expires_at", 0)), timezone.utc).replace(tzinfo=None)
        try:
            if not creds.valid:
                creds.refresh(Request())
            youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
            status: dict = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
            if publish_at is not None:
                status.update(privacyStatus="private", publishAt=publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            body = {"snippet": {"title": title, "description": description, "tags": tags, "categoryId": CATEGORY_ID, "defaultLanguage": language},
                    "status": status}
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=CHUNK, resumable=True))
            response = None
            while response is None:
                if cancel_check:
                    cancel_check()
                progress, response = request.next_chunk()
                if progress and on_progress:
                    on_progress(progress.progress())
        except RefreshError as exc:
            raise UploadError("Google no renovó el acceso (revocado o caducado): vuelve a conectar el canal en Canales") from exc
        except HttpError as exc:
            raise UploadError(map_http_error(exc.resp.status, exc.content)) from exc
        video_id = (response or {}).get("id")
        if not video_id:
            raise UploadError("YouTube no devolvió el identificador del vídeo")
        expiry = creds.expiry.replace(tzinfo=timezone.utc).timestamp() if creds.expiry else token.get("expires_at", 0)
        return UploadResult(video_id, {**token, "access_token": creds.token, "refresh_token": creds.refresh_token or token.get("refresh_token"), "expires_at": int(expiry)})


def make_uploader() -> YouTubeUploader:
    return YouTubeUploader()
