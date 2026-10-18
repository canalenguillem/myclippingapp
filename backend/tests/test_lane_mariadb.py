"""Carrera real de workers sobre MariaDB. Se omite por defecto (los tests usan SQLite, que no tiene GET_LOCK).

Ejecutar contra la BD de desarrollo, dentro del contenedor del backend:
    docker compose exec -e RUN_MARIADB_TESTS=1 backend python -m pytest -q tests/test_lane_mariadb.py
Crea y borra sus propios usuarios (lane*@test.local).
"""
import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_MARIADB_TESTS") != "1", reason="necesita MariaDB real")


def test_two_workers_never_claim_two_renders_and_the_lock_is_always_released():
    from app.db import SessionLocal
    from app.db.models import Job, User
    from app.jobs import queue

    db = SessionLocal()
    users = []
    for i in range(2):
        u = User(email=f"lane{i}@test.local", password_hash="x", max_concurrent_jobs=1)
        db.add(u)
        db.commit()
        users.append(u)
    ids = [u.id for u in users]
    try:
        for _ in range(25):
            db.query(Job).filter(Job.user_id.in_(ids)).delete(synchronize_session=False)
            db.commit()
            for u in users:
                queue.enqueue(db, u.id, "render")
            claimed, barrier = [], threading.Barrier(2)

            def worker(name):
                s = SessionLocal()
                barrier.wait()
                j = queue.claim_next(s, name)
                claimed.append(j.id if j else None)
                s.close()

            threads = [threading.Thread(target=worker, args=(f"w{k}",)) for k in range(2)]
            t0 = time.monotonic()
            [t.start() for t in threads]
            [t.join() for t in threads]
            assert time.monotonic() - t0 < 5, "un worker esperó al cerrojo: no se liberó"
            assert len([c for c in claimed if c is not None]) == 1
            assert db.query(Job).filter(Job.user_id.in_(ids), Job.type == "render", Job.status == "running").count() == 1
        # el cerrojo no se queda retenido
        assert db.get_bind().connect().exec_driver_sql("SELECT IS_FREE_LOCK('clip_claim')").scalar() == 1
    finally:
        db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
