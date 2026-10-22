import subprocess

import numpy as np
import pytest

from app.pipeline import screens, vertical
from app.services import storage
from tests.test_clips_api import _clip, _project


def frame(page=None, color=(90, 70, 50)):
    """Fotograma sintético: webcam marrón; `page=(x0, x1)` en fracciones: columna de página blanca con una banda de texto."""
    f = np.zeros((screens.H, screens.W, 3), dtype=np.uint8)
    f[:] = color
    if page:
        x0, x1 = int(page[0] * screens.W), int(page[1] * screens.W)
        f[:, x0:x1] = 250
        f[40:50, x0 + 5:x1 - 5] = 30                                     # una línea de texto oscuro
    return f


def test_page_box_finds_a_white_page_and_ignores_a_plain_webcam():
    assert screens.page_box(frame()) is None
    x, y, w, h = screens.page_box(frame((0.36, 1.0)))
    assert (round(x, 2), round(w, 2)) == (0.36, 0.64) and y == 0 and h == 1.0
    assert screens.page_box(frame((0.9, 1.0))) is None                          # una franja estrecha no es una pantalla
    assert screens.page_box(frame((0.69, 1.0))) is None                         # ni una de menos del 40 % del ancho (un fondo blanco de rueda de prensa)


def test_two_white_margins_around_a_dark_embedded_video_are_one_screen():
    f = frame((0.36, 1.0))
    f[:, int(0.47 * screens.W):int(0.7 * screens.W)] = (20, 20, 20)           # un vídeo oscuro en medio
    x, y, w, h = screens.page_box(f)
    assert round(x, 2) == 0.36 and round(x + w, 2) == 1.0


def test_segments_need_two_seconds_fill_short_gaps_and_use_the_median_box():
    page = (0.36, 0.0, 0.64, 1.0)
    boxes = [None] * 4 + [page] * 3 + [None] * 4 + [page] * 8 + [None, None, page, page] + [None] * 6            # 2 fps
    out = screens.segments_from_boxes(boxes)
    assert len(out) == 1                                                                                          # el primer tramo (1,5 s) se descarta
    assert out[0]["start"] == 5.5 and out[0]["end"] == 11.5 and out[0]["w"] > 0.63                               # el hueco de 1 s se rellena
    assert screens.segments_from_boxes([page] * 3 + [None] * 10) == []                                           # 1,5 s: no da tiempo a leerlo


def make_video(path, seconds=8):
    """Vídeo de prueba 640×360: 3 s de webcam, 3 s con una página blanca a la derecha (x ≥ 0,36), 2 s de webcam."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x5a4632:s=640x360:r=10:d={seconds}",
           "-vf", "drawbox=x=230:y=0:w=410:h=360:color=white:t=fill:enable='between(t,3,6)',drawbox=x=250:y=60:w=300:h=24:color=black:t=fill:enable='between(t,3,6)'",
           "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def test_detect_on_a_real_video_gives_the_expected_range(tmp_path):
    video = make_video(tmp_path / "v.mp4")
    out = screens.detect(video, 0, 8)
    assert len(out) == 1
    r = out[0]
    assert abs(r["start"] - 3.0) <= 0.6 and abs(r["end"] - 6.0) <= 0.6 and abs(r["x"] - 0.36) < 0.04 and r["w"] > 0.6
    shifted = screens.detect(video, 2, 8)
    assert abs(shifted[0]["start"] - 3.0) <= 0.6                                    # los tiempos son del vídeo original, no del recorte


def test_the_filter_overlays_the_fitted_region_only_during_the_range(tmp_path):
    video = make_video(tmp_path / "v.mp4")
    for layout in ("split", "full"):
        out = tmp_path / f"{layout}.mp4"
        vertical.make_vertical_clip(video, 0, 8, out, layout=layout, top_ratio=0.5 if layout == "split" else 0.65, draft=True,
                                    screens=[{"start": 3.0, "end": 6.0, "x": 0.36, "y": 0.0, "w": 0.64, "h": 1.0}])

        def sample(t):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-vf", "crop=4:4:270:120",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
            return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).mean(axis=0)

        assert sample(1.0)[0] < 130                       # fuera del tramo: el recorte normal (marrón)
        assert sample(4.5).min() > 200                    # durante el tramo: la página blanca ajustada al ancho
        assert sample(7.0)[0] < 130


def test_clip_patch_validates_and_sorts_screen_ranges_and_detect_endpoint_needs_the_source(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    c = _clip(db, p, 10.0, 40.0)
    good = [{"start": 30.0, "end": 36.0, "x": 0.36, "y": 0.0, "w": 0.64, "h": 1.0}, {"start": 12.0, "end": 18.5, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]
    out = client.patch(f"/api/clips/{c.id}", json={"screen_ranges": good}, headers=h).json()["screen_ranges"]
    assert [r["start"] for r in out] == [12.0, 30.0]
    for bad in ({**good[0], "end": 29.0}, {**good[0], "x": 0.5, "w": 0.6}, {**good[0], "w": 0.01}, {**good[0], "extra": 1}):
        assert client.patch(f"/api/clips/{c.id}", json={"screen_ranges": [bad]}, headers=h).status_code == 422, bad
    assert client.patch(f"/api/clips/{c.id}", json={"screen_ranges": []}, headers=h).json()["screen_ranges"] == []
    r = client.post(f"/api/clips/{c.id}/screens/detect", json={}, headers=h)
    assert r.status_code == 409 and "vídeo original" in r.json()["detail"]
    video = make_video(storage.project_dir(p.user_id, p.id) / "source.mp4", seconds=60)
    p.video_path = storage.rel(video)
    db.commit()
    assert client.post(f"/api/clips/{c.id}/screens/detect", json={"start": 0, "end": 8}, headers=h).json()["ranges"][0]["start"] > 2.0


def test_a_plain_white_backdrop_without_text_is_not_a_screen(tmp_path):
    """Falso positivo real (clip 207): el fondo blanco de una rueda de prensa tiene la forma de una página pero no tiene texto."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x5a4632:s=640x360:r=10:d=8", "-vf",
           "drawbox=x=160:y=0:w=480:h=360:color=white:t=fill:enable='between(t,2,7)'", "-pix_fmt", "yuv420p", str(tmp_path / "w.mp4")]
    subprocess.run(cmd, check=True)
    assert screens.detect(tmp_path / "w.mp4", 0, 8) == []
    assert screens.ink_fraction(frame((0.36, 1.0)), (0.36, 0.0, 0.64, 1.0)) > screens.MIN_INK
    assert screens.ink_fraction(np.full((screens.H, screens.W, 3), 250, dtype=np.uint8), (0.36, 0.0, 0.64, 1.0)) == 0
