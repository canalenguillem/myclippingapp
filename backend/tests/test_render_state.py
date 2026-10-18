from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import StatementError

from app.config import get_settings
from app.db.models import Clip, Job, Project, ProjectStatus, RenderState, User
from app.jobs import queue
from app.services import storage
from tests.test_transcript_edit import _project  # proyecto con words.json y speakers A/B


def _clip(db, p, folder, state=RenderState.NONE, start=10.0, end=40.0, **kw):
    c = Clip(project_id=p.id, user_id=p.user_id, start=start, end=end, title="t", render_state=state, **kw)
    if state in (RenderState.DRAFT, RenderState.FINAL):
        for attr, name in (("draft_path", "draft.mp4"), ("rendered_path", "final.mp4"), ("thumbnail_path", "thumb.jpg")):
            if attr == "rendered_path" and state is RenderState.DRAFT:
                continue
            f = folder / f"c{start}_{name}"
            f.write_bytes(b"x")
            setattr(c, attr, storage.rel(f))
    db.add(c)
    db.commit()
    return c


def exists(c, attr):
    rel = getattr(c, attr)
    return bool(rel) and storage.absolute(rel).exists()


# --- modelo -------------------------------------------------------------------------------------

def test_render_state_values_and_defaults(client, tmp_path, monkeypatch):
    assert [s.value for s in RenderState] == ["none", "rendering", "draft", "final", "failed"]
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent)
    assert c.render_state is RenderState.NONE
    assert (c.draft_path, c.render_error, c.rendered_at, c.analysis_path) == (None, None, None, None)


def test_invalid_render_state_is_rejected(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent)
    c.render_state = "rendered"  # el estado antiguo de Clip.status ya no existe aquí
    with pytest.raises(StatementError):
        db.commit()


def test_migration_0003_adds_render_columns_with_none_default(tmp_path, monkeypatch):
    db_file = tmp_path / "mig.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "app" / "migrations"))
    try:
        command.upgrade(cfg, "0002")
        eng = create_engine(f"sqlite:///{db_file}")
        with eng.begin() as c:
            c.execute(text("INSERT INTO users (id, email, password_hash, name, role, is_active, max_concurrent_jobs, max_video_minutes, created_at) VALUES (1,'a@x.com','x','','user',1,1,180,'2026-01-01')"))
            c.execute(text("INSERT INTO projects (id, user_id, source_url, title, status, speakers, created_at) VALUES (1,1,'u','t','ready','{}','2026-01-01')"))
            c.execute(text("INSERT INTO clips (id, project_id, user_id, start, end, title, reason, score, transcript, hook, emphasis_json, parts, graphics_json, intro_enabled, outro_enabled, layout, focus, zoom, top_ratio, status, seo_title, seo_description, seo_tags, privacy, created_at) VALUES (1,1,1,1.0,31.0,'t','',0,'','','[]','[]','[]',0,1,'split','center',1.0,0.5,'detected','','','','private','2026-01-01')"))
        command.upgrade(cfg, "head")
        with eng.begin() as c:
            row = c.execute(text("SELECT render_state, draft_path, render_error, rendered_at, analysis_path FROM clips WHERE id = 1")).one()
        assert tuple(row) == ("none", None, None, None, None)
        command.downgrade(cfg, "0002")
        with eng.begin() as c:
            cols = {r[1] for r in c.execute(text("PRAGMA table_info(clips)"))}
        assert "render_state" not in cols and "draft_path" not in cols
    finally:
        get_settings.cache_clear()


# --- API ----------------------------------------------------------------------------------------

def test_clip_out_exposes_render_state_and_flags_but_not_paths(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.DRAFT)
    body = client.get(f"/api/clips/{c.id}").json()
    assert (body["render_state"], body["has_draft"], body["has_final"], body["render_error"]) == ("draft", True, False, None)
    assert not any("path" in k for k in body)


def test_editing_a_render_affecting_field_invalidates_the_renders_and_deletes_the_files(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.FINAL)
    files = [storage.absolute(getattr(c, a)) for a in ("draft_path", "rendered_path", "thumbnail_path") if getattr(c, a)]
    assert files and all(f.exists() for f in files)
    r = client.patch(f"/api/clips/{c.id}", json={"end": 45.0}, headers=h)
    assert r.status_code == 200 and r.json()["render_state"] == "none" and not r.json()["has_final"]
    db.refresh(c)
    assert (c.draft_path, c.rendered_path, c.thumbnail_path) == (None, None, None)
    assert not any(f.exists() for f in files)


def test_title_only_or_unchanged_values_keep_the_render(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.DRAFT)
    client.patch(f"/api/clips/{c.id}", json={"title": "otro título"}, headers=h)          # no cambia el vídeo
    client.patch(f"/api/clips/{c.id}", json={"end": 40.0, "layout": "split"}, headers=h)  # mismos valores
    db.refresh(c)
    assert c.render_state is RenderState.DRAFT and exists(c, "draft_path")


def test_each_render_affecting_field_invalidates(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    for field, value in (("start", 12.0), ("hook", "nuevo gancho"), ("layout", "full"), ("focus", "left"),
                         ("zoom", 1.5), ("top_ratio", 0.6), ("intro_enabled", True)):
        c = _clip(db, p, path.parent, RenderState.DRAFT, start=10.0 + len(field))
        assert client.patch(f"/api/clips/{c.id}", json={field: value}, headers=h).json()["render_state"] == "none", field


def test_a_failed_render_is_cleared_when_the_clip_is_edited(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.FAILED, render_error="ffmpeg falló")
    r = client.patch(f"/api/clips/{c.id}", json={"hook": "x"}, headers=h).json()
    assert (r["render_state"], r["render_error"]) == ("none", None)


def test_cannot_edit_or_delete_a_clip_while_it_renders(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.RENDERING)
    assert client.patch(f"/api/clips/{c.id}", json={"hook": "x"}, headers=h).status_code == 409
    assert client.delete(f"/api/clips/{c.id}", headers=h).status_code == 409
    assert db.get(Clip, c.id) is not None


def test_deleting_a_clip_removes_its_render_files(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, path.parent, RenderState.FINAL)
    files = [storage.absolute(getattr(c, a)) for a in ("draft_path", "rendered_path", "thumbnail_path") if getattr(c, a)]
    assert client.delete(f"/api/clips/{c.id}", headers=h).status_code == 204
    assert not any(f.exists() for f in files)


def test_editing_the_transcript_invalidates_the_projects_renders_only(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    mine = _clip(db, p, path.parent, RenderState.FINAL, start=10.0)
    none_yet = _clip(db, p, path.parent, RenderState.NONE, start=50.0)
    other = Project(user_id=p.user_id, source_url="https://youtu.be/y", title="otro", status=ProjectStatus.READY)
    db.add(other)
    db.commit()
    foreign = _clip(db, other, path.parent, RenderState.DRAFT, start=70.0)
    r = client.patch(f"/api/projects/{p.id}/transcript/words", json={"revision": 1, "edits": [{"index": 0, "text": "Nuevo"}]}, headers=h)
    assert r.status_code == 200
    for c in (mine, none_yet, foreign):
        db.refresh(c)
    assert mine.render_state is RenderState.NONE and not mine.rendered_path
    assert none_yet.render_state is RenderState.NONE
    assert foreign.render_state is RenderState.DRAFT and exists(foreign, "draft_path")  # otro proyecto: intacto


def test_reassigning_speakers_and_changing_their_cards_invalidate_renders(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    a = _clip(db, p, path.parent, RenderState.DRAFT, start=10.0)
    client.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [{"start_index": 0, "end_index": 2, "speaker": "B"}]}, headers=h)
    db.refresh(a)
    assert a.render_state is RenderState.NONE
    b = _clip(db, p, path.parent, RenderState.FINAL, start=60.0)
    cards = {k: {**v, "name": "Cambiado"} for k, v in p.speakers.items()}
    assert client.put(f"/api/projects/{p.id}/speakers", json=cards, headers=h).status_code == 200
    db.refresh(b)
    assert b.render_state is RenderState.NONE


def test_speaker_cards_cannot_change_while_a_job_runs_for_the_project(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    queue.enqueue(db, p.user_id, "render", {"project_id": p.id, "clip_id": 1})
    assert client.put(f"/api/projects/{p.id}/speakers", json=p.speakers, headers=h).status_code == 409
