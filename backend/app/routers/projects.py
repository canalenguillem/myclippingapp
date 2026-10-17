import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import get_db
from app.db.models import Job, Project, User
from app.jobs import queue
from app.services import storage, transcription
from app.services.video_download import is_youtube_url

router = APIRouter(prefix="/api/projects", tags=["projects"])

BUSY = {"downloading", "transcribing"}


class ProjectOut(BaseModel):
    id: int
    source_url: str
    title: str
    duration: float | None
    status: str
    error: str | None
    created_at: datetime | None
    model_config = {"from_attributes": True}


class ProjectIn(BaseModel):
    source_url: str = Field(max_length=1024)
    language: str = Field(default="auto", pattern=r"^(auto|[a-z]{2})$")


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
    project = Project(user_id=user.id, source_url=url, title=url, status="downloading")
    db.add(project)
    db.commit()
    job = queue.enqueue(db, user.id, "ingest", {"project_id": project.id, "language": body.language})
    return ProjectCreated.model_validate({**ProjectOut.model_validate(project).model_dump(), "job_id": job.id})


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_owned(db, Project, project_id, user)


@router.get("/{project_id}/transcript")
def get_transcript(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    if not project.words_path:
        raise HTTPException(409, "Todavía no hay transcripción")
    return transcription.load_words(storage.absolute(project.words_path))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = get_owned(db, Project, project_id, user)
    active = db.scalars(
        select(Job).where(Job.user_id == user.id, Job.status.in_(("queued", "running")), Job.type == "ingest")
    ).all()
    if any((j.payload or {}).get("project_id") == project.id for j in active):
        raise HTTPException(409, "Hay un job en marcha para este proyecto: cancélalo primero")
    shutil.rmtree(storage.media_root() / f"u{user.id}" / f"p{project.id}", ignore_errors=True)
    db.delete(project)
    db.commit()
