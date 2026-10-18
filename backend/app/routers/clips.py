import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db.models import Clip, Job, Project, RenderState, User
from app.db import get_db
from app.jobs import queue
from app.pipeline import ffops
from app.services import clips as clips_service
from app.services import cortinilla as cortinilla_service
from app.services import fx_request, media_sign, silences as silences_service, storage, transcription

router = APIRouter(tags=["clips"])

MIN_CLIP_SECONDS = 5.0
MAX_CLIP_SECONDS = 180.0  # tope de un Short
EDITABLE = ("detected", "approved")
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
    status: str
    render_state: str
    has_draft: bool
    has_final: bool
    render_error: str | None
    render_job_id: int | None = None
    created_at: datetime | None


def _out(c: Clip, render_job_id: int | None = None) -> ClipOut:
    return ClipOut(
        id=c.id, project_id=c.project_id, start=c.start, end=c.end, duration=round(c.end - c.start, 3),
        title=c.title, reason=c.reason, score=c.score, transcript=c.transcript, hook=c.hook,
        emphasis=c.emphasis_json or [], parts=c.parts or [], layout=c.layout, focus=c.focus, zoom=c.zoom,
        top_ratio=c.top_ratio, intro_enabled=c.intro_enabled, cortinilla_at=c.cortinilla_at,
        status=c.status, render_state=c.render_state.value, has_draft=bool(c.draft_path),
        has_final=bool(c.rendered_path), render_error=c.render_error, render_job_id=render_job_id, created_at=c.created_at,
    )


class ClipPatch(BaseModel):
    """Solo estos campos son editables; cualquier otro (status, user_id…) se rechaza con 422."""

    model_config = ConfigDict(extra="forbid")

    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, max_length=255)
    hook: str | None = Field(default=None, max_length=255)
    layout: Literal["split", "full", "facecam"] | None = None
    focus: Literal["left", "center", "right"] | None = None
    zoom: float | None = Field(default=None, ge=1.0, le=3.0)
    top_ratio: float | None = Field(default=None, ge=0.2, le=0.9)
    intro_enabled: bool | None = None
    cortinilla_at: float | None = Field(default=None, gt=0)


class DetectIn(BaseModel):
    parts: int | None = Field(default=None, ge=1, le=12)
    clips_per_part: int = Field(default=5, ge=1, le=10)
    target_dur: int = Field(default=40, ge=15, le=90)


class JobRef(BaseModel):
    job_id: int


class RenderIn(BaseModel):
    quality: Literal["draft", "final"] = "draft"


def _render_jobs(db: Session, user_id: int) -> dict[int, int]:
    """{clip_id: job_id} de los renders del usuario en cola o en marcha."""
    jobs = db.scalars(select(Job).where(Job.user_id == user_id, Job.type == "render", Job.status.in_(("queued", "running")))).all()
    return {int(j.payload["clip_id"]): j.id for j in sorted(jobs, key=lambda j: j.id) if (j.payload or {}).get("clip_id")}


@router.get("/api/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    clips = db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == user.id).order_by(Clip.start)).all()
    jobs = _render_jobs(db, user.id)
    return [_out(c, jobs.get(c.id)) for c in clips]


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
    return _out(clip, _render_jobs(db, user.id).get(clip.id))


@router.patch("/api/clips/{clip_id}", response_model=ClipOut)
def patch_clip(clip_id: int, body: ClipPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status not in EDITABLE:
        raise HTTPException(409, f"Un clip en estado «{clip.status}» no se puede editar")
    if clip.render_state is RenderState.RENDERING:
        raise HTTPException(409, "El clip se está renderizando; espera a que termine o cancela el render")
    changes = body.model_dump(exclude_unset=True)
    # `cortinilla_at: null` vuelve a la posición automática; en los demás campos null significa «sin cambio»
    really_changed = {k for k, v in changes.items() if (v is not None or k == "cortinilla_at") and getattr(clip, k) != v}
    start, end = changes.get("start", clip.start), changes.get("end", clip.end)
    if "start" in changes or "end" in changes:
        project = db.get(Project, clip.project_id)
        if end <= start:
            raise HTTPException(422, "El fin debe ser posterior al inicio")
        if not MIN_CLIP_SECONDS <= end - start <= MAX_CLIP_SECONDS:
            raise HTTPException(422, f"La duración debe estar entre {MIN_CLIP_SECONDS:.0f} y {MAX_CLIP_SECONDS:.0f} s")
        if project.duration and end > project.duration + 0.05:
            raise HTTPException(422, "El fin está fuera de la duración del vídeo")
    if changes.get("cortinilla_at") is not None and changes["cortinilla_at"] > end - start - cortinilla_service.END_MARGIN:
        raise HTTPException(422, "La cortinilla de inicio no puede entrar en el último segundo del clip")
    for field, value in changes.items():
        if value is not None or field == "cortinilla_at":
            setattr(clip, field, value)
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
    if clip.layout != "split":
        raise HTTPException(409, f"Solo se renderiza el diseño partido (split); este clip usa «{clip.layout}»")
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
    words = fx_request.clip_words(transcription.load_words(storage.absolute(project.words_path))["words"], start, end)
    silences = []
    if project.silences_path:
        try:
            silences = cortinilla_service.rebase_silences(silences_service.load_silences(storage.absolute(project.silences_path)), start, end)
        except (OSError, ValueError):
            silences = []
    duration = end - start
    sentence = set(cortinilla_service.candidates(words, silences, duration, sentence_only=True))
    every = cortinilla_service.candidates(words, silences, duration, sentence_only=False)
    return {
        "duration": round(duration, 3),
        "intro": cortinilla_service.INTRO_SECONDS,
        "default": cortinilla_service.default_position(words, silences, duration),
        "positions": [{"at": at, "sentence": at in sentence} for at in every],
    }
