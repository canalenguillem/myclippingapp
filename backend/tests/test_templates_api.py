from fastapi.testclient import TestClient

from app.db.models import Clip, RenderState
from app.routers import templates as templates_router
from app.services.fx_client import FxUnavailable
from tests.test_clips_api import _clip, _login, _project

BODY = {"name": "Mi canal", "preset": "editorial", "colors": {"primary": "#112233"}, "sfx": True, "cortinilla_default": True,
        "cortinilla": {"title": "Spain Facts", "kicker": "España en datos", "duration": 3.6, "handle": "@micanal",
                       "outro_text": "Parte 2 en el canal", "outro_duration": 2.5, "like": "ME GUSTA", "subscribe": "SUSCRÍBETE"}}


def test_create_list_get_patch_delete(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    r = client.post("/api/templates", json=BODY, headers=h)
    assert r.status_code == 201
    t = r.json()
    assert t["colors"] == {"primary": "#112233"} and t["cortinilla"]["title"] == "Spain Facts" and t["cortinilla_default"] is True
    assert [x["id"] for x in client.get("/api/templates").json()] == [t["id"]]
    assert client.get(f"/api/templates/{t['id']}").json()["name"] == "Mi canal"
    out = client.patch(f"/api/templates/{t['id']}", json={"name": " Otro ", "cortinilla": {**BODY["cortinilla"], "title": "Nuevo Titulo"}}, headers=h).json()
    assert out["name"] == "Otro" and out["cortinilla"]["title"] == "Nuevo Titulo" and out["colors"] == {"primary": "#112233"}
    assert client.delete(f"/api/templates/{t['id']}", headers=h).status_code == 204
    assert client.get("/api/templates").json() == [] and client.get(f"/api/templates/{t['id']}").status_code == 404


def test_validation(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    bad = [{**BODY, "name": ""}, {**BODY, "preset": "otro"}, {**BODY, "colors": {"primary": "rojo"}}, {**BODY, "extra": 1},
           {**BODY, "cortinilla": {**BODY["cortinilla"], "duration": 99}}, {**BODY, "cortinilla": {**BODY["cortinilla"], "title": "x" * 41}},
           {**BODY, "cortinilla": {**BODY["cortinilla"], "color": "azul"}}, {**BODY, "cortinilla": {**BODY["cortinilla"], "like": ""}},
           {**BODY, "cortinilla": {**BODY["cortinilla"], "otro": 1}}]
    for body in bad:
        assert client.post("/api/templates", json=body, headers=h).status_code == 422, body
    assert client.post("/api/templates", json={"name": "solo nombre"}, headers=h).json()["cortinilla"]["duration"] == 3.6  # valores por defecto


def test_templates_are_isolated_between_users(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    tid = client.post("/api/templates", json=BODY, headers=h).json()["id"]
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.get("/api/templates").json() == []
    for call in (other.get(f"/api/templates/{tid}"), other.patch(f"/api/templates/{tid}", json={"name": "x"}, headers=hb), other.delete(f"/api/templates/{tid}", headers=hb)):
        assert call.status_code == 404
    assert client.get(f"/api/templates/{tid}").status_code == 200


def test_editing_a_template_invalidates_the_renders_that_use_it_and_deleting_unlinks(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    tid = client.post("/api/templates", json=BODY, headers=h).json()["id"]
    c = _clip(db, p, template_id=tid, render_state=RenderState.DRAFT, draft_path="u1/p1/clip_1/draft.mp4")
    busy = _clip(db, p, 50.0, 80.0, template_id=tid, render_state=RenderState.RENDERING)
    p.default_template_id = tid
    db.commit()
    client.patch(f"/api/templates/{tid}", json={"sfx": False}, headers=h)
    db.expire_all()
    assert db.get(Clip, c.id).render_state is RenderState.NONE and db.get(Clip, c.id).draft_path is None
    assert db.get(Clip, busy.id).render_state is RenderState.RENDERING          # el que está en marcha no se toca
    client.delete(f"/api/templates/{tid}", headers=h)
    db.expire_all()
    assert db.get(Clip, c.id).template_id is None and db.get(Clip, busy.id).template_id is None
    db.refresh(p)
    assert p.default_template_id is None


def test_clip_and_project_choose_a_template_only_if_it_is_theirs(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    mine = client.post("/api/templates", json=BODY, headers=h).json()["id"]
    c = _clip(db, p)
    assert client.patch(f"/api/clips/{c.id}", json={"template_id": mine}, headers=h).json()["template_id"] == mine
    assert client.get(f"/api/clips/{c.id}").json()["template_id"] == mine
    assert client.patch(f"/api/projects/{p.id}", json={"default_template_id": mine}, headers=h).json()["default_template_id"] == mine
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    theirs = other.post("/api/templates", json=BODY, headers=hb).json()["id"]
    assert client.patch(f"/api/clips/{c.id}", json={"template_id": theirs}, headers=h).status_code == 404
    assert client.patch(f"/api/projects/{p.id}", json={"default_template_id": theirs}, headers=h).status_code == 404
    assert client.patch(f"/api/projects/{p.id}", json={"default_template_id": None}, headers=h).json()["default_template_id"] is None


class FakeClient:
    def __init__(self, fail=False):
        self.requests, self.fail = [], fail

    def preview(self, request):
        self.requests.append(request)
        if self.fail:
            raise FxUnavailable("sin servicio")
        return {"html": "<!doctype html>", "duration": 8.3}


def test_preview_proxies_to_the_service_with_the_template_values(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    fake = FakeClient()
    monkeypatch.setattr(templates_router, "make_fx_client", lambda: fake)
    r = client.post("/api/templates/preview", json={"colors": {"primary": "#112233"}, "cortinilla": BODY["cortinilla"]}, headers=h)
    assert r.status_code == 200 and r.json() == {"html": "<!doctype html>", "duration": 8.3}
    req = fake.requests[0]
    assert req["cortinilla"] == {"duration": 3.6, "color": "#112233", "title": "Spain Facts", "kicker": "España en datos"}
    assert req["outro"]["handle"] == "@micanal" and req["outro"]["text"] == "Parte 2 en el canal" and req["outro"]["color"] == "#112233"


def test_preview_errors_are_503_and_need_login(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    monkeypatch.setattr(templates_router, "make_fx_client", lambda: FakeClient(fail=True))
    assert client.post("/api/templates/preview", json={}, headers=h).status_code == 503
    monkeypatch.setattr(templates_router, "make_fx_client", lambda: None)
    assert client.post("/api/templates/preview", json={}, headers=h).status_code == 503
    assert TestClient(client.app).post("/api/templates/preview", json={}).status_code in (401, 403)


def test_template_null_on_a_clip_goes_back_to_no_template(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    mine = client.post("/api/templates", json=BODY, headers=h).json()["id"]
    c = _clip(db, p, template_id=mine)
    assert client.patch(f"/api/clips/{c.id}", json={"template_id": None}, headers=h).json()["template_id"] is None
