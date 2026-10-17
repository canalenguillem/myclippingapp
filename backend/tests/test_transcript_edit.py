import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Clip, Job, Project, ProjectStatus, User
from app.jobs import queue
from app.services import storage, transcription

PW = "una-clave-larga-1"


def base_data():
    words = [{"text": f"w{i}", "start": float(i), "end": i + 0.5, "confidence": 0.9, "speaker": "A" if i < 6 else "B"} for i in range(10)]
    return {"version": 2, "revision": 1, "language": "es", "text": " ".join(w["text"] for w in words), "words": words,
            "segments": [{"start": 0.0, "end": 5.5, "speaker": "A", "text": "w0 w1 w2 w3 w4 w5"},
                         {"start": 6.0, "end": 9.5, "speaker": "B", "text": "w6 w7 w8 w9"}]}


def _login(c, email="a@x.com"):
    assert c.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    return {"X-CSRF-Token": c.cookies.get("csrf")}


def _project(client, tmp_path, monkeypatch, email="a@x.com"):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    h = _login(client, email)
    db = client.session_factory()
    user = db.query(User).filter(User.email == email).one()
    p = Project(user_id=user.id, source_url="https://youtu.be/x", title="T", duration=100.0, status=ProjectStatus.READY,
                speakers={"A": {"name": "Ana", "role": "", "caption_style": "sans_upper", "is_source": False},
                          "B": {"name": "Bea", "role": "", "caption_style": "serif_italic", "is_source": True}})
    db.add(p)
    db.commit()
    folder = storage.project_dir(user.id, p.id)
    transcription.save_words(base_data(), folder / "words.json")
    p.words_path = storage.rel(folder / "words.json")
    db.commit()
    return h, db, p, folder / "words.json"


def words_of(path):
    return json.loads(path.read_text())


# --- corregir texto -----------------------------------------------------------------------------

def test_edit_words_keeps_times_speaker_and_confidence_and_bumps_revision(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = words_of(path)
    r = client.patch(f"/api/projects/{p.id}/transcript/words", json={"revision": 1, "edits": [{"index": 2, "text": "Nietos"}]}, headers=h)
    assert r.status_code == 200 and r.json() == {"revision": 2}
    after = words_of(path)
    assert after["revision"] == 2 and after["words"][2]["text"] == "Nietos"
    for b, a in zip(before["words"], after["words"]):
        assert {k: v for k, v in b.items() if k != "text"} == {k: v for k, v in a.items() if k != "text"}
    assert "Nietos" in after["text"] and after["segments"][0]["text"] == "w0 w1 Nietos w3 w4 w5"
    assert after["segments"][1]["text"] == "w6 w7 w8 w9"
    assert client.get(f"/api/projects/{p.id}/transcript").json()["revision"] == 2


def test_edit_refreshes_clip_transcript_and_emphasis_text(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    c = Clip(project_id=p.id, user_id=p.user_id, start=1.0, end=5.5, transcript="w1 w2 w3 w4 w5",
             emphasis_json=[{"start": 2.0, "text": "w2"}, {"start": 4.0, "text": "w4"}])
    db.add(c)
    db.commit()
    client.patch(f"/api/projects/{p.id}/transcript/words", json={"revision": 1, "edits": [{"index": 2, "text": "Sánchez"}]}, headers=h)
    db.refresh(c)
    assert c.transcript == "w1 Sánchez w3 w4 w5"
    assert c.emphasis_json == [{"start": 2.0, "text": "Sánchez"}, {"start": 4.0, "text": "w4"}]


@pytest.mark.parametrize("body,code", [
    ({"revision": 1, "edits": [{"index": 99, "text": "x"}]}, 422),
    ({"revision": 1, "edits": [{"index": 0, "text": ""}]}, 422),
    ({"revision": 1, "edits": [{"index": 0, "text": "dos palabras"}]}, 422),
    ({"revision": 1, "edits": [{"index": 0, "text": "a\nb"}]}, 422),
    ({"revision": 1, "edits": [{"index": 0, "text": "x" * 81}]}, 422),
    ({"revision": 1, "edits": [{"index": -1, "text": "x"}]}, 422),
    ({"revision": 1, "edits": []}, 422),
    ({"revision": 1, "edits": [{"index": 0, "text": "x", "start": 5.0}]}, 422),   # los tiempos no se editan
    ({"revision": 7, "edits": [{"index": 0, "text": "x"}]}, 409),                  # revisión antigua
])
def test_edit_words_rejects_bad_input_and_leaves_file_untouched(client, tmp_path, monkeypatch, body, code):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = path.read_text()
    assert client.patch(f"/api/projects/{p.id}/transcript/words", json=body, headers=h).status_code == code
    assert path.read_text() == before


def test_a_failing_edit_in_a_batch_applies_none_of_them(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = path.read_text()
    r = client.patch(f"/api/projects/{p.id}/transcript/words", json={"revision": 1, "edits": [{"index": 0, "text": "ok"}, {"index": 99, "text": "x"}]}, headers=h)
    assert r.status_code == 422 and path.read_text() == before


def test_edits_blocked_while_a_job_runs_and_isolated_between_users(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    body = {"revision": 1, "edits": [{"index": 0, "text": "x"}]}
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    for call in (other.patch(f"/api/projects/{p.id}/transcript/words", json=body, headers=hb),
                 other.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [{"start_index": 0, "end_index": 1, "speaker": "A"}]}, headers=hb),
                 other.put(f"/api/projects/{p.id}/speakers", json={"A": {}}, headers=hb)):
        assert call.status_code == 404
    queue.enqueue(db, p.user_id, "detect", {"project_id": p.id})
    assert client.patch(f"/api/projects/{p.id}/transcript/words", json=body, headers=h).status_code == 409
    assert client.patch(f"/api/projects/{p.id}/transcript/words", json=body).status_code == 403  # sin CSRF


# --- reasignar speakers -------------------------------------------------------------------------

def test_reassign_speaker_range_changes_only_the_speaker_and_regroups_segments(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = words_of(path)
    r = client.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [{"start_index": 3, "end_index": 7, "speaker": "B"}]}, headers=h)
    assert r.status_code == 200 and r.json()["revision"] == 2
    after = words_of(path)
    assert [w["speaker"] for w in after["words"]] == list("AAA") + list("BBBBB") + list("BB")
    for b, a in zip(before["words"], after["words"]):
        assert (b["text"], b["start"], b["end"], b["confidence"]) == (a["text"], a["start"], a["end"], a["confidence"])
    assert [(s["speaker"], s["text"]) for s in after["segments"]] == [("A", "w0 w1 w2"), ("B", "w3 w4 w5 w6 w7 w8 w9")]
    assert after["segments"][0]["start"] == 0.0 and after["segments"][1]["end"] == 9.5


@pytest.mark.parametrize("rng", [
    {"start_index": 0, "end_index": 3, "speaker": "Z"},     # speaker inexistente
    {"start_index": 5, "end_index": 2, "speaker": "A"},     # rango invertido
    {"start_index": 0, "end_index": 99, "speaker": "A"},    # fuera de rango
])
def test_reassign_rejects_bad_ranges(client, tmp_path, monkeypatch, rng):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = path.read_text()
    assert client.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [rng]}, headers=h).status_code == 422
    assert path.read_text() == before


def test_stale_revision_conflicts_between_two_editors(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    ok = client.patch(f"/api/projects/{p.id}/transcript/words", json={"revision": 1, "edits": [{"index": 0, "text": "a"}]}, headers=h)
    late = client.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [{"start_index": 0, "end_index": 1, "speaker": "B"}]}, headers=h)
    assert (ok.status_code, late.status_code) == (200, 409)


def test_concurrent_updates_with_the_same_revision_only_one_wins(tmp_path):
    path = tmp_path / "words.json"
    transcription.save_words(base_data(), path)
    results, barrier = [], threading.Barrier(8)

    def worker(i):
        barrier.wait()
        try:
            transcription.update_words(path, 1, lambda d: d["words"][0].update(text=f"t{i}"))
            results.append("ok")
        except transcription.RevisionConflict:
            results.append("conflict")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["conflict"] * 7 + ["ok"]
    assert words_of(path)["revision"] == 2


# --- fichas de speakers -------------------------------------------------------------------------

def test_put_speakers_replaces_cards_and_project_exposes_them(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    cards = {"A": {"name": "Soto Ivars", "role": "periodista", "caption_style": "sans_upper", "is_source": False},
             "B": {"name": "Gómez", "role": "expolítico", "caption_style": "serif_italic", "is_source": True}}
    assert client.put(f"/api/projects/{p.id}/speakers", json=cards, headers=h).status_code == 200
    assert client.get(f"/api/projects/{p.id}").json()["speakers"] == cards


@pytest.mark.parametrize("cards", [
    {"A": {"caption_style": "comic"}, "B": {}},                    # estilo inválido
    {"A": {"name": "x" * 81}, "B": {}},
    {"A": {"is_source": "quizá"}, "B": {}},
    {"A": {"bold": True}, "B": {}},                                # campo desconocido
    {"A b": {}, "B": {}}, {"A": {}},                               # etiqueta inválida / quita B, que tiene palabras
])
def test_put_speakers_validation(client, tmp_path, monkeypatch, cards):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    before = dict(p.speakers)
    assert client.put(f"/api/projects/{p.id}/speakers", json=cards, headers=h).status_code == 422
    db.refresh(p)
    assert p.speakers == before


def test_can_add_a_new_speaker_label_and_then_assign_words_to_it(client, tmp_path, monkeypatch):
    h, db, p, path = _project(client, tmp_path, monkeypatch)
    cards = {**p.speakers, "C": {"name": "Cris", "role": "", "caption_style": "sans_upper", "is_source": False}}
    assert client.put(f"/api/projects/{p.id}/speakers", json=cards, headers=h).status_code == 200
    r = client.patch(f"/api/projects/{p.id}/transcript/speakers", json={"revision": 1, "ranges": [{"start_index": 8, "end_index": 9, "speaker": "C"}]}, headers=h)
    assert r.status_code == 200 and words_of(path)["words"][9]["speaker"] == "C"
