import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Job, Project, User
from app.jobs import handlers, queue
from app.jobs.handlers import Cancelled, JobContext
from app.services import video_download

PW = "una-clave-larga-1"


@pytest.mark.parametrize("url,ok", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("http://m.youtube.com/watch?v=abc", True),
    ("https://evil.com/watch?v=abc", False),
    ("https://youtube.com.evil.com/x", False),
    ("http://169.254.169.254/latest/meta-data", False),
    ("file:///etc/passwd", False),
    ("javascript:alert(1)", False),
    ("", False),
])
def test_youtube_url_allowlist(url, ok):
    assert video_download.is_youtube_url(url) is ok


def _login(client, email="a@x.com"):
    assert client.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    return {"X-CSRF-Token": client.cookies.get("csrf")}


def test_create_project_rejects_non_youtube_and_enqueues_ingest(client):
    h = _login(client)
    assert client.post("/api/projects", json={"source_url": "http://localhost:8000/x"}, headers=h).status_code == 400
    r = client.post("/api/projects", json={"source_url": "https://youtu.be/abc", "language": "es"}, headers=h)
    assert r.status_code == 201
    db = client.session_factory()
    job = db.get(Job, r.json()["job_id"])
    assert job.type == "ingest" and job.payload == {"project_id": r.json()["id"], "language": "es"}
    assert client.post("/api/projects", json={"source_url": "https://youtu.be/a", "language": "xx-yy"}, headers=h).status_code == 422


def test_projects_isolated_between_users(client):
    ha = _login(client)
    b = TestClient(client.app)
    hb = _login(b, "b@x.com")
    pid = client.post("/api/projects", json={"source_url": "https://youtu.be/abc"}, headers=ha).json()["id"]
    assert b.get("/api/projects").json() == []
    assert b.get(f"/api/projects/{pid}").status_code == 404
    assert b.get(f"/api/projects/{pid}/transcript").status_code == 404
    assert b.delete(f"/api/projects/{pid}", headers=hb).status_code == 404


def _setup_ingest(client, tmp_path, monkeypatch, duration=60):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    h = _login(client)
    pid = client.post("/api/projects", json={"source_url": "https://youtu.be/abc"}, headers=h).json()["id"]
    db = client.session_factory()
    job = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=job.id, user_id=job.user_id, log_file=tmp_path / "logs" / "j.log")

    def fake_download(url, out_dir, log, on_progress):
        on_progress(0.5)
        f = out_dir / "source.mp4"
        f.write_bytes(b"video")
        return f

    monkeypatch.setattr(video_download, "probe", lambda url, log: {"title": "Charla", "duration": duration})
    monkeypatch.setattr(video_download, "download", fake_download)
    monkeypatch.setattr(video_download, "extract_audio", lambda v, a: (a.write_bytes(b"mp3"), a)[1])
    return db, ctx, job, pid


def test_ingest_happy_path(client, tmp_path, monkeypatch):
    from app.services import transcription
    db, ctx, job, pid = _setup_ingest(client, tmp_path, monkeypatch)
    monkeypatch.setattr(transcription, "transcribe_words", lambda audio, lang: {
        "language": "es", "text": "hola mundo", "words": [{"text": "hola", "start": 0.1, "end": 0.4, "confidence": 0.9}]})
    handlers.ingest(ctx, job.payload)
    p = db.get(Project, pid)
    assert (p.status, p.title, p.duration) == ("transcribed", "Charla", 60)
    assert (tmp_path / p.video_path).exists()
    assert json.loads((tmp_path / p.words_path).read_text())["words"][0]["text"] == "hola"
    assert client.get(f"/api/projects/{pid}/transcript").json()["language"] == "es"


def test_ingest_rejects_video_over_user_limit(client, tmp_path, monkeypatch):
    db, ctx, job, pid = _setup_ingest(client, tmp_path, monkeypatch, duration=181 * 60)
    with pytest.raises(video_download.DownloadError, match="límite"):
        handlers.ingest(ctx, job.payload)
    p = db.get(Project, pid)
    assert p.status == "failed" and "180" in p.error


def test_ingest_cancel_marks_project_failed(client, tmp_path, monkeypatch):
    db, ctx, job, pid = _setup_ingest(client, tmp_path, monkeypatch)
    queue.cancel(db, db.get(Job, job.id))
    with pytest.raises(Cancelled):
        handlers.ingest(ctx, job.payload)
    assert db.get(Project, pid).status == "failed"


def test_ingest_cannot_touch_other_users_project(client, tmp_path, monkeypatch):
    db, ctx, job, pid = _setup_ingest(client, tmp_path, monkeypatch)
    other = User(email="o@x.com", password_hash="x")
    db.add(other)
    db.commit()
    ctx.user_id = other.id
    with pytest.raises(RuntimeError, match="no encontrado"):
        handlers.ingest(ctx, job.payload)


def test_storage_blocks_path_traversal(tmp_path, monkeypatch):
    from app.services import storage
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    with pytest.raises(ValueError):
        storage.absolute("../etc/passwd")
    assert storage.absolute("u1/p1/words.json").parent.name == "p1"
