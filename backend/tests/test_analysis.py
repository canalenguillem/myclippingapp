import numpy as np
import pytest

from app.pipeline import analysis
from tests.media_helpers import run

H, W = analysis.H, analysis.W
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def frames(n=40, text_rows=None, static_rows=None, toggle=True, moving=None):
    """Fotogramas 480x270 oscuros. `text_rows` (a, b): bloque blanco que aparece y desaparece; `static_rows`: bloque
    blanco permanente; `moving`: bloque blanco de 4 filas que recorre la imagen."""
    f = np.full((n, H, W, 3), 40, dtype=np.uint8)
    for i in range(n):
        if text_rows and (not toggle or i % 4 < 2):
            a, b = text_rows
            f[i, a:b, 40:230] = 255
        if static_rows:
            a, b = static_rows
            f[i, a:b, 40:230] = 255
        if moving:
            y = (i * moving) % (H - 8)
            f[i, y:y + 4, 100:170] = 255
    return f


def test_detects_text_that_appears_and_disappears_in_fixed_rows():
    r = analysis.detect_in_frames(frames(text_rows=(170, 180)), 0.5)
    assert r and r["y0"] <= 170 * 4 and r["y1"] >= 180 * 4 and r["y1"] - r["y0"] <= 60
    assert r["confidence"] >= 0.25


def test_static_white_areas_are_not_subtitles():
    assert analysis.detect_in_frames(frames(static_rows=(100, 140)), 0.5) is None
    assert analysis.detect_in_frames(frames(text_rows=(170, 180), toggle=False), 0.5) is None  # presente siempre: no cambia


def test_a_moving_object_is_not_a_subtitle():
    assert analysis.detect_in_frames(frames(moving=7), 0.5) is None


def test_nothing_to_find_or_too_few_frames():
    assert analysis.detect_in_frames(frames(), 0.5) is None
    assert analysis.detect_in_frames(frames(n=analysis.MIN_FRAMES - 1, text_rows=(170, 180)), 0.5) is None


def test_only_the_top_region_is_analyzed():
    f = frames(text_rows=(300, 310))        # filas 300–310 de 480: por debajo del corte al 50 %
    assert analysis.detect_in_frames(f, 0.5) is None
    assert analysis.detect_in_frames(f, 0.8) is not None


def test_green_subtitles_are_detected_too():
    f = frames(text_rows=None)
    for i in range(len(f)):
        if i % 4 < 2:
            f[i, 170:180, 40:230] = (30, 230, 30)
    assert analysis.detect_in_frames(f, 0.5) is not None


def test_tall_blocks_are_rejected_and_close_rows_are_merged():
    assert analysis.detect_in_frames(frames(text_rows=(100, 200)), 0.6) is None          # 100 filas = 400 px: no es un subtítulo
    f = frames()
    for i in range(len(f)):
        if i % 4 < 2:
            f[i, 170:174, 40:230] = 255
            f[i, 176:180, 40:230] = 255                                                   # hueco de 2 filas: se une
    r = analysis.detect_in_frames(f, 0.5)
    assert r and r["y0"] <= 170 * 4 and r["y1"] >= 180 * 4


def test_picks_the_most_persistent_block():
    f = frames()
    for i in range(len(f)):
        if i % 4 < 2:
            f[i, 170:180, 40:230] = 255           # aparece la mitad del tiempo
        if i % 4 < 3:
            f[i, 90:100, 40:230] = 255            # aparece más
    r = analysis.detect_in_frames(f, 0.5)
    assert r["y0"] <= 90 * 4 and r["y1"] >= 100 * 4


# --- con vídeo real (ffmpeg + drawtext) -------------------------------------------------------------------
SECONDS = 6


def video(path, drawtext, seconds=SECONDS):
    # 10 fps bastan: el análisis muestrea a 5 fps, y así los vídeos de prueba se generan rápido
    run("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x203040:s=1080x1920:r=10:d={seconds},noise=alls=30:allf=t,{drawtext}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return path


def subs(y, phrases):
    return ",".join(
        f"drawtext=fontfile={FONT}:text='{t}':fontsize=64:fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:y={y}:enable='between(t,{i * 1.0},{i * 1.0 + 0.8})'"
        for i, t in enumerate(phrases)
    )


PHRASES = ["HOLA MUNDO", "ESTO ES UNA PRUEBA", "OTRA FRASE MAS", "SE DICE ALGO", "FIN DEL TEXTO", "ULTIMA FRASE"]


def white_rows(video_path, t, tmp_path):
    """Filas del fotograma que tienen texto blanco, medidas directamente sobre la imagen (la verdad del terreno)."""
    from tests.media_helpers import frame_at

    img = frame_at(video_path, t, tmp_path)
    rows = [y for y in range(1920) if sum(1 for x in range(0, 1080, 3) if min(img.getpixel((x, y))) > 235) > 20]
    return min(rows), max(rows)


def test_real_video_with_burned_subtitles(tmp_path):
    v = video(tmp_path / "s.mp4", subs(700, PHRASES))
    top, bottom = white_rows(v, 0.4, tmp_path)           # donde está de verdad el texto en este vídeo
    r = analysis.detect_burned_subtitles(v, top_ratio=0.7, duration=SECONDS)
    assert r, "debía detectar los subtítulos quemados"
    assert r["y0"] <= top + 8 and r["y1"] >= bottom - 8, f"el texto está en {top}–{bottom} y se detectó {r}"
    assert r["y1"] - r["y0"] <= 160 and r["confidence"] >= 0.25


def test_real_video_without_subtitles_or_with_static_white_or_subs_below_the_split(tmp_path):
    assert analysis.detect_burned_subtitles(video(tmp_path / "n.mp4", "null"), top_ratio=0.7, duration=SECONDS) is None
    assert analysis.detect_burned_subtitles(video(tmp_path / "w.mp4", "drawbox=x=100:y=600:w=880:h=90:color=white:t=fill"), top_ratio=0.7, duration=SECONDS) is None
    assert analysis.detect_burned_subtitles(video(tmp_path / "b.mp4", subs(1500, PHRASES)), top_ratio=0.7, duration=SECONDS) is None


def test_a_broken_video_raises_a_clear_error(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes("no soy un vídeo".encode())
    with pytest.raises(analysis.AnalysisError, match="decodificar"):
        analysis.detect_burned_subtitles(bad, top_ratio=0.5, duration=SECONDS)
