from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import User
from tests.test_clips_api import _login


def two_users(client):
    ha = _login(client, "admin@x.com")                       # el primero que se registra es admin
    other = TestClient(client.app)
    hb = _login(other, "user@x.com")
    return ha, other, hb


def test_admin_lists_users_with_limits_lanes_and_job_counts(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "render_lanes", 2)
    ha, other, hb = two_users(client)
    out = client.get("/api/admin/users").json()
    assert out["render_lanes"] == 2
    assert [(u["email"], u["role"], u["max_concurrent_jobs"], u["running_jobs"], u["queued_jobs"]) for u in out["users"]] == [
        ("admin@x.com", "admin", 1, 0, 0), ("user@x.com", "user", 1, 0, 0)]


def test_admin_changes_a_users_limits_and_a_normal_user_cannot(client):
    ha, other, hb = two_users(client)
    uid = client.get("/api/admin/users").json()["users"][1]["id"]
    r = client.patch(f"/api/admin/users/{uid}", json={"max_concurrent_jobs": 2, "max_video_minutes": 90}, headers=ha)
    assert r.status_code == 200 and (r.json()["max_concurrent_jobs"], r.json()["max_video_minutes"]) == (2, 90)
    db = client.session_factory()
    assert db.get(User, uid).max_concurrent_jobs == 2
    assert other.get("/api/admin/users").status_code == 403
    assert other.patch(f"/api/admin/users/{uid}", json={"max_concurrent_jobs": 8}, headers=hb).status_code == 403


def test_admin_validation_and_cannot_deactivate_themselves(client):
    ha, other, hb = two_users(client)
    users = client.get("/api/admin/users").json()["users"]
    me, them = users[0]["id"], users[1]["id"]
    for bad in ({"max_concurrent_jobs": 0}, {"max_concurrent_jobs": 9}, {"max_video_minutes": 0}, {"role": "admin"}, {"is_active": "quizá"}):
        assert client.patch(f"/api/admin/users/{them}", json=bad, headers=ha).status_code == 422, bad
    assert client.patch(f"/api/admin/users/{me}", json={"is_active": False}, headers=ha).status_code == 422
    assert client.patch(f"/api/admin/users/{them}", json={"is_active": False}, headers=ha).json()["is_active"] is False
    assert client.patch("/api/admin/users/9999", json={"max_concurrent_jobs": 2}, headers=ha).status_code == 404
    assert TestClient(client.app).get("/api/admin/users").status_code == 401
