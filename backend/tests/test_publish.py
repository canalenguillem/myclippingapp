import json

import pytest

from app.config import get_settings
from app.db.models import Job, RenderState
from app.jobs.context import JobContext
from app.jobs.handlers import publish as publish_job
from app.services import publish as publish_service
from app.services import seo as seo_service
from app.services import storage
from tests.test_youtube_upload import world


def fake_generate(**kw):
    return seo_service.Seo("Un título de prueba", "Descripción generada", ["politica", "psoe"], source="plan_b")


def ctx_for(db, user, tmp_path):
    return JobContext(db=db, job_id=1, user_id=user.id, log_file=tmp_path / "pub.log")


def jobs_of(db, kind):
    return [j for j in db.query(Job).all() if j.type == kind]


def test_publish_now_generates_the_seo_with_source_header_and_queues_the_upload(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, seo_saved=False)
    clip.channel_id, clip.auto_publish = ch.id, "public"
    from app.db.models import Project
    project = db.get(Project, clip.project_id)
    project.source_url, project.source_handle = "https://www.youtube.com/watch?v=abcdefghijk", "@esRadio"
    db.commit()
    logs = []
    job_id = publish_service.publish_now(db, clip, logs.append, generate=fake_generate)
    db.refresh(clip)
    assert clip.status == "uploading" and clip.privacy == "public" and clip.publish_at is None
    assert clip.seo_title == "Un título de prueba" and clip.seo_description.startswith("@esRadio\nVídeo original: https://www.youtube.com/watch?v=abcdefghijk&t=1s")
    assert clip.seo_description.endswith("#Shorts") and clip.seo_tags == "politica,psoe"
    up = db.get(Job, job_id)
    assert up.type == "upload" and up.payload == {"clip_id": clip.id, "project_id": clip.project_id, "source": "final"}


def test_publish_now_keeps_seo_the_user_already_saved(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, seo_saved=True)
    clip.auto_publish = "unlisted"
    db.commit()
    publish_service.publish_now(db, clip, lambda m: None, generate=lambda **k: pytest.fail("no debe regenerar"))
    db.refresh(clip)
    assert clip.seo_title == "Un título" and clip.privacy == "unlisted"


@pytest.mark.parametrize("mutate,needle", [
    ("off", "no tiene activada"), ("unapproved", "solo se publican clips aprobados"), ("norender", "render final vigente"),
    ("nochannel", "no tiene canal"), ("unlinked", "no está conectado"), ("uploaded", "ya está subido"),
])
def test_publish_now_blocks_unsafe_cases(client, tmp_path, monkeypatch, mutate, needle):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    clip.auto_publish = "public"
    if mutate == "off":
        clip.auto_publish = None
    elif mutate == "unapproved":
        clip.status = "detected"
    elif mutate == "norender":
        video.unlink()
    elif mutate == "nochannel":
        clip.channel_id = None
    elif mutate == "unlinked":
        ch.token_enc = None
    else:
        clip.status = "uploaded"
    db.commit()
    with pytest.raises(publish_service.PublishBlocked, match=needle):
        publish_service.publish_now(db, clip, lambda m: None, generate=fake_generate)
    assert jobs_of(db, "upload") == []


def test_a_failed_automatic_review_blocks_publishing_and_says_why(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    clip.auto_publish = "public"
    db.commit()
    (video.parent / "qa_final.json").write_text(json.dumps({"checks": [{"id": "audio", "level": "error", "message": "El vídeo no tiene audio"},
                                                                        {"id": "black", "level": "ok", "message": "bien"}]}))
    publish_job(ctx_for(db, user, tmp_path), {"clip_id": clip.id})
    db.refresh(clip)
    assert clip.auto_publish is None and clip.status == "approved" and "no tiene audio" in clip.upload_error and jobs_of(db, "upload") == []


def test_auto_publish_endpoint_rules(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    url = f"/api/clips/{clip.id}/auto-publish"
    r = client.put(url, json={"privacy": "public"}, headers=h)
    assert r.status_code == 200 and r.json()["auto_publish"] == "public"
    assert [j.payload["clip_id"] for j in jobs_of(db, "publish")] == [clip.id]                    # el final ya existe: se publica ya
    assert client.put(url, json={"privacy": "secreto"}, headers=h).status_code == 422
    assert client.put(url, json={"privacy": None}, headers=h).json()["auto_publish"] is None
    ch.token_enc = None
    db.commit()
    assert client.put(url, json={"privacy": "public"}, headers=h).status_code == 409
    clip.status = "detected"
    db.commit()
    assert client.put(url, json={"privacy": "public"}, headers=h).status_code == 409


def test_auto_publish_without_a_final_render_queues_it_and_unapproving_clears_the_flag(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, final=False)
    from app.db.models import Project
    p = db.get(Project, clip.project_id)
    p.video_path, p.words_path = "x/source.mp4", "x/words.json"
    clip.channel_id = ch.id
    db.commit()
    r = client.put(f"/api/clips/{clip.id}/auto-publish", json={"privacy": "unlisted"}, headers=h)
    assert r.status_code == 200 and r.json()["render_state"] == "rendering"
    renders = jobs_of(db, "render")
    assert len(renders) == 1 and renders[0].payload["quality"] == "final" and jobs_of(db, "publish") == []
    db.execute(Job.__table__.update().values(status="completed"))
    clip.render_state = RenderState.NONE
    db.commit()
    assert client.post(f"/api/clips/{clip.id}/unapprove", headers=h).json()["auto_publish"] is None


def test_a_degraded_render_with_plan_b_subtitles_is_never_published(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    clip.auto_publish = "public"
    clip.render_error = "Aviso: CaptureStageError: Navigation timeout; se usaron subtítulos simples, sin cortinillas"
    db.commit()
    publish_job(ctx_for(db, user, tmp_path), {"clip_id": clip.id})
    db.refresh(clip)
    assert clip.auto_publish is None and clip.status == "approved" and "plan B de subtítulos" in clip.upload_error and jobs_of(db, "upload") == []


def test_marking_a_clip_while_an_upload_is_running_still_queues_its_render_but_an_ingest_blocks(client, tmp_path, monkeypatch):
    from app.db.models import Project
    from app.jobs import queue
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, final=False)
    p = db.get(Project, clip.project_id)
    p.video_path, p.words_path = "x/source.mp4", "x/words.json"
    clip.channel_id = ch.id
    db.commit()
    queue.enqueue(db, user.id, "upload", {"clip_id": 999, "project_id": p.id, "source": "final"})            # otra subida del proyecto en marcha
    r = client.put(f"/api/clips/{clip.id}/auto-publish", json={"privacy": "public"}, headers=h)
    assert r.status_code == 200 and r.json()["render_state"] == "rendering"
    assert [j.payload["clip_id"] for j in jobs_of(db, "render")] == [clip.id]                                  # antes se quedaba sin render, sin avisar
    db.execute(Job.__table__.update().values(status="completed"))
    db.refresh(clip)                                                       # el endpoint la dejó en «rendering» desde otra sesión
    clip.render_state = RenderState.NONE
    db.commit()
    queue.enqueue(db, user.id, "ingest", {"project_id": p.id})
    assert client.put(f"/api/clips/{clip.id}/auto-publish", json={"privacy": "public"}, headers=h).status_code == 409   # y ahora el motivo se dice


def test_reconcile_gives_a_final_render_to_flagged_clips_left_without_one(client, tmp_path, monkeypatch):
    from app.db.models import Project
    from app.jobs import queue
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, final=False)
    p = db.get(Project, clip.project_id)
    p.video_path, p.words_path = "x/source.mp4", "x/words.json"
    clip.auto_publish = "public"
    db.commit()
    assert publish_service.reconcile(db) == 1
    db.refresh(clip)
    assert clip.render_state is RenderState.RENDERING and [j.payload["quality"] for j in jobs_of(db, "render")] == ["final"]
    assert publish_service.reconcile(db) == 0                                                                  # ya tiene su render pendiente: no se duplica
    clip.render_state = RenderState.NONE
    clip.auto_publish = None
    db.commit()
    assert publish_service.reconcile(db) == 0                                                                  # sin marca, nada


def test_editing_a_flagged_clip_turns_the_automatic_publication_off(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    clip.auto_publish = "public"
    db.commit()
    assert client.patch(f"/api/clips/{clip.id}", json={"hook": "Otro gancho"}, headers=h).json()["auto_publish"] is None
