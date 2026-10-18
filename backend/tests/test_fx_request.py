import pytest

from app.services.fx_request import HOOK_SECONDS, MAX_WORDS, build_fx_request, clip_words

W = lambda text, start, end, speaker="A": {"text": text, "start": start, "end": end, "speaker": speaker}


def test_clip_words_are_relative_to_the_clip_start_in_seconds():
    out = clip_words([W("antes", 5, 6), W("hola", 10.5, 11.0), W("mundo", 11.2, 11.6, "B"), W("después", 40, 41)], 10.0, 30.0)
    assert out == [{"text": "hola", "start": 0.5, "end": 1.0, "speaker": "A"}, {"text": "mundo", "start": 1.2, "end": 1.6, "speaker": "B"}]
    assert all(isinstance(v, float) for w in out for v in (w["start"], w["end"]))


def test_clip_words_clamp_to_the_clip_and_ignore_what_falls_outside():
    out = clip_words([W("borde", 9.97, 10.3), W("final", 29.8, 30.04), W("fuera", 30.5, 31)], 10.0, 30.0)
    assert [(w["text"], w["start"], w["end"]) for w in out] == [("borde", 0.0, 0.3), ("final", 19.8, 20.0)]


def test_clip_words_sanitize_text_and_speaker():
    out = clip_words([W("  ", 11, 12), W("x" * 200, 12, 13), {"text": "sin", "start": 13, "end": 14}, W("mal", 14, 15, "mal speaker!")], 10.0, 30.0)
    assert len(out[0]["text"]) == 80 and "speaker" not in out[1] and "speaker" not in out[2] and len(out) == 3


def test_clip_words_are_limited():
    many = [W("a", 10 + i * 0.001, 10 + i * 0.001 + 0.0005) for i in range(MAX_WORDS + 500)]
    assert len(clip_words(many, 10.0, 30.0)) == MAX_WORDS


def request(**kw):
    base = dict(video="u1/p1/clip_3/vertical_draft.mp4", output="u1/p1/clip_3/fx_full.mp4", quality="draft", duration=28.3333,
                top_ratio=0.5, words=[], speakers={}, hook="", preset="editorial", band=None)
    return build_fx_request(**{**base, **kw})


def test_request_shape_and_quality_mapping():
    r = request()
    assert r == {"video": "u1/p1/clip_3/vertical_draft.mp4", "output": "u1/p1/clip_3/fx_full.mp4", "quality": "draft", "fps": 30,
                 "duration": 28.333, "layout": {"mode": "split", "top_ratio": 0.5}, "words": [], "speakers": {}, "preset": "editorial", "sfx": True}
    assert request(quality="final")["quality"] == "standard"
    with pytest.raises(KeyError):
        request(quality="ultra")


def test_speakers_only_carry_the_contract_fields():
    r = request(speakers={"A": {"name": "Ana", "role": "periodista", "caption_style": "serif_italic", "is_source": True, "extra": 1},
                          "mal label!": {"name": "x"}, "B": {}})
    assert r["speakers"] == {
        "A": {"name": "Ana", "role": "periodista", "caption_style": "serif_italic", "is_source": True},
        "B": {"name": "", "role": "", "caption_style": "sans_upper", "is_source": False},
    }


def test_hook_and_band_are_optional():
    assert "hook" not in request(hook="   ") and "band" not in request()
    r = request(hook="  Nadie se lo esperaba ", band={"y0": 1380.0, "y1": 1470, "confidence": 0.8})
    assert r["hook"] == {"text": "Nadie se lo esperaba", "duration": HOOK_SECONDS}
    assert r["band"] == {"y0": 1380, "y1": 1470}  # sin `confidence`: el contrato es estricto
    assert len(request(hook="x" * 300)["hook"]["text"]) == 120


def test_cortinilla_and_outro_params_clamp_and_default():
    from app.services import fx_request as fx

    assert fx.cortinilla_params({}, {}, at=5.5, orbit=None) == {"at": 5.5, "duration": 3.6, "color": "#DA2E09", "title": "", "kicker": ""}
    c = fx.cortinilla_params({"duration": 0, "color": "#abcdef", "title": "x" * 99, "kicker": " k "}, {"primary": "#112233"}, at=5.0, orbit="u1/logo.png")
    assert c == {"at": 5.0, "duration": 1.0, "color": "#ABCDEF", "title": "x" * 40, "kicker": "k", "orbit": "u1/logo.png"}
    assert fx.cortinilla_params({"color": "no"}, {"primary": "#112233"}, at=1.0, orbit=None)["color"] == "#112233"
    o = fx.outro_params({"outro_duration": 50, "handle": "@a", "outro_text": "t", "subscribe": ""}, None)
    assert o == {"duration": 10.0, "color": "#DA2E09", "handle": "@a", "text": "t", "like": "ME GUSTA", "subscribe": "SUSCRÍBETE"}
    assert fx.outro_params({"outro_duration": "x"}, {})["duration"] == 2.5
