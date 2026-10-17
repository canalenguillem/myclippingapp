from fastapi.testclient import TestClient

from app.auth.deps import get_owned
from app.db.models import Project, User

PW = "una-clave-larga-1"


def register(client, email, name="x"):
    r = client.post("/api/auth/register", json={"email": email, "password": PW, "name": name})
    assert r.status_code == 201, r.text
    return r


def test_first_user_is_admin_second_is_user(client):
    assert register(client, "a@x.com").json()["role"] == "admin"
    other = TestClient(client.app)
    assert register(other, "b@x.com").json()["role"] == "user"


def test_duplicate_email_409(client):
    register(client, "a@x.com")
    r = TestClient(client.app).post("/api/auth/register", json={"email": "A@x.com", "password": PW})
    assert r.status_code == 409


def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401
    register(client, "a@x.com")
    assert client.get("/api/auth/me").json()["email"] == "a@x.com"


def test_login_wrong_password(client):
    register(client, "a@x.com")
    r = TestClient(client.app).post("/api/auth/login", json={"email": "a@x.com", "password": "otra-clave-larga"})
    assert r.status_code == 401


def test_post_without_csrf_header_is_403(client):
    register(client, "a@x.com")
    # logout no exige sesion, pero un endpoint protegido de escritura si: probamos con current_user directo
    from fastapi import Depends
    from app.auth.deps import current_user

    @client.app.post("/api/_probe")
    def probe(user=Depends(current_user)):
        return {"id": user.id}

    assert client.post("/api/_probe").status_code == 403
    token = client.cookies.get("csrf")
    assert client.post("/api/_probe", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.post("/api/_probe", headers={"X-CSRF-Token": "falso"}).status_code == 403


def test_registration_closed_after_first_user(client, monkeypatch):
    from app.config import get_settings
    register(client, "a@x.com")
    monkeypatch.setattr(get_settings(), "allow_registration", False)
    r = TestClient(client.app).post("/api/auth/register", json={"email": "b@x.com", "password": PW})
    assert r.status_code == 403


def test_get_owned_hides_other_users_resources(client):
    import pytest
    from fastapi import HTTPException

    register(client, "a@x.com")
    register(TestClient(client.app), "b@x.com")
    db = client.session_factory()
    a, b = db.query(User).order_by(User.id).all()
    p = Project(user_id=a.id, source_url="https://youtu.be/x")
    db.add(p)
    db.commit()
    assert get_owned(db, Project, p.id, a).id == p.id
    with pytest.raises(HTTPException) as e:
        get_owned(db, Project, p.id, b)
    assert e.value.status_code == 404
