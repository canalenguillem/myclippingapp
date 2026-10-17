import wave

import numpy as np
import pytest

from app.services import silences

SR = silences.SAMPLE_RATE


def tone(seconds, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def quiet(seconds, db=-60.0):
    """Ruido blanco con un RMS aproximado de `db` dBFS."""
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(SR * seconds)) * 32768 * 10 ** (db / 20)).astype(np.int16)


def find(samples):
    return silences.silences_from_db(silences.window_db(samples))


def test_finds_one_silence_between_two_tones():
    assert find(np.concatenate([tone(1.0), np.zeros(int(SR * 0.5), np.int16), tone(1.0)])) == [{"start": 1.0, "end": 1.5}]


def test_threshold_is_minus_45_db():
    assert find(np.concatenate([tone(1), quiet(0.5, -50), tone(1)])) == [{"start": 1.0, "end": 1.5}]
    assert find(np.concatenate([tone(1), quiet(0.5, -40), tone(1)])) == []


def test_short_gaps_are_not_silences():
    gap = np.zeros(int(SR * 0.05), np.int16)  # 0,05 s < mínimo de 0,10 s
    assert find(np.concatenate([tone(1), gap, tone(1)])) == []


def test_silence_at_start_and_end():
    z = np.zeros(int(SR * 0.5), np.int16)
    assert find(np.concatenate([z, tone(1), z])) == [{"start": 0.0, "end": 0.5}, {"start": 1.5, "end": 2.0}]


def test_empty_and_sub_window_input():
    assert find(np.array([], dtype=np.int16)) == []
    assert find(np.zeros(100, np.int16)) == []


def test_times_are_float_seconds():
    out = find(np.concatenate([tone(1), np.zeros(int(SR * 0.5), np.int16), tone(1)]))
    assert all(isinstance(v, float) for s in out for v in s.values())


def test_detect_silences_decodes_a_real_file_with_ffmpeg(tmp_path):
    samples = np.concatenate([tone(1.0), np.zeros(int(SR * 0.6), np.int16), tone(1.0), np.zeros(int(SR * 0.3), np.int16)])
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())
    found = silences.detect_silences(path)
    assert [round(s["start"], 1) for s in found] == [1.0, 2.6]
    assert [round(s["end"], 1) for s in found] == [1.6, 2.9]


def test_detect_silences_raises_on_garbage(tmp_path):
    bad = tmp_path / "x.mp3"
    bad.write_bytes(b"no soy audio")
    with pytest.raises(RuntimeError):
        silences.detect_silences(bad)


def test_save_and_load_roundtrip(tmp_path):
    f = tmp_path / "silences.json"
    silences.save_silences([{"start": 1.0, "end": 1.5}], f)
    assert silences.load_silences(f) == [{"start": 1.0, "end": 1.5}]
    assert [p.name for p in tmp_path.iterdir()] == ["silences.json"]


def test_min_silence_is_two_windows():
    two = np.concatenate([tone(1), np.zeros(int(SR * 0.1), np.int16), tone(1)])
    assert find(two) == [{"start": 1.0, "end": 1.1}]            # 0,10 s ya cuenta
    one = np.concatenate([tone(1), np.zeros(int(SR * 0.05), np.int16), tone(1)])
    assert find(one) == []                                       # 0,05 s no


def test_can_cut_helpers_agree_with_the_snaps():
    sil = [{"start": 4.2, "end": 5.0}, {"start": 10.05, "end": 11.0}]
    assert silences.can_cut_start(5.0, sil) and not silences.can_cut_start(7.0, sil)
    assert silences.can_cut_end(10.0, sil) and not silences.can_cut_end(7.0, sil)
    assert silences.can_cut_start(4.5, sil)  # ya dentro de un silencio
