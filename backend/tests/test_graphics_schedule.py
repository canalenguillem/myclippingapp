from app.services.graphics_schedule import schedule


def kw(at, text="INDULTOS", **extra):
    return {"type": "keyword", "at": at, "text": text, **extra}


def test_window_defaults_and_clamps():
    r = schedule([kw(10.0)], 40.0)
    assert r.beats == [{"type": "keyword", "at": 10.0, "text": "INDULTOS", "lead": 0.5, "duration": 2.5}] and r.dropped == []
    b = schedule([kw(10.0, lead=5, duration=99)], 40.0).beats[0]
    assert (b["lead"], b["duration"]) == (0.8, 4.0)          # entra como mucho 0,8 s antes y vive como mucho 4 s
    b = schedule([kw(10.0, lead=0, duration=0.2)], 40.0).beats[0]
    assert (b["lead"], b["duration"]) == (0.3, 2.0)


def test_invalid_beats_are_dropped_with_a_reason():
    r = schedule([{"type": "otro", "at": 5}, kw(5, text=" "), kw(-1), kw(99), "no soy un dict", kw(10)], 40.0)
    assert [b["at"] for b in r.beats] == [10]
    assert [d["reason"] for d in r.dropped] == ["motivo desconocido: 'otro'", "falta el texto", "la palabra gancho cae fuera del clip", "la palabra gancho cae fuera del clip"]


def test_a_big_graphic_waits_for_the_hook_to_finish():
    r = schedule([kw(2.5), kw(2.3), kw(2.8)], 40.0)
    assert [(b["at"], b["lead"]) for b in r.beats] == [(2.5, 0.3)]   # 2,5 entra a 2,2 s (acaba el gancho)
    assert {d["beat"]["at"] for d in r.dropped} == {2.3, 2.8}          # 2,3 choca con el gancho; 2,8 solapa con 2,5
    assert any(d["reason"] == "choca con el gancho" and d["beat"]["at"] == 2.3 for d in r.dropped)


def test_never_two_big_graphics_close_together_and_priority_wins():
    r = schedule([kw(10), kw(12), kw(16, priority=9), kw(30)], 40.0)
    assert [b["at"] for b in r.beats] == [10, 16, 30]          # 12 solapa con 10 (inicios a menos de 4 s); 16 más prioritario no choca
    assert r.dropped[0]["beat"]["at"] == 12 and "más prioritario" in r.dropped[0]["reason"]
    r2 = schedule([kw(10), kw(12, priority=9)], 40.0)           # la prioridad decide cuál se queda
    assert [b["at"] for b in r2.beats] == [12]


def test_gap_of_four_seconds_between_starts_is_enough():
    assert [b["at"] for b in schedule([kw(10), kw(14.5)], 40.0).beats] == [10, 14.5]


def test_never_crosses_the_initial_cortinilla():
    # palabra antes de la cortinilla (a 10 s): la ventana 8,5–11 se corta en 10
    b = schedule([kw(9.0)], 40.0, cortinilla_at=10.0).beats[0]
    assert (b["at"], b["lead"], b["duration"]) == (9.0, 0.5, 1.5)
    # palabra tras la cortinilla: entra al reanudar el clip
    b = schedule([kw(10.4)], 40.0, cortinilla_at=10.0).beats[0]
    assert (b["at"], b["lead"]) == (10.4, 0.4)
    r = schedule([kw(10.2), kw(9.5, text="A")], 40.0, cortinilla_at=10.0)
    assert [d["reason"] for d in r.dropped] == ["la palabra cae pegada a la cortinilla de inicio", "no cabe una ventana visible de 1,5 s"]
    assert r.beats == []


def test_trimmed_by_the_end_of_the_clip_or_dropped_if_too_short():
    assert schedule([kw(19.0)], 20.0).beats[0]["duration"] == 1.5   # 18,5 → 20 = 1,5 s: justo cabe
    r = schedule([kw(19.9)], 20.0)
    assert r.beats == [] and r.dropped[0]["reason"] == "no cabe una ventana visible de 1,5 s"


def test_output_matches_the_fx_worker_window():
    for beat in schedule([kw(2.8), kw(9.0), kw(25.0)], 40.0, cortinilla_at=10.0).beats:
        start = max(0.0, beat["at"] - beat["lead"])
        assert 0.3 <= beat["lead"] <= 0.8 and 1.5 <= beat["duration"] <= 4.0 and start + beat["duration"] <= 40.0
        assert not (start < 10.0 < start + beat["duration"])


def test_no_beats():
    assert schedule(None, 30.0).beats == [] and schedule([], 30.0).dropped == []
