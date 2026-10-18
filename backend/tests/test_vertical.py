import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline import vertical

FF = "ffmpeg"


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


@pytest.fixture(scope="module")
def levels_src(tmp_path_factory):
    """10 s a 1280x720 y 25 fps (no 30), cada segundo de un gris distinto, con fotogramas clave cada 10 s y audio."""
    d = tmp_path_factory.mktemp("src")
    parts = []
    for i in range(10):
        f = d / f"l{i}.mp4"
        run(FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x{(20 + 22 * i):02x}{(20 + 22 * i):02x}{(20 + 22 * i):02x}:s=1280x720:r=25:d=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(f))
        parts.append(f)
    lst = d / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    out = d / "levels.mp4"
    run(FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-f", "lavfi", "-i", "sine=f=440:d=10",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-g", "250", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out))
    return out


@pytest.fixture(scope="module")
def halves_src(tmp_path_factory):
    """4 s a 1280x720: mitad izquierda roja y mitad derecha azul."""
    out = tmp_path_factory.mktemp("halves") / "halves.mp4"
    run(FF, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x720:d=4", "-f", "lavfi", "-i", "color=c=blue:s=640x720:d=4",
        "-filter_complex", "[0][1]hstack", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out))
    return out


def probe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def frame_at(video, t, tmp_path):
    png = tmp_path / f"f_{t}.png"
    run(FF, "-y", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png))
    return Image.open(png).convert("RGB")


def first_blue_column(img, y):
    for x in range(img.width):
        r, g, b = img.getpixel((x, y))
        if b > 150 and r < 100:
            return x
    return None


# --- filtro -------------------------------------------------------------------------------------

def test_build_filter_geometry():
    f = vertical.build_filter(0.5, "center", 1.0)
    assert "scale=1080:960:force_original_aspect_ratio=increase" in f and "crop=1080:960:(iw-ow)/2:(ih-oh)/2" in f
    assert "scale=1080:960:force_original_aspect_ratio=decrease,pad=1080:960" in f and f.endswith("fps=30[v]")
    z = vertical.build_filter(0.6, "left", 1.5)
    assert "scale=1620:1728" in z and "crop=1080:1152:0:" in z and "scale=1080:768:force_original_aspect_ratio=decrease" in z
    assert "crop=1080:960:iw-ow:" in vertical.build_filter(0.5, "right")
    d = vertical.build_filter(0.5, "center", 1.0, 540, 960)
    assert "crop=540:480" in d and "pad=540:480" in d


def test_top_height_is_always_even():
    for ratio in (0.33, 0.55, 0.7, 0.85):
        top = int(vertical.CANVAS_H * ratio)
        assert f"crop=1080:{top - top % 2}" in vertical.build_filter(ratio)


# --- vídeo real ---------------------------------------------------------------------------------

def test_output_is_vertical_30fps_with_dense_keyframes_and_audio(levels_src, tmp_path):
    out = vertical.make_vertical_clip(levels_src, 2.0, 6.0, tmp_path / "out.mp4")
    info = probe(out, "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate:format=duration")
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30/1")
    assert a["codec_name"] == "aac" and a["sample_rate"] == "48000"
    assert float(info["format"]["duration"]) == pytest.approx(4.0, abs=0.1)
    times = [float(f["pts_time"]) for f in probe_keyframes(out)]
    assert times and max(b - a for a, b in zip(times, times[1:])) <= 1.05  # el origen tenía uno cada 10 s


def probe_keyframes(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-skip_frame", "nokey", "-select_streams", "v", "-show_entries", "frame=pts_time", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["frames"]


def test_the_cut_is_frame_accurate_even_between_source_keyframes(levels_src, tmp_path):
    out = vertical.make_vertical_clip(levels_src, 3.5, 6.0, tmp_path / "cut.mp4")  # medio segundo después del segundo 3
    levels = lambda sec: 20 + 22 * sec
    for t, sec in ((0.25, 3), (0.75, 4), (1.75, 5)):
        luma = frame_at(out, t, tmp_path).convert("L").getpixel((540, 200))
        assert abs(luma - levels(sec)) <= 8, (t, luma, levels(sec))


def test_draft_is_540x960(levels_src, tmp_path):
    out = vertical.make_vertical_clip(levels_src, 0.0, 2.0, tmp_path / "d.mp4", draft=True)
    v = probe(out, "stream=width,height")["streams"][0]
    assert (v["width"], v["height"]) == (540, 960)


def test_focus_moves_the_top_crop_and_the_bottom_keeps_the_whole_scene(halves_src, tmp_path):
    cols = {}
    for focus in ("left", "center", "right"):
        out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / f"{focus}.mp4", focus=focus)
        img = frame_at(out, 0.3, tmp_path)
        cols[focus] = first_blue_column(img, 200)
        # abajo: escena completa (rojo a la izquierda, azul a la derecha) con barras negras arriba y abajo
        bottom_y = 960 + 480
        assert img.getpixel((100, bottom_y))[0] > 150 and img.getpixel((1000, bottom_y))[2] > 150
        assert sum(img.getpixel((540, 960 + 20))) < 40 and sum(img.getpixel((540, 1900))) < 40
    assert cols["left"] == pytest.approx(853, abs=10)
    assert cols["center"] == pytest.approx(540, abs=10)
    assert cols["right"] == pytest.approx(226, abs=10)


def test_zoom_narrows_what_the_top_crop_shows(halves_src, tmp_path):
    out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "z.mp4", focus="left", zoom=2.0)
    assert first_blue_column(frame_at(out, 0.3, tmp_path), 200) is None  # con zoom 2 el recorte solo ve la parte roja


def test_top_ratio_moves_the_split(halves_src, tmp_path):
    out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "r.mp4", top_ratio=0.7)
    img = frame_at(out, 0.3, tmp_path)
    top_h = 1344  # 1920 * 0.7: abajo quedan 576 px y la escena (1280x720) cabe exacta en alto, con barras negras a los lados
    assert img.getpixel((10, top_h - 10))[0] > 150      # justo encima del corte: recorte superior (rojo)
    assert sum(img.getpixel((10, top_h + 10))) < 40     # justo debajo: barra lateral negra de la escena completa


def test_source_without_audio_still_works(halves_src, tmp_path):
    out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "na.mp4")
    types = [s["codec_type"] for s in probe(out, "stream=codec_type")["streams"]]
    assert types == ["video"]


def test_progress_is_monotonic_and_reaches_one(levels_src, tmp_path):
    seen = []
    vertical.make_vertical_clip(levels_src, 0.0, 8.0, tmp_path / "p.mp4", on_progress=seen.append)
    assert seen and seen[-1] == 1.0 and all(b >= a for a, b in zip(seen, seen[1:])) and 0.0 <= seen[0] <= 1.0


def test_cancel_kills_ffmpeg_and_leaves_no_file(levels_src, tmp_path):
    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    out = tmp_path / "c.mp4"
    with pytest.raises(Stop):
        vertical.make_vertical_clip(levels_src, 0.0, 10.0, out, cancel_check=cancel)
    assert not out.exists() and not list(tmp_path.glob("c.part*"))


def test_validation_and_ffmpeg_errors(levels_src, tmp_path):
    with pytest.raises(vertical.VerticalError, match="No existe"):
        vertical.make_vertical_clip(tmp_path / "no.mp4", 0, 1, tmp_path / "x.mp4")
    for kw, msg in (({"start": 5, "end": 5}, "posterior"), ({"start": -1, "end": 3}, "posterior"), ({"start": 0, "end": 3, "top_ratio": 0.1}, "top_ratio")):
        a = {"start": kw.pop("start"), "end": kw.pop("end")}
        with pytest.raises(vertical.VerticalError, match=msg):
            vertical.make_vertical_clip(levels_src, a["start"], a["end"], tmp_path / "x.mp4", **kw)
    with pytest.raises(vertical.VerticalError, match="Encuadre"):
        vertical.make_vertical_clip(levels_src, 0, 1, tmp_path / "x.mp4", focus="follow")
    bad = tmp_path / "corrupto.mp4"
    bad.write_bytes("no soy un vídeo".encode())
    with pytest.raises(vertical.VerticalError, match="ffmpeg falló"):
        vertical.make_vertical_clip(bad, 0, 1, tmp_path / "x.mp4")
    assert not (tmp_path / "x.mp4").exists()


# --- pantalla completa con la parte de abajo difuminada --------------------------------------

def test_full_layout_has_a_sharp_top_and_a_blurred_darker_bottom(halves_src, tmp_path):
    out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "full.mp4", layout="full", top_ratio=0.66)
    info = probe(out, "stream=width,height,r_frame_rate")["streams"]
    v = next(s for s in info if s.get("width"))
    assert (v["width"], v["height"], v["r_frame_rate"]) == (1080, 1920, "30/1")
    img = frame_at(out, 0.3, tmp_path)
    top_red, top_blue = img.getpixel((530, 300)), img.getpixel((550, 300))
    assert top_red[0] > 150 and top_blue[2] > 150, "arriba el corte rojo/azul es nítido"
    assert abs(top_red[0] - top_blue[0]) > 150
    low_a, low_b = img.getpixel((530, 1700)), img.getpixel((550, 1700))
    assert abs(low_a[0] - low_b[0]) < 70, "abajo el borde está difuminado"
    assert img.getpixel((100, 1700))[0] < top_red[0] - 20, "abajo está oscurecido"
    assert img.getpixel((100, 1700))[0] > 60 and img.getpixel((1000, 1700))[2] > 60, "pero sigue siendo el mismo vídeo"


def test_full_layout_respects_focus_zoom_and_ratio_and_the_draft_size(halves_src, tmp_path):
    # a 66 % el vídeo se escala a 1266 px de alto (2250 de ancho): el corte rojo/azul cae en x = 1125, fuera de un recorte de 1080
    cols = {}
    for focus in ("left", "center", "right"):
        out = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / f"{focus}.mp4", layout="full", focus=focus, top_ratio=0.66)
        cols[focus] = first_blue_column(frame_at(out, 0.3, tmp_path), 200)
    assert cols["left"] is None and cols["right"] == 0 and cols["center"] == pytest.approx(540, abs=10)
    draft = vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "d.mp4", layout="full", top_ratio=0.66, draft=True)
    v = next(s for s in probe(draft, "stream=width,height")["streams"] if s.get("width"))
    assert (v["width"], v["height"]) == (540, 960)
    img = frame_at(draft, 0.3, tmp_path)
    assert abs(img.getpixel((265, 150))[0] - img.getpixel((275, 150))[0]) > 150   # nítido arriba (66 % de 960 = 633 px)
    assert abs(img.getpixel((265, 800))[0] - img.getpixel((275, 800))[0]) < 70    # difuminado abajo


def test_unknown_layout_is_rejected(halves_src, tmp_path):
    with pytest.raises(vertical.VerticalError, match="Diseño no válido"):
        vertical.make_vertical_clip(halves_src, 0.0, 1.0, tmp_path / "x.mp4", layout="facecam")
