import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import SessionLocal, get_db
from app.db.models import Job, User
from app.jobs import queue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Tipos que un usuario puede encolar directamente. El resto los encola el propio backend.
USER_ENQUEUEABLE = {"demo"}  # ingest lo encola POST /api/projects


class JobOut(BaseModel):
    id: int
    type: str
    status: str
    progress: int
    error: str | None
    attempts: int
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    model_config = {"from_attributes": True}


class JobIn(BaseModel):
    type: str
    payload: dict = {}


@router.get("", response_model=list[JobOut])
def list_jobs(limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Job).where(Job.user_id == user.id).order_by(Job.id.desc()).limit(min(limit, 200))).all()


@router.post("", response_model=JobOut, status_code=201)
def create_job(body: JobIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.type not in USER_ENQUEUEABLE:
        raise HTTPException(400, f"Tipo no permitido: {body.type}")
    return queue.enqueue(db, user.id, body.type, body.payload)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_owned(db, Job, job_id, user)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = get_owned(db, Job, job_id, user)
    if not queue.cancel(db, job):
        raise HTTPException(409, "El job ya habia terminado")
    return job


@router.get("/{job_id}/log")
def job_log(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = get_owned(db, Job, job_id, user)
    path = queue.log_path_for(job.id)
    return {"log": path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""}


@router.get("/{job_id}/stream")
def stream_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """SSE: eventos `log` (lineas nuevas) y `status` ({status, progress}). Cierra al terminar el job."""
    get_owned(db, Job, job_id, user)
    path = queue.log_path_for(job_id)

    def events():
        offset, last = 0, None
        while True:
            chunk = ""
            if path.exists():
                with path.open("rb") as fh:
                    fh.seek(offset)
                    data = fh.read()
                    offset += len(data)
                    chunk = data.decode("utf-8", errors="replace")
            for line in chunk.splitlines():
                yield f"event: log\ndata: {json.dumps(line)}\n\n"
            with SessionLocal() as s:
                row = s.get(Job, job_id)
                state = {"status": row.status, "progress": row.progress, "error": row.error}
            if state != last:
                yield f"event: status\ndata: {json.dumps(state)}\n\n"
                last = state
            if state["status"] in queue.TERMINAL and not chunk:
                return
            time.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
