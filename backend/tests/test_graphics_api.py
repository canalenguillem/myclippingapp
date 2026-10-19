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


def _asset(db, user_id, name="hucha"):
    from app.db.models import Asset
    a = Asset(user_id=user_id, name=name, path="")
    db.add(a)
    db.commit()
    return a


def test_image_graphics_need_an_owned_asset_and_valid_options(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    a = _asset(db, p.user_id)
    ok = {"type": "image", "at": 12.0, "asset_id": a.id, "style": "card", "effect": "vaporize"}
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [ok]}, headers=h).json()["graphics"] == [ok]
    for bad in ({"type": "image", "at": 5.0}, {**ok, "style": "otro"}, {**ok, "effect": "explotar"}, {**ok, "asset_id": 0},
                {"type": "emoji", "at": 5.0, "emoji": "🐷", "effect": "break"}):
        assert client.patch(f"/api/clips/{c.id}", json={"graphics": [bad]}, headers=h).status_code == 422, bad
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [{**ok, "asset_id": 99999}]}, headers=h).status_code == 404
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    from app.db.models import User
    theirs = _asset(db, db.query(User).filter(User.email == "b@x.com").one().id)
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [{**ok, "asset_id": theirs.id}]}, headers=h).status_code == 404   # imagen ajena
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [{"type": "emoji", "at": 5.0, "emoji": "🐷", "effect": "vaporize"}]}, headers=h).status_code == 200


def test_plan_counts_an_image_as_a_big_graphic(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    a = _asset(db, p.user_id)
    body = {"graphics": [{"type": "image", "at": 12.0, "asset_id": a.id, "effect": "vaporize"}, {**KW, "at": 13.0}]}
    plan = client.post(f"/api/clips/{c.id}/graphics-plan", json=body, headers=h).json()
    assert [b["type"] for b in plan["beats"]] == ["image"] and "más prioritario" in plan["dropped"][0]["reason"]   # la imagen gana a la tarjeta


def test_entry_and_explode_are_accepted_for_images_and_emoji_but_validated(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    a = _asset(db, p.user_id)
    img = {"type": "image", "at": 12.0, "asset_id": a.id, "style": "card", "entry": "punch", "effect": "explode"}
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [img]}, headers=h).json()["graphics"] == [img]
    assert client.patch(f"/api/clips/{c.id}", json={"graphics": [{"type": "emoji", "at": 5.0, "emoji": "💣", "effect": "explode"}]}, headers=h).status_code == 200
    for bad in ({**img, "entry": "volar"}, {"type": "emoji", "at": 5.0, "emoji": "💣", "entry": "punch"}, {"type": "keyword", "at": 5.0, "text": "x", "entry": "drop"}):
        assert client.patch(f"/api/clips/{c.id}", json={"graphics": [bad]}, headers=h).status_code == 422, bad
    plan = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": [img]}, headers=h).json()
    assert plan["beats"][0]["lead"] == 0.7 and plan["beats"][0]["start"] == 11.3


def _words_project(client, tmp_path, monkeypatch):
    """Proyecto con palabras reales (una por 0,4 s) para el planificador."""
    from app.services import transcription
    h, db, p = _project(client, tmp_path, monkeypatch, words=False)
    text = ("Hay muchos pensionistas en España cada vez más y el sistema de pensiones ha petado paga con deuda y saca dinero de todos lados "
            "para pagar las pensiones que son la mitad del gasto público en España Dicen que con los inmigrantes sí pero los informes de Funcas "
            "te cuentan que no da y eso funciona electoralmente para el PSOE").split()
    ws = [{"text": w, "start": round(i * 0.4, 3), "end": round(i * 0.4 + 0.3, 3), "confidence": 1, "speaker": "A"} for i, w in enumerate(text)]
    folder = storage.project_dir(p.user_id, p.id)
    transcription.save_words({"words": ws}, folder / "words.json")
    p.words_path = storage.rel(folder / "words.json")
    db.commit()
    return h, db, p, ws


def test_suggest_returns_anchored_scheduled_proposals_and_saves_nothing(client, tmp_path, monkeypatch):
    from app.config import get_settings
    h, db, p, ws = _words_project(client, tmp_path, monkeypatch)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    c = _clip(db, p, 0.0, 30.0)
    r = client.post(f"/api/clips/{c.id}/graphics-plan/suggest", json={"graphics": []}, headers=h)
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "plan_b" and out["notes"] and 0 < len(out["beats"]) <= out["max_beats"] == 5
    starts = {round(w["start"], 3) for w in ws}
    assert all(b["at"] in starts and b["reason"] and b["type"] in ("emoji", "image") for b in out["beats"])
    assert {b.get("emoji") for b in out["beats"]} & {"🧓", "💥", "💸"}
    maps = [b for b in out["beats"] if b["type"] == "image"]                                # el texto nombra España: su mapa entra solo
    assert len(maps) == 1 and "mapa de España" in maps[0]["reason"] and maps[0]["style"] == "original"
    assert [a["name"] for a in client.get("/api/assets").json()] == ["Mapa de España"]
    db.refresh(c)
    assert c.graphics_json == []                                                           # no guarda nada


def test_suggest_keeps_what_the_user_already_has_and_checks_ownership(client, tmp_path, monkeypatch):
    from app.config import get_settings
    h, db, p, ws = _words_project(client, tmp_path, monkeypatch)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    c = _clip(db, p, 0.0, 30.0)
    out = client.post(f"/api/clips/{c.id}/graphics-plan/suggest", json={"graphics": []}, headers=h).json()["beats"]
    mine = [{"type": "emoji", "at": out[0]["at"], "emoji": "🔥"}]
    again = client.post(f"/api/clips/{c.id}/graphics-plan/suggest", json={"graphics": mine}, headers=h).json()["beats"]
    assert all(not (b["type"] == "emoji" and abs(b["at"] - mine[0]["at"]) < 2.4) for b in again)       # nada pisa lo que ya hay
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post(f"/api/clips/{c.id}/graphics-plan/suggest", json={"graphics": []}, headers=hb).status_code == 404
    assert client.post(f"/api/clips/{c.id}/graphics-plan/suggest", json={"graphics": [], "start": 5.0, "end": 5.5}, headers=h).status_code == 422


def test_counter_strike_and_lower_third_are_saved_scheduled_and_validated(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    items = [{"type": "counter", "at": 5.0, "to_value": 700, "suffix": " ml", "label": "agua"},
             {"type": "strike", "at": 12.0, "text": " PSOE "}, {"type": "lower_third", "at": 20.0, "name": " Ana López ", "role": "periodista"}]
    out = client.patch(f"/api/clips/{c.id}", json={"graphics": items}, headers=h).json()["graphics"]
    assert out[0] == {"type": "counter", "at": 5.0, "from_value": 0.0, "to_value": 700.0, "suffix": " ml", "label": "agua"}
    assert out[1]["text"] == "PSOE" and out[2]["name"] == "Ana López"
    plan = client.post(f"/api/clips/{c.id}/graphics-plan", json={"graphics": items}, headers=h).json()
    assert [b["type"] for b in plan["beats"]] == ["counter", "strike", "lower_third"] and plan["beats"][0]["lead"] == 0.8
    for bad in ({"type": "counter", "at": 5}, {"type": "counter", "at": 5, "to_value": "x"}, {"type": "strike", "at": 5}, {"type": "lower_third", "at": 5, "name": " "}):
        assert client.patch(f"/api/clips/{c.id}", json={"graphics": [bad]}, headers=h).status_code == 422, bad
