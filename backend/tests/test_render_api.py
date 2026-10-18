import shutil

import pytest
from fastapi.testclient import TestClient

from app.db.models import Job, RenderState
from app.services import storage
from tests.media_helpers import make_source, probe
from tests.test_clips_api import _clip, _login, _project


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make_source(tmp_path_factory.mktemp("rapi") / "s.mp4", 4)


def render_jobs(db):
    db.expire_all()
    return db.query(Job).filter(Job.type == "render").order_by(Job.id).all()


def test_draft_enqueues_a_render_job_and_marks_the_clip(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    c = _clip(db, p)
    r = client.post(f"/api/clips/{c.id}/render", json={}, headers=h)
    assert r.status_code == 202
    (job,) = render_jobs(db)
    assert job.id == r.json()["job_id"] and job.payload == {"clip_id": c.id, "project_id": p.id, "quality": "draft"}
    out = client.get(f"/api/clips/{c.id}").json()
    assert out["render_state"] == "rendering" and out["render_job_id"] == job.id and out["render_error"] is None
    assert client.get(f"/api/projects/{p.id}/clips").json()[0]["render_job_id"] == job.id
    assert client.post(f"/api/clips/{c.id}/render", json={}, headers=h).status_code == 409  # ya en marcha


def test_final_needs_an_approved_clip(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    c = _clip(db, p)
    assert client.post(f"/api/clips/{c.id}/render", json={"quality": "final"}, headers=h).status_code == 409
    client.post(f"/api/clips/{c.id}/approve", headers=h)
    assert client.post(f"/api/clips/{c.id}/render", json={"quality": "final"}, headers=h).status_code == 202


def test_rejects_bad_requests(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p)
    assert client.post(f"/api/clips/{c.id}/render", json={}, headers=h).status_code == 409      # sin vídeo de origen
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    assert client.post(f"/api/clips/{c.id}/render", json={"quality": "ultra"}, headers=h).status_code == 422
    c.layout = "full"
    db.commit()
    r = client.post(f"/api/clips/{c.id}/render", json={}, headers=h)
    assert r.status_code == 409 and "split" in r.json()["detail"]
    assert not render_jobs(db) and client.get(f"/api/clips/{c.id}").json()["render_state"] == "none"


def test_no_render_while_another_job_runs_in_the_project(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    a, b = _clip(db, p, 10, 40), _clip(db, p, 50, 80)
    assert client.post(f"/api/clips/{a.id}/render", json={}, headers=h).status_code == 202
    assert client.post(f"/api/clips/{b.id}/render", json={}, headers=h).status_code == 202  # otros renders se encolan
    db.add(Job(user_id=p.user_id, type="detect", status="queued", payload={"project_id": p.id}))
    db.commit()
    c = _clip(db, p, 85, 95)
    assert client.post(f"/api/clips/{c.id}/render", json={}, headers=h).status_code == 409


def test_cancel_a_queued_render_restores_the_state(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    c = _clip(db, p, draft_path="u1/p1/clip_1/draft.mp4", render_state=RenderState.DRAFT)
    client.post(f"/api/clips/{c.id}/render", json={}, headers=h)
    assert client.post(f"/api/clips/{c.id}/render/cancel", headers=h).status_code == 204
    out = client.get(f"/api/clips/{c.id}").json()
    assert out["render_state"] == "draft" and out["render_job_id"] is None and render_jobs(db)[0].status == "cancelled"
    assert client.post(f"/api/clips/{c.id}/render/cancel", headers=h).status_code == 409  # nada en curso


def test_cancel_through_the_jobs_endpoint_also_restores(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    c = _clip(db, p)
    job_id = client.post(f"/api/clips/{c.id}/render", json={}, headers=h).json()["job_id"]
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=h).status_code == 200
    assert client.get(f"/api/clips/{c.id}").json()["render_state"] == "none"


def test_render_urls_and_still(client, tmp_path, monkeypatch, sample):
    h, db, p = _project(client, tmp_path, monkeypatch)
    folder = storage.project_dir(p.user_id, p.id) / "clip_1"
    folder.mkdir(parents=True)
    shutil.copy(sample, folder / "draft.mp4")
    c = _clip(db, p, 0.0, 4.0, draft_path=storage.rel(folder / "draft.mp4"), render_state=RenderState.DRAFT)
    urls = client.get(f"/api/clips/{c.id}/render-urls").json()
    assert urls["draft"]["url"].startswith("/api/media/") and urls["final"] is None and urls["thumbnail"] is None
    assert client.get(urls["draft"]["url"]).status_code == 200
    r = client.get(f"/api/clips/{c.id}/still", params={"t": 1.5})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/clips/{c.id}/still", params={"t": 99}).status_code == 422
    assert client.get(f"/api/clips/{c.id}/still", params={"t": -1}).status_code == 422
    assert client.get(f"/api/clips/{c.id}/still", params={"t": 1, "quality": "final"}).status_code == 409


def test_render_endpoints_are_isolated_between_users(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    p.video_path = "u1/p1/source.mp4"
    db.commit()
    c = _clip(db, p)
    client.post(f"/api/clips/{c.id}/render", json={}, headers=h)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    for call in (other.post(f"/api/clips/{c.id}/render", json={}, headers=hb), other.post(f"/api/clips/{c.id}/render/cancel", headers=hb),
                 other.get(f"/api/clips/{c.id}/render-urls"), other.get(f"/api/clips/{c.id}/still", params={"t": 1})):
        assert call.status_code == 404
    assert other.get("/api/jobs").json() == []
