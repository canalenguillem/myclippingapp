from fastapi.testclient import TestClient

from app.db.models import Project, ProjectStatus, User
from tests.test_clips_api import _login


def project(db, user_id, speakers):
    p = Project(user_id=user_id, source_url="u", title="T", duration=10.0, status=ProjectStatus.READY, speakers=speakers)
    db.add(p)
    db.commit()
    return p


def card(name="", role="", style="sans_upper", source=False):
    return {"name": name, "role": role, "caption_style": style, "is_source": source}


def test_known_speakers_are_ordered_by_use_and_keep_the_latest_role_and_style(client):
    _login(client)
    db = client.session_factory()
    uid = db.query(User).one().id
    project(db, uid, {"A": card("Juan Soto Ivars", "escritor", "serif_italic"), "B": card("Pedro Sánchez", "presidente del Gobierno", source=True), "C": card()})
    project(db, uid, {"A": card("juan soto ivars", "periodista", "sans_upper"), "B": card("Ana Rosa")})        # mismo nombre con otra grafía
    p3 = project(db, uid, {"A": card("Juan Soto Ivars", "", "serif_italic"), "B": card("Juan Soto Ivars", "otra vez en el mismo vídeo")})
    out = client.get("/api/speakers/known").json()
    assert [e["name"] for e in out] == ["Juan Soto Ivars", "Ana Rosa", "Pedro Sánchez"]            # 3 vídeos, 1, 1 (empate por nombre)
    soto = out[0]
    assert soto["uses"] == 3 and soto["role"] == "periodista"                                      # el más reciente con cargo (el último vídeo no lo tenía)
    assert soto["caption_style"] == "serif_italic" and soto["last_project_id"] == p3.id            # estilo del vídeo más reciente
    assert next(e for e in out if e["name"] == "Pedro Sánchez")["is_source"] is True
    assert all(e["name"] for e in out)                                                              # los hablantes sin nombre no salen


def test_known_speakers_can_exclude_the_current_project_and_are_private(client):
    _login(client)
    db = client.session_factory()
    uid = db.query(User).one().id
    keep = project(db, uid, {"A": card("Ana", "jefa")})
    project(db, uid, {"A": card("Luis", "técnico")})
    assert [e["name"] for e in client.get(f"/api/speakers/known?exclude_project={keep.id}").json()] == ["Luis"]
    other = TestClient(client.app)
    _login(other, "b@x.com")
    assert other.get("/api/speakers/known").json() == []                                            # nada de otros usuarios
    assert TestClient(client.app).get("/api/speakers/known").status_code in (401, 403)
