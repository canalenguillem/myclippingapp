from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db.models import Clip, Job, Project, RenderState, User
from app.db import get_db
from app.jobs import queue
from app.services import clips as clips_service
from app.services import storage, transcription

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
    outro_enabled: bool
    status: str
    render_state: str
    has_draft: bool
    has_final: bool
    render_error: str | None
    created_at: datetime | None


def _out(c: Clip) -> ClipOut:
    return ClipOut(
        id=c.id, project_id=c.project_id, start=c.start, end=c.end, duration=round(c.end - c.start, 3),
        title=c.title, reason=c.reason, score=c.score, transcript=c.transcript, hook=c.hook,
        emphasis=c.emphasis_json or [], parts=c.parts or [], layout=c.layout, focus=c.focus, zoom=c.zoom,
        top_ratio=c.top_ratio, intro_enabled=c.intro_enabled, outro_enabled=c.outro_enabled,
        status=c.status, render_state=c.render_state.value, has_draft=bool(c.draft_path),
        has_final=bool(c.rendered_path), render_error=c.render_error, created_at=c.created_at,
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
    outro_enabled: bool | None = None


class DetectIn(BaseModel):
    parts: int | None = Field(default=None, ge=1, le=12)
    clips_per_part: int = Field(default=5, ge=1, le=10)
    target_dur: int = Field(default=40, ge=15, le=90)


class JobRef(BaseModel):
    job_id: int


@router.get("/api/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    clips = db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == user.id).order_by(Clip.start)).all()
    return [_out(c) for c in clips]


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
    return _out(get_owned(db, Clip, clip_id, user))


@router.patch("/api/clips/{clip_id}", response_model=ClipOut)
def patch_clip(clip_id: int, body: ClipPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    clip = get_owned(db, Clip, clip_id, user)
    if clip.status not in EDITABLE:
        raise HTTPException(409, f"Un clip en estado «{clip.status}» no se puede editar")
    if clip.render_state is RenderState.RENDERING:
        raise HTTPException(409, "El clip se está renderizando; espera a que termine o cancela el render")
    changes = body.model_dump(exclude_unset=True)
    really_changed = {k for k, v in changes.items() if v is not None and getattr(clip, k) != v}
    start, end = changes.get("start", clip.start), changes.get("end", clip.end)
    if "start" in changes or "end" in changes:
        project = db.get(Project, clip.project_id)
        if end <= start:
            raise HTTPException(422, "El fin debe ser posterior al inicio")
        if not MIN_CLIP_SECONDS <= end - start <= MAX_CLIP_SECONDS:
            raise HTTPException(422, f"La duración debe estar entre {MIN_CLIP_SECONDS:.0f} y {MAX_CLIP_SECONDS:.0f} s")
        if project.duration and end > project.duration + 0.05:
            raise HTTPException(422, "El fin está fuera de la duración del vídeo")
    for field, value in changes.items():
        if value is not None:
            setattr(clip, field, value)
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
