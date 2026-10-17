from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import StatementError

from app.config import get_settings
from app.db.models import Clip, Project, ProjectStatus, User


def _user_project(db, **kw):
    u = User(email="a@x.com", password_hash="x")
    db.add(u)
    db.commit()
    p = Project(user_id=u.id, source_url="https://youtu.be/x", **kw)
    db.add(p)
    db.commit()
    return u, p


def test_project_status_values_and_busy():
    assert [s.value for s in ProjectStatus] == ["downloading", "transcribing", "detecting", "ready", "failed"]
    assert ProjectStatus.DETECTING.busy and ProjectStatus.DOWNLOADING.busy
    assert not ProjectStatus.READY.busy and not ProjectStatus.FAILED.busy


def test_project_defaults(client):
    db = client.session_factory()
    _, p = _user_project(db)
    assert p.status is ProjectStatus.DOWNLOADING
    assert p.speakers == {} and p.silences_path is None


def test_invalid_status_is_rejected(client):
    db = client.session_factory()
    u, p = _user_project(db)
    p.status = "transcribed"  # el estado provisional ya no existe
    with pytest.raises(StatementError):
        db.commit()


def test_clip_parts_default_is_empty_list(client):
    db = client.session_factory()
    u, p = _user_project(db)
    c = Clip(project_id=p.id, user_id=u.id, start=1.0, end=31.5)
    db.add(c)
    db.commit()
    assert c.parts == [] and isinstance(c.start, float)


def test_migration_0002_converts_transcribed_and_adds_columns(tmp_path, monkeypatch):
    db_file = tmp_path / "mig.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "app" / "migrations"))
    try:
        command.upgrade(cfg, "0001")
        eng = create_engine(f"sqlite:///{db_file}")
        with eng.begin() as c:
            c.execute(text("INSERT INTO users (id, email, password_hash, name, role, is_active, max_concurrent_jobs, max_video_minutes, created_at) VALUES (1,'a@x.com','x','','user',1,1,180,'2026-01-01')"))
            c.execute(text("INSERT INTO projects (id, user_id, source_url, title, status, created_at) VALUES (1,1,'u','t','transcribed','2026-01-01'), (2,1,'u','t','ready','2026-01-01')"))
        command.upgrade(cfg, "head")
        with eng.begin() as c:
            rows = dict(c.execute(text("SELECT id, status FROM projects")).all())
            cols = {r[1] for r in c.execute(text("PRAGMA table_info(projects)"))}
            speakers = c.execute(text("SELECT speakers FROM projects WHERE id = 1")).scalar()
        assert rows == {1: "detecting", 2: "ready"}
        assert {"speakers", "silences_path"} <= cols
        assert speakers == "{}"
        command.downgrade(cfg, "0001")
        with eng.begin() as c:
            assert c.execute(text("SELECT status FROM projects WHERE id = 1")).scalar() == "transcribed"
    finally:
        get_settings.cache_clear()
