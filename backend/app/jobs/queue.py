"""Cola de jobs sobre la tabla `jobs`. Reclamar = pasar queued -> running de forma atomica."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.db.models import Job, User  # noqa: F401

STALE_AFTER = timedelta(minutes=2)
MAX_ATTEMPTS = 3
TERMINAL = {"completed", "failed", "cancelled"}
RENDER_TYPE = "render"  # carril global: solo un job de este tipo en marcha en todo el sistema


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def log_path_for(job_id: int):
    return get_settings().media_dir / "logs" / f"{job_id}.log"


def enqueue(db: Session, user_id: int, type_: str, payload: dict | None = None) -> Job:
    job = Job(user_id=user_id, type=type_, payload=payload or {})
    db.add(job)
    db.flush()
    job.log_path = str(log_path_for(job.id))
    db.commit()
    return job


@contextmanager
def _claim_lock(db: Session):
    """Serializa los reclamos entre workers: sin esto, dos workers podrian saltarse
    max_concurrent_jobs de un usuario (o el carril de render) a la vez.

    El cerrojo `GET_LOCK` pertenece a una CONEXION, no a la sesion: se toma y se libera en una conexion
    dedicada. Si se usara la de la sesion, el `commit()` de `claim_next` la devuelve al pool y `RELEASE_LOCK`
    podria ir por otra conexion distinta: el cerrojo quedaria retenido y los demas workers esperarian 10 s
    en cada intento."""
    engine = db.get_bind()
    if engine.dialect.name not in ("mysql", "mariadb"):
        yield
        return
    with engine.connect() as lock_conn:
        got = lock_conn.exec_driver_sql("SELECT GET_LOCK('clip_claim', 10)").scalar()
        if got != 1:
            yield False
            return
        try:
            yield
        finally:
            lock_conn.exec_driver_sql("SELECT RELEASE_LOCK('clip_claim')")


def claim_next(db: Session, worker_id: str) -> Job | None:
    running = (
        select(func.count()).select_from(Job)
        .where(Job.user_id == User.id, Job.status == "running")
        .correlate(User).scalar_subquery()
    )
    # Carril de render: un `render` en cola no se reclama mientras haya otro en marcha (de cualquier usuario).
    # No bloquea a los demás tipos de job: un detect de otro usuario sigue pudiendo pasar por delante.
    other = aliased(Job)
    render_busy = exists().where(other.type == RENDER_TYPE, other.status == "running")
    with _claim_lock(db) as ok:
        if ok is False:
            return None
        job = db.scalars(
            select(Job).join(User, User.id == Job.user_id)
            .where(Job.status == "queued", User.is_active.is_(True), running < User.max_concurrent_jobs,
                   or_(Job.type != RENDER_TYPE, ~render_busy))
            .order_by(Job.created_at, Job.id).limit(1).with_for_update(skip_locked=True)
        ).first()
        if job is None:
            db.rollback()
            return None
        now = utcnow()
        job.status, job.locked_by, job.heartbeat_at = "running", worker_id, now
        job.started_at, job.attempts = job.started_at or now, job.attempts + 1
        db.commit()
        return job


def heartbeat(db: Session, job_ids: list[int]) -> None:
    if job_ids:
        db.execute(update(Job).where(Job.id.in_(job_ids), Job.status == "running").values(heartbeat_at=utcnow()))
        db.commit()


def requeue_stale(db: Session) -> int:
    """Jobs 'running' sin latido (worker caido) vuelven a la cola, o fallan si ya se intentaron 3 veces."""
    cutoff = utcnow() - STALE_AFTER
    stale = db.scalars(select(Job).where(Job.status == "running", Job.heartbeat_at < cutoff)).all()
    for job in stale:
        if job.attempts < MAX_ATTEMPTS:
            job.status, job.locked_by, job.progress = "queued", None, 0
        else:
            job.status, job.error, job.ended_at = "failed", "Sin latido tras varios intentos", utcnow()
    db.commit()
    return len(stale)


def set_progress(db: Session, job_id: int, progress: int) -> None:
    db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(progress=max(0, min(100, progress))))
    db.commit()


def finish(db: Session, job_id: int, error: str | None = None) -> None:
    """No pisa un 'cancelled': si el usuario cancelo mientras corria, se queda cancelado."""
    values = {"ended_at": utcnow(), "locked_by": None}
    if error is None:
        values.update(status="completed", progress=100)
    else:
        values.update(status="failed", error=error[:2000])
    db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(**values))
    db.commit()


def cancel(db: Session, job: Job) -> bool:
    if job.status in TERMINAL:
        return False
    job.status, job.ended_at = "cancelled", utcnow()
    db.commit()
    return True


def is_cancelled(db: Session, job_id: int) -> bool:
    db.expire_all()
    return db.scalar(select(Job.status).where(Job.id == job_id)) == "cancelled"


def active_job(db: Session, user_id: int, project_id: int, *, ignore_types: tuple[str, ...] = ()) -> Job | None:
    """Job en cola o en marcha de este proyecto (de cualquier tipo salvo `ignore_types`), o None."""
    jobs = db.scalars(select(Job).where(Job.user_id == user_id, Job.status.in_(("queued", "running")))).all()
    return next((j for j in jobs if j.type not in ignore_types and (j.payload or {}).get("project_id") == project_id), None)
