"""Job `render`: un clip → vídeo vertical con capas de estilo (borrador o final).

Pasos: vertical con ffmpeg → análisis (subtítulos quemados) → servicio de render (HyperFrames) o, si no está,
subtítulos ASS con ffmpeg → miniatura → estado del clip. El estado de render (`Clip.render_state`) va aparte del
editorial: un clip sigue «detectado» o «aprobado» mientras se renderiza.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable

from app.db.models import BrandTemplate, Clip, Project, RenderState
from app.jobs import queue
from app.pipeline import analysis as analysis_mod
from app.pipeline import ass_fallback, ffops, vertical
from app.services import clips as clips_service
from app.services import fx_request, storage, transcription
from app.services.fx_client import FxError, make_fx_client

from .context import Cancelled, JobContext

DEFAULT_PRESET = "editorial"
CANCEL_POLL_SECONDS = 1.0


class RenderError(RuntimeError):
    pass


def _stage(ctx: JobContext, lo: int, hi: int) -> Callable[[float], None]:
    """Callback de progreso 0..1 que mapea a [lo, hi] del progreso del job, sin repetir valores."""
    last = {"v": -1}

    def report(fraction: float) -> None:
        value = int(lo + max(0.0, min(1.0, fraction)) * (hi - lo))
        if value != last["v"]:
            last["v"] = value
            ctx.progress(value)

    return report


def _cancel_check(ctx: JobContext) -> Callable[[], None]:
    """Comprueba la cancelación como mucho una vez por segundo (cada comprobación es una consulta a la BD)."""
    last = {"t": 0.0}

    def check() -> None:
        now = time.monotonic()
        if now - last["t"] >= CANCEL_POLL_SECONDS:
            last["t"] = now
            ctx.check_cancelled()

    return check


def _settled_state(clip: Clip) -> RenderState:
    """Estado al que volver si el render se cancela: el que correspondería a los ficheros que quedan."""
    if clip.rendered_path:
        return RenderState.FINAL
    if clip.draft_path:
        return RenderState.DRAFT
    return RenderState.NONE


def render(ctx: JobContext, payload: dict) -> None:
    db = ctx.db
    clip = db.get(Clip, int(payload["clip_id"]))
    if clip is None or clip.user_id != ctx.user_id:
        raise RenderError("Clip no encontrado")
    quality = payload.get("quality", "draft")
    if quality not in fx_request.QUALITY:
        raise RenderError(f"Calidad de render no válida: {quality!r}")
    draft = quality == "draft"
    project = db.get(Project, clip.project_id)

    def fail(message: str) -> None:
        clip.render_state, clip.render_error = RenderState.FAILED, message[:2000]
        db.commit()

    try:
        if not draft and clip.status != "approved":
            raise RenderError("El render final solo se hace con el clip aprobado")
        if clip.layout != "split":
            raise RenderError(f"Solo se renderiza el diseño partido (split); este clip usa «{clip.layout}»")
        if not project.video_path or not project.words_path:
            raise RenderError("El proyecto aún no tiene vídeo y transcripción")
        source = storage.absolute(project.video_path)
        if not source.is_file():
            raise RenderError("No se encuentra el vídeo de origen en el disco")
    except RenderError as exc:
        fail(str(exc))
        raise

    clip.render_state, clip.render_error = RenderState.RENDERING, None
    db.commit()
    folder = storage.project_dir(project.user_id, project.id) / f"clip_{clip.id}"
    folder.mkdir(parents=True, exist_ok=True)
    duration = round(clip.end - clip.start, 3)
    width, height = vertical.canvas_for(draft)
    cancel = _cancel_check(ctx)
    vertical_path, fx_full = folder / f"vertical_{quality}.mp4", folder / "fx_full.mp4"
    target = folder / ("draft.mp4" if draft else "final.mp4")
    warning: str | None = None
    try:
        ctx.log(f"Render {'borrador' if draft else 'final'} del clip {clip.id}: {clip.start:.2f}–{clip.end:.2f} s ({duration:.1f} s)")
        vertical.make_vertical_clip(source, clip.start, clip.end, vertical_path, top_ratio=clip.top_ratio, focus=clip.focus,
                                    zoom=clip.zoom, draft=draft, on_progress=_stage(ctx, 0, 20), cancel_check=cancel)
        ctx.log("Clip vertical listo")

        try:
            band = analysis_mod.detect_burned_subtitles(vertical_path, top_ratio=clip.top_ratio, duration=duration)
        except analysis_mod.AnalysisError as exc:
            ctx.log(f"No se pudo analizar el clip ({exc}); la banda irá centrada")
            band = None
        analysis_file = folder / "analysis.json"
        analysis_file.write_text(json.dumps({"version": 1, "burned_subtitles": band}), encoding="utf-8")
        clip.analysis_path = storage.rel(analysis_file)
        ctx.log("Subtítulos quemados detectados en las filas " + (f"{band['y0']}–{band['y1']} (confianza {band['confidence']})" if band else "—: ninguno"))
        ctx.progress(25)

        words = fx_request.clip_words(transcription.load_words(storage.absolute(project.words_path))["words"], clip.start, clip.end)
        template = db.get(BrandTemplate, clip.template_id) if clip.template_id else None
        preset = template.preset if template and template.user_id == ctx.user_id else DEFAULT_PRESET
        request = fx_request.build_fx_request(
            video=storage.rel(vertical_path), output=storage.rel(target if not draft else fx_full), quality=quality,
            duration=duration, top_ratio=clip.top_ratio, words=words, speakers=project.speakers, hook=clip.hook,
            preset=preset, band=band,
        )

        client = make_fx_client()
        if client is None:
            warning = "FX_WORKER_URL no está configurado"
        else:
            try:
                ctx.log(f"Enviando al servicio de render ({len(words)} palabras, preset {preset})")
                result = client.render(request, on_progress=_stage(ctx, 25, 92 if draft else 95), cancel_check=cancel)
                ctx.log(f"Servicio de render: listo en {result.seconds or 0:.0f} s")
            except FxError as exc:
                warning = str(exc)
        if warning:
            ctx.log(f"{warning}: se usan subtítulos ASS con ffmpeg (sin banda, estilos ni gancho)")
            ass_fallback.burn_subtitles(vertical_path, words, target, duration=duration, width=width, height=height,
                                        top_ratio=clip.top_ratio, draft=draft, on_progress=_stage(ctx, 25, 92), cancel_check=cancel)
        elif draft:
            ffops.downscale(fx_full, target, width=width, height=height, duration=duration, on_progress=_stage(ctx, 92, 97), cancel_check=cancel)

        thumb = folder / "thumb.jpg"
        ffops.make_thumbnail(target, thumb, at=min(duration * 0.35, max(0.0, duration - 0.2)))
        ctx.progress(98)

        if draft:
            clip.draft_path = storage.rel(target)
        else:
            clip.rendered_path = storage.rel(target)
        clip.render_state = _settled_state(clip)  # FINAL si existe el final, aunque lo último que se hizo fuera un borrador
        clip.thumbnail_path = storage.rel(thumb)
        clip.rendered_at = queue.utcnow()
        clip.render_error = f"Aviso: {warning}; se usaron subtítulos simples" if warning else None
        db.commit()
        ctx.log("Render terminado")
    except Cancelled:
        clip.render_state, clip.render_error = _settled_state(clip), None
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        vertical_path.unlink(missing_ok=True)
        fx_full.unlink(missing_ok=True)
