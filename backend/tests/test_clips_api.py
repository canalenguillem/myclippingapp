import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Clip, Job, Project, ProjectStatus, User
from app.services import storage, transcription

PW = "una-clave-larga-1"
WORDS = [{"text": f"p{i}", "start": float(i), "end": i + 0.5, "confidence": 1, "speaker": "A"} for i in range(100)]


def _login(c, email="a@x.com"):
    assert c.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    return {"X-CSRF-Token": c.cookies.get("csrf")}


def _project(client, tmp_path, monkeypatch, email="a@x.com", words=True):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    h = _login(client, email)
    db = client.session_factory()
    user = db.query(User).filter(User.email == email).one()
    p = Project(user_id=user.id, source_url="https://youtu.be/x", title="T", duration=100.0, status=ProjectStatus.READY)
    db.add(p)
    db.commit()
    if words:
        folder = storage.project_dir(user.id, p.id)
        transcription.save_words({"words": WORDS}, folder / "words.json")
        p.words_path = storage.rel(folder / "words.json")
        db.commit()
    return h, db, p


def _clip(db, p, start=10.0, end=40.0, status="detected", **kw):
    c = Clip(project_id=p.id, user_id=p.user_id, start=start, end=end, title="t", status=status, **kw)
    db.add(c)
    db.commit()
    return c


def test_list_is_chronological_and_floats(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    _clip(db, p, 50.0, 80.0)
    _clip(db, p, 10.0, 40.0, hook="gancho", emphasis_json=[{"start": 12.0, "text": "x"}], parts=["a"])
    out = client.get(f"/api/projects/{p.id}/clips").json()
    assert [c["start"] for c in out] == [10.0, 50.0]
    assert out[0]["duration"] == 30.0 and out[0]["hook"] == "gancho" and out[0]["emphasis"] == [{"start": 12.0, "text": "x"}]
    assert out[0]["parts"] == ["a"] and out[0]["layout"] == "split" and out[0]["status"] == "detected"


def test_cortinilla_de_inicio_is_off_by_default(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    _clip(db, p)
    assert client.get(f"/api/projects/{p.id}/clips").json()[0]["intro_enabled"] is False


def test_clips_isolated_between_users(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.get(f"/api/projects/{p.id}/clips").status_code == 404
    for call in (other.get(f"/api/clips/{c.id}"), other.patch(f"/api/clips/{c.id}", json={"title": "x"}, headers=hb),
                 other.post(f"/api/clips/{c.id}/approve", headers=hb), other.delete(f"/api/clips/{c.id}", headers=hb),
                 other.post(f"/api/projects/{p.id}/detect", json={}, headers=hb)):
        assert call.status_code == 404
    assert client.get(f"/api/clips/{c.id}").status_code == 200


def test_patch_updates_fields_and_refreshes_transcript(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p)
    r = client.patch(f"/api/clips/{c.id}", json={"start": 20.0, "end": 26.0, "title": "Nuevo", "layout": "full",
                                                  "focus": "left", "zoom": 1.5, "top_ratio": 0.6, "intro_enabled": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["start"], body["end"], body["duration"], body["layout"], body["intro_enabled"]) == (20.0, 26.0, 6.0, "full", True)
    assert body["transcript"] == "p20 p21 p22 p23 p24 p25"
    assert client.patch(f"/api/clips/{c.id}", json={"hook": "solo gancho"}, headers=h).json()["start"] == 20.0  # parcial


@pytest.mark.parametrize("body", [
    {"start": 30.0, "end": 20.0},        # fin antes que inicio
    {"start": 10.0, "end": 12.0},        # < 5 s
    {"start": 0.0, "end": 200.0},        # > 180 s y fuera del vídeo
    {"end": 100.5},                      # fuera de la duración del vídeo
    {"start": -1.0},
    {"zoom": 9.0}, {"top_ratio": 0.1}, {"layout": "diagonal"}, {"focus": "arriba"},
    {"status": "uploaded"}, {"user_id": 99}, {"score": 100},   # mass assignment
])
def test_patch_rejects_invalid_values(client, tmp_path, monkeypatch, body):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p)
    assert client.patch(f"/api/clips/{c.id}", json=body, headers=h).status_code == 422
    db.refresh(c)
    assert (c.start, c.end, c.status) == (10.0, 40.0, "detected")


def test_patch_only_while_detected_or_approved_and_requires_csrf(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    rendered = _clip(db, p, status="rendered")
    assert client.patch(f"/api/clips/{rendered.id}", json={"title": "x"}, headers=h).status_code == 409
    ok = _clip(db, p, 50.0, 80.0)
    assert client.patch(f"/api/clips/{ok.id}", json={"title": "x"}).status_code == 403  # sin CSRF


def test_approve_unapprove_transitions(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p)
    assert client.post(f"/api/clips/{c.id}/unapprove", headers=h).status_code == 409
    assert client.post(f"/api/clips/{c.id}/approve", headers=h).json()["status"] == "approved"
    assert client.post(f"/api/clips/{c.id}/approve", headers=h).status_code == 409
    assert client.patch(f"/api/clips/{c.id}", json={"title": "editable aprobado"}, headers=h).status_code == 200
    assert client.post(f"/api/clips/{c.id}/unapprove", headers=h).json()["status"] == "detected"
    r = _clip(db, p, 50.0, 80.0, status="rendered")
    assert client.post(f"/api/clips/{r.id}/approve", headers=h).status_code == 409


def test_delete(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c, busy = _clip(db, p), _clip(db, p, 50.0, 80.0, status="rendering")
    assert client.delete(f"/api/clips/{c.id}", headers=h).status_code == 204
    assert client.get(f"/api/clips/{c.id}").status_code == 404
    assert client.delete(f"/api/clips/{busy.id}", headers=h).status_code == 409


def test_detect_endpoint_enqueues_job_with_params(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    r = client.post(f"/api/projects/{p.id}/detect", json={"parts": 2, "clips_per_part": 3, "target_dur": 30}, headers=h)
    assert r.status_code == 202
    job = db.get(Job, r.json()["job_id"])
    assert job.type == "detect" and job.payload == {"project_id": p.id, "clips_per_part": 3, "target_dur": 30, "parts": 2}
    assert client.post(f"/api/projects/{p.id}/detect", json={}, headers=h).status_code == 409  # ya hay uno en marcha


def test_detect_endpoint_defaults_and_validation(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    jid = client.post(f"/api/projects/{p.id}/detect", json={}, headers=h).json()["job_id"]
    assert db.get(Job, jid).payload == {"project_id": p.id, "clips_per_part": 5, "target_dur": 40}
    db.get(Job, jid).status = "completed"
    db.commit()
    for bad in ({"target_dur": 5}, {"clips_per_part": 99}, {"parts": 0}):
        assert client.post(f"/api/projects/{p.id}/detect", json=bad, headers=h).status_code == 422


def test_detect_endpoint_needs_a_transcript(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch, words=False)
    assert client.post(f"/api/projects/{p.id}/detect", json={}, headers=h).status_code == 409


def test_cortinilla_at_is_validated_and_reset_when_the_trim_changes(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    assert client.get(f"/api/clips/{c.id}").json()["cortinilla_at"] is None
    assert "outro_enabled" not in client.get(f"/api/clips/{c.id}").json()
    assert client.patch(f"/api/clips/{c.id}", json={"cortinilla_at": 12.5}, headers=h).json()["cortinilla_at"] == 12.5
    assert client.patch(f"/api/clips/{c.id}", json={"cortinilla_at": 29.5}, headers=h).status_code == 422  # último segundo
    assert client.patch(f"/api/clips/{c.id}", json={"cortinilla_at": 0}, headers=h).status_code == 422
    assert client.patch(f"/api/clips/{c.id}", json={"outro_enabled": False}, headers=h).status_code == 422  # ya no existe
    assert client.patch(f"/api/clips/{c.id}", json={"end": 45.0}, headers=h).json()["cortinilla_at"] is None
    assert client.patch(f"/api/clips/{c.id}", json={"end": 50.0, "cortinilla_at": 8.0}, headers=h).json()["cortinilla_at"] == 8.0


def test_new_clips_take_the_cortinilla_default_from_the_template(client, tmp_path, monkeypatch):
    from app.db.models import BrandTemplate
    from app.services import clips as clips_service
    from app.services.clip_detector import ClipCandidate
    h, db, p = _project(client, tmp_path, monkeypatch)
    cand = ClipCandidate(start=10.0, end=40.0, title="t", reason="", score=5, transcript="x", hook="h", emphasis=[], parts=[])
    clips_service.replace_detected_clips(db, p, [cand])
    assert db.query(Clip).one().intro_enabled is False
    t = BrandTemplate(user_id=p.user_id, name="m", cortinilla_default=True)
    db.add(t)
    db.commit()
    p.default_template_id = t.id
    db.commit()
    clips_service.replace_detected_clips(db, p, [cand])
    assert db.query(Clip).one().intro_enabled is True
