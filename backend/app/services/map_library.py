"""Mapas de países en la librería del usuario: crear los que faltan y localizar el de cada país."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset
from app.services import assets as assets_service
from app.services import country_maps, storage

MAX_ASSETS = 200
MAP_PREFIX = "Mapa de "


def existing(db: Session, user_id: int) -> dict[str, Asset]:
    """País → su mapa en la librería del usuario."""
    maps = db.scalars(select(Asset).where(Asset.user_id == user_id, Asset.kind == "map")).all()
    return {a.source.removeprefix("country:"): a for a in maps if a.source.startswith("country:")}


class LibraryFull(Exception):
    pass


def ensure(db: Session, user_id: int, names: list[str], *, strict: bool = False) -> list[Asset]:
    """Crea los mapas que aún no están y devuelve solo los nuevos. Si la librería está llena: `strict` lanza LibraryFull;
    si no, se crean los que quepan."""
    have = existing(db, user_id)
    todo = [n for n in dict.fromkeys(names) if n not in have]
    room = MAX_ASSETS - len(db.scalars(select(Asset.id).where(Asset.user_id == user_id)).all())
    if len(todo) > room:
        if strict:
            raise LibraryFull(f"Superarías el máximo de {MAX_ASSETS} imágenes: borra alguna")
        todo = todo[:max(room, 0)]
    folder = storage.media_root() / f"u{user_id}" / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    created: list[Asset] = []
    for name in todo:
        png, width, height = assets_service.process_upload(country_maps.render(name))
        asset = Asset(user_id=user_id, kind="map", name=f"{MAP_PREFIX}{name}", tags=["mapa", name.lower()], source=f"country:{name}",
                      license_note="Natural Earth (dominio público) vía world-atlas", width=width, height=height, size_bytes=len(png))
        db.add(asset)
        db.commit()
        target = folder / f"{asset.id}.png"
        target.write_bytes(png)
        asset.path = storage.rel(target)
        db.commit()
        created.append(asset)
    return created
