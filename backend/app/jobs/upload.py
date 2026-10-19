"""Job `upload`: sube el vídeo final de un clip aprobado al canal elegido, con los textos SEO ya guardados."""
from __future__ import annotations

from app.db.models import Clip, YouTubeChannel
from app.jobs import queue
from app.services import crypto, storage
from app.services.youtube_oauth import ClientSecret
from app.services.youtube_upload import UploadError, make_uploader

from .context import Cancelled, JobContext


class UploadJobError(RuntimeError):
    pass


def upload(ctx: JobContext, payload: dict) -> None:
    db = ctx.db
    clip = db.get(Clip, int(payload["clip_id"]))
    if clip is None or clip.user_id != ctx.user_id:
        raise UploadJobError("Clip no encontrado")
    if clip.youtube_video_id:  # reintento tras haberse subido ya: no se duplica el vídeo
        ctx.log(f"El clip ya está en YouTube ({clip.youtube_video_id}); no se sube otra vez")
        clip.status = "uploaded"
        db.commit()
        return

    def fail(message: str) -> None:
        clip.status, clip.upload_error = "approved", message[:2000]
        db.commit()

    channel = db.get(YouTubeChannel, clip.channel_id) if clip.channel_id else None
    try:
        if channel is None or channel.user_id != ctx.user_id:
            raise UploadJobError("El canal de destino ya no existe")
        if not channel.token_enc or not channel.client_secret_enc:
            raise UploadJobError("El canal no está conectado: conéctalo en Canales")
        if not clip.rendered_path:
            raise UploadJobError("El clip no tiene render final")
        video = storage.absolute(clip.rendered_path)
        if not video.is_file():
            raise UploadJobError("No se encuentra el vídeo final en el disco")
        secret = ClientSecret(**crypto.decrypt_json(channel.client_secret_enc))
        token = crypto.decrypt_json(channel.token_enc)
    except (UploadJobError, crypto.CryptoError, TypeError, ValueError) as exc:
        fail(str(exc))
        raise UploadJobError(str(exc)) from exc

    ctx.log(f"Subiendo a «{channel.yt_title or channel.name}» ({'programado' if clip.publish_at else clip.privacy}): {clip.seo_title}")
    last = {"p": -1}

    def on_progress(fraction: float) -> None:
        percent = 5 + int(fraction * 90)
        if percent != last["p"]:
            last["p"] = percent
            ctx.progress(percent)

    try:
        result = make_uploader().upload(
            secret=secret, token=token, video=video, title=clip.seo_title, description=clip.seo_description,
            tags=[t for t in (clip.seo_tags or "").split(",") if t.strip()], language=channel.language, privacy=clip.privacy,
            publish_at=clip.publish_at, on_progress=on_progress, cancel_check=ctx.check_cancelled,
        )
    except Cancelled:
        clip.status, clip.upload_error = "approved", None
        db.commit()
        raise
    except UploadError as exc:
        fail(str(exc))
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise
    # primero lo importante: el id del vídeo (si el resto falla, el reintento no duplica la subida)
    clip.youtube_video_id, clip.status, clip.uploaded_at, clip.upload_error = result.video_id, "uploaded", queue.utcnow(), None
    channel.token_enc = crypto.encrypt_json(result.token)  # puede haberse renovado el acceso
    db.commit()
    ctx.log(f"Subido: https://www.youtube.com/shorts/{result.video_id}")
