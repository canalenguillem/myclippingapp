"""Administración de usuarios: cuántos jobs a la vez puede tener cada uno, minutos máximos de vídeo y si está activo."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_admin
from app.config import get_settings
from app.db import get_db
from app.db.models import Job, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    max_concurrent_jobs: int
    max_video_minutes: int
    running_jobs: int
    queued_jobs: int
    created_at: datetime | None


class AdminUsersOut(BaseModel):
    render_lanes: int          # renders a la vez en todo el sistema (RENDER_LANES; se cambia en el .env del servidor)
    users: list[AdminUserOut]


class AdminUserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=8)
    max_video_minutes: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool | None = None


def _out(db: Session, u: User) -> AdminUserOut:
    counts = dict(db.execute(select(Job.status, func.count()).where(Job.user_id == u.id, Job.status.in_(("running", "queued"))).group_by(Job.status)).all())
    return AdminUserOut(id=u.id, email=u.email, name=u.name or "", role=u.role, is_active=u.is_active, max_concurrent_jobs=u.max_concurrent_jobs,
                        max_video_minutes=u.max_video_minutes, running_jobs=counts.get("running", 0), queued_jobs=counts.get("queued", 0), created_at=u.created_at)


@router.get("/users", response_model=AdminUsersOut)
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.id)).all()
    return AdminUsersOut(render_lanes=max(1, get_settings().render_lanes), users=[_out(db, u) for u in users])


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def patch_user(user_id: int, body: AdminUserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No encontrado")
    sent = body.model_fields_set
    if "is_active" in sent and body.is_active is False and user.id == admin.id:
        raise HTTPException(422, "No puedes desactivar tu propia cuenta")
    for field in ("max_concurrent_jobs", "max_video_minutes", "is_active"):
        if field in sent and getattr(body, field) is not None:
            setattr(user, field, getattr(body, field))
    db.commit()
    return _out(db, user)
