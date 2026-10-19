import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Clip, Job, Project, ProjectStatus, RenderState, User, YouTubeChannel
from app.jobs import queue
from app.jobs import upload as upload_job
from app.jobs.context import Cancelled, JobContext
from app.services import crypto, seo, storage
from app.services.youtube_upload import UploadError, UploadResult, map_http_error
from tests.test_clips_api import _login

SECRET = {"client_id": "1-a.apps.googleusercontent.com", "client_secret": "GOCSPX-x", "project_id": "p", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
          "token_uri": "https://oauth2.googleapis.com/token"}
TOKEN = {"access_token": "old", "refresh_token": "r", "scope": "s", "expires_at": int(time.time()) + 3600}


# --- textos SEO -------------------------------------------------------------------------------------

def test_clean_title_description_and_tags_follow_youtube_limits():
    assert seo.clean_title("  Hola    mundo  ") == "Hola mundo"
    assert "<" not in seo.clean_title("a <b> c") and ">" not in seo.clean_title("a <b> c")
    long = " ".join(["palabra"] * 40)
    t = seo.clean_title(long)
    assert len(t) <= 100 and not t.endswith(" ") and t.split(" ")[-1] == "palabra"
    d = seo.clean_description("Línea uno <script>")
    assert d.endswith("#Shorts") and "<" not in d and ">" not in d
    assert seo.clean_description("Ya lleva #shorts aquí").count("#") == 1                     # no se duplica (sin mirar mayúsculas)
    assert seo.clean_description("") == "#Shorts" and len(seo.clean_description("x" * 9000)) <= seo.DESCRIPTION_MAX + 10
    tags = seo.clean_tags(["PSOE", "psoe", " política  española ", "#Shorts", "a,b", "", "x" * 50, "<b>", 5])
    assert tags[:3] == ["PSOE", "política española", "Shorts"] and "x" * 30 in tags and all(len(t) <= 30 for t in tags)
    many = seo.clean_tags([f"etiqueta{i}" for i in range(50)])
    assert len(many) <= seo.TAGS_MAX and sum(len(t) + 1 for t in many) <= seo.TAGS_TOTAL_CHARS
    assert seo.clean_tags("no es una lista") == []


def test_generate_uses_the_model_answer_cleaned_and_falls_back_without_it():
    seen = {}

    def llm(system, user):
        seen["system"], seen["user"] = system, user
        return {"title": "Según él, <b>Sánchez</b> miente", "description": "Opina que…", "tags": ["política", "PSOE"]}

    out = seo.generate(title="T", hook="H", reason="R", transcript="texto largo", emphasis=["hostia"], channel_name="Spain Facts", language="es",
                       seo_rules="Sin insultos", llm=llm)
    assert out.source == "model" and "<" not in out.title and out.title.startswith("Según él,")
    assert out.description.endswith("#Shorts") and out.tags == ["política", "PSOE"]
    assert "Sin insultos" in seen["user"] and "Spain Facts" in seen["user"] and "texto largo" in seen["user"] and "opinión" in seen["system"]
    for bad in (None, {}, {"title": "  "}):
        b = seo.generate(title="T", hook="Gancho del clip", reason="Motivo", transcript="t", emphasis=["uno", "dos"], channel_name="c", language="es", seo_rules="",
                         llm=lambda s, u, bad=bad: bad)
        assert b.source == "plan_b" and b.title == "Gancho del clip" and b.description.startswith("Motivo") and b.tags[:3] == ["shorts", "uno", "dos"]
    assert seo.generate(title="T", hook="", reason="", transcript="", emphasis=[], channel_name="c", language="es", seo_rules="", llm=None).title == "T"


def test_default_llm_needs_a_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    assert seo.default_llm("s", "u") is None


def test_http_errors_are_explained():
    body = lambda reason: json.dumps({"error": {"errors": [{"reason": reason}], "message": "m"}})  # noqa: E731
    assert "cuota diaria" in map_http_error(403, body("quotaExceeded"))
    assert "límite de subidas" in map_http_error(400, body("uploadLimitExceeded"))
    assert "no tiene un canal" in map_http_error(401, body("youtubeSignupRequired"))
    assert "caducó" in map_http_error(401, b"{}")
    assert map_http_error(500, "no json") == "YouTube respondió 500"
    assert map_http_error(418, json.dumps({"error": {"message": "soy una tetera"}})).endswith("soy una tetera")


# --- datos de prueba ----------------------------------------------------------------------------------

def world(client, tmp_path, monkeypatch, *, linked=True, state="approved", final=True, seo_saved=True):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    h = _login(client)
    db = client.session_factory()
    user = db.query(User).one()
    project = Project(user_id=user.id, source_url="u", title="T", duration=100.0, status=ProjectStatus.READY)
    db.add(project)
    db.commit()
    video = storage.project_dir(user.id, project.id) / "clip_1" / "final.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mp4")
    clip = Clip(project_id=project.id, user_id=user.id, start=1.0, end=40.0, title="Título", hook="Gancho", status=state, transcript="hola",
                rendered_path=storage.rel(video) if final else None, render_state=RenderState.FINAL if final else RenderState.NONE)
    ch = YouTubeChannel(user_id=user.id, name="Spain Facts", language="es", yt_title="Spain facts", client_secret_enc=crypto.encrypt_json(SECRET),
                        token_enc=crypto.encrypt_json(TOKEN) if linked else None)
    db.add_all([clip, ch])
    db.commit()
    if seo_saved:
        clip.channel_id, clip.seo_title, clip.seo_description, clip.seo_tags = ch.id, "Un título", "Una descripción #Shorts", "politica,psoe"
        db.commit()
    return h, db, clip, ch, user, video


SEO_BODY = lambda ch, **k: {"channel_id": ch.id, "title": "Un <título>", "description": "Texto", "tags": ["a", "A", "b"], **k}  # noqa: E731


# --- API ----------------------------------------------------------------------------------------------

def test_generate_returns_a_proposal_without_saving(client, tmp_path, monkeypatch):
    h, db, clip, ch, *_ = world(client, tmp_path, monkeypatch, seo_saved=False)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    r = client.post(f"/api/clips/{clip.id}/seo/generate", json={"channel_id": ch.id}, headers=h)
    assert r.status_code == 200 and r.json()["source"] == "plan_b" and r.json()["title"] == "Gancho" and r.json()["description"].endswith("#Shorts")
    db.refresh(clip)
    assert clip.seo_title == ""                                   # no guarda nada
    assert client.post(f"/api/clips/{clip.id}/seo/generate", json={"channel_id": 9999}, headers=h).status_code == 404


def test_save_seo_cleans_validates_and_exposes_the_fields(client, tmp_path, monkeypatch):
    h, db, clip, ch, *_ = world(client, tmp_path, monkeypatch, seo_saved=False)
    out = client.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch, privacy="unlisted"), headers=h).json()
    assert (out["seo_title"], out["seo_tags"], out["privacy"], out["channel_id"]) == ("Un título", ["a", "b"], "unlisted", ch.id) and out["seo_description"].endswith("#Shorts")
    soon, later = datetime.now(timezone.utc) + timedelta(seconds=30), datetime.now(timezone.utc) + timedelta(days=2)
    assert client.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch, publish_at=later.isoformat()), headers=h).json()["publish_at"] is not None
    assert client.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch, publish_at=soon.isoformat()), headers=h).status_code == 422       # tiene que ser futura
    assert client.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch, privacy="public", publish_at=later.isoformat()), headers=h).status_code == 422
    for bad in ({"title": ""}, {"title": "x" * 101}, {"tags": ["x"] * 16}, {"privacy": "secreto"}, {"extra": 1}, {"title": "<>"}):
        assert client.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch, **bad), headers=h).status_code == 422, bad


@pytest.mark.parametrize("kw,needle", [({"state": "detected"}, "aprobados"), ({"final": False}, "render final"), ({"seo_saved": False}, "Guarda antes"),
                                       ({"linked": False}, "no está conectado")])
def test_upload_preconditions(client, tmp_path, monkeypatch, kw, needle):
    h, db, clip, ch, *_ = world(client, tmp_path, monkeypatch, **kw)
    r = client.post(f"/api/clips/{clip.id}/upload", json={"channel_id": ch.id}, headers=h)
    assert r.status_code == 409 and needle in r.json()["detail"] and db.query(Job).count() == 0


def test_upload_enqueues_a_job_marks_the_clip_and_never_uploads_twice_or_to_another_channel(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch)
    other = YouTubeChannel(user_id=user.id, name="Otro", token_enc=crypto.encrypt_json(TOKEN), client_secret_enc=crypto.encrypt_json(SECRET))
    db.add(other)
    db.commit()
    assert client.post(f"/api/clips/{clip.id}/upload", json={"channel_id": other.id}, headers=h).status_code == 409   # no coincide con el guardado
    r = client.post(f"/api/clips/{clip.id}/upload", json={"channel_id": ch.id}, headers=h)
    assert r.status_code == 202
    job = db.query(Job).one()
    assert job.type == "upload" and job.payload == {"clip_id": clip.id, "project_id": clip.project_id} and job.id == r.json()["job_id"]
    db.refresh(clip)
    assert clip.status == "uploading" and client.get(f"/api/clips/{clip.id}").json()["upload_job_id"] == job.id
    assert "Ya se está subiendo" in client.post(f"/api/clips/{clip.id}/upload", json={"channel_id": ch.id}, headers=h).json()["detail"]
    assert client.patch(f"/api/clips/{clip.id}", json={"title": "x"}, headers=h).status_code == 409                   # no se edita mientras sube
    assert client.post(f"/api/jobs/{job.id}/cancel", headers=h).status_code == 200                                     # cancelar en cola lo deja aprobado
    db.refresh(clip)
    assert clip.status == "approved"


def test_an_uploaded_clip_cannot_be_uploaded_again(client, tmp_path, monkeypatch):
    h, db, clip, ch, *_ = world(client, tmp_path, monkeypatch)
    clip.youtube_video_id, clip.status = "abc123", "uploaded"
    db.commit()
    assert "ya está subido" in client.post(f"/api/clips/{clip.id}/upload", json={"channel_id": ch.id}, headers=h).json()["detail"]
    assert client.get(f"/api/clips/{clip.id}").json()["youtube_video_id"] == "abc123"


def test_upload_endpoints_are_isolated(client, tmp_path, monkeypatch):
    h, db, clip, ch, *_ = world(client, tmp_path, monkeypatch)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    for call in (other.post(f"/api/clips/{clip.id}/upload", json={"channel_id": ch.id}, headers=hb), other.put(f"/api/clips/{clip.id}/seo", json=SEO_BODY(ch), headers=hb),
                 other.post(f"/api/clips/{clip.id}/seo/generate", json={"channel_id": ch.id}, headers=hb)):
        assert call.status_code == 404


# --- job --------------------------------------------------------------------------------------------

class FakeUploader:
    def __init__(self, error=None, cancel=False):
        self.error, self.cancel, self.calls = error, cancel, []

    def upload(self, **kw):
        self.calls.append(kw)
        kw["on_progress"](0.5)
        if self.cancel:
            kw["cancel_check"]()
        if self.error:
            raise self.error
        kw["on_progress"](1.0)
        return UploadResult("VIDEO123", {**kw["token"], "access_token": "nuevo", "expires_at": 999})


def run(client, db, clip, user, monkeypatch, uploader):
    monkeypatch.setattr(upload_job, "make_uploader", lambda: uploader)
    job = queue.enqueue(db, user.id, "upload", {"clip_id": clip.id, "project_id": clip.project_id})
    claimed = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=claimed.id, user_id=user.id, log_file=get_settings().media_dir / "j.log")
    try:
        upload_job.upload(ctx, claimed.payload)
    finally:
        queue.finish(db, claimed.id)   # libera el cupo del usuario para el siguiente job
        db.refresh(clip)
    return ctx


def test_job_uploads_saves_the_video_id_and_the_refreshed_token(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch)
    clip.privacy, clip.publish_at = "unlisted", None
    db.commit()
    up = FakeUploader()
    ctx = run(client, db, clip, user, monkeypatch, up)
    assert (clip.status, clip.youtube_video_id, clip.upload_error) == ("uploaded", "VIDEO123", None) and clip.uploaded_at
    (call,) = up.calls
    assert call["video"] == video and call["title"] == "Un título" and call["tags"] == ["politica", "psoe"] and call["privacy"] == "unlisted"
    assert call["language"] == "es" and call["secret"].client_id == SECRET["client_id"] and call["token"]["refresh_token"] == "r"
    db.refresh(ch)
    assert crypto.decrypt_json(ch.token_enc)["access_token"] == "nuevo"
    assert "https://www.youtube.com/shorts/VIDEO123" in (get_settings().media_dir / "j.log").read_text()
    assert db.get(Job, ctx.job_id).progress >= 50


def test_job_passes_the_scheduled_time(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch)
    clip.publish_at = datetime.utcnow() + timedelta(days=1)
    db.commit()
    up = FakeUploader()
    run(client, db, clip, user, monkeypatch, up)
    assert up.calls[0]["publish_at"] == clip.publish_at


def test_job_failure_returns_the_clip_to_approved_with_the_message(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch, state="uploading")
    with pytest.raises(UploadError):
        run(client, db, clip, user, monkeypatch, FakeUploader(error=UploadError("Se agotó la cuota diaria")))
    assert (clip.status, clip.upload_error, clip.youtube_video_id) == ("approved", "Se agotó la cuota diaria", None)
    with pytest.raises(RuntimeError):
        run(client, db, clip, user, monkeypatch, FakeUploader(error=RuntimeError("boom")))
    assert clip.upload_error == "RuntimeError: boom" and clip.status == "approved"


def test_job_cancel_returns_the_clip_to_approved_without_an_error(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch, state="uploading")
    with pytest.raises(Cancelled):
        run(client, db, clip, user, monkeypatch, _Cancelling())
    assert (clip.status, clip.upload_error) == ("approved", None)


class _Cancelling(FakeUploader):
    def upload(self, **kw):
        raise Cancelled()


def test_job_never_uploads_twice(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch, state="uploading")
    clip.youtube_video_id = "YA_SUBIDO"
    db.commit()
    up = FakeUploader()
    run(client, db, clip, user, monkeypatch, up)
    assert up.calls == [] and clip.status == "uploaded" and clip.youtube_video_id == "YA_SUBIDO"


@pytest.mark.parametrize("mutate,needle", [("unlink", "no está conectado"), ("nofile", "No se encuentra el vídeo"), ("nochannel", "ya no existe")])
def test_job_checks_before_calling_google(client, tmp_path, monkeypatch, mutate, needle):
    h, db, clip, ch, user, video = world(client, tmp_path, monkeypatch, state="uploading")
    if mutate == "unlink":
        ch.token_enc = None
    elif mutate == "nofile":
        video.unlink()
    else:
        clip.channel_id = None
    db.commit()
    up = FakeUploader()
    with pytest.raises(upload_job.UploadJobError, match=needle):
        run(client, db, clip, user, monkeypatch, up)
    assert up.calls == [] and clip.status == "approved" and needle in clip.upload_error


def test_job_refuses_a_channel_of_another_user(client, tmp_path, monkeypatch):
    h, db, clip, ch, user, _ = world(client, tmp_path, monkeypatch, state="uploading")
    other = User(email="o@x.com", password_hash="x")
    db.add(other)
    db.commit()
    ch.user_id = other.id
    db.commit()
    with pytest.raises(upload_job.UploadJobError, match="ya no existe"):
        run(client, db, clip, user, monkeypatch, FakeUploader())
