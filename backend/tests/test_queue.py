from datetime import timedelta

from fastapi.testclient import TestClient

from app.db.models import Job, User
from app.jobs import queue

PW = "una-clave-larga-1"


def mkuser(db, email, limit=1):
    u = User(email=email, password_hash="x", max_concurrent_jobs=limit)
    db.add(u)
    db.commit()
    return u


def test_claim_fifo_and_per_user_limit(client):
    db = client.session_factory()
    a, b = mkuser(db, "a@x.com", 1), mkuser(db, "b@x.com", 1)
    a1, a2 = queue.enqueue(db, a.id, "demo"), queue.enqueue(db, a.id, "demo")
    b1 = queue.enqueue(db, b.id, "demo")

    assert queue.claim_next(db, "w1").id == a1.id
    # a ya tiene 1 corriendo (limite 1): se salta a2 y toca el de b
    assert queue.claim_next(db, "w1").id == b1.id
    assert queue.claim_next(db, "w1") is None
    queue.finish(db, a1.id)
    assert queue.claim_next(db, "w1").id == a2.id


def test_cancel_running_is_not_overwritten_by_finish(client):
    db = client.session_factory()
    u = mkuser(db, "a@x.com")
    j = queue.enqueue(db, u.id, "demo")
    queue.claim_next(db, "w1")
    queue.cancel(db, db.get(Job, j.id))
    queue.finish(db, j.id)
    assert db.get(Job, j.id).status == "cancelled"


def test_requeue_stale_then_fail_after_max_attempts(client):
    db = client.session_factory()
    u = mkuser(db, "a@x.com")
    j = queue.enqueue(db, u.id, "demo")
    for expected in ("queued", "queued", "failed"):
        queue.claim_next(db, "w1")
        job = db.get(Job, j.id)
        job.heartbeat_at = queue.utcnow() - timedelta(minutes=5)
        db.commit()
        assert queue.requeue_stale(db) == 1
        assert db.get(Job, j.id).status == expected


def test_inactive_user_jobs_not_claimed(client):
    db = client.session_factory()
    u = mkuser(db, "a@x.com")
    queue.enqueue(db, u.id, "demo")
    u.is_active = False
    db.commit()
    assert queue.claim_next(db, "w1") is None


def test_jobs_api_isolated_between_users(client):
    a = client
    b = TestClient(client.app)
    for c, mail in ((a, "a@x.com"), (b, "b@x.com")):
        assert c.post("/api/auth/register", json={"email": mail, "password": PW}).status_code == 201
    h = lambda c: {"X-CSRF-Token": c.cookies.get("csrf")}
    r = a.post("/api/jobs", json={"type": "demo"}, headers=h(a))
    assert r.status_code == 201
    jid = r.json()["id"]
    assert [j["id"] for j in a.get("/api/jobs").json()] == [jid]
    assert b.get("/api/jobs").json() == []
    assert b.get(f"/api/jobs/{jid}").status_code == 404
    assert b.post(f"/api/jobs/{jid}/cancel", headers=h(b)).status_code == 404
    assert b.get(f"/api/jobs/{jid}/log").status_code == 404
    assert a.post("/api/jobs", json={"type": "render"}, headers=h(a)).status_code == 400
