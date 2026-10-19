import shutil
import subprocess

import pytest

from app.pipeline import focus, vertical

SPEAKERS = {"A": {"focus_x": 0.0}, "B": {"focus_x": 1.0}}


def w(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker, "text": "x"}


def test_track_follows_speakers_and_ignores_interjections():
    words = [w(0, 3, "A"), w(3, 3.3, "B"), w(3.3, 6, "A"), w(6, 9, "B")]
    assert focus.build_track(words, SPEAKERS) == [(0.0, 0.0), (6.0, 1.0)]


def test_track_without_speakers_is_centered():
    assert focus.build_track([], SPEAKERS) == [(0.0, 0.5)]
    assert focus.build_track([w(0, 1, "Z")], SPEAKERS) == [(0.0, 0.5)]


def test_position_is_smooth_and_reaches_target():
    track = [(0.0, 0.0), (4.0, 1.0)]
    assert focus.position_at(track, 3.9) == 0.0
    assert 0.2 < focus.position_at(track, 4.125) < 0.8
    assert focus.position_at(track, 5.0) == pytest.approx(1.0)


def test_unknown_focus_rejected():
    with pytest.raises(vertical.VerticalError):
        vertical.build_filter(focus="nope")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg")
def test_ffmpeg_crop_follows_track(tmp_path):
    src = tmp_path / "src.mp4"
    # 1280x360: mitad izquierda roja, derecha azul
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=6",
                    "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=6", "-filter_complex", "[0][1]hstack",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    out = tmp_path / "out.mp4"
    vertical.make_vertical_clip(src, 0, 6, out, top_ratio=0.5, focus="speaker", track=[(0.0, 0.0), (3.0, 1.0)], draft=True)

    def pixel(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-vf", "crop=4:4:270:100",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        return raw[0], raw[2]

    r0, b0 = pixel(1.0)
    r1, b1 = pixel(5.0)
    assert r0 > 150 and b0 < 100
    assert b1 > 150 and r1 < 100


def test_track_from_asd_uses_face_centers_and_holds_on_silence():
    data = {"speakers": [{"id": 0, "center_norm": [0.2, 0.5]}, {"id": 1, "center_norm": [0.8, 0.5]}],
            "segments": [{"start": 0, "end": 3, "speaker": 0}, {"start": 3, "end": 3.4, "speaker": 1},
                         {"start": 3.4, "end": 5, "speaker": -1}, {"start": 5, "end": 6, "speaker": 0},
                         {"start": 6, "end": 9, "speaker": 1}]}
    assert focus.track_from_asd(data) == [(0.0, 0.2), (6.0, 0.8)]
    assert focus.track_from_asd({}) == [(0.0, 0.5)]


def test_asd_client_without_url_returns_none(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services import asd_client
    monkeypatch.setenv("ASD_WORKER_URL", "")
    get_settings.cache_clear()
    assert not asd_client.configured()
    assert asd_client.fetch_segments(tmp_path / "x.mp4") is None
    cache = tmp_path / "c.json"
    cache.write_text('{"speakers": []}')
    assert asd_client.fetch_segments(tmp_path / "x.mp4", cache) == {"speakers": []}
