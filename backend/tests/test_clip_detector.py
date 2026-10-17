import json
from types import SimpleNamespace as NS

import pytest

from app.config import get_settings
from app.services import clip_detector as cd

# Transcripción sintética: 40 frases de 6 palabras. Frase k empieza en k*3.2 s y acaba en k*3.2+2.9 s
# (palabras de 0,4 s con 0,1 s entre ellas, 0,3 s entre frases).
SENTENCES = [f"Sentencia{k} uno dos tres cuatro cinco." for k in range(40)]
SENTENCES[3] = "Pedro Sánchez anunció ayer quinientos millones."


def make_words(sentences, speaker="A", t0=0.0):
    words, t = [], t0
    for s in sentences:
        for w in s.split():
            words.append({"text": w, "start": round(t, 3), "end": round(t + 0.4, 3), "confidence": 1.0, "speaker": speaker})
            t += 0.5
        t += -0.1 + 0.3  # la última palabra no deja su hueco de 0,1 s; entre frases hay 0,3 s
    return words


def tr(sentences=SENTENCES, **kw):
    return {"words": make_words(sentences, **kw)}


def cue_start(k):
    return round(k * 3.2, 3)


def cue_end(k):
    return round(k * 3.2 + 2.9, 3)


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return NS(choices=[NS(message=NS(content=r if isinstance(r, str) else json.dumps(r)))])


def clip_json(start, end, **kw):
    return {"start": start, "end": end, "title": "t", "reason": "r", "score": 80, "hook": "h",
            "emphasis_words": [], "parts": [], **kw}


# --- frases -------------------------------------------------------------------------------------

def test_cue_times_match_the_synthetic_layout():
    cues = cd.build_cues(make_words(SENTENCES))
    assert len(cues) == 40
    assert cues[2].start == pytest.approx(cue_start(2)) and cues[2].end == pytest.approx(cue_end(2))


def test_cues_cover_every_word_exactly_once():
    words = make_words(SENTENCES)
    cues = cd.build_cues(words)
    assert cues[0].lo == 0 and cues[-1].hi == len(words) - 1
    assert all(b.lo == a.hi + 1 for a, b in zip(cues, cues[1:]))


def test_cues_split_on_long_pause_speaker_change_and_length():
    w = lambda t, s, e, sp="A": {"text": t, "start": s, "end": e, "speaker": sp}
    assert len(cd.build_cues([w("a", 0, .4), w("b", 1.6, 2.0)])) == 2  # pausa 1,2 s > 0,8 s
    assert len(cd.build_cues([w("a", 0, .4), w("b", .5, .9, "B")])) == 2  # cambio de speaker
    assert len(cd.build_cues([w(f"p{i}", i * .5, i * .5 + .4) for i in range(40)])) == 1  # 40 palabras sin puntuación: una frase


def test_overlong_sentence_is_split_at_its_longest_pause_not_by_a_counter():
    # 130 palabras seguidas; en la 70 hay una pausa de 0,5 s (menor que 0,8: no es pausa «dura»)
    words, t = [], 0.0
    for i in range(130):
        if i == 70:
            t += 0.5
        words.append({"text": f"p{i}", "start": t, "end": t + 0.4, "speaker": "A"})
        t += 0.5
    cues = cd.build_cues(words)
    assert all(c.hi - c.lo + 1 <= 60 for c in cues)
    assert any(c.hi == 69 for c in cues) and any(c.lo == 70 for c in cues)  # corta donde está la pausa
    assert cues[0].lo == 0 and cues[-1].hi == 129 and all(b.lo == a.hi + 1 for a, b in zip(cues, cues[1:]))


def test_a_long_but_reasonable_sentence_is_never_cut():
    words = [{"text": f"p{i}", "start": i * .45, "end": i * .45 + .4, "speaker": "A"} for i in range(50)]  # 22 s
    assert len(cd.build_cues(words)) == 1


def test_cues_ignore_abbreviation_free_text_but_split_on_question_marks():
    w = lambda t, s: {"text": t, "start": s, "end": s + .4, "speaker": "A"}
    cues = cd.build_cues([w("¿Qué", 0), w("pasó?", .5), w("Nada.", 1.0)])
    assert [c.text for c in cues] == ["¿Qué pasó?", "Nada."]


# --- ajuste de límites --------------------------------------------------------------------------

def test_snap_to_cues():
    cues = cd.build_cues(make_words(SENTENCES))
    assert cd.snap_to_cues(6.5, 38.3, cues) == (pytest.approx(cue_start(2)), pytest.approx(cue_end(11)))


def test_trim_to_max_moves_the_end_back_to_a_sentence_end():
    cues = cd.build_cues(make_words(SENTENCES))
    s, e = cd.trim_to_max(0.0, 100.0, cues, 55)
    assert e == pytest.approx(cue_end(16)) and e - s <= 55
    assert cd.trim_to_max(0.0, 30.0, cues, 55) == (0.0, 30.0)


def test_extend_to_target_grows_to_sentence_boundaries():
    cues = cd.build_cues(make_words(SENTENCES))
    s, e = cd.extend_to_target(cue_start(2), 14.5, cues, 40, 55, cues[-1].end)
    assert s == pytest.approx(cue_start(2)) and e == pytest.approx(cue_end(14)) and e - s >= 40


def test_map_emphasis_uses_absolute_seconds_ignores_accents_and_skips_unknown():
    words = make_words(SENTENCES)
    found = cd.map_emphasis(["SANCHEZ", "quinientos", "inventada"], words, cue_start(2), cue_end(11))
    assert found == [{"start": pytest.approx(cue_start(3) + 0.5), "text": "Sánchez"},
                     {"start": pytest.approx(cue_start(3) + 2.0), "text": "quinientos"}]
    assert cd.map_emphasis(["quinientos"], words, cue_start(5), cue_end(11)) == []  # fuera del clip


def test_map_emphasis_accepts_phrases_and_falls_back_to_the_longest_word():
    words = make_words(SENTENCES)
    # «anunció ayer» está seguido en la frase 3: el énfasis cae en la palabra más larga (anunció)
    [e] = cd.map_emphasis(["anunció ayer"], words, cue_start(2), cue_end(11))
    assert e["text"] == "anunció" and e["start"] == pytest.approx(cue_start(3) + 1.0)
    # la secuencia no está seguida («Sánchez quinientos»): se recurre a la palabra más larga (quinientos)
    [e] = cd.map_emphasis(["Sánchez quinientos"], words, cue_start(2), cue_end(11))
    assert e["text"] == "quinientos"
    assert cd.map_emphasis(["palabras que no existen"], words, cue_start(2), cue_end(11)) == []


def test_map_emphasis_never_reuses_a_word_twice():
    out = cd.map_emphasis(["quinientos", "Quinientos millones"], make_words(SENTENCES), cue_start(2), cue_end(11))
    assert len(out) == 2 and out[0]["text"] == "quinientos" and out[1]["text"] == "millones"


def test_resolve_parts():
    assert cd.resolve_parts(14 * 60, None) == 1 and cd.resolve_parts(31 * 60, None) == 2
    assert cd.resolve_parts(10, None) == 1 and cd.resolve_parts(10, 4) == 4


# --- detector -----------------------------------------------------------------------------------

def test_detect_clips_snaps_validates_and_maps_the_llm_response():
    client = FakeClient({"clips": [clip_json(
        6.5, 38.3, score="85", hook="uno dos tres cuatro cinco seis siete ocho nueve",
        emphasis_words=["sanchez", "quinientos", "inventada"], parts=["a", "b", "c", "d", "e"])]})
    [c] = cd.detect_clips(tr(), client=client, target_dur=40)
    assert (c.start, c.end) == (pytest.approx(cue_start(2)), pytest.approx(cue_end(11)))
    assert isinstance(c.start, float) and isinstance(c.end, float)
    assert c.score == 85 and c.hook == "uno dos tres cuatro cinco seis"
    assert [e["text"] for e in c.emphasis] == ["Sánchez", "quinientos"]
    assert c.parts == ["a", "b", "c", "d"]
    assert "Sentencia2" in c.transcript and "Sentencia12" not in c.transcript
    assert c.to_dict()["duration"] == pytest.approx(31.7, abs=0.01)


def test_prompt_asks_for_hook_emphasis_parts_and_duration_limits():
    client = FakeClient({"clips": []})
    cd.detect_clips(tr(), client=client, target_dur=40, clips_per_part=3, model="m-test")
    call = client.calls[0]
    prompt = call["messages"][1]["content"]
    assert call["model"] == "m-test" and call["response_format"] == {"type": "json_object"}
    for needle in ("'hook'", "'emphasis_words'", "'parts'", "entre 30 y 55", "hasta 3 clips", "[0] 0.0-2.9s: Sentencia0"):
        assert needle in prompt, needle
    assert "[A]" not in prompt  # un solo speaker: sin etiquetas


def test_prompt_tags_speakers_only_when_there_are_several():
    a, b = make_words(SENTENCES[:20], "A"), make_words(SENTENCES[20:], "B", t0=70.0)
    client = FakeClient({"clips": []})
    cd.detect_clips({"words": a + b}, client=client)
    assert "[A] Sentencia0" in client.calls[0]["messages"][1]["content"]


def test_short_clip_is_extended_to_the_minimum_duration():
    [c] = cd.detect_clips(tr(), client=FakeClient({"clips": [clip_json(cue_start(2), cue_end(4))]}), target_dur=40)
    assert c.end - c.start >= 30


def test_clip_longer_than_max_is_trimmed():
    [c] = cd.detect_clips(tr(), client=FakeClient({"clips": [clip_json(cue_start(0), cue_end(30))]}), target_dur=40)
    assert c.end - c.start <= 55


def test_malformed_clips_are_dropped_without_failing_the_rest():
    bad = [{"start": "x", "end": 5}, {"start": 10, "end": 5}, {"title": "sin tiempos"}, {"start": 1, "end": float("inf")}]
    cs = cd.detect_clips(tr(), client=FakeClient({"clips": bad + [clip_json(cue_start(2), cue_end(11))]}), target_dur=40)
    assert len(cs) == 1


def test_score_is_clamped_and_coerced():
    for raw, want in (("85", 85), (250, 100), (-5, 0), ("alto", 0), (None, 0)):
        [c] = cd.detect_clips(tr(), client=FakeClient({"clips": [clip_json(cue_start(2), cue_end(11), score=raw)]}))
        assert c.score == want


def test_overlapping_clips_keep_the_best_score_and_result_is_chronological():
    resp = {"clips": [clip_json(cue_start(2), cue_end(11), score=60), clip_json(cue_start(3), cue_end(12), score=90),
                      clip_json(cue_start(25), cue_end(34), score=70)]}
    cs = cd.detect_clips(tr(), client=FakeClient(resp), target_dur=40)
    assert [c.score for c in cs] == [90, 70]
    assert cs[0].start < cs[1].start


def test_one_failed_part_does_not_kill_the_others():
    client = FakeClient("esto no es json", {"clips": [clip_json(cue_start(22), cue_end(31))]})
    cs = cd.detect_clips(tr(), client=client, parts=2, target_dur=40)
    assert len(client.calls) == 2 and len(cs) == 1 and cs[0].start >= cue_start(20)


def test_all_parts_failing_raises():
    with pytest.raises(cd.DetectionError, match="todas las partes"):
        cd.detect_clips(tr(), client=FakeClient(RuntimeError("boom"), RuntimeError("boom")), parts=2)


def test_missing_api_key_and_empty_transcript(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    with pytest.raises(cd.DetectionError, match="OPENAI_API_KEY"):
        cd.detect_clips(tr())
    with pytest.raises(cd.DetectionError, match="palabras"):
        cd.detect_clips({"words": []}, client=FakeClient())


# --- ajuste con silencios -----------------------------------------------------------------------

def gap(k):
    """Silencio entre la frase k y la k+1 (0,3 s en la transcripción sintética)."""
    return {"start": cue_end(k), "end": cue_start(k + 1)}


def test_snap_prefers_a_sentence_boundary_with_silence_within_reach():
    cues = cd.build_cues(make_words(SENTENCES))
    # el más cercano a 6,5 s es la frase 2 (6,4 s), pero solo hay silencio ANTES de la frase 3 (9,6 s)
    s, e = cd.snap_to_cues(6.5, 38.3, cues, [gap(2), gap(11)])
    assert s == pytest.approx(cue_start(3)) and e == pytest.approx(cue_end(11))
    # sin silencios (o ninguno al alcance) se queda el límite de frase más cercano
    assert cd.snap_to_cues(6.5, 38.3, cues, [])[0] == pytest.approx(cue_start(2))
    assert cd.snap_to_cues(6.5, 38.3, cues, [gap(20)])[0] == pytest.approx(cue_start(2))


def test_snap_ignores_silences_beyond_the_reach():
    cues = cd.build_cues(make_words(SENTENCES))
    far = gap(7)  # frase 8 empieza en 25,6 s: a 19 s de 6,5
    assert cd.snap_to_cues(6.5, 38.3, cues, [far, gap(11)])[0] == pytest.approx(cue_start(2))


def test_trim_prefers_a_silent_end_when_it_is_close_to_the_longest_fit():
    cues = cd.build_cues(make_words(SENTENCES))
    quiet = lambda t: abs(t - cue_end(15)) < 0.01  # solo la frase 15 acaba en silencio
    s, e = cd.trim_to_max(0.0, 100.0, cues, 55, quiet)
    assert e == pytest.approx(cue_end(15))  # 50,9 s en vez de 54,1 s (frase 16)
    s, e = cd.trim_to_max(0.0, 100.0, cues, 55, lambda t: False)
    assert e == pytest.approx(cue_end(16))  # nada tiene silencio: el último que cabe


def test_detect_clips_returns_boundaries_in_silence_when_they_exist_nearby():
    from app.services import silences as sl

    sil = [gap(2), gap(11)]
    [c] = cd.detect_clips(tr(), client=FakeClient({"clips": [clip_json(6.5, 38.3)]}), target_dur=25, silences=sil)
    assert (c.start, c.end) == (pytest.approx(cue_start(3)), pytest.approx(cue_end(11)))
    assert sl.can_cut_start(c.start, sil) and sl.can_cut_end(c.end, sil)


def _words_with_midsentence_pause():
    """Frase 1 con una pausa de 1 s tras la palabra 3 (sin puntuación), frase 2 normal."""
    words, t = [], 0.0
    for k, text in enumerate(["uno dos tres cuatro cinco seis.", "siete ocho nueve diez once doce.", "trece catorce quince dieciseis diecisiete dieciocho."]):
        for n, w in enumerate(text.split()):
            words.append({"text": w, "start": round(t, 3), "end": round(t + 0.4, 3), "speaker": "A"})
            t += 0.5
            if k == 1 and n == 2:
                t += 1.0  # pausa interna de 1,5 s (> 0,8: se convierte en límite de frase «blando»)
        t += 0.2
    return words


def test_sentence_boundary_beats_a_nearer_silent_pause_inside_a_sentence():
    words = _words_with_midsentence_pause()
    cues = cd.build_cues(words)
    assert len(cues) == 4  # la frase 2 queda partida en dos por su pausa interna
    mid = cues[1]  # «siete ocho nueve»: acaba en la pausa, sin puntuación
    assert not mid.text.endswith(".")
    pause = {"start": mid.end, "end": cues[2].start}
    # el fin pedido cae a 0,2 s de la pausa interna con silencio, pero hay finales de frase al alcance: ganan ellos
    _, e = cd.snap_to_cues(0.0, mid.end + 0.2, cues, [pause])
    assert e != pytest.approx(mid.end)
    assert e in (pytest.approx(cues[0].end), pytest.approx(cues[2].end))


def test_inner_pause_with_silence_is_used_only_when_no_sentence_end_is_in_reach():
    words = _words_with_midsentence_pause()
    cues = cd.build_cues(words)
    mid = cues[1]
    far = [c for c in cues if c.text.endswith(".")]
    # alcance recortado a mano: ningún final de frase al alcance → la pausa interna con silencio es la opción 3
    old = cd.SILENCE_REACH
    cd.SILENCE_REACH = 0.5
    try:
        _, e = cd.snap_to_cues(0.0, mid.end + 0.1, cues, [{"start": mid.end, "end": cues[2].start}])
    finally:
        cd.SILENCE_REACH = old
    assert e == pytest.approx(mid.end)
    assert far  # (hay finales de frase, pero fuera del alcance recortado)


def test_trim_prefers_sentence_ends_over_inner_pauses():
    words = _words_with_midsentence_pause()
    cues = cd.build_cues(words)
    best = max(cues, key=lambda c: c.end)
    s, e = cd.trim_to_max(0.0, 100.0, cues, cues[2].end + 0.1)  # cabe hasta la frase 2 entera
    assert e == pytest.approx(cues[2].end)
