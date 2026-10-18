"""Plantillas de marca por usuario: cortinillas (inicio y final), preset de estilo y vista previa sin renderizar."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import get_db
from app.db.models import BrandTemplate, Clip, Project, User
from app.services import clips as clips_service
from app.services import fx_request
from app.services.fx_client import FxError, make_fx_client

router = APIRouter(prefix="/api/templates", tags=["templates"])

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CortinillaIn(BaseModel):
    """Textos y tiempos de las cortinillas. Todo depende del canal, por eso lo edita cada usuario."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=40)          # la última palabra sale en serif cursiva
    kicker: str = Field(default="", max_length=60)
    color: str | None = None                                # None = color primario de la plantilla o el de marca por defecto
    duration: float = Field(default=3.6, ge=1.0, le=10.0)
    handle: str = Field(default="", max_length=40)
    outro_text: str = Field(default="", max_length=80)
    outro_duration: float = Field(default=2.5, ge=1.0, le=10.0)
    like: str = Field(default="ME GUSTA", min_length=1, max_length=20)
    subscribe: str = Field(default="SUSCRÍBETE", min_length=1, max_length=20)

    @field_validator("color")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        if v is not None and not _HEX.match(v):
            raise ValueError("color debe ser #RRGGBB")
        return v.upper() if v else v


class ColorsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str | None = None

    @field_validator("primary")
    @classmethod
    def _primary(cls, v: str | None) -> str | None:
        if v is not None and not _HEX.match(v):
            raise ValueError("primary debe ser #RRGGBB")
        return v.upper() if v else v


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    preset: Literal["editorial", "hormozi", "minimal"] = "editorial"
    colors: ColorsIn = Field(default_factory=ColorsIn)
    sfx: bool = True
    cortinilla_default: bool = False
    cortinilla: CortinillaIn = Field(default_factory=CortinillaIn)


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    preset: Literal["editorial", "hormozi", "minimal"] | None = None
    colors: ColorsIn | None = None
    sfx: bool | None = None
    cortinilla_default: bool | None = None
    cortinilla: CortinillaIn | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    preset: str
    colors: dict
    sfx: bool
    cortinilla_default: bool
    cortinilla: dict
    created_at: datetime | None


def _out(t: BrandTemplate) -> TemplateOut:
    return TemplateOut(id=t.id, name=t.name, preset=t.preset, colors=t.colors or {}, sfx=t.sfx, cortinilla_default=t.cortinilla_default,
                       cortinilla=t.cortinilla or {}, created_at=t.created_at)


def _dump(model: BaseModel | None) -> dict:
    return model.model_dump(exclude_none=True) if model is not None else {}


@router.get("", response_model=list[TemplateOut])
def list_templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(t) for t in db.scalars(select(BrandTemplate).where(BrandTemplate.user_id == user.id).order_by(BrandTemplate.id)).all()]


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(body: TemplateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = BrandTemplate(user_id=user.id, name=body.name.strip(), preset=body.preset, colors=_dump(body.colors), sfx=body.sfx,
                      cortinilla_default=body.cortinilla_default, cortinilla=_dump(body.cortinilla))
    db.add(t)
    db.commit()
    return _out(t)


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(get_owned(db, BrandTemplate, template_id, user))


@router.patch("/{template_id}", response_model=TemplateOut)
def patch_template(template_id: int, body: TemplatePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = get_owned(db, BrandTemplate, template_id, user)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        t.name = changes["name"].strip()
    for field in ("preset", "sfx", "cortinilla_default"):
        if field in changes:
            setattr(t, field, changes[field])
    if body.colors is not None:
        t.colors = _dump(body.colors)
    if body.cortinilla is not None:
        t.cortinilla = _dump(body.cortinilla)
    # Los renders de los clips que usan esta plantilla ya no reflejan su aspecto: se invalidan (no los que están en marcha).
    stale = db.scalars(select(Clip).where(Clip.template_id == t.id, Clip.user_id == user.id)).all()
    for clip in stale:
        if clip.render_state.value in ("draft", "final", "failed"):
            clips_service.invalidate_render(clip)
    db.commit()
    return _out(t)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = get_owned(db, BrandTemplate, template_id, user)
    # Los clips y proyectos que la usaban vuelven a la plantilla por defecto (sin plantilla); sus renders ya no valen.
    for clip in db.scalars(select(Clip).where(Clip.template_id == t.id, Clip.user_id == user.id)).all():
        if clip.render_state.value in ("draft", "final", "failed"):
            clips_service.invalidate_render(clip)
    db.execute(update(Clip).where(Clip.template_id == t.id).values(template_id=None))
    db.execute(update(Project).where(Project.default_template_id == t.id).values(default_template_id=None))
    db.delete(t)
    db.commit()


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colors: ColorsIn = Field(default_factory=ColorsIn)
    cortinilla: CortinillaIn = Field(default_factory=CortinillaIn)


@router.post("/preview")
def preview(body: PreviewIn, user: User = Depends(current_user)):
    """HTML autocontenido de la cortinilla de inicio y la final, para <hyperframes-player srcdoc>. No guarda nada."""
    client = make_fx_client()
    if client is None:
        raise HTTPException(503, "El servicio de render no está configurado")
    config, colors = _dump(body.cortinilla), _dump(body.colors)
    start = fx_request.cortinilla_params(config, colors, at=1.0, orbit=None)
    start.pop("at")
    request = {"cortinilla": start, "outro": fx_request.outro_params(config, colors)}
    try:
        return client.preview(request)
    except FxError as exc:
        raise HTTPException(503, str(exc)) from exc
