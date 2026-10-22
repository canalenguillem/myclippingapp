import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, get_owned
from app.db import get_db
from app.db.models import Clip, Project, User
from app.jobs import queue
from app.services import clips as clips_service
from app.services import speakers as speakers_service
from app.services import storage, transcription

router = APIRouter(prefix="/api/projects/{project_id}", tags=["transcript"])

LABEL = re.compile(r"^[A-Za-z0-9]{1,8}$")


class WordEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=80)


class WordsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    edits: list[WordEdit] = Field(min_length=1, max_length=2000)


class SpeakerRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    speaker: str | None = None      # None = quitar el speaker de esas palabras («sin speaker»)


class SpeakersPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    ranges: list[SpeakerRange] = Field(min_length=1, max_length=500)


class SpeakerCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=80)
    role: str = Field(default="", max_length=120)
    caption_style: str = "sans_upper"
    is_source: bool = False
    focus_x: float = Field(default=0.5, ge=0, le=1)  # dónde está en el plano (0 izquierda, 1 derecha); lo usa «Sigue al hablante»


class Revision(BaseModel):
    revision: int


def _editable(db: Session, user: User, project_id: int) -> Project:
    project = get_owned(db, Project, project_id, user)
    if not project.words_path:
        raise HTTPException(409, "El proyecto aún no tiene transcripción")
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto; espera a que termine")
    return project


def _refresh_clips(db: Session, project: Project, words: list[dict], changed: dict[float, str]) -> None:
    """Los clips guardan una copia del texto y de las palabras de énfasis: se actualizan con la corrección."""
    for clip in db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == project.user_id)):
        clip.transcript = clips_service.text_between(words, clip.start, clip.end)
        if clip.emphasis_json and changed:
            clip.emphasis_json = [
                {**e, "text": changed[w]} if (w := next((s for s in changed if abs(s - e["start"]) < 0.001), None)) is not None else e
                for e in clip.emphasis_json
            ]
    db.commit()


def _run(path, revision: int, mutate):
    try:
        return transcription.update_words(path, revision, mutate)
    except transcription.RevisionConflict:
        raise HTTPException(409, "La transcripción cambió mientras la editabas; recárgala")


@router.patch("/transcript/words", response_model=Revision)
def edit_words(project_id: int, body: WordsPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Corrige el texto de palabras concretas conservando sus tiempos, speaker y confianza."""
    project = _editable(db, user, project_id)
    path = storage.absolute(project.words_path)
    changed: dict[float, str] = {}

    def mutate(data: dict) -> None:
        n = len(data["words"])
        for e in body.edits:
            if e.index >= n:
                raise HTTPException(422, f"Índice de palabra fuera de rango: {e.index}")
            text = e.text.strip()
            if not text or any(ch in text for ch in "\n\r\t") or " " in text:
                raise HTTPException(422, "Cada palabra debe ser un solo token sin espacios ni saltos de línea")
            data["words"][e.index]["text"] = text
            changed[data["words"][e.index]["start"]] = text
        transcription.rebuild_text(data)
        transcription.refresh_segments(data, regroup=False)

    revision = _run(path, body.revision, mutate)
    _refresh_clips(db, project, transcription.load_words(path)["words"], changed)
    clips_service.invalidate_project_renders(db, project)  # los subtítulos renderizados llevan el texto viejo
    return Revision(revision=revision)


@router.patch("/transcript/speakers", response_model=Revision)
def reassign_speakers(project_id: int, body: SpeakersPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reasigna el speaker de rangos de palabras (índices inclusivos) sin tocar los tiempos."""
    project = _editable(db, user, project_id)
    path = storage.absolute(project.words_path)
    known = set(project.speakers or {})
    for r in body.ranges:
        if r.speaker is not None and r.speaker not in known:
            raise HTTPException(422, f"El speaker «{r.speaker}» no existe en este proyecto")
        if r.end_index < r.start_index:
            raise HTTPException(422, "end_index no puede ser menor que start_index")

    def mutate(data: dict) -> None:
        n = len(data["words"])
        for r in body.ranges:
            if r.end_index >= n:
                raise HTTPException(422, f"Índice de palabra fuera de rango: {r.end_index}")
            for w in data["words"][r.start_index:r.end_index + 1]:
                if r.speaker is None:
                    w.pop("speaker", None)
                else:
                    w["speaker"] = r.speaker
        transcription.refresh_segments(data, regroup=True)

    revision = _run(path, body.revision, mutate)
    clips_service.invalidate_project_renders(db, project)  # el estilo de subtítulo depende del speaker
    return Revision(revision=revision)


@router.put("/speakers")
def put_speakers(project_id: int, body: dict[str, SpeakerCard], user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Sustituye las fichas de speakers (nombre, cargo, estilo de subtítulo, clip citado)."""
    project = get_owned(db, Project, project_id, user)
    if queue.active_job(db, user.id, project.id):
        raise HTTPException(409, "Hay un job en marcha para este proyecto; espera a que termine")
    for label, card in body.items():
        if not LABEL.match(label):
            raise HTTPException(422, f"Etiqueta de speaker no válida: {label!r}")
        if card.caption_style not in speakers_service.CAPTION_STYLES:
            raise HTTPException(422, f"caption_style debe ser uno de {speakers_service.CAPTION_STYLES}")
    if project.words_path:
        used = set(transcription.speaker_labels(transcription.load_words(storage.absolute(project.words_path))))
        missing = used - set(body)
        if missing:
            raise HTTPException(422, f"No se pueden quitar speakers que aún tienen palabras: {sorted(missing)}")
    project.speakers = {label: card.model_dump() for label, card in body.items()}
    db.commit()
    clips_service.invalidate_project_renders(db, project)  # nombre, cargo y estilo salen en el render
    return project.speakers
