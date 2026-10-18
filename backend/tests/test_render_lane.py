from datetime import timedelta

from app.db.models import Job, User
from app.jobs import queue


def mkuser(db, email, limit=1):
    u = User(email=email, password_hash="x", max_concurrent_jobs=limit)
    db.add(u)
    db.commit()
    return u


def test_only_one_render_runs_in_the_whole_system(client):
    db = client.session_factory()
    a, b = mkuser(db, "a@x.com"), mkuser(db, "b@x.com")
    ra, rb = queue.enqueue(db, a.id, "render"), queue.enqueue(db, b.id, "render")
    assert queue.claim_next(db, "w1").id == ra.id
    assert queue.claim_next(db, "w2") is None          # el render de B espera aunque haya otro worker libre
    queue.finish(db, ra.id)
    assert queue.claim_next(db, "w2").id == rb.id      # al liberarse el carril, entra el siguiente


def test_the_lane_applies_even_if_one_user_may_run_several_jobs(client):
    db = client.session_factory()
    a = mkuser(db, "a@x.com", limit=3)
    r1, r2 = queue.enqueue(db, a.id, "render"), queue.enqueue(db, a.id, "render")
    assert queue.claim_next(db, "w").id == r1.id
    assert queue.claim_next(db, "w") is None


def test_a_waiting_render_does_not_block_other_job_types(client):
    db = client.session_factory()
    a, b = mkuser(db, "a@x.com"), mkuser(db, "b@x.com")
    ra = queue.enqueue(db, a.id, "render")
    rb = queue.enqueue(db, b.id, "render")
    detect = queue.enqueue(db, b.id, "detect")  # llega después, pero no es un render
    assert queue.claim_next(db, "w").id == ra.id
    claimed = queue.claim_next(db, "w")
    assert claimed.id != rb.id and claimed.type != "render"
    assert claimed.id == detect.id


def test_renders_run_in_arrival_order(client):
    db = client.session_factory()
    users = [mkuser(db, f"u{i}@x.com") for i in range(3)]
    jobs = [queue.enqueue(db, u.id, "render") for u in users]
    order = []
    for _ in jobs:
        j = queue.claim_next(db, "w")
        order.append(j.id)
        queue.finish(db, j.id)
    assert order == [j.id for j in jobs]


def test_failed_and_cancelled_renders_free_the_lane(client):
    db = client.session_factory()
    a, b = mkuser(db, "a@x.com"), mkuser(db, "b@x.com")
    ra, rb = queue.enqueue(db, a.id, "render"), queue.enqueue(db, b.id, "render")
    queue.claim_next(db, "w")
    assert queue.claim_next(db, "w") is None
    queue.finish(db, ra.id, error="ffmpeg falló")
    assert queue.claim_next(db, "w").id == rb.id
    rc = queue.enqueue(db, a.id, "render")
    assert queue.claim_next(db, "w") is None
    queue.cancel(db, db.get(Job, rb.id))
    assert queue.claim_next(db, "w").id == rc.id


def test_a_dead_render_frees_the_lane_after_the_stale_timeout(client):
    db = client.session_factory()
    a, b = mkuser(db, "a@x.com"), mkuser(db, "b@x.com")
    ra, rb = queue.enqueue(db, a.id, "render"), queue.enqueue(db, b.id, "render")
    queue.claim_next(db, "w1")
    db.get(Job, ra.id).heartbeat_at = queue.utcnow() - timedelta(minutes=5)  # el worker murió
    db.commit()
    assert queue.requeue_stale(db) == 1
    # A vuelve a la cola (llegó antes que B) y el carril está libre
    assert queue.claim_next(db, "w2").id == ra.id
