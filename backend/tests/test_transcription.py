import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import Job, Project, ProjectStatus
from app.jobs import handlers, queue
from app.jobs.handlers import JobContext
from app.services import speakers, storage, transcription, video_download

PW = "una-clave-larga-1"


def W(text, start_ms, end_ms, speaker=None, conf=0.9):
    return NS(text=text, start=start_ms, end=end_ms, confidence=conf, speaker=speaker)


def U(speaker, start_ms, end_ms, text):
    return NS(speaker=speaker, start=start_ms, end=end_ms, text=text)


def test_build_transcript_converts_ms_to_seconds_and_keeps_speakers():
    tx = NS(
        text="hola que tal bien",
        words=[W("hola", 100, 400, "A"), W("que", 400, 600, "A"), W("tal", 600, 900, "A"), W("bien", 1200, 1500, "B")],
        utterances=[U("A", 100, 900, "hola que tal"), U("B", 1200, 1500, "bien")],
        json_response={"language_code": "es"},
    )
    data = transcription.build_transcript(tx)
    assert data["version"] == 2 and data["revision"] == 1 and data["language"] == "es"
    assert data["words"][0] == {"text": "hola", "start": 0.1, "end": 0.4, "confidence": 0.9, "speaker": "A"}
    assert all(isinstance(w["start"], float) for w in data["words"])
    assert data["segments"] == [
        {"start": 0.1, "end": 0.9, "speaker": "A", "text": "hola que tal"},
        {"start": 1.2, "end": 1.5, "speaker": "B", "text": "bien"},
    ]


def test_segments_cover_exactly_the_words_of_their_speaker():
    tx = NS(
        text="a b c d", json_response={},
        words=[W("a", 0, 100, "A"), W("b", 100, 200, "A"), W("c", 300, 400, "B"), W("d", 400, 500, "A")],
        utterances=[U("A", 0, 200, "a b"), U("B", 300, 400, "c"), U("A", 400, 500, "d")],
    )
    data = transcription.build_transcript(tx)
    for seg in data["segments"]:
        inside = [w for w in data["words"] if w["start"] >= seg["start"] and w["end"] <= seg["end"]]
        assert {w["speaker"] for w in inside} == {seg["speaker"]}
        assert " ".join(w["text"] for w in inside) == seg["text"]


def test_words_without_speaker_take_it_from_the_overlapping_utterance():
    tx = NS(text="a b", json_response={}, words=[W("a", 0, 100), W("b", 1000, 1100)],
            utterances=[U("A", 0, 500, "a"), U("B", 900, 1200, "b")])
    assert [w["speaker"] for w in transcription.build_transcript(tx)["words"]] == ["A", "B"]


def test_segments_derived_from_words_when_no_utterances():
    tx = NS(text="a b c", json_response={}, utterances=None,
            words=[W("a", 0, 100, "A"), W("b", 100, 200, "A"), W("c", 200, 300, "B")])
    segs = transcription.build_transcript(tx)["segments"]
    assert [(s["speaker"], s["text"]) for s in segs] == [("A", "a b"), ("B", "c")]
    assert segs[0]["end"] == 0.2


def test_empty_transcript_raises():
    with pytest.raises(transcription.TranscriptionError):
        transcription.build_transcript(NS(text="", words=[], utterances=[], json_response={}))


def test_has_speakers_false_for_legacy_v1():
    assert transcription.has_speakers({"words": [{"text": "x", "start": 0, "end": 1}]}) is False
    assert transcription.has_speakers({"words": [{"text": "x", "start": 0, "end": 1, "speaker": "A"}]}) is True
    assert transcription.has_speakers({"words": []}) is False


def test_save_words_is_atomic_and_leaves_no_tmp(tmp_path):
    f = tmp_path / "words.json"
    transcription.save_words({"a": 1}, f)
    transcription.save_words({"a": 2}, f)
    assert json.loads(f.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["words.json"]


def test_merge_speakers_keeps_user_edits_and_adds_new_labels():
    existing = {"A": {"name": "Ana", "role": "periodista", "caption_style": "serif_italic", "is_source": True}}
    merged = speakers.merge_speakers(existing, ["A", "B"])
    assert merged["A"]["name"] == "Ana" and merged["A"]["is_source"] is True
    assert merged["B"] == speakers.default_speaker()
    assert "A" in speakers.merge_speakers(existing, ["B"])  # no borra fichas que desaparecen
    assert existing == {"A": {"name": "Ana", "role": "periodista", "caption_style": "serif_italic", "is_source": True}}


# --- re-transcribir -----------------------------------------------------------------------------

def _login(client, email="a@x.com"):
    assert client.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    return {"X-CSRF-Token": client.cookies.get("csrf")}


def _project_with_words(client, tmp_path, monkeypatch, revision=1):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    h = _login(client)
    pid = client.post("/api/projects", json={"source_url": "https://youtu.be/abc"}, headers=h).json()["id"]
    db = client.session_factory()
    queue.cancel(db, db.query(Job).first())  # el ingest encolado no interesa
    p = db.get(Project, pid)
    folder = storage.project_dir(p.user_id, p.id)
    (folder / "source.mp4").write_bytes(b"v")
    (folder / "audio.mp3").write_bytes(b"a")
    transcription.save_words({"version": 1, "revision": revision, "language": "es", "text": "x",
                              "words": [{"text": "x", "start": 0.0, "end": 1.0, "confidence": 1}]}, folder / "words.json")
    p.video_path, p.words_path, p.status = storage.rel(folder / "source.mp4"), storage.rel(folder / "words.json"), ProjectStatus.READY
    db.commit()
    return h, pid, db


def test_transcript_endpoint_flags_legacy_without_speakers(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch)
    assert client.get(f"/api/projects/{pid}/transcript").json()["has_speakers"] is False


def test_retranscribe_enqueues_transcribe_only_job(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch)
    r = client.post(f"/api/projects/{pid}/retranscribe", json={"language": "es", "speakers_expected": 2}, headers=h)
    assert r.status_code == 202
    job = db.get(Job, r.json()["job_id"])
    assert job.payload == {"project_id": pid, "transcribe_only": True, "language": "es", "speakers_expected": 2}
    # mientras corre, no se puede lanzar otro ni borrar el proyecto
    assert client.post(f"/api/projects/{pid}/retranscribe", json={}, headers=h).status_code == 409
    assert client.delete(f"/api/projects/{pid}", headers=h).status_code == 409


def test_retranscribe_refuses_to_overwrite_manual_edits_without_force(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch, revision=3)
    assert client.post(f"/api/projects/{pid}/retranscribe", json={}, headers=h).status_code == 409
    assert client.post(f"/api/projects/{pid}/retranscribe", json={"force": True}, headers=h).status_code == 202


def test_retranscribe_isolated_between_users(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch)
    other = TestClient(client.app)
    hb = _login(other, "b@x.com")
    assert other.post(f"/api/projects/{pid}/retranscribe", json={}, headers=hb).status_code == 404


def test_retranscribe_job_skips_download_and_merges_speakers(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch)
    p = db.get(Project, pid)
    p.speakers = {"A": {"name": "Ana", "role": "", "caption_style": "serif_italic", "is_source": True}}
    db.commit()
    jid = client.post(f"/api/projects/{pid}/retranscribe", json={}, headers=h).json()["job_id"]
    job = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=job.id, user_id=job.user_id, log_file=tmp_path / "logs" / "j.log")

    def boom(*a, **k):
        raise AssertionError("no debe descargar")

    from app.services import silences
    monkeypatch.setattr(silences, "detect_silences", lambda audio: [])  # proyecto legacy: sin silences.json
    monkeypatch.setattr(video_download, "download", boom)
    monkeypatch.setattr(video_download, "probe", boom)
    monkeypatch.setattr(transcription, "transcribe_words", lambda audio, lang, n=None: {
        "version": 2, "revision": 1, "language": "es", "text": "x", "segments": [],
        "words": [{"text": "x", "start": 0.0, "end": 1.0, "confidence": 1, "speaker": s} for s in ("A", "B")]})
    handlers.ingest(ctx, job.payload)
    p = db.get(Project, pid)
    assert p.status is ProjectStatus.READY  # vuelve al estado que tenía
    assert p.speakers["A"]["name"] == "Ana" and p.speakers["B"]["name"] == ""
    assert p.silences_path  # los legacy se miden al re-transcribir
    assert client.get(f"/api/projects/{pid}/transcript").json()["has_speakers"] is True


def test_failed_retranscribe_restores_previous_status(client, tmp_path, monkeypatch):
    h, pid, db = _project_with_words(client, tmp_path, monkeypatch)
    client.post(f"/api/projects/{pid}/retranscribe", json={}, headers=h)
    job = queue.claim_next(db, "w")
    ctx = JobContext(db=db, job_id=job.id, user_id=job.user_id, log_file=tmp_path / "logs" / "j.log")

    def fail(*a, **k):
        raise transcription.TranscriptionError("AssemblyAI caído")

    from app.services import silences
    monkeypatch.setattr(silences, "detect_silences", lambda audio: [])
    monkeypatch.setattr(transcription, "transcribe_words", fail)
    with pytest.raises(transcription.TranscriptionError):
        handlers.ingest(ctx, job.payload)
    p = db.get(Project, pid)
    assert p.status is ProjectStatus.READY and "AssemblyAI caído" in p.error
