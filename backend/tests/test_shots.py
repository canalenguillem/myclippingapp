import subprocess

import numpy as np
import pytest

from app.pipeline import focus, shots

WIN = 0.487


def face(x, h, w=None):
    w = w or h * 0.6
    return {"x": x - w / 2, "y": 0.2, "w": w, "h": h, "score": 0.9}


def test_window_fraction_depends_on_the_layout():
    assert round(shots.window_fraction(1920, 1080, 0.65), 3) == 0.487
    assert round(shots.window_fraction(1920, 1080, 0.5), 3) == 0.633
    assert shots.window_fraction(480, 854, 0.5) == 1.0                         # un original vertical ya cabe entero


def test_classify_wide_face_and_multi():
    assert shots.classify([], WIN)[0] == "wide"
    assert shots.classify([face(0.9, 0.05)], WIN)[0] == "wide"                  # una cara de 5 % del alto no cuenta
    kind, data = shots.classify([face(0.5, 0.22), face(0.1, 0.05)], WIN)
    assert kind == "face" and data["x"] == pytest.approx(0.5)
    kind, data = shots.classify([face(0.45, 0.2), face(0.55, 0.2)], WIN)       # dos caras juntas caben en el recorte
    assert kind == "face" and data["x"] == pytest.approx(0.5)
    kind, data = shots.classify([face(0.2, 0.38), face(0.8, 0.36)], WIN)       # dos webcams separadas: no caben
    assert kind == "multi" and len(data["boxes"]) == 2


def test_decide_follows_big_faces_but_shows_the_whole_frame_when_the_speaker_is_a_small_background_face():
    call = [("multi", {"boxes": [(0.15, 0.30, 1.0), (0.70, 0.90, 0.95)]})] * 3
    assert shots.decide(call, [0.0987, 0.0987, 0.79]) == {"kind": "snap", "centers": [0.225, 0.8]}          # el ASD se pega a la webcam real
    studio = [("multi", {"boxes": [(0.84, 0.94, 1.0), (0.45, 0.53, 0.6)]})] * 3                               # el «hablante» es el presentador pequeño
    assert shots.decide(studio, [0.49, 0.49]) == {"kind": "wide"}
    assert shots.decide(call, []) == {"kind": "wide"}                                                        # sin ASD, no se puede elegir
    assert shots.decide([("face", {"x": 0.5}), ("face", {"x": 0.52}), ("wide", {})], []) == {"kind": "face", "x": 0.51}
    assert shots.decide([], [0.5]) == {"kind": "keep"}


def test_clusters_group_close_values():
    assert shots._clusters([0.2, 0.22, 0.8, 0.79, 0.5]) == [[0.2, 0.22], [0.5], [0.79, 0.8]]


def make_cut_video(path):
    """6 s a 10 fps: 0–2 s rojo, 2–4 s azul, 4–6 s verde (cortes de plano limpios)."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=10:d=2", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=10:d=2",
           "-f", "lavfi", "-i", "color=c=green:s=640x360:r=10:d=2", "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def test_plan_splits_at_the_cuts_and_decides_each_shot(tmp_path):
    video = make_cut_video(tmp_path / "c.mp4")

    def fake_detect(frame):                              # rojo: una cara grande; azul: nada; verde: dos webcams
        r, g, b = frame.reshape(-1, 3).mean(axis=0)
        if r > 150:
            return [face(0.55, 0.25)]
        if g > 100:
            return [face(0.2, 0.38), face(0.8, 0.36)]
        return []

    plan = shots.plan(video, 0, 6, window=WIN, asd_at=lambda t: 0.19, detect=fake_detect)
    assert [(round(p["start"]), round(p["end"]), p["kind"]) for p in plan] == [(0, 2, "face"), (2, 4, "wide"), (4, 6, "snap")]
    assert plan[0]["x"] == pytest.approx(0.55, abs=0.01) and plan[2]["centers"] == [0.2, 0.8]


def test_apply_shots_overrides_per_shot_and_jumps_at_cuts():
    base = [(0.0, 0.5), (10.0, 0.1)]
    plan = [{"start": 0.0, "end": 5.0, "kind": "face", "x": 0.7}, {"start": 5.0, "end": 9.0, "kind": "wide"}, {"start": 9.0, "end": 14.0, "kind": "snap", "centers": [0.2, 0.8]}]
    out = focus.apply_shots(base, plan)
    assert out[0] == (0.0, 0.7, focus.CUT_EASE)
    assert [p[:2] for p in out] == [(0.0, 0.7), (5.0, 0.5), (9.0, 0.2)]      # wide conserva la base; snap pega 0,5→0,2 y 0,1→0,2 (sin pasos repetidos)
    expr = focus.x_expr(out)
    assert "clip((t-5.000)/0.040" in expr                                                                 # el salto en el corte es casi instantáneo
    assert focus.position_at(out, 4.9) == pytest.approx(0.7) and focus.position_at(out, 5.5) == pytest.approx(0.5)


def test_apply_shots_without_a_usable_plan_keeps_the_track():
    base = [(0.0, 0.3)]
    assert focus.apply_shots(base, []) == base
