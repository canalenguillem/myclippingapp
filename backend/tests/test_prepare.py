import pytest

from app.config import get_settings
from app.db.models import Clip, Job, RenderState, User, YouTubeChannel
from app.jobs.context import JobContext
from app.jobs.prepare import prepare as prepare_job
from app.pipeline import screens as screens_mod
from app.services import crypto
from tests.test_graphics_api import _clip, _words_project
from tests.test_youtube_upload import SECRET, TOKEN


def ctx_for(db, user, tmp_path):
    return JobContext(db=db, job_id=1, user_id=user.id, log_file=tmp_path / "prep.log")


def world(client, tmp_path, monkeypatch, *, linked=True):
    h, db, p, ws = _words_project(client, tmp_path, monkeypatch)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    user = db.query(User).one()
    ch = YouTubeChannel(user_id=user.id, name="Canal", language="es", yt_title="Canal", client_secret_enc=crypto.encrypt_json(SECRET),
                        token_enc=crypto.encrypt_json(TOKEN) if linked else None)
    db.add(ch)
    db.commit()
    p.video_path, p.channel = "u/source.mp4", None
    db.commit()
    clip = _clip(db, p, 0.0, 30.0)
    clip.channel_id, clip.layout, clip.status = ch.id, "full", "detected"
    db.commit()
    video = tmp_path / "source.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr("app.jobs.prepare.source_service.ensure_source", lambda project, log, on_progress=None: video)
    monkeypatch.setattr(screens_mod, "detect", lambda *a, **k: [{"start": 5.0, "end": 12.0, "x": 0.3, "y": 0.0, "w": 0.7, "h": 1.0}])
    return h, db, user, clip


def jobs_of(db, kind):
    return [j for j in db.query(Job).all() if j.type == kind]


def test_prepare_does_the_whole_process_and_marks_the_publication(client, tmp_path, monkeypatch):
    h, db, user, clip = world(client, tmp_path, monkeypatch)
    prepare_job(ctx_for(db, user, tmp_path), {"clip_id": clip.id, "privacy": "public"})
    db.refresh(clip)
    assert clip.intro_enabled is True and clip.cortinilla_at is None                      # cortinilla de inicio activada
    assert clip.screen_ranges == [{"start": 5.0, "end": 12.0, "x": 0.3, "y": 0.0, "w": 0.7, "h": 1.0}]
    assert len(clip.graphics_json) > 0 and all("reason" not in g for g in clip.graphics_json)    # gráficos sugeridos y guardados
    assert clip.status == "approved" and clip.auto_publish == "public" and clip.render_state is RenderState.RENDERING
    renders = jobs_of(db, "render")
    assert len(renders) == 1 and renders[0].payload == {"clip_id": clip.id, "project_id": clip.project_id, "quality": "final"}


def test_prepare_without_privacy_only_prepares_and_keeps_the_users_graphics(client, tmp_path, monkeypatch):
    h, db, user, clip = world(client, tmp_path, monkeypatch)
    mine = [{"type": "keyword", "at": 8.0, "text": "MIO"}]
    clip.graphics_json = mine
    db.commit()
    prepare_job(ctx_for(db, user, tmp_path), {"clip_id": clip.id, "privacy": None})
    db.refresh(clip)
    assert clip.auto_publish is None and clip.graphics_json == mine and clip.status == "approved" and len(jobs_of(db, "render")) == 1


def test_prepare_survives_a_failing_screen_detection_and_clears_an_old_render(client, tmp_path, monkeypatch):
    h, db, user, clip = world(client, tmp_path, monkeypatch)

    def boom(*a, **k):
        raise screens_mod.ScreenError("ffmpeg falló")

    monkeypatch.setattr(screens_mod, "detect", boom)
    clip.draft_path, clip.render_state = "u/old.mp4", RenderState.DRAFT
    db.commit()
    prepare_job(ctx_for(db, user, tmp_path), {"clip_id": clip.id, "privacy": "unlisted"})
    db.refresh(clip)
    assert clip.screen_ranges in (None, []) and clip.draft_path is None and clip.auto_publish == "unlisted" and clip.render_state is RenderState.RENDERING


def test_prepare_endpoint_rules(client, tmp_path, monkeypatch):
    h, db, user, clip = world(client, tmp_path, monkeypatch)
    url = f"/api/clips/{clip.id}/prepare"
    ok = client.post(url, json={"privacy": "public"}, headers=h)
    assert ok.status_code == 202 and ok.json()["job_id"] == jobs_of(db, "prepare")[0].id
    assert client.post(url, json={"privacy": "public"}, headers=h).status_code == 409                  # ya se está preparando
    assert client.post(url, json={"privacy": "secreto"}, headers=h).status_code == 422
    assert client.get(f"/api/projects/{clip.project_id}/clips", headers=h).json()[0]["prepare_job_id"] == jobs_of(db, "prepare")[0].id
    db.execute(Job.__table__.update().values(status="completed"))
    db.commit()
    ch = db.query(YouTubeChannel).one()
    ch.token_enc = None
    db.commit()
    assert client.post(url, json={"privacy": "public"}, headers=h).status_code == 409                  # publicar exige canal conectado
    assert client.post(url, json={"privacy": None}, headers=h).status_code == 202                      # solo preparar no
    db.execute(Job.__table__.update().values(status="completed"))
    clip.status = "uploaded"
    db.commit()
    assert client.post(url, json={"privacy": None}, headers=h).status_code == 409


def test_auto_detection_of_screens_after_detecting_clips_keeps_every_clips_result(client, tmp_path, monkeypatch):
    """`check_cancelled` descarta lo no guardado: la detección debe guardar clip a clip (antes solo sobrevivía el último)."""
    from app.db.models import Project
    from app.jobs.handlers import _detect_screens
    h, db, user, clip = world(client, tmp_path, monkeypatch)
    project = db.get(Project, clip.project_id)
    second = _clip(db, project, 31.0, 60.0)
    third = _clip(db, project, 61.0, 90.0)
    calls = []

    def fake_detect(video, start, end):
        calls.append(start)
        return [{"start": start + 1.0, "end": start + 4.0, "x": 0.3, "y": 0.0, "w": 0.7, "h": 1.0}]

    monkeypatch.setattr(screens_mod, "detect", fake_detect)
    monkeypatch.setattr("app.services.source.available", lambda p: True)
    clip.screen_ranges = []
    db.commit()
    _detect_screens(ctx_for(db, user, tmp_path), project)
    for c in (clip, second, third):
        db.refresh(c)
    assert [len(c.screen_ranges or []) for c in (clip, second, third)] == [1, 1, 1] and len(calls) == 3
