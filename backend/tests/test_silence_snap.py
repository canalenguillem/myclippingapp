import pytest

from app.services.silences import snap_end, snap_start

S = lambda a, b: {"start": a, "end": b}


def test_start_goes_back_into_the_silence_before_the_first_word_with_a_pad():
    assert snap_start(5.0, [S(4.2, 5.0)]) == pytest.approx(4.8)   # colchón de 0,2 s
    assert snap_start(5.0, [S(4.9, 5.0)]) == pytest.approx(4.9)   # silencio más corto que el colchón
    assert snap_start(5.0, [S(4.2, 4.95)]) == pytest.approx(4.75)  # acaba justo antes de la palabra


def test_start_never_moves_forward_and_never_cuts_words():
    assert snap_start(5.0, [S(5.3, 5.5)]) == 5.0          # pausa a mitad de frase, posterior: no se toca
    assert snap_start(5.0, [S(3.0, 6.0)]) == 5.0          # ya está dentro de un silencio largo
    assert snap_start(5.0, [S(3.0, 4.3)]) == 5.0          # el silencio queda fuera de la ventana de 0,6 s
    assert snap_start(5.0, []) == 5.0


def test_start_picks_the_nearest_silence_and_stays_non_negative():
    assert snap_start(5.0, [S(4.0, 4.1), S(4.6, 4.9)]) == pytest.approx(4.7)
    assert snap_start(0.1, [S(0.0, 0.1)]) == 0.0


def test_end_goes_forward_into_the_silence_after_the_last_word_with_a_pad():
    assert snap_end(10.0, [S(10.05, 11.0)]) == pytest.approx(10.25)
    assert snap_end(10.0, [S(10.0, 10.1)]) == pytest.approx(10.1)


def test_end_never_cuts_words():
    assert snap_end(10.0, [S(9.2, 9.8)]) == 10.0          # silencio anterior: no se toca
    assert snap_end(10.0, [S(8.0, 12.0)]) == 10.0         # ya dentro de un silencio largo
    assert snap_end(10.0, [S(11.0, 12.0)]) == 10.0        # fuera de la ventana
    assert snap_end(10.0, []) == 10.0


def test_end_is_clamped_to_the_video_duration():
    assert snap_end(10.0, [S(10.05, 11.0)], total=10.1) == pytest.approx(10.1)


def test_results_are_floats():
    assert isinstance(snap_start(5.0, [S(4.2, 5.0)]), float) and isinstance(snap_end(10.0, [S(10.05, 11.0)]), float)
