"""Persistencia de los clips detectados."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Clip, Project, RenderState
from app.services import storage
from app.services.clip_detector import ClipCandidate


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return min(a_end, b_end) - max(a_start, b_start) > 0.5 * min(a_end - a_start, b_end - b_start)


def replace_detected_clips(db: Session, project: Project, candidates: list[ClipCandidate]) -> tuple[int, int]:
    """Sustituye los clips sin trabajar (`detected`) por los nuevos. Los demás (aprobados, renderizados…)
    se conservan, y un candidato que se pise con uno de ellos se descarta para no duplicarlo.
    Devuelve (insertados, descartados por solape)."""
    db.execute(delete(Clip).where(Clip.project_id == project.id, Clip.user_id == project.user_id, Clip.status == "detected"))
    kept = db.scalars(select(Clip).where(Clip.project_id == project.id, Clip.user_id == project.user_id)).all()
    inserted = skipped = 0
    for c in candidates:
        if any(_overlaps(c.start, c.end, k.start, k.end) for k in kept):
            skipped += 1
            continue
        db.add(Clip(
            project_id=project.id, user_id=project.user_id, start=c.start, end=c.end, title=c.title,
            reason=c.reason, score=c.score, transcript=c.transcript, hook=c.hook, emphasis_json=c.emphasis,
            parts=c.parts, template_id=project.default_template_id, channel_id=project.default_channel_id,
        ))
        inserted += 1
    db.commit()
    return inserted, skipped


def text_between(words: list[dict], start: float, end: float) -> str:
    """Texto de las palabras que caen dentro de [start, end] (segundos), para refrescar `Clip.transcript`."""
    return " ".join(w["text"] for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05)[:2000]


# Campos del clip que cambian el vídeo renderizado: editarlos deja obsoletos el borrador y el final.
RENDER_AFFECTING = frozenset({"start", "end", "hook", "layout", "focus", "zoom", "top_ratio", "intro_enabled"})


def drop_render_files(clip: Clip) -> None:
    """Borra del disco los ficheros de render del clip (si existen) y limpia sus rutas."""
    for attr in ("draft_path", "rendered_path", "thumbnail_path"):
        rel = getattr(clip, attr)
        if rel:
            try:
                storage.absolute(rel).unlink(missing_ok=True)
            except (ValueError, OSError):
                pass  # ruta rara o fichero ya ido: no impide limpiar el estado
        setattr(clip, attr, None)


def invalidate_render(clip: Clip) -> None:
    drop_render_files(clip)
    clip.render_state = RenderState.NONE
    clip.render_error = None
    clip.rendered_at = None


def invalidate_project_renders(db: Session, project: Project) -> int:
    """Texto de la transcripción o estilo de los speakers cambiaron: los renders del proyecto ya no valen."""
    clips = db.scalars(
        select(Clip).where(
            Clip.project_id == project.id, Clip.user_id == project.user_id,
            Clip.render_state.in_((RenderState.DRAFT, RenderState.FINAL, RenderState.FAILED)),
        )
    ).all()
    for clip in clips:
        invalidate_render(clip)
    db.commit()
    return len(clips)
