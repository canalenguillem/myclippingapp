"""Job `render`: un clip → vídeo vertical con capas de estilo (borrador o final).

Pasos: vertical con ffmpeg → análisis (subtítulos quemados) → servicio de render (HyperFrames) o, si no está,
subtítulos ASS con ffmpeg → miniatura → estado del clip. El estado de render (`Clip.render_state`) va aparte del
editorial: un clip sigue «detectado» o «aprobado» mientras se renderiza.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable

from app.db.models import Asset, BrandTemplate, Clip, Project, RenderState
from app.jobs import queue
from app.pipeline import analysis as analysis_mod
from app.pipeline import ass_fallback, ffops, vertical
from app.pipeline import focus as focus_mod
from app.services import asd_client
from app.services import qa as qa_service
from app.services import clips as clips_service
from app.services import cortinilla as cortinilla_service
from app.services import fx_request, graphics_schedule, silences as silences_mod, storage, transcription
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


def _load_silences(project: Project, clip: Clip) -> list[dict]:
    """Silencios del vídeo entero que tocan el clip, relativos a su inicio. Sin fichero, sin silencios."""
    if not project.silences_path:
        return []
    try:
        return cortinilla_service.rebase_silences(silences_mod.load_silences(storage.absolute(project.silences_path)), clip.start, clip.end)
    except (OSError, ValueError):
        return []


def _resolve_images(db, user_id: int, beats: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cambia `asset_id` por la ruta de la imagen (solo del usuario y si existe en disco); el resto se descarta con motivo."""
    out: list[dict] = []
    missing: list[dict] = []
    for beat in beats:
        if not isinstance(beat, dict) or beat.get("type") != "image":
            out.append(beat)
            continue
        asset = db.get(Asset, beat.get("asset_id") or 0)
        path = None
        if asset is not None and asset.user_id == user_id and asset.path:
            try:
                path = asset.path if storage.absolute(asset.path).is_file() else None
            except ValueError:
                path = None
        if path is None:
            missing.append({"beat": beat, "reason": "la imagen ya no existe en la librería"})
            continue
        resolved = {k: v for k, v in beat.items() if k != "asset_id"}
        resolved["image"] = path
        out.append(resolved)
    return out, missing


def _qa(ctx, folder, target, quality: str, expected: float, plan) -> None:
    """Revisión automática y hoja de contactos del render. Nunca tumba el render: si algo falla, solo se anota en el log."""
    try:
        ffops.contact_sheet(target, folder / f"contact_{quality}.jpg", duration=expected)
        results = qa_service.check(target, expected_duration=expected, beats=plan.beats, dropped=plan.dropped)
        (folder / f"qa_{quality}.json").write_text(json.dumps({"quality": quality, "checks": results, "level": qa_service.worst(results)}), encoding="utf-8")
        bad = [r["message"] for r in results if r["level"] != "ok"]
        ctx.log("Revisión automática: " + ("; ".join(bad) if bad else "todo correcto"))
    except Exception as exc:  # noqa: BLE001
        ctx.log(f"No se pudo hacer la revisión automática ({type(exc).__name__}: {exc})")


def _speaker_track(ctx, clip, project, source, folder, words, cancel) -> list[tuple[float, float]]:
    """Recorrido del encuadre «Sigue al hablante». Con worker de ASD (GPU) se detecta quién habla y dónde está su cara;
    sin él, o si falla, se usan las posiciones de los speakers (slider) y la diarización de la transcripción."""
    if asd_client.configured():
        cache = folder / f"asd_{clip.start:.3f}_{clip.end:.3f}.json"
        data = None
        try:
            raw = folder / "asd_input.mp4"
            if not cache.is_file():
                ctx.log("Detectando quién habla (worker de GPU)…")
                ffops.cut_for_analysis(source, clip.start, clip.end, raw, cancel_check=cancel)
            data = asd_client.fetch_segments(raw, cache)
            raw.unlink(missing_ok=True)
        except (ffops.FfopsError, OSError) as exc:
            ctx.log(f"No se pudo preparar el tramo para el worker de ASD ({exc})")
        if data and data.get("speakers"):
            track = focus_mod.track_from_asd(data)
            ctx.log("Encuadre que sigue al hablante (detección de cara): " + ", ".join(f"{t:.1f} s → {x:.2f}" for t, x in track))
            return track
        ctx.log("El worker de ASD no respondió o no vio caras; se usan las posiciones de los speakers")
    track = focus_mod.build_track(words, project.speakers)
    ctx.log("Encuadre que sigue al hablante (posiciones de los speakers): " + ", ".join(f"{t:.1f} s → {x:.2f}" for t, x in track))
    return track


def _orbit_path(db, template: BrandTemplate | None, user_id: int) -> str | None:
    """Imagen que orbita en la cortinilla: la de la librería que eligió el usuario en la plantilla (si es suya y existe en el
    disco) o, si no, el `logo_path` de la plantilla."""
    if not template:
        return None
    asset_id = (template.cortinilla or {}).get("orbit_asset_id")
    if asset_id:
        asset = db.get(Asset, int(asset_id))
        if asset is not None and asset.user_id == user_id and asset.path:
            try:
                if storage.absolute(asset.path).is_file():
                    return asset.path
            except ValueError:
                pass
    if not template.logo_path:
        return None
    try:
        return template.logo_path if storage.absolute(template.logo_path).is_file() else None
    except ValueError:
        return None


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
        if clip.layout not in vertical.LAYOUTS:
            raise RenderError(f"Solo se renderizan los diseños partido (split) y pantalla completa (full); este clip usa «{clip.layout}»")
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
        words = fx_request.clip_words(transcription.load_words(storage.absolute(project.words_path))["words"], clip.start, clip.end)
        track = _speaker_track(ctx, clip, project, source, folder, words, cancel) if clip.focus == vertical.SPEAKER else None
        vertical.make_vertical_clip(source, clip.start, clip.end, vertical_path, top_ratio=clip.top_ratio, focus=clip.focus, track=track,
                                    zoom=clip.zoom, layout=clip.layout, draft=draft, on_progress=_stage(ctx, 0, 20), cancel_check=cancel)
        ctx.log("Clip vertical listo")

        band = None
        if clip.layout == "full":
            # los subtítulos van siempre en la zona difuminada de abajo: da igual que el vídeo original traiga los suyos
            ctx.log("Pantalla completa: la banda de subtítulos va en la zona difuminada de abajo")
        else:
            try:
                band = analysis_mod.detect_burned_subtitles(vertical_path, top_ratio=clip.top_ratio, duration=duration)
            except analysis_mod.AnalysisError as exc:
                ctx.log(f"No se pudo analizar el clip ({exc}); la banda irá centrada")
            ctx.log("Subtítulos quemados detectados en las filas " + (f"{band['y0']}–{band['y1']} (confianza {band['confidence']})" if band else "—: ninguno"))
        analysis_file = folder / "analysis.json"
        analysis_file.write_text(json.dumps({"version": 1, "burned_subtitles": band}), encoding="utf-8")
        clip.analysis_path = storage.rel(analysis_file)
        ctx.progress(25)

        template = db.get(BrandTemplate, clip.template_id) if clip.template_id else None
        template = template if template and template.user_id == ctx.user_id else None
        preset = template.preset if template else DEFAULT_PRESET

        # Cortinilla de inicio (opcional): la posición pedida —o la que elige el programador— se lleva a un silencio.
        at: float | None = None
        notes: list[str] = []
        if clip.intro_enabled:
            silences = _load_silences(project, clip)
            at = cortinilla_service.resolve_position(clip.cortinilla_at, words, silences, duration)
            if at is None:
                notes.append("no hay un silencio válido donde insertar la cortinilla de inicio; se omitió")
                ctx.log("Sin cortinilla de inicio: " + notes[-1])
        config = (template.cortinilla if template else None) or {}
        colors = template.colors if template else {}
        start_params = fx_request.cortinilla_params(config, colors, at=at, orbit=_orbit_path(db, template, ctx.user_id)) if at is not None else None
        end_params = fx_request.outro_params(config, colors)
        # Gráficos ligados a la transcripción: el programador deja solo los que caben (sin cruzar la cortinilla ni el gancho).
        beats, missing = _resolve_images(db, ctx.user_id, clip.graphics_json or [])
        plan = graphics_schedule.schedule(beats, duration, cortinilla_at=at, single_lane=clip.layout == "full")
        plan.dropped[:0] = missing
        for d in plan.dropped:
            ctx.log(f"Gráfico descartado ({d['reason']}): {d['beat'].get('type')} «{d['beat'].get('text') or d['beat'].get('emoji') or d['beat'].get('image') or d['beat'].get('asset_id', '')}» a {d['beat'].get('at')} s")
        out_total = duration + (start_params["duration"] if start_params else 0.0) + end_params["duration"]
        ctx.log(f"Cortinillas: inicio {'a los %.1f s del clip' % at if at is not None else 'no'}, final {end_params['duration']:.1f} s → vídeo de {out_total:.1f} s")
        request = fx_request.build_fx_request(
            video=storage.rel(vertical_path), output=storage.rel(target if not draft else fx_full), quality=quality,
            duration=duration, top_ratio=clip.top_ratio, layout=clip.layout, words=words, speakers=project.speakers, hook=clip.hook,
            preset=preset, band=band, cortinilla=start_params, outro=end_params, graphics=plan.beats, sfx=bool(template.sfx) if template else True,
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
            ctx.log(f"{warning}: se usan subtítulos ASS con ffmpeg (sin banda, estilos, gancho ni cortinillas)")
            ass_fallback.burn_subtitles(vertical_path, words, target, duration=duration, width=width, height=height,
                                        top_ratio=clip.top_ratio, draft=draft, on_progress=_stage(ctx, 25, 92), cancel_check=cancel)
        elif draft:
            ffops.downscale(fx_full, target, width=width, height=height, duration=out_total, on_progress=_stage(ctx, 92, 97), cancel_check=cancel)

        thumb = folder / "thumb.jpg"
        thumb_at = min(duration * 0.35, max(0.0, duration - 0.2))
        if start_params and thumb_at >= at:
            thumb_at += start_params["duration"]  # en tiempo de salida: nunca dentro de la cortinilla
        ffops.make_thumbnail(target, thumb, at=thumb_at)
        ctx.progress(97)
        _qa(ctx, folder, target, quality, out_total, plan)
        ctx.progress(98)

        if draft:
            clip.draft_path = storage.rel(target)
        else:
            clip.rendered_path = storage.rel(target)
        clip.render_state = clips_service.settled_state(clip)  # FINAL si existe el final, aunque lo último que se hizo fuera un borrador
        clip.thumbnail_path = storage.rel(thumb)
        clip.rendered_at = queue.utcnow()
        if warning:
            notes.append(f"{warning}; se usaron subtítulos simples, sin cortinillas")
        clip.render_error = "Aviso: " + "; ".join(notes) if notes else None
        db.commit()
        ctx.log("Render terminado")
    except Cancelled:
        clip.render_state, clip.render_error = clips_service.settled_state(clip), None
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        vertical_path.unlink(missing_ok=True)
        fx_full.unlink(missing_ok=True)
