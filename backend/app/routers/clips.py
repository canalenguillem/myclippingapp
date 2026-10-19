import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db.models import Asset, BrandTemplate, Clip, YouTubeChannel, Job, Project, RenderState, User
from app.db import get_db
from app.jobs import queue
from app.pipeline import ffops
from app.services import clips as clips_service
from app.services import cortinilla as cortinilla_service
from app.services import country_maps, map_library, fx_request, graphics_planner, graphics_schedule, seo as seo_service, media_sign, silences as silences_service, storage, transcription

router = APIRouter(tags=["clips"])

MIN_CLIP_SECONDS = 5.0
MAX_CLIP_SECONDS = 180.0  # tope de un Short
EDITABLE = ("detected", "approved")
NULLABLE = ("cortinilla_at", "template_id")  # en el PATCH, null vuelve al valor automático / sin plantilla
NOT_DELETABLE = ("planning", "rendering", "uploading")


class ClipOut(BaseModel):
    id: int
    project_id: int
    start: float
    end: float
    duration: float
    title: str
    reason: str
    score: int
    transcript: str
    hook: str
    emphasis: list[dict]
    parts: list[str]
    layout: str
    focus: str
    zoom: float
    top_ratio: float
    intro_enabled: bool
    cortinilla_at: float | None
    template_id: int | None
    graphics: list[dict]
    seo_title: str
    seo_description: str
    seo_tags: list[str]
    channel_id: int | None
    privacy: str
    publish_at: datetime | None
    youtube_video_id: str | None
    uploaded_at: datetime | None
    upload_error: str | None
    status: str
    render_state: str
    has_draft: bool
    has_final: bool
    render_error: str | None
    render_job_id: int | None = None
    upload_job_id: int | None = None
    created_at: datetime | None


def _out(c: Clip, render_job_id: int | None = None, upload_job_id: int | None = None) -> ClipOut:
    return ClipOut(
        id=c.id, project_id=c.project_id, start=c.start, end=c.end, duration=round(c.end - c.start, 3),
        title=c.title, reason=c.reason, score=c.score, transcript=c.transcript, hook=c.hook,
        emphasis=c.emphasis_json or [], parts=c.parts or [], layout=c.layout, focus=c.focus, zoom=c.zoom,
        top_ratio=c.top_ratio, intro_enabled=c.intro_enabled, cortinilla_at=c.cortinilla_at, template_id=c.template_id, graphics=c.graphics_json or [],
        seo_title=c.seo_title or "", seo_description=c.seo_description or "", seo_tags=[t for t in (c.seo_tags or "").split(",") if t.strip()],
        channel_id=c.channel_id, privacy=c.privacy, publish_at=c.publish_at, youtube_video_id=c.youtube_video_id, uploaded_at=c.uploaded_at,
        upload_error=c.upload_error,
        status=c.status, render_state=c.render_state.value, has_draft=bool(c.draft_path),
        has_final=bool(c.rendered_path), render_error=c.render_error, render_job_id=render_job_id, upload_job_id=upload_job_id, created_at=c.created_at,
    )


class GraphicIn(BaseModel):
    """Un gráfico ligado a la transcripción. `at` son segundos DEL CLIP (inicio de la palabra gancho)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["keyword", "emoji", "image", "counter", "strike", "lower_third"]
    at: float = Field(ge=0)
    text: str | None = Field(default=None, max_length=40)
    emoji: str | None = Field(default=None, max_length=16)
    target: str | None = Field(default=None, max_length=16)
    zone: Literal["bottom", "top"] | None = None
    asset_id: int | None = Field(default=None, ge=1)                                  # imagen de la librería (type=image)
    style: Literal["original", "card", "silhouette", "red"] | None = None            # cómo se viste la imagen
    entry: Literal["pop", "punch", "slide_left", "slide_right", "slide_top", "drop"] | None = None   # cómo entra (imagen)
    effect: Literal["pop", "vaporize", "break", "explode"] | None = None             # qué pasa en la palabra (emoji: pop | vaporize | explode)
    from_value: float | None = Field(default=None, ge=-1e9, le=1e9)                  # contador: cifra de partida
    to_value: float | None = Field(default=None, ge=-1e9, le=1e9)                    # contador: cifra a la que llega en la palabra
    prefix: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=12)
    label: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, max_length=40)                             # rótulo: nombre
    role: str | None = Field(default=None, max_length=60)                            # rótulo: cargo
    lead: float | None = Field(default=None, ge=0, le=1)
    duration: float | None = Field(default=None, ge=1, le=6)
    priority: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _fields(self):
        if self.type in ("keyword", "strike") and not (self.text or "").strip():
            raise ValueError("la tarjeta necesita texto")
        if self.type == "counter" and (self.to_value is None):
            raise ValueError("el contador necesita la cifra final")
        if self.type == "lower_third" and not (self.name or "").strip():
            raise ValueError("el rótulo necesita un nombre")
        if self.type == "image":
            if self.asset_id is None:
                raise ValueError("falta la imagen")
        if self.type == "emoji" and self.effect == "break":
            raise ValueError("un emoji solo puede aparecer, vaporizarse o explotar")
        if self.type != "image" and self.entry not in (None, "pop"):
            raise ValueError("solo las imágenes tienen entrada con movimiento")
        if self.type == "emoji":
            if not graphics_schedule.is_emoji(self.emoji or ""):
                raise ValueError("emoji no válido")
            if self.target not in (None, "") and not graphics_schedule.is_emoji(self.target):
                raise ValueError("el objetivo no es un emoji")
        return self


def _beats(items: list[GraphicIn]) -> list[dict]:
    out = []
    for g in items:
        beat = {k: v for k, v in g.model_dump().items() if v not in (None, "")}
        for key in ("text", "name", "role"):
            if key in beat:
                beat[key] = beat[key].strip()
        if beat["type"] == "counter":
            beat.setdefault("from_value", 0.0)
        out.append(beat)
    return sorted(out, key=lambda b: b["at"])


class ClipPatch(BaseModel):
    """Solo estos campos son editables; cualquier otro (status, user_id…) se rechaza con 422."""

    model_config = ConfigDict(extra="forbid")

    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, max_length=255)
    hook: str | None = Field(default=None, max_length=255)
    layout: Literal["split", "full", "facecam"] | None = None
    focus: Literal["left", "center", "right", "speaker"] | None = None
    zoom: float | None = Field(default=None, ge=1.0, le=3.0)
    top_ratio: float | None = Field(default=None, ge=0.2, le=0.9)
    intro_enabled: bool | None = None
    template_id: int | None = Field(default=None, ge=1)
    graphics: list[GraphicIn] | None = Field(default=None, max_length=40)
    cortinilla_at: float | None = Field(default=None, gt=0)


class DetectIn(BaseModel):
    parts: int | None = Field(default=None, ge=1, le=12)
    clips_per_part: int = Field(default=5, ge=1, le=10)
    target_dur: int = Field(default=40, ge=15, le=90)


class JobRef(BaseModel):
    job_id: int


class RenderIn(BaseModel):
    quality: Literal["draft", "final"] = "draft"


def _render_jobs(db: Session, user_id: int, kind: str = "render") -> dict[int, int]:
    """{clip_id: job_id} de los jobs `kind` (render o upload) del usuario en cola o en marcha."""
    jobs = db.scalars(select(Job).where(Job.user_id == user_id, Job.type == kind, Job.status.in_(("queued", "running")))).all()
    return {int(j.payload["clip_id"]): j.id for j in sorted(jobs, key=lambda j: j.id) if (j.payload or {}).get("clip_id")}


@router.get("/api/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    clips = db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == user.id).order_by(Clip.start)).all()
    jobs, uploads = _render_jobs(db, user.id), _render_jobs(db, user.id, "upload")
    return [_out(c, jobs.get(c.id), uploads.get(c.id)) for c in clips]


@router.post("/api/projects/{project_id}/detect", response_model=JobRef, status_code=202)
def detect(project_id: int, body: DetectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    if not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene transcripción")
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    payload = {"project_id": project.id, "clips_per_part": body.clips_per_part, "target_dur": body.target_dur}
    if body.parts:
        payload["parts"] = body.parts
    return JobRef(job_id=queue.enqueue(db, user.id, "detect", payload).id)


@router.get("/api/clips/{clip_id}", response_model=ClipOut)
def get_clip(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    return _out(clip, _render_jobs(db, user.id).get(clip.id), _render_jobs(db, user.id, "upload").get(clip.id))


@router.patch("/api/clips/{clip_id}", response_model=ClipOut)
def patch_clip(clip_id: int, body: ClipPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status not in EDITABLE:
        raise HTTPException(409, f"Un clip en estado «{clip.status}» no se puede editar")
    if clip.render_state is RenderState.RENDERING:
        raise HTTPException(409, "El clip se está renderizando; espera a que termine o cancela el render")
    changes = body.model_dump(exclude_unset=True)
    new_graphics = _beats(body.graphics) if body.graphics is not None else None
    changes.pop("graphics", None)
    old_start = clip.start
    # `cortinilla_at: null` vuelve a la posición automática; en los demás campos null significa «sin cambio»
    really_changed = {k for k, v in changes.items() if (v is not None or k in NULLABLE) and getattr(clip, k) != v}
    start, end = changes.get("start", clip.start), changes.get("end", clip.end)
    if "start" in changes or "end" in changes:
        project = db.get(Project, clip.project_id)
        if end <= start:
            raise HTTPException(422, "El fin debe ser posterior al inicio")
        if not MIN_CLIP_SECONDS <= end - start <= MAX_CLIP_SECONDS:
            raise HTTPException(422, f"La duración debe estar entre {MIN_CLIP_SECONDS:.0f} y {MAX_CLIP_SECONDS:.0f} s")
        if project.duration and end > project.duration + 0.05:
            raise HTTPException(422, "El fin está fuera de la duración del vídeo")
    if changes.get("template_id") is not None:
        get_owned(db, BrandTemplate, changes["template_id"], user)  # una plantilla ajena responde 404
    if changes.get("cortinilla_at") is not None and changes["cortinilla_at"] > end - start - cortinilla_service.END_MARGIN:
        raise HTTPException(422, "La cortinilla de inicio no puede entrar en el último segundo del clip")
    if new_graphics is not None:
        for aid in {b["asset_id"] for b in new_graphics if "asset_id" in b}:
            get_owned(db, Asset, aid, user)  # una imagen ajena (o inexistente) responde 404
    if new_graphics is not None and any(b["at"] > end - start for b in new_graphics):
        raise HTTPException(422, "Un gráfico se ancla fuera del clip")
    for field, value in changes.items():
        if value is not None or field in NULLABLE:
            setattr(clip, field, value)
    if new_graphics is not None:
        really_changed |= {"graphics_json"} if new_graphics != (clip.graphics_json or []) else set()
        clip.graphics_json = new_graphics
    elif ("start" in changes or "end" in changes) and clip.graphics_json:
        # los gráficos van en segundos del clip: al mover el inicio se desplazan para seguir pegados a su palabra
        shift = clip.start - old_start
        moved = [{**b, "at": round(b["at"] - shift, 3)} for b in clip.graphics_json]
        moved = [b for b in moved if 0 <= b["at"] <= clip.end - clip.start]
        if moved != clip.graphics_json:
            really_changed.add("graphics_json")
            clip.graphics_json = moved
    if ("start" in changes or "end" in changes) and "cortinilla_at" not in changes:
        clip.cortinilla_at = None  # es relativa al inicio del clip: con otro recorte ya no apunta al mismo sitio
    if "start" in changes or "end" in changes:
        project = db.get(Project, clip.project_id)
        if project.words_path:
            words = transcription.load_words(storage.absolute(project.words_path))["words"]
            clip.transcript = clips_service.text_between(words, clip.start, clip.end)
    if really_changed & clips_service.RENDER_AFFECTING and clip.render_state is not RenderState.NONE:
        clips_service.invalidate_render(clip)  # el borrador y el final ya no corresponden a lo editado
    db.commit()
    return _out(clip)


@router.post("/api/clips/{clip_id}/approve", response_model=ClipOut)
def approve_clip(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status != "detected":
        raise HTTPException(409, f"Solo se puede aprobar un clip detectado (está «{clip.status}»)")
    clip.status = "approved"
    db.commit()
    return _out(clip)


@router.post("/api/clips/{clip_id}/unapprove", response_model=ClipOut)
def unapprove_clip(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status != "approved":
        raise HTTPException(409, f"Solo se puede desaprobar un clip aprobado (está «{clip.status}»)")
    clip.status = "detected"
    db.commit()
    return _out(clip)


@router.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status in NOT_DELETABLE:
        raise HTTPException(409, f"El clip está en proceso («{clip.status}»)")
    if clip.render_state is RenderState.RENDERING:
        raise HTTPException(409, "El clip se está renderizando; cancela el render primero")
    clips_service.drop_render_files(clip)
    db.delete(clip)
    db.commit()


@router.post("/api/clips/{clip_id}/render", response_model=JobRef, status_code=202)
def render_clip(clip_id: int, body: RenderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Encola el render: borrador de cualquier clip editable; final solo si está aprobado."""
    clip = get_owned(db, Clip, clip_id, user)
    project = db.get(Project, clip.project_id)
    if clip.status not in EDITABLE:
        raise HTTPException(409, f"Un clip en estado «{clip.status}» no se puede renderizar")
    if body.quality == "final" and clip.status != "approved":
        raise HTTPException(409, "El render final solo se hace con el clip aprobado")
    if clip.layout not in ("split", "full"):
        raise HTTPException(409, f"Solo se renderizan los diseños partido (split) y pantalla completa (full); este clip usa «{clip.layout}»")
    if not project.video_path or not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene vídeo y transcripción")
    if clip.render_state is RenderState.RENDERING:
        raise HTTPException(409, "El clip ya se está renderizando")
    if queue.active_job(db, user.id, project.id, ignore_types=("render",)):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    job = queue.enqueue(db, user.id, "render", {"clip_id": clip.id, "project_id": project.id, "quality": body.quality})
    clip.render_state, clip.render_error = RenderState.RENDERING, None
    db.commit()
    return JobRef(job_id=job.id)


@router.post("/api/clips/{clip_id}/render/cancel", status_code=204)
def cancel_render(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    job_id = _render_jobs(db, user.id).get(clip.id)
    if job_id is None:
        raise HTTPException(409, "El clip no tiene un render en curso")
    job = db.get(Job, job_id)
    was_queued = job.status == "queued"
    queue.cancel(db, job)
    if was_queued:  # en marcha, el handler restaura el estado al ver la cancelación
        clips_service.restore_after_cancel(db, job)


@router.get("/api/clips/{clip_id}/render-urls")
def render_urls(clip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """URLs firmadas del borrador, del final y de la miniatura (None si no existen)."""
    clip = get_owned(db, Clip, clip_id, user)
    sign = lambda rel: media_sign.signed_url(rel) if rel else None  # noqa: E731
    return {"draft": sign(clip.draft_path), "final": sign(clip.rendered_path), "thumbnail": sign(clip.thumbnail_path)}


@router.get("/api/clips/{clip_id}/still")
def still(clip_id: int, t: float = Query(ge=0), quality: Literal["draft", "final"] = "draft",
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Un fotograma del render ya hecho en el segundo `t` del clip, para validar sin ver el vídeo entero."""
    clip = get_owned(db, Clip, clip_id, user)
    rel = clip.rendered_path if quality == "final" else clip.draft_path
    if not rel:
        raise HTTPException(409, f"El clip no tiene render {'final' if quality == 'final' else 'borrador'}")
    if t > clip.end - clip.start:
        raise HTTPException(422, "El instante está fuera del clip")
    video = storage.absolute(rel)
    if not video.is_file():
        raise HTTPException(409, "No se encuentra el fichero del render")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            out = ffops.make_thumbnail(video, Path(tmp) / "still.jpg", at=t, width=540 if quality == "draft" else 1080)
        except ffops.FfopsError as exc:
            raise HTTPException(500, str(exc)) from exc
        return Response(out.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


@router.get("/api/clips/{clip_id}/cortinilla-options")
def cortinilla_options(clip_id: int, start: float | None = Query(default=None, ge=0), end: float | None = Query(default=None, ge=0),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Dónde puede entrar la cortinilla de inicio: silencios que no pisan palabras (`sentence`: cierran una frase)
    y la posición que elegiría el programador. Con `start`/`end` se calcula para un recorte aún sin guardar."""
    clip = get_owned(db, Clip, clip_id, user)
    project = db.get(Project, clip.project_id)
    start = clip.start if start is None else start
    end = clip.end if end is None else end
    if end - start < 1.0:
        raise HTTPException(422, "Recorte no válido")
    if not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene transcripción")
    words, silences = _words_and_silences(db, project, start, end)
    duration = end - start
    sentence = set(cortinilla_service.candidates(words, silences, duration, sentence_only=True))
    every = cortinilla_service.candidates(words, silences, duration, sentence_only=False)
    return {
        "duration": round(duration, 3),
        "intro": cortinilla_service.INTRO_SECONDS,
        "default": cortinilla_service.default_position(words, silences, duration),
        "positions": [{"at": at, "sentence": at in sentence} for at in every],
    }


def _words_and_silences(db: Session, project: Project, start: float, end: float) -> tuple[list[dict], list[dict]]:
    """Palabras del recorte (relativas a su inicio) y silencios que lo tocan, como los usa el job de render."""
    words = fx_request.clip_words(transcription.load_words(storage.absolute(project.words_path))["words"], start, end)
    silences: list[dict] = []
    if project.silences_path:
        try:
            silences = cortinilla_service.rebase_silences(silences_service.load_silences(storage.absolute(project.silences_path)), start, end)
        except (OSError, ValueError):
            silences = []
    return words, silences


class PlanIn(BaseModel):
    """Lo que hay en el formulario del editor, guardado o no: el plan se calcula sobre eso."""

    model_config = ConfigDict(extra="forbid")

    graphics: list[GraphicIn] = Field(default_factory=list, max_length=40)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    layout: Literal["split", "full", "facecam"] | None = None
    intro_enabled: bool | None = None
    cortinilla_at: float | None = Field(default=None, gt=0)


@router.post("/api/clips/{clip_id}/graphics-plan")
def graphics_plan(clip_id: int, body: PlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Qué haría el programador con estos gráficos: ventana real de cada uno, los descartados con su motivo y dónde cae la
    cortinilla de inicio. No guarda nada."""
    clip = get_owned(db, Clip, clip_id, user)
    project = db.get(Project, clip.project_id)
    start = clip.start if body.start is None else body.start
    end = clip.end if body.end is None else body.end
    if end - start < 1.0:
        raise HTTPException(422, "Recorte no válido")
    if not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene transcripción")
    duration = end - start
    words, silences = _words_and_silences(db, project, start, end)
    intro = clip.intro_enabled if body.intro_enabled is None else body.intro_enabled
    at = cortinilla_service.resolve_position(body.cortinilla_at, words, silences, duration) if intro else None
    layout = body.layout or clip.layout
    plan = graphics_schedule.schedule(_beats(body.graphics), duration, cortinilla_at=at, single_lane=layout == "full")
    return {
        "duration": round(duration, 3),
        "cortinilla_at": at,
        "hook_seconds": graphics_schedule.HOOK_SECONDS,
        "beats": [{**b, "start": round(max(0.0, b["at"] - b["lead"]), 3), "end": round(max(0.0, b["at"] - b["lead"]) + b["duration"], 3)} for b in plan.beats],
        "dropped": plan.dropped,
    }


# --- YouTube: textos SEO y subida ---------------------------------------------------------------------

def _channel(db: Session, user: User, channel_id: int) -> YouTubeChannel:
    ch = db.get(YouTubeChannel, channel_id)
    if ch is None or ch.user_id != user.id:
        raise HTTPException(404, "Canal no encontrado")
    return ch


class SeoGenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int = Field(ge=1)


class SeoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=seo_service.TITLE_MAX)
    description: str = Field(max_length=seo_service.DESCRIPTION_MAX)
    tags: list[str] = Field(default_factory=list, max_length=seo_service.TAGS_MAX)
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: datetime | None = None


class UploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int = Field(ge=1)   # el canal que el usuario VE en pantalla: si no coincide con el guardado, no se sube
    source: Literal["final", "draft"] = "final"   # «draft»: sube el borrador (540x960) sin esperar al render final


def _editable_for_seo(clip: Clip) -> None:
    if clip.status not in EDITABLE:
        raise HTTPException(409, f"Un clip en estado «{clip.status}» no admite cambios en sus textos de YouTube")


@router.post("/api/clips/{clip_id}/seo/generate")
def generate_seo(clip_id: int, body: SeoGenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Propone título, descripción y etiquetas para el canal elegido. No guarda nada: el usuario los revisa y los guarda."""
    clip = get_owned(db, Clip, clip_id, user)
    ch = _channel(db, user, body.channel_id)
    project = db.get(Project, clip.project_id)
    seo = seo_service.generate(
        title=clip.title, hook=clip.hook, reason=clip.reason, transcript=clip.transcript, emphasis=[e.get("text", "") for e in clip.emphasis_json or []],
        channel_name=ch.yt_title or ch.name, language=ch.language, seo_rules=ch.seo_rules or "",
    )
    description = seo_service.with_source(seo.description, handle=project.source_handle, url=project.source_url, start=clip.start)
    return {"title": seo.title, "description": description, "tags": seo.tags, "source": seo.source}


@router.put("/api/clips/{clip_id}/seo", response_model=ClipOut)
def save_seo(clip_id: int, body: SeoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    _editable_for_seo(clip)
    ch = _channel(db, user, body.channel_id)
    if body.publish_at is not None:
        when = body.publish_at.astimezone(timezone.utc).replace(tzinfo=None) if body.publish_at.tzinfo else body.publish_at
        if body.privacy != "private":
            raise HTTPException(422, "Para programar la publicación, la privacidad tiene que ser «privado» (YouTube lo publica solo a esa hora)")
        if when < datetime.utcnow() + timedelta(minutes=2):
            raise HTTPException(422, "La hora de publicación tiene que ser futura")
    else:
        when = None
    clean = seo_service.clean(seo_service.Seo(body.title, body.description, body.tags))
    if not clean.title:
        raise HTTPException(422, "El título no puede quedar vacío")
    clip.channel_id, clip.seo_title, clip.seo_description, clip.seo_tags = ch.id, clean.title, clean.description, ",".join(clean.tags)
    clip.privacy, clip.publish_at, clip.upload_error = body.privacy, when, None
    db.commit()
    return _out(clip)


@router.post("/api/clips/{clip_id}/upload", response_model=JobRef, status_code=202)
def upload_clip(clip_id: int, body: UploadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Encola la subida del vídeo final con los textos guardados. Nunca sube a otro canal que el que el usuario está viendo."""
    clip = get_owned(db, Clip, clip_id, user)
    if clip.youtube_video_id or clip.status == "uploaded":
        raise HTTPException(409, "Este clip ya está subido a YouTube")
    if clip.status == "uploading":
        raise HTTPException(409, "Ya se está subiendo")
    if clip.status != "approved":
        raise HTTPException(409, "Solo se suben clips aprobados")
    if body.source == "final" and (not clip.rendered_path or clip.render_state is not RenderState.FINAL):
        raise HTTPException(409, "Primero hay que hacer el render final del clip (o elige subir el borrador)")
    if body.source == "draft" and (not clip.draft_path or clip.render_state not in (RenderState.DRAFT, RenderState.FINAL)):
        raise HTTPException(409, "No hay un borrador vigente: renderiza el borrador otra vez")
    if not clip.seo_title.strip() or clip.channel_id is None:
        raise HTTPException(409, "Guarda antes los textos de YouTube (título, descripción y etiquetas) para un canal")
    if clip.channel_id != body.channel_id:
        raise HTTPException(409, "El canal elegido no coincide con el de los textos guardados: vuelve a guardarlos")
    ch = _channel(db, user, clip.channel_id)
    if not ch.token_enc:
        raise HTTPException(409, "El canal no está conectado a YouTube: conéctalo en Canales")
    if queue.active_job(db, user.id, clip.project_id, ignore_types=("render",)):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    job = queue.enqueue(db, user.id, "upload", {"clip_id": clip.id, "project_id": clip.project_id, "source": body.source})
    clip.status, clip.upload_error = "uploading", None
    db.commit()
    return JobRef(job_id=job.id)


@router.post("/api/clips/{clip_id}/graphics-plan/suggest")
def suggest_graphics(clip_id: int, body: PlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Propone gráficos a partir de la transcripción del recorte y de las imágenes del usuario. No guarda nada: devuelve solo lo
    que cabe junto a lo que el formulario ya tiene (que manda). El usuario lo revisa y lo edita en la línea de tiempo."""
    clip = get_owned(db, Clip, clip_id, user)
    project = db.get(Project, clip.project_id)
    start = clip.start if body.start is None else body.start
    end = clip.end if body.end is None else body.end
    if end - start < 1.0:
        raise HTTPException(422, "Recorte no válido")
    if not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene transcripción")
    duration = end - start
    words, silences = _words_and_silences(db, project, start, end)
    if not words:
        raise HTTPException(409, "El recorte no tiene palabras transcritas")
    intro = clip.intro_enabled if body.intro_enabled is None else body.intro_enabled
    at = cortinilla_service.resolve_position(body.cortinilla_at, words, silences, duration) if intro else None
    # los países que se nombran en el recorte tienen su mapa en la librería (se crean los que faltan)
    mentioned = [name for name, _ in country_maps.mentions(words)][:graphics_planner.MAX_MAP_BEATS]
    map_library.ensure(db, user.id, mentioned)
    assets = [{"id": a.id, "name": a.name, "tags": a.tags or []} for a in db.scalars(select(Asset).where(Asset.user_id == user.id).order_by(Asset.id)).all()]
    maps = {name: a.id for name, a in map_library.existing(db, user.id).items()}
    result = graphics_planner.plan(words=words, duration=duration, hook=clip.hook, assets=assets, existing=_beats(body.graphics),
                                   cortinilla_at=at, single_lane=(body.layout or clip.layout) == "full", maps=maps, speakers=project.speakers)
    clean = []
    for beat in result.beats:
        reason = beat.pop("reason", "")
        try:
            GraphicIn(**beat)
        except ValueError:
            continue
        clean.append({**beat, "reason": reason})
    return {"beats": clean, "source": result.source, "notes": result.notes, "max_beats": graphics_planner.max_beats(duration)}
