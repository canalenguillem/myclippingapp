"""Publicar en YouTube sin intervención: al acabar el render final de un clip marcado con `auto_publish` se generan los textos SEO
(con el @ y el enlace del vídeo original) y se encola la subida con la privacidad elegida.

Salvaguardas: solo clips aprobados con canal conectado; si la revisión automática del render encontró fallos, NO se publica y
el motivo queda en `upload_error` (el clip sigue aprobado y con su render, para revisarlo a mano)."""
from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.models import Clip, Project, RenderState, YouTubeChannel
from app.jobs import queue
from app.services import seo as seo_service
from app.services import storage

PRIVACIES = ("public", "unlisted", "private")


class PublishBlocked(RuntimeError):
    """Motivo (para el usuario) por el que no se publica."""


def _qa_errors(clip: Clip, project: Project) -> list[str]:
    degraded = ["El render salió con el plan B de subtítulos (sin banda, estilos ni cortinillas): vuelve a renderizarlo"] if "subtítulos simples" in (clip.render_error or "") else []
    report = storage.project_dir(project.user_id, project.id) / f"clip_{clip.id}" / "qa_final.json"
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return degraded                # sin informe (la revisión no pudo ejecutarse): no bloquea por eso
    return degraded + [c["message"] for c in data.get("checks", []) if c.get("level") == "error"]


def publish_now(db: Session, clip: Clip, log: Callable[[str], None], *, generate: Callable[..., seo_service.Seo] = seo_service.generate) -> int:
    """Genera los textos, comprueba y encola la subida del final. Devuelve el id del job de subida; lanza PublishBlocked si no procede."""
    project = db.get(Project, clip.project_id)
    if clip.auto_publish not in PRIVACIES:
        raise PublishBlocked("El clip no tiene activada la publicación automática")
    if clip.status == "uploaded" or clip.youtube_video_id:
        raise PublishBlocked("El clip ya está subido a YouTube")
    if clip.status != "approved":
        raise PublishBlocked(f"El clip está «{clip.status}»: solo se publican clips aprobados")
    if clip.render_state is not RenderState.FINAL or not clip.rendered_path or not storage.absolute(clip.rendered_path).is_file():
        raise PublishBlocked("El clip no tiene un render final vigente")
    channel = db.get(YouTubeChannel, clip.channel_id) if clip.channel_id else None
    if channel is None or channel.user_id != clip.user_id:
        raise PublishBlocked("El clip no tiene canal de YouTube: elígelo en el proyecto")
    if not channel.token_enc:
        raise PublishBlocked("El canal no está conectado a YouTube: conéctalo en Canales")
    errors = _qa_errors(clip, project)
    if errors:
        raise PublishBlocked("La revisión automática del render encontró fallos, no se publicó: " + "; ".join(errors))

    if not clip.seo_title.strip():
        log("Generando los textos SEO…")
        seo = generate(title=clip.title, hook=clip.hook, reason=clip.reason, transcript=clip.transcript,
                       emphasis=[e.get("text", "") for e in clip.emphasis_json or []], channel_name=channel.yt_title or channel.name,
                       language=channel.language, seo_rules=channel.seo_rules or "")
        description = seo_service.with_source(seo.description, handle=project.source_handle, url=project.source_url, start=clip.start)
        clean = seo_service.clean(seo_service.Seo(seo.title, description, seo.tags))
        clip.seo_title, clip.seo_description, clip.seo_tags = clean.title, clean.description, ",".join(clean.tags)
        log(f"Textos listos ({seo.source}): {clean.title}")
    clip.privacy, clip.publish_at = clip.auto_publish, None
    job = queue.enqueue(db, clip.user_id, "upload", {"clip_id": clip.id, "project_id": clip.project_id, "source": "final"})
    clip.status, clip.upload_error = "uploading", None
    db.commit()
    log(f"Subida encolada ({clip.privacy})")
    return job.id
