import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Project, ProjectStatus, User
from app.services import media_sign, storage

PW = "una-clave-larga-1"
DATA = bytes(range(256)) * 40  # 10 240 bytes reconocibles


def _login(c, email="a@x.com"):
    assert c.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    return {"X-CSRF-Token": c.cookies.get("csrf")}


def _project(client, tmp_path, monkeypatch, email="a@x.com", with_video=True):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    _login(client, email)
    db = client.session_factory()
    user = db.query(User).filter(User.email == email).one()
    p = Project(user_id=user.id, source_url="https://youtu.be/x", title="T", status=ProjectStatus.READY)
    db.add(p)
    db.commit()
    folder = storage.project_dir(user.id, p.id)
    if with_video:
        (folder / "source.mp4").write_bytes(DATA)
        (folder / "words.json").write_text("{}")
        p.video_path = storage.rel(folder / "source.mp4")
        db.commit()
    return db, p, folder


def anon(client):
    return TestClient(client.app)  # sin cookies: los <video> reales pueden no llevarlas


def test_signed_url_serves_the_file_without_a_session(client, tmp_path, monkeypatch):
    db, p, _ = _project(client, tmp_path, monkeypatch)
    out = client.get(f"/api/projects/{p.id}/video-url").json()
    assert out["expires_in"] == 3600 and out["url"].startswith("/api/media/u")
    r = anon(client).get(out["url"])
    assert r.status_code == 200 and r.content == DATA and r.headers["content-type"] == "video/mp4"
    assert "private" in r.headers["cache-control"]


def test_range_requests_return_partial_content(client, tmp_path, monkeypatch):
    db, p, _ = _project(client, tmp_path, monkeypatch)
    url = client.get(f"/api/projects/{p.id}/video-url").json()["url"]
    r = anon(client).get(url, headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == DATA[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(DATA)}"
    assert anon(client).get(url, headers={"Range": "bytes=10000-"}).content == DATA[10000:]


def test_tampered_or_expired_signature_is_403(client, tmp_path, monkeypatch):
    db, p, _ = _project(client, tmp_path, monkeypatch)
    url = client.get(f"/api/projects/{p.id}/video-url").json()["url"]
    q = parse_qs(urlparse(url).query)
    path = urlparse(url).path
    a = anon(client)
    assert a.get(f"{path}?exp={q['exp'][0]}&sig={'0' * 64}").status_code == 403           # firma falsa
    assert a.get(f"{path}?exp={int(q['exp'][0]) + 9999}&sig={q['sig'][0]}").status_code == 403  # exp alargado
    assert a.get(f"{path}x?exp={q['exp'][0]}&sig={q['sig'][0]}").status_code == 403          # otra ruta
    assert a.get(path).status_code == 422                                                       # sin firma
    expired = media_sign.sign(p.video_path, int(time.time()) - 5)
    assert a.get(f"{path}?exp={int(time.time()) - 5}&sig={expired}").status_code == 403


def test_signature_does_not_transfer_between_paths(client, tmp_path, monkeypatch):
    db, p, folder = _project(client, tmp_path, monkeypatch)
    (folder / "other.mp4").write_bytes(b"secreto")
    exp = int(time.time()) + 60
    sig = media_sign.sign(p.video_path, exp)
    other = storage.rel(folder / "other.mp4")
    assert anon(client).get(f"/api/media/{other}?exp={exp}&sig={sig}").status_code == 403


def test_correctly_signed_paths_outside_media_dir_or_non_media_are_404(client, tmp_path, monkeypatch):
    db, p, folder = _project(client, tmp_path, monkeypatch)
    exp = int(time.time()) + 60
    for rel in ("../etc/passwd", "u1/../../etc/passwd", f"u{p.user_id}/p{p.id}/words.json", f"u{p.user_id}/p{p.id}/nada.mp4"):
        r = anon(client).get(f"/api/media/{rel}?exp={exp}&sig={media_sign.sign(rel, exp)}")
        assert r.status_code == 404, rel


def test_video_url_is_owner_only_and_needs_a_session(client, tmp_path, monkeypatch):
    db, p, _ = _project(client, tmp_path, monkeypatch)
    other = TestClient(client.app)
    _login(other, "b@x.com")
    assert other.get(f"/api/projects/{p.id}/video-url").status_code == 404
    assert TestClient(client.app).get(f"/api/projects/{p.id}/video-url").status_code == 401


def test_video_url_needs_a_downloaded_video(client, tmp_path, monkeypatch):
    db, p, _ = _project(client, tmp_path, monkeypatch, with_video=False)
    assert client.get(f"/api/projects/{p.id}/video-url").status_code == 409


def test_signed_urls_use_a_key_derived_from_the_jwt_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "jwt_secret", "uno")
    a = media_sign.sign("x.mp4", 10)
    monkeypatch.setattr(get_settings(), "jwt_secret", "dos")
    assert media_sign.sign("x.mp4", 10) != a
    monkeypatch.setattr(get_settings(), "jwt_secret", "")
    with pytest.raises(RuntimeError):
        media_sign.sign("x.mp4", 10)
