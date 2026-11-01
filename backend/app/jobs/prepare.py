"""Job `prepare`: deja un clip listo con UN clic. Hace, en orden, lo que antes eran siete pasos a mano en el editor:
cortinilla de inicio activada, pantallas compartidas detectadas, gráficos sugeridos por la IA, clip aprobado y render final encolado;
y si se pidió publicar, marca la publicación automática (SEO + subida al terminar el render, con las mismas salvaguardas)."""
from __future__ import annotations

from fastapi import HTTPException

from app.db.models import Clip, Project, RenderState, User
from app.jobs import queue
from app.pipeline import screens as screens_mod
from app.services import clips as clips_service
from app.services import source as source_service
from app.services import storage, video_download

from .context import JobContext


class PrepareError(RuntimeError):
    pass


def prepare(ctx: JobContext, payload: dict) -> None:
    from app.routers import clips as clips_router      # la sugerencia de gráficos es la misma lógica del botón del editor

    db = ctx.db
    clip = db.get(Clip, int(payload["clip_id"]))
    if clip is None or clip.user_id != ctx.user_id:
        raise PrepareError("Clip no encontrado")
    if clip.status not in ("detected", "approved") or clip.render_state is RenderState.RENDERING:
        raise PrepareError(f"El clip está «{clip.status}»/{clip.render_state.value}: no se puede preparar ahora")
    project = db.get(Project, clip.project_id)
    user = db.get(User, ctx.user_id)
    privacy = payload.get("privacy")
    ctx.log(f"Preparando el clip {clip.id}: {clip.hook or clip.title}" + (f" · se publicará ({privacy}) al acabar el render" if privacy else " · sin publicar"))

    if clip.draft_path or clip.rendered_path:
        clips_service.invalidate_render(clip)           # lo que se va a cambiar deja obsoleto el render anterior
    ctx.progress(5)

    clip.intro_enabled, clip.cortinilla_at = True, None   # cortinilla de inicio activada, en la posición automática
    ctx.log("Cortinilla de inicio: activada")
    db.commit()                      # `check_cancelled` hace expire_all(): lo que no esté guardado se perdería

    ctx.check_cancelled()
    try:
        video = source_service.ensure_source(project, ctx.log)
        db.commit()
        clip.screen_ranges = screens_mod.detect(video, clip.start, clip.end)
        ctx.log(f"Pantallas compartidas (tuits, webs): {len(clip.screen_ranges)} tramo(s)")
    except (video_download.DownloadError, screens_mod.ScreenError, OSError) as exc:
        ctx.log(f"No se pudieron buscar pantallas compartidas ({exc}); se sigue sin ellas")
    db.commit()
    ctx.progress(30)

    ctx.check_cancelled()
    if not clip.graphics_json:
        try:
            result = clips_router.suggest_graphics(clip.id, clips_router.PlanIn(graphics=[]), user, db)
            beats = [{k: v for k, v in b.items() if k != "reason"} for b in result["beats"]]
            clip.graphics_json = clips_router._beats([clips_router.GraphicIn(**b) for b in beats])
            ctx.log(f"Gráficos sugeridos ({result['source']}): {len(clip.graphics_json)}" + ("".join(f" · {n}" for n in result["notes"])))
        except HTTPException as exc:
            ctx.log(f"No se pudieron sugerir gráficos ({exc.detail}); se sigue sin ellos")
    else:
        ctx.log(f"Gráficos: se conservan los {len(clip.graphics_json)} que ya tenía")
    ctx.progress(70)

    clip.status = "approved"
    clip.auto_publish = privacy if privacy in ("public", "unlisted", "private") else None
    queue.enqueue(db, ctx.user_id, "render", {"clip_id": clip.id, "project_id": project.id, "quality": "final"})
    clip.render_state, clip.render_error, clip.upload_error = RenderState.RENDERING, None, None
    db.commit()
    ctx.log("Clip aprobado y render final encolado" + (": al terminar se publicará solo" if clip.auto_publish else ""))
    ctx.progress(100)
