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


# --- objeto que orbita (imagen de la librería) -------------------------------------------------------

def _asset(client, tmp_path, name="mapa"):
    import io
    from PIL import Image
    from app.db.models import Asset, User
    from app.services import storage
    db = client.session_factory()
    user = db.query(User).filter(User.email == "a@x.com").one()
    a = Asset(user_id=user.id, name=name, width=60, height=60)
    db.add(a)
    db.commit()
    folder = storage.media_root() / f"u{user.id}" / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (400, 300), (218, 46, 9, 255))
    img.save(folder / f"{a.id}.png")
    a.path = storage.rel(folder / f"{a.id}.png")
    db.commit()
    return a


def test_orbit_asset_is_saved_in_the_template_and_must_be_the_users_own(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = _asset(client, tmp_path)
    body = {**BODY, "cortinilla": {**BODY["cortinilla"], "orbit_asset_id": a.id}}
    t = client.post("/api/templates", json=body, headers=h).json()
    assert t["cortinilla"]["orbit_asset_id"] == a.id
    assert client.patch(f"/api/templates/{t['id']}", json={"cortinilla": {**BODY["cortinilla"]}}, headers=h).json()["cortinilla"].get("orbit_asset_id") is None   # quitarla
    assert client.post("/api/templates", json={**BODY, "cortinilla": {**BODY["cortinilla"], "orbit_asset_id": 99999}}, headers=h).status_code == 404
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post("/api/templates", json=body, headers=hb).status_code == 404                  # imagen de otro usuario
    assert client.post("/api/templates", json={**BODY, "cortinilla": {**BODY["cortinilla"], "orbit_asset_id": 0}}, headers=h).status_code == 422


def test_an_image_used_as_orbit_cannot_be_deleted(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = _asset(client, tmp_path)
    t = client.post("/api/templates", json={**BODY, "cortinilla": {**BODY["cortinilla"], "orbit_asset_id": a.id}}, headers=h).json()
    r = client.delete(f"/api/assets/{a.id}", headers=h)
    assert r.status_code == 409 and "1 plantilla" in r.json()["detail"]
    client.patch(f"/api/templates/{t['id']}", json={"cortinilla": BODY["cortinilla"]}, headers=h)
    assert client.delete(f"/api/assets/{a.id}", headers=h).status_code == 204


def test_preview_embeds_the_chosen_image_as_a_small_data_uri(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    a = _asset(client, tmp_path)
    fake = FakeClient()
    monkeypatch.setattr(templates_router, "make_fx_client", lambda: fake)
    client.post("/api/templates/preview", json={"cortinilla": {**BODY["cortinilla"], "orbit_asset_id": a.id}}, headers=h)
    orbit = fake.requests[0]["cortinilla"]["orbit"]
    assert orbit.startswith("data:image/png;base64,") and len(orbit) < 20000
    client.post("/api/templates/preview", json={"cortinilla": BODY["cortinilla"]}, headers=h)
    assert "orbit" not in fake.requests[1]["cortinilla"]
    assert client.post("/api/templates/preview", json={"cortinilla": {**BODY["cortinilla"], "orbit_asset_id": 99999}}, headers=h).status_code == 404


# --- canal de YouTube por defecto del proyecto --------------------------------------------------------

def _channel(client, h, name="Canal"):
    return client.post("/api/channels", json={"name": name}, headers=h).json()["id"]


def test_project_default_channel_is_exposed_validated_and_applied_to_clips_without_one(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    ch1, ch2 = _channel(client, h, "Uno"), _channel(client, h, "Dos")
    sin, con, subido = _clip(db, p, 10, 40), _clip(db, p, 50, 80, channel_id=ch2), _clip(db, p, 90, 99, status="uploaded")
    out = client.patch(f"/api/projects/{p.id}", json={"default_channel_id": ch1}, headers=h).json()
    assert out["default_channel_id"] == ch1 and client.get(f"/api/projects/{p.id}").json()["default_channel_id"] == ch1
    db.expire_all()
    assert db.get(Clip, sin.id).channel_id == ch1                      # el que no tenía canal lo recibe
    assert db.get(Clip, con.id).channel_id == ch2                      # el que ya tenía uno no se pisa
    assert db.get(Clip, subido.id).channel_id is None                  # ni los ya subidos
    assert client.patch(f"/api/projects/{p.id}", json={"default_template_id": None}, headers=h).json()["default_channel_id"] == ch1   # tocar la plantilla no toca el canal
    assert client.patch(f"/api/projects/{p.id}", json={"default_channel_id": None}, headers=h).json()["default_channel_id"] is None


def test_project_default_channel_must_be_the_users_own(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    theirs = other.post("/api/channels", json={"name": "Ajeno"}, headers=hb).json()["id"]
    assert client.patch(f"/api/projects/{p.id}", json={"default_channel_id": theirs}, headers=h).status_code == 404
    assert client.patch(f"/api/projects/{p.id}", json={"default_channel_id": 99999}, headers=h).status_code == 404


def test_new_clips_take_the_project_default_channel(client, tmp_path, monkeypatch):
    from app.services import clips as clips_service
    from app.services.clip_detector import ClipCandidate
    h, db, p = _project(client, tmp_path, monkeypatch)
    ch = _channel(client, h)
    client.patch(f"/api/projects/{p.id}", json={"default_channel_id": ch}, headers=h)
    db.refresh(p)
    clips_service.replace_detected_clips(db, p, [ClipCandidate(start=10.0, end=40.0, title="t", reason="", score=5, transcript="x", hook="h", emphasis=[], parts=[])])
    assert db.query(Clip).one().channel_id == ch
