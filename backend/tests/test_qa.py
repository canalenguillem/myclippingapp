import subprocess

import pytest

from app.pipeline import ffops
from app.services import qa


def make(path, seconds=6, audio=True, black=False, volume="-6dB"):
    src = "color=c=black:s=360x640:r=30" if black else "testsrc2=size=360x640:rate=30"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{src}:d={seconds}" if black else f"{src}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-af", f"volume={volume}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


def levels(results):
    return {r["id"]: r["level"] for r in results}


def test_a_good_video_passes_every_check(tmp_path):
    v = make(tmp_path / "a.mp4")
    r = qa.check(v, expected_duration=6.0, beats=[{"type": "keyword", "at": 3.0, "lead": 0.5, "duration": 2.5}])
    assert set(levels(r).values()) == {"ok"} and qa.worst(r) == "ok"


def test_duration_audio_and_black_problems_are_reported(tmp_path):
    r = qa.check(make(tmp_path / "a.mp4", seconds=6), expected_duration=9.0, beats=[])
    assert levels(r)["duration"] == "error"
    assert levels(qa.check(make(tmp_path / "n.mp4", audio=False), expected_duration=6.0, beats=[]))["audio"] == "error"
    assert levels(qa.check(make(tmp_path / "q.mp4", volume="-70dB"), expected_duration=6.0, beats=[]))["audio"] == "error"
    assert levels(qa.check(make(tmp_path / "l.mp4", volume="+12dB"), expected_duration=6.0, beats=[]))["audio"] == "warn"
    assert levels(qa.check(make(tmp_path / "b.mp4", black=True), expected_duration=6.0, beats=[]))["black"] == "error"


def test_graphics_overlaps_short_windows_and_dropped_are_reported(tmp_path):
    v = make(tmp_path / "a.mp4")
    big = lambda at: {"type": "keyword", "at": at, "lead": 0.5, "duration": 2.5}  # noqa: E731
    r = qa.check(v, expected_duration=6.0, beats=[big(3.0), big(4.0), {"type": "emoji", "at": 3.5, "lead": 0.2, "duration": 0.5}], dropped=[{"beat": {}, "reason": "x"}])
    lv = levels(r)
    assert lv["overlap"] == "error" and lv["visible"] == "warn" and lv["dropped"] == "warn" and qa.worst(r) == "error"


def test_contact_sheet_is_one_jpeg_with_a_frame_every_few_seconds(tmp_path):
    v = make(tmp_path / "a.mp4", seconds=10)
    out = ffops.contact_sheet(v, tmp_path / "sheet.jpg", duration=10, cols=3, width=120)
    assert out.read_bytes()[:2] == b"\xff\xd8"
    with pytest.raises(ffops.FfopsError):
        ffops.contact_sheet(tmp_path / "no.mp4", tmp_path / "x.jpg")


def test_qa_endpoint_serves_the_report_and_the_contact_sheet_only_for_existing_renders(client, tmp_path, monkeypatch):
    import json
    from app.services import storage
    from tests.test_clips_api import _clip, _project
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    assert client.get(f"/api/clips/{c.id}/qa", headers=h).json() == {"draft": None, "final": None}
    folder = storage.project_dir(p.user_id, p.id) / f"clip_{c.id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "draft.mp4").write_bytes(b"x")
    (folder / "contact_draft.jpg").write_bytes(b"\xff\xd8")
    (folder / "qa_draft.json").write_text(json.dumps({"quality": "draft", "level": "warn", "checks": [{"id": "audio", "level": "warn", "message": "m"}]}))
    c.draft_path = storage.rel(folder / "draft.mp4")
    db.commit()
    out = client.get(f"/api/clips/{c.id}/qa", headers=h).json()
    assert out["final"] is None and out["draft"]["level"] == "warn" and out["draft"]["contact"]["url"].startswith("/api/media/")
    assert client.get(out["draft"]["contact"]["url"]).status_code == 200
