"""Librería de assets del usuario: subir, listar, renombrar y borrar imágenes para los gráficos."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import get_db
from app.db.models import Asset, BrandTemplate, Clip, User
from app.services import assets as assets_service
from app.services import country_maps
from app.services import media_sign, storage

router = APIRouter(prefix="/api/assets", tags=["assets"])
MAX_ASSETS = 200


class AssetOut(BaseModel):
    id: int
    name: str
    kind: str
    tags: list[str]
    width: int
    height: int
    url: str | None
    created_at: datetime | None


def _out(a: Asset) -> AssetOut:
    return AssetOut(id=a.id, name=a.name, kind=a.kind, tags=a.tags or [], width=a.width, height=a.height,
                    url=media_sign.signed_url(a.path)["url"] if a.path else None, created_at=a.created_at)


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=10)


def used_by(db: Session, user_id: int, asset_id: int) -> tuple[int, int]:
    """(clips con un gráfico de esta imagen, plantillas que la usan como objeto que orbita)."""
    clips = db.scalars(select(Clip).where(Clip.user_id == user_id)).all()
    templates = db.scalars(select(BrandTemplate).where(BrandTemplate.user_id == user_id)).all()
    return (sum(1 for c in clips if any(g.get("asset_id") == asset_id for g in (c.graphics_json or []) if isinstance(g, dict))),
            sum(1 for t in templates if (t.cortinilla or {}).get("orbit_asset_id") == asset_id))


@router.get("", response_model=list[AssetOut])
def list_assets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_out(a) for a in db.scalars(select(Asset).where(Asset.user_id == user.id).order_by(Asset.id.desc())).all()]


class MapsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    countries: list[str] = Field(min_length=1, max_length=60)


@router.get("/maps/countries")
def map_countries(user: User = Depends(current_user)):
    """Países de los que se puede generar el mapa, en español."""
    return country_maps.available()


@router.post("/maps", response_model=list[AssetOut], status_code=201)
def add_country_maps(body: MapsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Genera el mapa de cada país pedido y lo añade a la librería (los que ya están no se duplican). Devuelve los nuevos."""
    names = list(dict.fromkeys(body.countries))
    unknown = [n for n in names if n not in country_maps.names()]
    if unknown:
        raise HTTPException(422, f"País desconocido: {', '.join(unknown)}")
    have = {a.source for a in db.scalars(select(Asset).where(Asset.user_id == user.id, Asset.kind == "map")).all()}
    todo = [n for n in names if f"country:{n}" not in have]
    total = len(db.scalars(select(Asset.id).where(Asset.user_id == user.id)).all())
    if total + len(todo) > MAX_ASSETS:
        raise HTTPException(409, f"Superarías el máximo de {MAX_ASSETS} imágenes: borra alguna")
    folder = storage.media_root() / f"u{user.id}" / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    created: list[Asset] = []
    for name in todo:
        png, width, height = assets_service.process_upload(country_maps.render(name))
        asset = Asset(user_id=user.id, kind="map", name=f"Mapa de {name}", tags=["mapa", name.lower()], source=f"country:{name}",
                      license_note="Natural Earth (dominio público) vía world-atlas", width=width, height=height, size_bytes=len(png))
        db.add(asset)
        db.commit()
        target = folder / f"{asset.id}.png"
        target.write_bytes(png)
        asset.path = storage.rel(target)
        db.commit()
        created.append(asset)
    return [_out(a) for a in created]


@router.post("", response_model=AssetOut, status_code=201)
async def upload_asset(file: UploadFile = File(...), name: str = Form(default=""), user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    if db.scalar(select(Asset.id).where(Asset.user_id == user.id).offset(MAX_ASSETS - 1).limit(1)) is not None:
        raise HTTPException(409, f"Has llegado al máximo de {MAX_ASSETS} imágenes: borra alguna")
    data = await file.read(assets_service.MAX_BYTES + 1)
    try:
        png, width, height = assets_service.process_upload(data)
    except assets_service.AssetError as exc:
        raise HTTPException(422, str(exc)) from exc
    label = (name or (file.filename or "").rsplit(".", 1)[0] or "Imagen").strip()[:120] or "Imagen"
    asset = Asset(user_id=user.id, name=label, width=width, height=height, size_bytes=len(png))
    db.add(asset)
    db.commit()
    folder = storage.media_root() / f"u{user.id}" / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{asset.id}.png"
    target.write_bytes(png)
    asset.path = storage.rel(target)
    db.commit()
    return _out(asset)


@router.patch("/{asset_id}", response_model=AssetOut)
def patch_asset(asset_id: int, body: AssetPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = get_owned(db, Asset, asset_id, user)
    if body.name is not None:
        asset.name = body.name.strip()
    if body.tags is not None:
        asset.tags = [t.strip()[:40] for t in body.tags if t.strip()]
    db.commit()
    return _out(asset)


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = get_owned(db, Asset, asset_id, user)
    clips, templates = used_by(db, user.id, asset.id)
    if clips or templates:
        parts = ([f"{clips} clip{'s' if clips != 1 else ''}"] if clips else []) + ([f"{templates} plantilla{'s' if templates != 1 else ''}"] if templates else [])
        raise HTTPException(409, f"La imagen se usa en {' y '.join(parts)}: quítala primero de ahí")
    if asset.path:
        try:
            storage.absolute(asset.path).unlink(missing_ok=True)
        except (ValueError, OSError):
            pass
    db.delete(asset)
    db.commit()
