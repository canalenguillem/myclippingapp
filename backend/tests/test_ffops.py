import pytest
from PIL import Image

from app.pipeline import ffops
from tests.media_helpers import make_source, probe, run


@pytest.fixture(scope="module")
def vertical(tmp_path_factory):
    d = tmp_path_factory.mktemp("ffops")
    out = d / "v.mp4"
    src = make_source(d / "h.mp4", 4)
    run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=1080:1920,fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out))
    return out


def test_thumbnail_is_a_jpeg_of_the_requested_width(vertical, tmp_path):
    out = ffops.make_thumbnail(vertical, tmp_path / "t.jpg", at=1.5)
    img = Image.open(out)
    assert img.format == "JPEG" and img.size == (540, 960)
    assert not list(tmp_path.glob("*.part*"))


def test_thumbnail_before_the_start_and_past_the_end(vertical, tmp_path):
    assert ffops.make_thumbnail(vertical, tmp_path / "a.jpg", at=-5).exists()      # se limita a 0
    with pytest.raises(ffops.FfopsError, match="miniatura"):
        ffops.make_thumbnail(vertical, tmp_path / "b.jpg", at=99)                  # más allá del final: no hay fotograma
    assert not (tmp_path / "b.jpg").exists()


def test_downscale_to_the_draft_size_keeps_audio_and_reports_progress(vertical, tmp_path):
    seen = []
    out = ffops.downscale(vertical, tmp_path / "d.mp4", width=540, height=960, duration=4, on_progress=seen.append)
    info = probe(out, "stream=codec_type,width,height")["streams"]
    assert [(s["codec_type"], s.get("width"), s.get("height")) for s in info] == [("video", 540, 960), ("audio", None, None)]
    assert seen and seen[-1] == 1.0


def test_downscale_cancel_and_errors(vertical, tmp_path):
    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    with pytest.raises(Stop):
        ffops.downscale(vertical, tmp_path / "c.mp4", width=540, height=960, duration=4, cancel_check=cancel)
    assert not (tmp_path / "c.mp4").exists() and not list(tmp_path.glob("c.part*"))
    bad = tmp_path / "x.mp4"
    bad.write_bytes("no soy un vídeo".encode())
    with pytest.raises(ffops.FfopsError, match="reducir"):
        ffops.downscale(bad, tmp_path / "o.mp4", width=540, height=960, duration=1)
