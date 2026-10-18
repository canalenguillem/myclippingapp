from fastapi.testclient import TestClient

from app.db.models import RenderState
from app.services import silences as silences_service
from app.services import storage
from tests.test_clips_api import _clip, _login, _project

KW = {"type": "keyword", "at": 12.0, "text": " Indultos "}
EM = {"type": "emoji", "at": 20.0, "emoji": "🐔", "target": "🗳️"}


def test_graphics_are_saved_cleaned_sorted_and_exposed(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    assert client.get(f"/api/clips/{c.id}").json()["graphics"] == []
    out = client.patch(f"/api/clips/{c.id}", json={"graphics": [EM, KW]}, headers=h).json()
    assert out["graphics"] == [{"type": "keyword", "at": 12.0, "text": "Indultos"}, {"type": "emoji", "at": 20.0, "emoji": "🐔", "target": "🗳️"}]
    assert client.get(f"/api/clips/{c.id}").json()["graphics"] == out["graphics"]
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": []}, headers=h).json()["graphics"] == []


def test_invalid_graphics_are_rejected(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    bad = [{"type": "otro", "at": 1}, {"type": "keyword", "at": 5}, {"type": "keyword", "at": 5, "text": " "}, {"type": "emoji", "at": 5, "emoji": "abc"},
           {"type": "emoji", "at": 5, "emoji": "<b>"}, {"type": "emoji", "at": 5, "emoji": "🐔", "target": "x"}, {**KW, "at": -1}, {**KW, "extra": 1},
           {**KW, "text": "x" * 41}, {**KW, "duration": 99}]
    for g in bad:
        assert client.patch(f"/api/clips/{c.id}", json={"graphics": [g]}, headers=h).status_code == 422, g
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [{**KW, "at": 31}]}, headers=h).status_code == 422   # el clip dura 30 s
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [KW] * 41}, headers=h).status_code == 422


def test_editing_graphics_invalidates_the_render(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0, render_state=RenderState.DRAFT, draft_path="u1/p1/clip_1/draft.mp4")
    out = client.patch(f"/api/clips/{c.id}", json={"graphics": [KW]}, headers=h).json()
    assert out["render_state"] == "none"
    db.refresh(c)
    c.render_state, c.draft_path = RenderState.DRAFT, "u1/p1/clip_1/draft.mp4"
    db.commit()
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [KW]}, headers=h).json()["render_state"] == "draft"   # sin cambios: se conserva


def test_moving_the_start_shifts_the_graphics_so_they_stay_on_their_word(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    client.patch(f"/api/clips/{c.id}", json={"graphics": [{**KW, "at": 3.0}, {**KW, "at": 12.0}, EM]}, headers=h)
    out = client.patch(f"/api/clips/{c.id}", json={"start": 14.0}, headers=h).json()
    assert [g["at"] for g in out["graphics"]] == [8.0, 16.0]       # el de 3 s cae antes del nuevo inicio: se pierde; los otros se acercan 4 s
    out = client.patch(f"/api/clips/{c.id}", json={"end": 30.0}, headers=h).json()   # el clip dura ahora 16 s
    assert [g["at"] for g in out["graphics"]] == [8.0, 16.0]        # 16,0 es justo la duración del clip: se conserva
    # con el recorte y los gráficos juntos manda lo que envía el formulario
    out = client.patch(f"/api/clips/{c.id}", json={"start": 12.0, "graphics": [{**KW, "at": 1.0}]}, headers=h).json()
    assert [g["at"] for g in out["graphics"]] == [1.0]


def _silences(db, p, items):
    path = storage.project_dir(p.user_id, p.id) / "silences.json"
    silences_service.save_silences(items, path)
    p.silences_path = storage.rel(path)
    db.commit()


def test_plan_shows_effective_windows_dropped_beats_and_the_cortinilla(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0, intro_enabled=True)
    _silences(db, p, [{"start": 20.5, "end": 20.95}])   # centro en 10,725 s del clip
    body = {"graphics": [{**KW, "at": 9.5}, {**KW, "at": 20.0}, {"type": "keyword", "at": 1.0, "text": "gancho"}]}
    r = client.post(f"/api/clips/{c.id}/graphics-plan", json=body, headers=h)
    assert r.status_code == 200
    plan = r.json()
    assert plan["duration"] == 30.0 and plan["cortinilla_at"] == 10.725 and plan["hook_seconds"] == 2.2
    # 9,5 (ventana 9,0–11,5) cruza los 10,725 s: se recorta y sale antes; el de 20 s entra normal; el de 1 s choca con el gancho
    assert [(b["at"], b["start"], b["end"]) for b in plan["beats"]] == [(9.5, 9.0, 10.725), (20.0, 19.5, 22.0)]
    assert [d["reason"] for d in plan["dropped"]] == ["choca con el gancho"]


def test_plan_follows_the_form_not_the_saved_clip(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    base = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": [KW]}, headers=h).json()
    assert base["cortinilla_at"] is None
    _silences(db, p, [{"start": 20.5, "end": 20.95}])
    withc = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": [KW], "intro_enabled": True}, headers=h).json()
    assert withc["cortinilla_at"] == 10.725
    full = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": [KW, {"type": "emoji", "at": 12.5, "emoji": "🔥"}], "layout": "full"}, headers=h).json()
    assert [b["type"] for b in full["beats"]] == ["keyword"] and "más prioritario" in full["dropped"][0]["reason"]   # en full, un solo hueco
    trimmed = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": [KW], "start": 20.0, "end": 40.0}, headers=h).json()
    assert trimmed["duration"] == 20.0


def test_graphics_endpoints_are_isolated(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post(f"/api/clips/{c.id}/graphics-plan", json={}, headers=hb).status_code == 404
    assert other.patch(f"/api/clips/{c.id}", json={"graphics": [KW]}, headers=hb).status_code == 404
