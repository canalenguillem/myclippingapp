import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Clip, Job, Project, ProjectStatus, User
from app.jobs import handlers, queue
from app.jobs.handlers import Cancelled, JobContext
from app.services import clip_detector, clips as clips_service, silences, storage, transcription
from app.services.clip_detector import ClipCandidate

PW = "una-clave-larga-1"
WORDS = {"version": 2, "revision": 1, "language": "es", "text": "x", "segments": [],
         "words": [{"text": "x", "start": 0.0, "end": 1.0, "confidence": 1, "speaker": "A"}]}


def cand(start, end, score=80, title="t"):
    return ClipCandidate(start=start, end=end, title=title, reason="r", score=score, transcript="txt",
                         hook="gancho", emphasis=[{"start": start + 1.0, "text": "clave"}], parts=["a", "b"])


def _setup(client, tmp_path, monkeypatch, sil=None, status=ProjectStatus.DETECTING):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    assert client.post("/api/auth/register", json={"email": "a@x.com", "password": PW}).status_code == 201
    db = client.session_factory()
    user = db.query(User).one()
    p = Project(user_id=user.id, source_url="https://youtu.be/x", title="T", duration=120.0, status=status)
    db.add(p)
    db.commit()
    folder = storage.project_dir(user.id, p.id)
    transcription.save_words(WORDS, folder / "words.json")
    p.words_path = storage.rel(folder / "words.json")
    if sil is not None:
        silences.save_silences(sil, folder / "silences.json")
        p.silences_path = storage.rel(folder / "silences.json")
    db.commit()
    job = queue.enqueue(db, user.id, "detect", {"project_id": p.id})
    claimed = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=claimed.id, user_id=user.id, log_file=tmp_path / "logs" / "j.log")
    return db, ctx, p, claimed.payload


def test_detect_saves_clips_snapped_to_silences_and_marks_project_ready(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch, sil=[{"start": 9.5, "end": 10.0}, {"start": 40.05, "end": 41.0}])
    monkeypatch.setattr(clip_detector, "detect_clips", lambda data, **kw: [cand(10.0, 40.0)])
    handlers.detect(ctx, payload)
    [c] = db.query(Clip).all()
    assert c.start == pytest.approx(9.8) and c.end == pytest.approx(40.25)
    assert isinstance(c.start, float) and isinstance(c.end, float)
    assert (c.hook, c.parts, c.score, c.user_id, c.status) == ("gancho", ["a", "b"], 80, p.user_id, "detected")
    assert c.emphasis_json == [{"start": 11.0, "text": "clave"}]
    assert db.get(Project, p.id).status is ProjectStatus.READY


def test_detect_works_without_silences_file_and_passes_params(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch)
    payload = {**payload, "parts": 3, "clips_per_part": 2, "target_dur": 25}
    seen = {}
    monkeypatch.setattr(clip_detector, "detect_clips", lambda data, **kw: seen.update(kw) or [cand(10.0, 40.0)])
    handlers.detect(ctx, payload)
    assert (seen["parts"], seen["clips_per_part"], seen["target_dur"]) == (3, 2, 25)
    c = db.query(Clip).one()
    assert (c.start, c.end) == (10.0, 40.0)


def test_end_is_clamped_to_project_duration(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch, sil=[{"start": 119.9, "end": 125.0}])
    monkeypatch.setattr(clip_detector, "detect_clips", lambda data, **kw: [cand(90.0, 119.8)])
    handlers.detect(ctx, payload)
    assert db.query(Clip).one().end <= 120.0


def test_redetect_replaces_only_unworked_clips_and_skips_overlaps(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch, status=ProjectStatus.READY)
    uid = p.user_id
    db.add_all([Clip(project_id=p.id, user_id=uid, start=0.0, end=30.0, title="aprobado", status="approved"),
                Clip(project_id=p.id, user_id=uid, start=60.0, end=90.0, title="viejo", status="detected")])
    db.commit()
    monkeypatch.setattr(clip_detector, "detect_clips", lambda data, **kw: [cand(5.0, 33.0, title="pisa"), cand(40.0, 70.0, title="nuevo")])
    handlers.detect(ctx, payload)
    assert sorted(c.title for c in db.query(Clip).all()) == ["aprobado", "nuevo"]


def test_detect_failure_on_new_project_marks_failed_but_on_ready_project_keeps_ready(client, tmp_path, monkeypatch):
    def boom(data, **kw):
        raise clip_detector.DetectionError("sin saldo")

    monkeypatch.setattr(clip_detector, "detect_clips", boom)
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch)
    with pytest.raises(clip_detector.DetectionError):
        handlers.detect(ctx, payload)
    db.refresh(p)
    assert p.status is ProjectStatus.FAILED and "sin saldo" in p.error

    p.status = ProjectStatus.READY
    db.commit()
    with pytest.raises(clip_detector.DetectionError):
        handlers.detect(ctx, payload)
    db.refresh(p)
    assert p.status is ProjectStatus.READY and "sin saldo" in p.error


def test_detect_can_be_cancelled_between_parts(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch)

    def detect_with_progress(data, **kw):
        kw["progress"](0.0)
        return []

    monkeypatch.setattr(clip_detector, "detect_clips", detect_with_progress)
    queue.cancel(db, db.get(Job, ctx.job_id))
    with pytest.raises(Cancelled):
        handlers.detect(ctx, payload)


def test_detect_cannot_touch_another_users_project(client, tmp_path, monkeypatch):
    db, ctx, p, payload = _setup(client, tmp_path, monkeypatch)
    other = User(email="o@x.com", password_hash="x")
    db.add(other)
    db.commit()
    ctx.user_id = other.id
    with pytest.raises(RuntimeError, match="no encontrado"):
        handlers.detect(ctx, payload)


def test_ingest_enqueues_detect_when_done(client, tmp_path, monkeypatch):
    from app.services import video_download
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    assert client.post("/api/auth/register", json={"email": "a@x.com", "password": PW}).status_code == 201
    h = {"X-CSRF-Token": client.cookies.get("csrf")}
    pid = client.post("/api/projects", json={"source_url": "https://youtu.be/abc"}, headers=h).json()["id"]
    db = client.session_factory()
    job = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=job.id, user_id=job.user_id, log_file=tmp_path / "logs" / "j.log")

    def fake_download(url, out_dir, log, on_progress):
        f = out_dir / "source.mp4"
        f.write_bytes(b"v")
        return f

    monkeypatch.setattr(video_download, "probe", lambda url, log: {"title": "T", "duration": 60})
    monkeypatch.setattr(video_download, "download", fake_download)
    monkeypatch.setattr(video_download, "extract_audio", lambda v, a: (a.write_bytes(b"m"), a)[1])
    monkeypatch.setattr(silences, "detect_silences", lambda audio: [])
    monkeypatch.setattr(transcription, "transcribe_words", lambda audio, lang, n=None: WORDS)
    handlers.ingest(ctx, job.payload)
    detect_jobs = db.query(Job).filter(Job.type == "detect").all()
    assert len(detect_jobs) == 1 and detect_jobs[0].payload == {"project_id": pid}
    assert detect_jobs[0].user_id == job.user_id
    assert db.get(Project, pid).status is ProjectStatus.DETECTING  # sigue detectando hasta que corra `detect`
