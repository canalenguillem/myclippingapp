"""Consumidor de la cola: reclama jobs y los ejecuta en un pool de hilos."""
from __future__ import annotations

import os
import socket
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.db import SessionLocal
from app.jobs import queue
from app.jobs.handlers import HANDLERS, Cancelled, JobContext

POLL_SECONDS = 2
HEARTBEAT_SECONDS = 10
CLEANUP_SECONDS = 3600

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
_running: set[int] = set()
_running_lock = threading.Lock()


def run_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(queue.Job, job_id)
        ctx = JobContext(db=db, job_id=job.id, user_id=job.user_id, log_file=queue.log_path_for(job.id))
        handler = HANDLERS.get(job.type)
        try:
            if handler is None:
                raise RuntimeError(f"Sin handler para el tipo '{job.type}'")
            handler(ctx, job.payload or {})
            queue.finish(db, job_id)
        except Cancelled:
            ctx.log("cancelado por el usuario")
        except Exception as exc:  # noqa: BLE001 - cualquier fallo del handler marca el job como fallido
            ctx.log(traceback.format_exc())
            queue.finish(db, job_id, error=f"{type(exc).__name__}: {exc}")
    finally:
        db.close()
        with _running_lock:
            _running.discard(job_id)


def heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        with _running_lock:
            ids = list(_running)
        db = SessionLocal()
        try:
            queue.heartbeat(db, ids)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            db.close()


def clean_old_media() -> None:
    """Libera el disco de los proyectos sin actividad (lo pesado se regenera descargando el vídeo de nuevo)."""
    from app.services import cleanup

    days = get_settings().media_retention_days
    db = SessionLocal()
    try:
        projects, freed = cleanup.cleanup_old(db, days)
        if projects:
            print(f"worker: {projects} proyecto(s) sin actividad en {days} días; liberados {freed / 1e9:.1f} GB", flush=True)
    except Exception:  # noqa: BLE001 - la limpieza nunca debe parar el worker
        traceback.print_exc()
    finally:
        db.close()


def main() -> None:
    slots = max(1, get_settings().worker_concurrency)
    print(f"worker {WORKER_ID}: {slots} slots", flush=True)
    db = SessionLocal()
    print(f"worker: {queue.requeue_stale(db)} jobs huerfanos devueltos a la cola", flush=True)
    db.close()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    last_stale_check = time.monotonic()
    last_cleanup = 0.0
    with ThreadPoolExecutor(max_workers=slots) as pool:
        while True:
            with _running_lock:
                free = slots - len(_running)
            claimed = None
            if free > 0:
                db = SessionLocal()
                try:
                    claimed = queue.claim_next(db, WORKER_ID)
                    if claimed is not None:
                        with _running_lock:
                            _running.add(claimed.id)
                        pool.submit(run_job, claimed.id)
                    if time.monotonic() - last_stale_check > 60:
                        queue.requeue_stale(db)
                        last_stale_check = time.monotonic()
                except Exception:  # noqa: BLE001 - la BD puede caer un momento; reintentamos
                    traceback.print_exc()
                finally:
                    db.close()
            if time.monotonic() - last_cleanup > CLEANUP_SECONDS:
                last_cleanup = time.monotonic()
                clean_old_media()
            if claimed is None:
                time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
