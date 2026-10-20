import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.config import get_settings
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import get_db
from app.db.models import BrandTemplate, Clip, Job, Project, ProjectStatus, RenderState, User, YouTubeChannel
from app.jobs import queue
from app.services import media_sign, storage, transcription
from app.services import cleanup, seo as seo_service
from app.services import source as source_service
from app.services.video_download import is_youtube_url

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    source_url: str
    title: str
    duration: float | None
    status: str
    error: str | None
    speakers: dict
    default_template_id: int | None = None
    default_channel_id: int | None = None
    source_handle: str = ""
    created_at: datetime | None
    model_config = {"from_attributes": True}


class ProjectIn(BaseModel):
    source_url: str = Field(max_length=1024)
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2})$")
    speakers_expected: int | None = Field(default=None, ge=1, le=10)


class RetranscribeIn(BaseModel):
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2})$")
    speakers_expected: int | None = Field(default=None, ge=1, le=10)
    force: bool = False  # sin esto, no se pisan las correcciones manuales de la transcripción


class JobRef(BaseModel):
    job_id: int


class ProjectCreated(ProjectOut):
    job_id: int


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())).all()


@router.post("", response_model=ProjectCreated, status_code=201)
def create_project(body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    url = body.source_url.strip()
    if not is_youtube_url(url):
        raise HTTPException(400, "Solo se admiten enlaces de YouTube (youtube.com / youtu.be)")
    project = Project(user_id=user.id, source_url=url, title=url, status=ProjectStatus.DOWNLOADING)
    db.add(project)
    db.commit()
    payload = {"project_id": project.id, "language": body.language}
    if body.speakers_expected:
        payload["speakers_expected"] = body.speakers_expected
    job = queue.enqueue(db, user.id, "ingest", payload)
    return ProjectCreated.model_validate({**ProjectOut.model_validate(project).model_dump(), "job_id": job.id})


class ProjectPatch(BaseModel):
    model_config = {"extra": "forbid"}

    default_template_id: int | None = Field(default=None, ge=1)
    default_channel_id: int | None = Field(default=None, ge=1)
    source_handle: str | None = Field(default=None, max_length=200)   # @ del canal original; vacío lo quita


@router.patch("/{project_id}", response_model=ProjectOut)
def patch_project(project_id: int, body: ProjectPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Plantilla y canal de YouTube por defecto del proyecto. Los toman los clips que se detecten a partir de ahora; el canal se
    pone además a los clips existentes que aún no tienen uno (nunca se pisa el de un clip que ya lo tiene)."""
    project = get_owned(db, Project, project_id, user)
    sent = body.model_fields_set
    if "default_template_id" in sent:
        if body.default_template_id is not None:
            get_owned(db, BrandTemplate, body.default_template_id, user)
        project.default_template_id = body.default_template_id
        if body.default_template_id is not None:
            # los clips aún sin plantilla y sin renderizar la reciben (un clip ya renderizado no se toca: quedaría obsoleto)
            tpl = db.get(BrandTemplate, body.default_template_id)
            db.execute(update(Clip).where(Clip.project_id == project.id, Clip.user_id == user.id, Clip.template_id.is_(None),
                                          Clip.status.in_(("detected", "approved")), Clip.render_state == RenderState.NONE)
                       .values(template_id=body.default_template_id, **({"intro_enabled": True} if tpl and tpl.cortinilla_default else {})))
    if "default_channel_id" in sent:
        if body.default_channel_id is not None:
            get_owned(db, YouTubeChannel, body.default_channel_id, user)
        project.default_channel_id = body.default_channel_id
        if body.default_channel_id is not None:
            db.execute(update(Clip).where(Clip.project_id == project.id, Clip.user_id == user.id, Clip.channel_id.is_(None),
                                          Clip.status.in_(("detected", "approved"))).values(channel_id=body.default_channel_id))
    if "source_handle" in sent:
        handle = seo_service.normalize_handle(body.source_handle or "")
        if (body.source_handle or "").strip() and not handle:
            raise HTTPException(422, "El @ del canal no es válido (letras, números, puntos, guiones)")
        project.source_handle = handle
    db.commit()
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_owned(db, Project, project_id, user)


@router.get("/{project_id}/transcript")
def get_transcript(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    if not project.words_path:
        raise HTTPException(409, "Todavía no hay transcripción")
    data = transcription.load_words(storage.absolute(project.words_path))
    data["has_speakers"] = transcription.has_speakers(data)
    return data


@router.post("/{project_id}/retranscribe", response_model=JobRef, status_code=202)
def retranscribe(
    project_id: int, body: RetranscribeIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    project = get_owned(db, Project, project_id, user)
    if not project.video_path or not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene vídeo y transcripción")
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    current = transcription.load_words(storage.absolute(project.words_path))
    if current.get("revision", 1) > 1 and not body.force:
        raise HTTPException(409, "La transcripción tiene correcciones manuales; usa force=true para sobrescribirlas")
    payload = {"project_id": project.id, "transcribe_only": True, "language": body.language}
    if body.speakers_expected:
        payload["speakers_expected"] = body.speakers_expected
    return JobRef(job_id=queue.enqueue(db, user.id, "ingest", payload).id)


@router.post("/{project_id}/retry", response_model=JobRef, status_code=202)
def retry_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reintenta un proyecto que falló (sin créditos de OpenAI, red caída…): si ya tiene transcripción, solo vuelve a detectar los
    clips; si no, repite la descarga y la transcripción desde el principio."""
    project = get_owned(db, Project, project_id, user)
    if project.status is not ProjectStatus.FAILED:
        raise HTTPException(409, "Solo se pueden reintentar los proyectos que han fallado")
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    if project.words_path:
        project.status, project.error = ProjectStatus.DETECTING, None
        job = queue.enqueue(db, user.id, "detect", {"project_id": project.id, "clips_per_part": 5, "target_dur": 40})
    else:
        project.status, project.error = ProjectStatus.DOWNLOADING, None
        job = queue.enqueue(db, user.id, "ingest", {"project_id": project.id, "language": "auto"})
    db.commit()
    return JobRef(job_id=job.id)


@router.get("/{project_id}/video-url")
def video_url(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """URL firmada y con caducidad del vídeo fuente, para reproducirlo en el navegador."""
    project = get_owned(db, Project, project_id, user)
    if not project.video_path:
        raise HTTPException(409, "El proyecto aún no tiene vídeo")
    if not source_service.available(project):
        raise HTTPException(409, "El vídeo original se borró para liberar espacio; se descarga solo al renderizar un clip")
    return media_sign.signed_url(project.video_path)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto: cancélalo primero")
    shutil.rmtree(storage.media_root() / f"u{user.id}" / f"p{project.id}", ignore_errors=True)
    db.delete(project)
    db.commit()


speakers_router = APIRouter(prefix="/api/speakers", tags=["projects"])


@speakers_router.get("/known")
def known_speakers(exclude_project: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hablantes con nombre que el usuario ya ha puesto en sus proyectos, para no escribirlos otra vez: el nombre, el cargo y el
    estilo más recientes de cada persona y en cuántos proyectos sale. Del más usado al menos."""
    projects = db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())).all()
    people: dict[str, dict] = {}
    for p in projects:
        if exclude_project is not None and p.id == exclude_project:
            continue
        seen_here: set[str] = set()
        for card in (p.speakers or {}).values():
            name = str(card.get("name", "")).strip()
            key = name.lower()
            if not name or key in seen_here:
                continue
            seen_here.add(key)
            entry = people.setdefault(key, {"name": name, "role": str(card.get("role", "")).strip(), "caption_style": card.get("caption_style", "sans_upper"),
                                            "is_source": bool(card.get("is_source", False)), "uses": 0, "last_project_id": p.id})
            entry["uses"] += 1
            if not entry["role"] and str(card.get("role", "")).strip():   # el cargo más reciente que no esté vacío
                entry["role"] = str(card["role"]).strip()
    return sorted(people.values(), key=lambda e: (-e["uses"], e["name"].lower()))


class StorageProjectOut(BaseModel):
    id: int
    title: str
    bytes: int
    heavy_bytes: int
    last_activity: str | None
    has_source: bool


class StorageOut(BaseModel):
    free_bytes: int
    total_bytes: int
    retention_days: int
    projects: list[StorageProjectOut]


storage_router = APIRouter(prefix="/api/storage", tags=["storage"])


@storage_router.get("", response_model=StorageOut)
def storage_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Disco libre y lo que ocupa cada proyecto del usuario (lo pesado se puede liberar: se regenera descargando de nuevo)."""
    free, total = cleanup.disk()
    rows = []
    for p in db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())).all():
        u = cleanup.usage(storage.project_dir(p.user_id, p.id))
        rows.append(StorageProjectOut(id=p.id, title=p.title, bytes=u.total, heavy_bytes=u.heavy, last_activity=cleanup.utc_iso(u.last_activity),
                                      has_source=source_service.available(p)))
    return StorageOut(free_bytes=free, total_bytes=total, retention_days=get_settings().media_retention_days, projects=rows)


@router.post("/{project_id}/free-space")
def free_space(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Borra el vídeo original, el audio y los renders del proyecto; se regeneran al volver a renderizar."""
    project = get_owned(db, Project, project_id, user)
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto")
    return {"freed_bytes": cleanup.free_project(db, project)}
