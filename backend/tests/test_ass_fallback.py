import pytest

from app.pipeline import ass_fallback as ass
from tests.media_helpers import frame_at, make_source, probe, run

W = lambda text, start, end, speaker="A": {"text": text, "start": start, "end": end, "speaker": speaker}


def test_group_phrases_follows_the_same_rules_as_the_render_service():
    g = ass.group_phrases([W("a", 0, .1), W("b", .15, .25), W("c", .3, .4), W("d", .45, .55), W("e", .6, .7)], 5)
    assert [len(x) for x in g] == [4, 1]
    assert [len(x) for x in ass.group_phrases([W("Hola,", 0, .3), W("amigo", .35, .6)], 5)] == [1, 1]
    assert [len(x) for x in ass.group_phrases([W("a", 0, .3), W("b", .9, 1.2)], 5)] == [1, 1]
    assert [len(x) for x in ass.group_phrases([W("a", 0, .3, "A"), W("b", .35, .6, "B")], 5)] == [1, 1]
    assert [len(x) for x in ass.group_phrases([W("constitucional", 0, .5), W("tribunal", .55, 1), W("de", 1.05, 1.2)], 5)] == [1, 2]
    assert [w["text"] for g in ass.group_phrases([W("a", 0, .3), W("fuera", 6, 6.3)], 5) for w in g] == ["a"]


def test_ass_time_format():
    assert ass._ass_time(0) == "0:00:00.00" and ass._ass_time(61.256) == "0:01:01.26" and ass._ass_time(3725.5) == "1:02:05.50"
    assert ass._ass_time(-3) == "0:00:00.00"


def test_bgr_color_order():
    assert ass._bgr("#DA2E09") == "&H00092EDA"


def test_build_ass_structure_position_and_karaoke():
    text = ass.build_ass([W("Hola", 0.5, 0.9), W("mundo", 1.0, 1.5)], duration=5, top_ratio=0.7)
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text and "Style: Karaoke,DejaVu Sans,64," in text
    line = [l for l in text.splitlines() if l.startswith("Dialogue")][0]
    assert "0:00:00.50,0:00:01.75" in line               # termina 0,25 s después de la última palabra
    assert "\\an5\\pos(540,1344)" in line                 # centrado en el corte (1920 * 0,7)
    assert "{\\kf40}HOLA {\\kf50}MUNDO" in line           # mayúsculas y duración de cada palabra en centésimas


def test_build_ass_escapes_override_characters_and_shrinks_long_phrases():
    text = ass.build_ass([W("{\\an1}hack", 0, 1), W("x" * 22, 1.1, 2)], duration=5)
    assert "{\\an1}" not in text and "HACK" in text
    sizes = [int(l.split("\\fs")[1].split("}")[0]) for l in text.splitlines() if l.startswith("Dialogue")]
    assert sizes[0] == 64 and sizes[1] < 64


def test_build_ass_scales_with_the_canvas():
    text = ass.build_ass([W("Hola", 0, 1)], duration=3, width=540, height=960)
    assert "PlayResX: 540" in text and "\\pos(270,480)" in text and "Style: Karaoke,DejaVu Sans,32," in text


def test_filter_escape():
    assert ass._filter_escape("/a/b:c'd\\e.ass") == "/a/b\\:c\\'d\\\\e.ass"


@pytest.fixture(scope="module")
def vertical_src(tmp_path_factory):
    d = tmp_path_factory.mktemp("assv")
    src = make_source(d / "h.mp4", 3)
    out = d / "v.mp4"
    run("ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=540:960,fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out))
    return out


def test_burn_subtitles_draws_text_at_the_split_and_keeps_audio(vertical_src, tmp_path):
    out = ass.burn_subtitles(vertical_src, [W("Hola", 0.3, 0.9), W("mundo", 1.0, 1.6)], tmp_path / "o.mp4", duration=3, width=540, height=960, top_ratio=0.5, draft=True)
    types = [s["codec_type"] for s in probe(out, "stream=codec_type")["streams"]]
    assert types == ["video", "audio"]
    img = frame_at(out, 1.1, tmp_path)
    base = frame_at(vertical_src, 1.1, tmp_path, "base")
    bright = lambda im, y0, y1: sum(1 for x in range(0, 540, 2) for y in range(y0, y1, 2) if sum(im.getpixel((x, y))) > 600)
    assert bright(img, 450, 510) > 30 and bright(base, 450, 510) == 0   # texto blanco junto al corte (y = 480)
    assert bright(img, 100, 200) == 0                                   # y nada lejos de él
    assert not list(tmp_path.glob("*.part*")) and not list(tmp_path.glob("*.ass"))


def test_burn_subtitles_reports_progress_and_can_be_cancelled(vertical_src, tmp_path):
    seen = []
    ass.burn_subtitles(vertical_src, [W("Hola", 0.3, 0.9)], tmp_path / "p.mp4", duration=3, width=540, height=960, top_ratio=0.5, draft=True, on_progress=seen.append)
    assert seen and seen[-1] == 1.0

    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    out = tmp_path / "c.mp4"
    with pytest.raises(Stop):
        ass.burn_subtitles(vertical_src, [W("Hola", 0.3, 0.9)], out, duration=3, width=540, height=960, top_ratio=0.5, cancel_check=cancel)
    assert not out.exists() and not list(tmp_path.glob("c.part*"))


def test_burn_subtitles_fails_cleanly_on_a_bad_video(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes("no soy un vídeo".encode())
    with pytest.raises(ass.AssError, match="subtítulos"):
        ass.burn_subtitles(bad, [W("a", 0, 1)], tmp_path / "o.mp4", duration=1, width=540, height=960, top_ratio=0.5)
    assert not (tmp_path / "o.mp4").exists()


def test_a_phrase_never_overlaps_the_next_one():
    words = [{"text": "uno,", "start": 0.0, "end": 0.7, "speaker": "A"}, {"text": "dos.", "start": 0.72, "end": 1.2, "speaker": "A"},
             {"text": "tres", "start": 1.25, "end": 1.6, "speaker": "A"}]
    rows = [l.split(",")[1:3] for l in ass.build_ass(words, duration=3.0).splitlines() if l.startswith("Dialogue")]
    assert len(rows) >= 2
    for (_, end), (start, _) in zip(rows, rows[1:]):
        assert end <= start
