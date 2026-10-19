import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.models import YouTubeChannel
from app.routers import channels as channels_router
from app.services import crypto, youtube_oauth
from tests.test_clips_api import _login

SECRET = {"web": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-super-secreto", "project_id": "mi-proyecto",
                  "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}


def secret_file(data=None):
    return {"file": ("client_secret.json", json.dumps(data or SECRET).encode(), "application/json")}


# --- cifrado -------------------------------------------------------------------------------------

def test_crypto_roundtrip_and_tamper_detection(monkeypatch):
    token = crypto.encrypt_json({"secreto": "valor-reconocible"})
    assert "valor-reconocible" not in token and crypto.decrypt_json(token) == {"secreto": "valor-reconocible"}
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(token[:-4] + "AAAA")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "app_encryption_key", "")
    with pytest.raises(crypto.CryptoError, match="vacía"):
        crypto.encrypt("x")


# --- client_secret.json --------------------------------------------------------------------------

def test_parse_accepts_web_and_installed_and_hides_the_secret_in_the_hint():
    s = youtube_oauth.parse_client_secret(json.dumps(SECRET))
    assert (s.client_id, s.project_id) == ("123-abc.apps.googleusercontent.com", "mi-proyecto")
    assert "super-secreto" not in s.hint and "mi-proyecto" in s.hint
    inst = {"installed": {**SECRET["web"]}}
    assert youtube_oauth.parse_client_secret(json.dumps(inst)).client_id.endswith("googleusercontent.com")


@pytest.mark.parametrize("data,msg", [
    (b"no es json", "JSON válido"), (b"[1,2]", "client_secret.json de Google"), (b'{"otra": {}}', "«web» o «installed»"),
    (json.dumps({"web": {**SECRET["web"], "client_id": "x"}}).encode(), "Faltan el client_id"),
    (json.dumps({"web": {**SECRET["web"], "client_secret": ""}}).encode(), "Faltan el client_id"),
    (json.dumps({"web": {**SECRET["web"], "token_uri": "https://malo.example.com/token"}}).encode(), "token_uri no es de Google"),
    (json.dumps({"web": {**SECRET["web"], "token_uri": "http://oauth2.googleapis.com/token"}}).encode(), "token_uri no es de Google"),
    (json.dumps({"web": {**SECRET["web"], "auth_uri": "https://accounts.google.com.evil.io/auth"}}).encode(), "auth_uri no es de Google"),
])
def test_parse_rejects_bad_files(data, msg):
    with pytest.raises(youtube_oauth.SecretError, match=msg):
        youtube_oauth.parse_client_secret(data)


# --- state firmado -------------------------------------------------------------------------------

def test_state_roundtrip_expiry_and_tampering():
    state = youtube_oauth.sign_state(7, 42)
    assert youtube_oauth.verify_state(state) == (7, 42)
    assert youtube_oauth.sign_state(7, 42) != state                                   # nonce distinto cada vez
    with pytest.raises(youtube_oauth.OAuthError, match="caducó"):
        youtube_oauth.verify_state(state, now=time.time() + youtube_oauth.STATE_TTL + 5)
    body, sig = state.split(".")
    for bad in (f"{body}.{sig[:-3]}AAA", f"{youtube_oauth._b64(b'8.42.x.9999999999')}.{sig}", "basura", "a.b.c", ""):
        with pytest.raises(youtube_oauth.OAuthError):
            youtube_oauth.verify_state(bad)


# --- cliente de Google ---------------------------------------------------------------------------

def google_with(handler):
    return youtube_oauth.GoogleClient(httpx.Client(transport=httpx.MockTransport(handler)))


def test_exchange_code_returns_tokens_and_requires_a_refresh_token():
    secret = youtube_oauth.parse_client_secret(json.dumps(SECRET))
    seen = {}

    def ok(request):
        seen.update(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "ya29", "refresh_token": "1//r", "expires_in": 3599, "scope": "a b"})

    token = google_with(ok).exchange_code(secret, "CODIGO")
    assert (token["access_token"], token["refresh_token"]) == ("ya29", "1//r") and token["expires_at"] > time.time() + 3000
    assert seen["code"] == "CODIGO" and seen["grant_type"] == "authorization_code" and seen["redirect_uri"].endswith("/api/youtube/callback")
    with pytest.raises(youtube_oauth.OAuthError, match="refresh_token"):
        google_with(lambda r: httpx.Response(200, json={"access_token": "x"})).exchange_code(secret, "c")
    with pytest.raises(youtube_oauth.OAuthError, match="invalid_grant"):
        google_with(lambda r: httpx.Response(400, json={"error": "invalid_grant"})).exchange_code(secret, "c")
    with pytest.raises(youtube_oauth.OAuthError, match="No se pudo hablar"):
        google_with(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))).exchange_code(secret, "c")


def test_channel_info_reads_the_channel_or_explains_why_not():
    ok = lambda r: httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "Spain Facts", "thumbnails": {"default": {"url": "https://x/y.jpg"}}}}]})  # noqa: E731
    assert google_with(ok).channel_info("tok") == {"id": "UC1", "title": "Spain Facts", "thumbnail": "https://x/y.jpg"}
    with pytest.raises(youtube_oauth.OAuthError, match="no tiene un canal"):
        google_with(lambda r: httpx.Response(200, json={"items": []})).channel_info("tok")
    with pytest.raises(youtube_oauth.OAuthError, match="403"):
        google_with(lambda r: httpx.Response(403, json={})).channel_info("tok")


# --- API de canales ------------------------------------------------------------------------------

class FakeGoogle:
    def __init__(self, fail=None, title="Spain facts"):
        self.fail, self.codes, self.title, self.refreshed = fail, [], title, 0

    def refresh(self, secret, token):
        self.refreshed += 1
        if self.fail:
            raise youtube_oauth.OAuthError(self.fail)
        return {**token, "access_token": "renovado", "expires_at": int(time.time()) + 3600}

    def exchange_code(self, secret, code):
        self.codes.append(code)
        if self.fail:
            raise youtube_oauth.OAuthError(self.fail)
        return {"access_token": "ya29.fake", "refresh_token": "1//refresh-fake", "scope": "s", "expires_at": int(time.time()) + 3600}

    def channel_info(self, access_token):
        return {"id": "UC123", "title": self.title, "thumbnail": "https://img/x.jpg"}


def make_channel(client, h, **extra):
    r = client.post("/api/channels", json={"name": "Spain Facts", **extra}, headers=h)
    assert r.status_code == 201
    return r.json()


def test_channel_crud_defaults_and_validation(client):
    h = _login(client)
    ch = make_channel(client, h)
    assert (ch["language"], ch["default_privacy"], ch["has_secret"], ch["linked"]) == ("es", "private", False, False)
    assert ch["redirect_uri"].endswith("/api/youtube/callback")
    out = client.patch(f"/api/channels/{ch['id']}", json={"name": " Otro ", "default_privacy": "unlisted", "seo_rules": "sin clickbait"}, headers=h).json()
    assert (out["name"], out["default_privacy"], out["seo_rules"]) == ("Otro", "unlisted", "sin clickbait")
    for bad in ({"name": ""}, {"name": "x", "language": "es-ES"}, {"name": "x", "default_privacy": "secreto"}, {"name": "x", "otro": 1}):
        assert client.post("/api/channels", json=bad, headers=h).status_code == 422
    assert client.delete(f"/api/channels/{ch['id']}", headers=h).status_code == 204 and client.get("/api/channels").json() == []


def test_client_secret_is_stored_encrypted_never_returned_and_replacing_it_unlinks(client, monkeypatch):
    h = _login(client)
    ch = make_channel(client, h)
    r = client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file()["file"] and secret_file(), headers=h)
    assert r.status_code == 200 and r.json()["has_secret"] and "super-secreto" not in r.text and "mi-proyecto" in r.json()["secret_hint"]
    db = client.session_factory()
    row = db.get(YouTubeChannel, ch["id"])
    assert "super-secreto" not in row.client_secret_enc and crypto.decrypt_json(row.client_secret_enc)["client_secret"] == "GOCSPX-super-secreto"
    # conectar y luego sustituir el JSON: el token y el canal enlazado se borran
    monkeypatch.setattr(channels_router, "google", FakeGoogle())
    start = client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()
    state = parse_qs(urlparse(start["url"]).query)["state"][0]
    assert client.get("/api/youtube/callback", params={"code": "c", "state": state}, follow_redirects=False).status_code == 303
    assert client.get("/api/channels").json()[0]["linked"] is True
    other = {"web": {**SECRET["web"], "client_id": "999-zzz.apps.googleusercontent.com", "project_id": "otro-proyecto"}}
    out = client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(other), headers=h).json()
    assert (out["linked"], out["yt_title"], out["linked_at"]) == (False, None, None) and "otro-proyecto" in out["secret_hint"]
    assert client.delete(f"/api/channels/{ch['id']}/client-secret", headers=h).json()["has_secret"] is False


def test_bad_secret_files_are_rejected_without_touching_the_current_one(client):
    h = _login(client)
    ch = make_channel(client, h)
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    bad = {"file": ("x.json", b'{"web": {"client_id": "a"}}', "application/json")}
    r = client.put(f"/api/channels/{ch['id']}/client-secret", files=bad, headers=h)
    assert r.status_code == 422 and "Faltan" in r.json()["detail"]
    big = {"file": ("x.json", b"{" + b" " * 30000 + b"}", "application/json")}
    assert client.put(f"/api/channels/{ch['id']}/client-secret", files=big, headers=h).status_code == 422
    assert "mi-proyecto" in client.get("/api/channels").json()[0]["secret_hint"]


def test_oauth_start_builds_the_google_url_with_a_signed_state(client):
    h = _login(client)
    ch = make_channel(client, h)
    assert client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).status_code == 409          # sin JSON no se puede conectar
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    start = client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()
    u = urlparse(start["url"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.netloc == "accounts.google.com" and q["client_id"] == "123-abc.apps.googleusercontent.com"
    assert q["access_type"] == "offline" and q["prompt"] == "select_account consent" and q["response_type"] == "code"
    assert "youtube.upload" in q["scope"] and q["redirect_uri"] == start["redirect_uri"] and "super-secreto" not in start["url"]
    assert youtube_oauth.verify_state(q["state"]) == (client.get("/api/auth/me").json()["id"], ch["id"])


def test_callback_links_the_channel_and_stores_the_token_encrypted(client, monkeypatch):
    h = _login(client)
    ch = make_channel(client, h)
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    fake = FakeGoogle()
    monkeypatch.setattr(channels_router, "google", fake)
    state = parse_qs(urlparse(client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()["url"]).query)["state"][0]
    r = client.get("/api/youtube/callback", params={"code": "CODIGO", "state": state}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith(f"/channels?linked={ch['id']}") and fake.codes == ["CODIGO"]
    out = client.get("/api/channels").json()[0]
    assert (out["linked"], out["yt_title"], out["yt_channel_id"], out["yt_thumbnail"]) == (True, "Spain facts", "UC123", "https://img/x.jpg") and out["linked_at"]
    row = client.session_factory().get(YouTubeChannel, ch["id"])
    assert "refresh-fake" not in row.token_enc and crypto.decrypt_json(row.token_enc)["refresh_token"] == "1//refresh-fake"
    assert "refresh" not in json.dumps(out)
    assert client.delete(f"/api/channels/{ch['id']}/token", headers=h).json()["linked"] is False


def test_callback_rejects_bad_state_and_reports_google_errors_back_to_the_page(client, monkeypatch):
    h = _login(client)
    ch = make_channel(client, h)
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    monkeypatch.setattr(channels_router, "google", FakeGoogle())
    good = parse_qs(urlparse(client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()["url"]).query)["state"][0]
    assert client.get("/api/youtube/callback", params={"code": "c", "state": "manipulado"}).status_code == 400
    assert client.get("/api/youtube/callback", params={"code": "c"}).status_code == 400
    denied = client.get("/api/youtube/callback", params={"error": "access_denied", "state": good}, follow_redirects=False)
    assert denied.status_code == 303 and "error=" in denied.headers["location"] and not client.get("/api/channels").json()[0]["linked"]
    monkeypatch.setattr(channels_router, "google", FakeGoogle(fail="Google rechazó el código: invalid_grant"))
    failed = client.get("/api/youtube/callback", params={"code": "c", "state": good}, follow_redirects=False)
    assert failed.status_code == 303 and "invalid_grant" in failed.headers["location"].replace("%20", " ")
    assert not client.get("/api/channels").json()[0]["linked"]


def test_channels_and_callback_are_isolated_between_users(client, monkeypatch):
    h = _login(client)
    ch = make_channel(client, h)
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    state = parse_qs(urlparse(client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()["url"]).query)["state"][0]
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.get("/api/channels").json() == []
    for call in (other.patch(f"/api/channels/{ch['id']}", json={"name": "x"}, headers=hb), other.delete(f"/api/channels/{ch['id']}", headers=hb),
                 other.get(f"/api/channels/{ch['id']}/oauth/start", headers=hb), other.delete(f"/api/channels/{ch['id']}/token", headers=hb),
                 other.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=hb)):
        assert call.status_code == 404
    monkeypatch.setattr(channels_router, "google", FakeGoogle())
    assert other.get("/api/youtube/callback", params={"code": "c", "state": state}, follow_redirects=False).status_code == 400   # state de otro usuario
    assert not client.get("/api/channels").json()[0]["linked"]


def linked_channel(client, h, monkeypatch, **fake_kw):
    ch = make_channel(client, h)
    client.put(f"/api/channels/{ch['id']}/client-secret", files=secret_file(), headers=h)
    fake = FakeGoogle(**fake_kw)
    monkeypatch.setattr(channels_router, "google", fake)
    state = parse_qs(urlparse(client.get(f"/api/channels/{ch['id']}/oauth/start", headers=h).json()["url"]).query)["state"][0]
    client.get("/api/youtube/callback", params={"code": "c", "state": state}, follow_redirects=False)
    return ch, fake


def test_refresh_rereads_the_name_and_avatar_after_the_channel_was_renamed(client, monkeypatch):
    h = _login(client)
    ch, fake = linked_channel(client, h, monkeypatch, title="Salud Senior +60")
    assert client.get("/api/channels").json()[0]["yt_title"] == "Salud Senior +60"
    fake.title = "Spain Facts"                                    # lo renombran en YouTube
    out = client.post(f"/api/channels/{ch['id']}/refresh", headers=h).json()
    assert (out["yt_title"], out["linked"], out["yt_channel_id"]) == ("Spain Facts", True, "UC123") and fake.refreshed == 0   # el acceso aún vale


def test_refresh_renews_an_expired_access_token_and_stores_it(client, monkeypatch):
    h = _login(client)
    ch, fake = linked_channel(client, h, monkeypatch)
    db = client.session_factory()
    row = db.get(YouTubeChannel, ch["id"])
    row.token_enc = crypto.encrypt_json({**crypto.decrypt_json(row.token_enc), "expires_at": int(time.time()) - 10})
    db.commit()
    assert client.post(f"/api/channels/{ch['id']}/refresh", headers=h).status_code == 200 and fake.refreshed == 1
    db.expire_all()
    assert crypto.decrypt_json(db.get(YouTubeChannel, ch["id"]).token_enc)["access_token"] == "renovado"


def test_refresh_errors_are_explained_and_need_a_connected_channel(client, monkeypatch):
    h = _login(client)
    ch = make_channel(client, h)
    assert client.post(f"/api/channels/{ch['id']}/refresh", headers=h).status_code == 409
    linked, fake = linked_channel(client, h, monkeypatch)
    db = client.session_factory()
    row = db.get(YouTubeChannel, linked["id"])
    row.token_enc = crypto.encrypt_json({**crypto.decrypt_json(row.token_enc), "expires_at": 0})
    db.commit()
    fake.fail = "Google no renovó el acceso (invalid_grant): vuelve a conectar el canal"
    r = client.post(f"/api/channels/{linked['id']}/refresh", headers=h)
    assert r.status_code == 502 and "invalid_grant" in r.json()["detail"]
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post(f"/api/channels/{linked['id']}/refresh", headers=hb).status_code == 404


def test_google_client_refresh_returns_a_new_expiry_and_rejects_revoked_tokens():
    secret = youtube_oauth.parse_client_secret(json.dumps(SECRET))
    seen = {}

    def ok(request):
        seen.update(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "nuevo", "expires_in": 3599})

    token = google_with(ok).refresh(secret, {"refresh_token": "r", "access_token": "viejo", "scope": "s"})
    assert seen["grant_type"] == "refresh_token" and seen["refresh_token"] == "r"
    assert (token["access_token"], token["refresh_token"]) == ("nuevo", "r") and token["expires_at"] > time.time() + 3000
    with pytest.raises(youtube_oauth.OAuthError, match="invalid_grant"):
        google_with(lambda r: httpx.Response(400, json={"error": "invalid_grant"})).refresh(secret, {"refresh_token": "r"})
