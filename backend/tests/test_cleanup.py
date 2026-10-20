import os
import time

from app.config import get_settings
from app.db.models import Job
from app.jobs import queue
from app.services import cleanup, storage
from tests.test_clips_api import _clip, _project


def world(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    folder = storage.project_dir(p.user_id, p.id)
    (folder / "source.mp4").write_bytes(b"v" * 5000)
    (folder / "audio.mp3").write_bytes(b"a" * 1000)
    (folder / "words.json").write_text('{"words": []}')
    (folder / "silences.json").write_text("[]")
    p.video_path = storage.rel(folder / "source.mp4")
    c = _clip(db, p, 10.0, 40.0)
    clip_dir = folder / f"clip_{c.id}"
    clip_dir.mkdir()
    for name in ("draft.mp4", "final.mp4", "thumb.jpg"):
        (clip_dir / name).write_bytes(b"x" * 2000)
    c.draft_path, c.rendered_path, c.thumbnail_path = (storage.rel(clip_dir / n) for n in ("draft.mp4", "final.mp4", "thumb.jpg"))
    c.render_state = "final"
    c.status = "uploaded"
    db.commit()
    return h, db, p, c, folder


def test_free_project_keeps_only_the_transcription_files_and_resets_the_clips(client, tmp_path, monkeypatch):
    h, db, p, c, folder = world(client, tmp_path, monkeypatch)
    u = cleanup.usage(folder)
    assert u.total > u.heavy > 11000
    freed = cleanup.free_project(db, p)
    assert freed == u.heavy
    assert sorted(f.name for f in folder.iterdir()) == ["silences.json", "words.json"]
    db.refresh(c)
    assert (c.draft_path, c.rendered_path, c.thumbnail_path) == (None, None, None) and c.render_state.value == "none" and c.status == "uploaded"
    assert p.video_path                                                          # la ruta se conserva: el vídeo se descarga de nuevo al renderizar


def test_free_project_does_nothing_while_a_job_is_active(client, tmp_path, monkeypatch):
    h, db, p, c, folder = world(client, tmp_path, monkeypatch)
    queue.enqueue(db, p.user_id, "render", {"clip_id": c.id, "project_id": p.id, "quality": "draft"})
    assert cleanup.free_project(db, p) == 0 and (folder / "source.mp4").exists()


def test_cleanup_old_only_frees_projects_without_recent_files(client, tmp_path, monkeypatch):
    h, db, p, c, folder = world(client, tmp_path, monkeypatch)
    assert cleanup.cleanup_old(db, 14) == (0, 0) and (folder / "source.mp4").exists()          # actividad reciente
    assert cleanup.cleanup_old(db, 0) == (0, 0)                                                   # desactivado
    old = time.time() - 30 * 86400
    for f in folder.rglob("*"):
        os.utime(f, (old, old))
    projects, freed = cleanup.cleanup_old(db, 14)
    assert projects == 1 and freed > 0 and not (folder / "source.mp4").exists()
    assert cleanup.cleanup_old(db, 14) == (0, 0)                                                  # ya limpio


def test_storage_endpoints_report_sizes_free_and_cannot_touch_other_users(client, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_clips_api import _login
    monkeypatch.setattr(get_settings(), "media_retention_days", 7)
    h, db, p, c, folder = world(client, tmp_path, monkeypatch)
    out = client.get("/api/storage").json()
    row = out["projects"][0]
    assert out["retention_days"] == 7 and out["free_bytes"] > 0 and row["id"] == p.id and row["heavy_bytes"] > 11000 and row["has_source"] is True
    assert client.get(f"/api/projects/{p.id}/video-url").status_code == 200
    freed = client.post(f"/api/projects/{p.id}/free-space", headers=h).json()["freed_bytes"]
    assert freed == row["heavy_bytes"]
    after = client.get("/api/storage").json()["projects"][0]
    assert after["heavy_bytes"] == 0 and after["has_source"] is False
    r = client.get(f"/api/projects/{p.id}/video-url")
    assert r.status_code == 409 and "se descarga solo" in r.json()["detail"]
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post(f"/api/projects/{p.id}/free-space", headers=hb).status_code == 404
    assert other.get("/api/storage").json()["projects"] == []
