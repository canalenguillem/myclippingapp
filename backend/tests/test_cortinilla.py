import pytest

from app.services import cortinilla as c


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


WORDS = [w("Hola", 0.0, 0.4), w("a", 0.45, 0.6), w("todos.", 0.65, 1.1),
         w("Esto", 4.6, 5.0), w("sigue", 5.05, 5.5), w("sin", 5.55, 5.8), w("parar,", 5.85, 6.3),
         w("y", 7.0, 7.1), w("acaba.", 7.15, 7.7), w("Fin", 9.4, 9.8)]
SIL = [{"start": 1.1, "end": 1.9}, {"start": 3.0, "end": 4.5}, {"start": 6.3, "end": 6.95}, {"start": 7.7, "end": 9.3}]


def test_time_map_delays_everything_after_the_insertion():
    m = c.TimeMap(at=5.0, seconds=3.6)
    assert m.to_out(4.99) == 4.99 and m.to_out(5.0) == 8.6 and m.to_out(10.0) == 13.6
    assert m.total(30.0) == 33.6


def test_time_map_without_insertion_is_identity():
    m = c.TimeMap()
    assert m.to_out(12.3) == 12.3 and m.total(30.0) == 30.0


def test_candidates_are_centers_of_silences_after_complete_sentences():
    assert c.candidates(WORDS, SIL, 12.0) == [1.5, 3.75, 8.5]  # 6.3–6.95 sigue a «parar,»: no cierra frase


def test_default_position_skips_the_intro_and_prefers_complete_sentences():
    assert c.default_position(WORDS, SIL, 12.0) == 8.5          # 1,5 y 3,75 caen dentro de los 4 s de intro; 6,6 no cierra frase
    assert c.default_position(WORDS, SIL, 12.0, intro=3.0) == 3.75


def test_default_position_falls_back_to_any_silence_then_none():
    only_comma = [{"start": 6.3, "end": 6.95}]
    assert c.default_position(WORDS, only_comma, 12.0) == 6.625
    assert c.default_position(WORDS, [], 12.0) is None


def test_never_inside_a_word_nor_in_the_last_second():
    bad = [{"start": 5.1, "end": 5.4}, {"start": 11.2, "end": 11.9}]
    assert c.candidates(WORDS, bad, 12.0, sentence_only=False) == []


def test_snap_moves_to_the_nearest_valid_point():
    assert c.snap_position(6.0, WORDS, SIL, 12.0) == 3.75  # 2,25 s de distancia frente a 2,5 s; 6,6 no cierra frase
    assert c.snap_position(7.0, WORDS, SIL, 12.0) == 8.5
    assert c.snap_position(0.0, WORDS, SIL, 12.0) == 1.5
    assert c.snap_position(5.0, WORDS, [], 12.0) is None


def test_rebase_silences_to_clip_time():
    out = c.rebase_silences([{"start": 8.0, "end": 9.0}, {"start": 99.0, "end": 100.0}, {"start": 19.0, "end": 22.0}], 10.0, 20.0)
    assert out == [{"start": 9.0, "end": 10.0}]
    assert c.rebase_silences([{"start": 5.0, "end": 12.0}], 10.0, 20.0) == [{"start": 0.0, "end": 2.0}]
