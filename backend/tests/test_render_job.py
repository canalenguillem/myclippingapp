import json
import shutil

import pytest

from app.config import get_settings
from app.db.models import BrandTemplate, Clip, Job, Project, ProjectStatus, RenderState, User
from app.jobs import queue
from app.jobs import render as render_mod
from app.jobs.context import Cancelled, JobContext
from app.jobs.handlers import HANDLERS
from app.pipeline import analysis
from app.services import storage, transcription
from app.services.fx_client import FxRenderFailed, FxResult, FxUnavailable
from tests.media_helpers import make_source, probe

SPEAKERS = {
    "A": {"name": "Ana", "role": "", "caption_style": "sans_upper", "is_source": False},
    "B": {"name": "Bea", "role": "", "caption_style": "serif_italic", "is_source": True},
}
WORDS = [{"text": f"p{i}", "start": 1.5 + i * 0.5, "end": 1.5 + i * 0.5 + 0.4, "confidence": 1, "speaker": "A" if i < 4 else "B"} for i in range(8)]


@pytest.fixture(scope="module")
def source_file(tmp_path_factory):
    return make_source(tmp_path_factory.mktemp("rsrc") / "source.mp4", 8)


class FakeFx:
    """Servicio de render falso: copia el clip vertical al `output` pedido (como haría el servicio real)."""

    def __init__(self, mode="ok"):
        self.mode, self.requests = mode, []

    def render(self, request, *, on_progress=None, cancel_check=None):
        self.requests.append(request)
        if self.mode == "unavailable":
            raise FxUnavailable("No se puede hablar con el servicio de render (ConnectError)")
        if self.mode == "failed":
            raise FxRenderFailed("Chrome se cayó")
        if self.mode == "cancel":
            raise Cancelled()
        if on_progress:
            on_progress(0.5)
        if cancel_check:
            cancel_check()
        shutil.copy(storage.absolute(request["video"]), storage.absolute(request["output"]))
        return FxResult(seconds=1.0)


class Env:
    pass


def setup(client, tmp_path, monkeypatch, source_file, *, status="approved", layout="split", words=True, fx="ok", **clip_kw):
    monkeypatch.setattr(get_settings(), "media_dir", tmp_path)
    db = client.session_factory()
    user = User(email="a@x.com", password_hash="x")
    db.add(user)
    db.commit()
    project = Project(user_id=user.id, source_url="https://youtu.be/x", title="T", duration=8.0, status=ProjectStatus.READY, speakers=SPEAKERS)
    db.add(project)
    db.commit()
    folder = storage.project_dir(user.id, project.id)
    shutil.copy(source_file, folder / "source.mp4")
    project.video_path = storage.rel(folder / "source.mp4")
    transcription.save_words({"words": WORDS if words else []}, folder / "words.json")
    project.words_path = storage.rel(folder / "words.json")
    clip = Clip(project_id=project.id, user_id=user.id, start=1.0, end=5.0, title="t", hook="Gancho", status=status, layout=layout, **clip_kw)
    db.add(clip)
    db.commit()
    e = Env()
    e.db, e.user, e.project, e.clip, e.folder = db, user, project, clip, folder / f"clip_{clip.id}"
    e.fx = FakeFx(fx) if fx else None
    monkeypatch.setattr(render_mod, "make_fx_client", lambda: e.fx)
    return e


def run_job(e, quality="draft", clip_id=None, user_id=None):
    job = queue.enqueue(e.db, e.user.id, "render", {"clip_id": clip_id or e.clip.id, "project_id": e.project.id, "quality": quality})
    claimed = queue.claim_next(e.db, "w")
    ctx = JobContext(db=e.db, job_id=claimed.id, user_id=user_id or e.user.id, log_file=e.folder.parent / "job.log")
    e.ctx = ctx
    try:
        render_mod.render(ctx, claimed.payload)
    finally:
        queue.finish(e.db, claimed.id)  # libera el carril de render para el siguiente job
        e.db.refresh(e.clip)
    return ctx


def files(e):
    return sorted(p.name for p in e.folder.iterdir()) if e.folder.exists() else []


def log(e):
    return (e.folder.parent / "job.log").read_text()


def test_render_is_a_registered_handler():
    assert HANDLERS["render"] is render_mod.render


def test_draft_end_to_end(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, status="detected")
    run_job(e)
    c = e.clip
    assert c.render_state is RenderState.DRAFT and c.render_error is None and c.rendered_path is None and c.rendered_at is not None
    draft = storage.absolute(c.draft_path)
    assert c.draft_path.endswith(f"clip_{c.id}/draft.mp4")
    v = probe(draft, "stream=codec_type,width,height")["streams"]
    assert [(s["codec_type"], s.get("width"), s.get("height")) for s in v] == [("video", 540, 960), ("audio", None, None)]
    assert storage.absolute(c.thumbnail_path).suffix == ".jpg" and storage.absolute(c.thumbnail_path).exists()
    assert json.loads(storage.absolute(c.analysis_path).read_text()) == {"version": 1, "burned_subtitles": None}
    assert files(e) == ["analysis.json", "draft.mp4", "thumb.jpg"]  # los intermedios (vertical y fx_full) se borran
    assert e.db.get(Job, e.ctx.job_id).progress >= 98
    assert "Servicio de render: listo" in log(e)


def test_the_request_sent_to_the_service(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    run_job(e)
    r = e.fx.requests[0]
    base = f"u{e.user.id}/p{e.project.id}/clip_{e.clip.id}"
    assert (r["video"], r["output"]) == (f"{base}/vertical_draft.mp4", f"{base}/fx_full.mp4")
    assert (r["quality"], r["duration"], r["layout"], r["preset"], r["fps"]) == ("draft", 4.0, {"mode": "split", "top_ratio": 0.5}, "editorial", 30)
    assert r["hook"] == {"text": "Gancho", "duration": 2.2} and "band" not in r
    assert r["words"][0] == {"text": "p0", "start": 0.5, "end": 0.9, "speaker": "A"}      # 1,5 s del vídeo = 0,5 s del clip
    assert [w["text"] for w in r["words"]] == ["p0", "p1", "p2", "p3", "p4", "p5", "p6"]  # p7 empieza a los 5,0 s: fuera
    assert set(r["speakers"]) == {"A", "B"} and r["speakers"]["B"]["is_source"] is True


def test_final_needs_an_approved_clip(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, status="detected")
    with pytest.raises(render_mod.RenderError, match="aprobado"):
        run_job(e, "final")
    assert e.clip.render_state is RenderState.FAILED and "aprobado" in e.clip.render_error and files(e) == []


def test_final_render_is_full_size_and_a_later_draft_keeps_the_final_state(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    run_job(e, "final")
    c = e.clip
    assert c.render_state is RenderState.FINAL and c.draft_path is None and c.rendered_path.endswith("final.mp4")
    assert e.fx.requests[0]["quality"] == "standard" and e.fx.requests[0]["output"].endswith("/final.mp4")
    v = probe(storage.absolute(c.rendered_path), "stream=width,height")["streams"][0]
    assert (v["width"], v["height"]) == (1080, 1920)
    run_job(e, "draft")  # un borrador posterior no degrada el estado: el final sigue siendo válido
    assert c.render_state is RenderState.FINAL and c.draft_path and c.rendered_path
    assert files(e) == ["analysis.json", "draft.mp4", "final.mp4", "thumb.jpg"]


def test_a_second_render_replaces_the_first(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    run_job(e)
    first = e.clip.rendered_at
    run_job(e)
    assert e.clip.render_state is RenderState.DRAFT and e.clip.rendered_at >= first and files(e) == ["analysis.json", "draft.mp4", "thumb.jpg"]


def test_burned_subtitles_become_the_band_rows(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    monkeypatch.setattr(analysis, "detect_burned_subtitles", lambda *a, **k: {"y0": 1380, "y1": 1470, "confidence": 0.8})
    run_job(e)
    assert e.fx.requests[0]["band"] == {"y0": 1380, "y1": 1470}
    assert json.loads(storage.absolute(e.clip.analysis_path).read_text())["burned_subtitles"]["confidence"] == 0.8
    assert "1380–1470" in log(e)


def test_an_analysis_failure_only_loses_the_band(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)

    def boom(*a, **k):
        raise analysis.AnalysisError("no se pudo decodificar")

    monkeypatch.setattr(analysis, "detect_burned_subtitles", boom)
    run_job(e)
    assert e.clip.render_state is RenderState.DRAFT and "band" not in e.fx.requests[0] and "la banda irá centrada" in log(e)


def test_the_template_preset_is_used_only_if_it_belongs_to_the_user(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    mine = BrandTemplate(user_id=e.user.id, name="mía", preset="hormozi")
    other_user = User(email="o@x.com", password_hash="x")
    e.db.add_all([mine, other_user])
    e.db.commit()
    theirs = BrandTemplate(user_id=other_user.id, name="ajena", preset="minimal")
    e.db.add(theirs)
    e.db.commit()
    e.clip.template_id = mine.id
    e.db.commit()
    run_job(e)
    assert e.fx.requests[0]["preset"] == "hormozi"
    e.clip.template_id = theirs.id
    e.db.commit()
    run_job(e)
    assert e.fx.requests[1]["preset"] == "editorial"


@pytest.mark.parametrize("fx,needle", [(None, "FX_WORKER_URL"), ("unavailable", "No se puede hablar"), ("failed", "Chrome se cayó")])
def test_falls_back_to_ass_subtitles_when_the_service_is_not_usable(client, tmp_path, monkeypatch, source_file, fx, needle):
    e = setup(client, tmp_path, monkeypatch, source_file, fx=fx)
    run_job(e)
    c = e.clip
    assert c.render_state is RenderState.DRAFT and storage.absolute(c.draft_path).exists()
    v = probe(storage.absolute(c.draft_path), "stream=width,height")["streams"][0]
    assert (v["width"], v["height"]) == (540, 960)
    assert c.render_error.startswith("Aviso:") and needle in c.render_error
    assert "subtítulos ASS" in log(e) and files(e) == ["analysis.json", "draft.mp4", "thumb.jpg"]


def test_cancelling_restores_the_state_that_matches_the_files(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, fx="cancel")
    with pytest.raises(Cancelled):
        run_job(e)
    assert e.clip.render_state is RenderState.NONE and e.clip.render_error is None and files(e) == ["analysis.json"]
    # con un borrador anterior, vuelve a DRAFT y el fichero sigue ahí
    e.fx.mode = "ok"
    run_job(e)
    draft = storage.absolute(e.clip.draft_path)
    e.fx.mode = "cancel"
    with pytest.raises(Cancelled):
        run_job(e)
    assert e.clip.render_state is RenderState.DRAFT and draft.exists()


@pytest.mark.parametrize("kw,msg", [({"layout": "full"}, "split"), ({"layout": "facecam"}, "split"), ({"words": False, "status": "approved"}, None)])
def test_unsupported_layout_fails_clearly(client, tmp_path, monkeypatch, source_file, kw, msg):
    e = setup(client, tmp_path, monkeypatch, source_file, **kw)
    if msg is None:
        run_job(e)  # sin palabras en el rango también renderiza
        assert e.fx.requests[0]["words"] == [] and e.clip.render_state is RenderState.DRAFT
        return
    with pytest.raises(render_mod.RenderError, match=msg):
        run_job(e)
    assert e.clip.render_state is RenderState.FAILED and msg in e.clip.render_error and files(e) == []


def test_missing_source_video_fails_clearly(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    storage.absolute(e.project.video_path).unlink()
    with pytest.raises(render_mod.RenderError, match="No se encuentra"):
        run_job(e)
    assert e.clip.render_state is RenderState.FAILED


def test_a_corrupt_source_fails_and_leaves_no_intermediates(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    storage.absolute(e.project.video_path).write_bytes("no soy un vídeo".encode())
    with pytest.raises(Exception, match="ffmpeg falló"):
        run_job(e)
    assert e.clip.render_state is RenderState.FAILED and "VerticalError" in e.clip.render_error and files(e) == []


def test_another_users_clip_is_not_found_and_untouched(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    other = User(email="o@x.com", password_hash="x")
    e.db.add(other)
    e.db.commit()
    with pytest.raises(render_mod.RenderError, match="no encontrado"):
        run_job(e, user_id=other.id)
    assert e.clip.render_state is RenderState.NONE and files(e) == []


def test_invalid_quality_and_unknown_clip(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    with pytest.raises(render_mod.RenderError, match="Calidad"):
        run_job(e, "ultra")
    with pytest.raises(render_mod.RenderError, match="no encontrado"):
        run_job(e, clip_id=99999)


# --- cortinillas (F6) ------------------------------------------------------------------------------------

def with_silences(e, silences):
    """Clip de 7 s (0,5–7,5 del vídeo) y silencios en segundos del vídeo."""
    from app.services import silences as silences_service

    e.clip.start, e.clip.end = 0.5, 7.5
    path = storage.project_dir(e.user.id, e.project.id) / "silences.json"
    silences_service.save_silences(silences, path)
    e.project.silences_path = storage.rel(path)
    e.db.commit()


SILENCE = [{"start": 5.6, "end": 6.4}]  # = 5,1–5,9 s del clip: centro en 5,5 s


def test_the_final_cortinilla_is_always_sent_and_the_initial_one_only_if_enabled(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    with_silences(e, SILENCE)
    run_job(e)
    r = e.fx.requests[0]
    assert "cortinilla" not in r and r["sfx"] is True
    assert r["outro"] == {"duration": 2.5, "color": "#DA2E09", "handle": "", "text": "", "like": "ME GUSTA", "subscribe": "SUSCRÍBETE"}
    assert "Cortinillas: inicio no, final 2.5 s → vídeo de 9.5 s" in log(e)


def test_initial_cortinilla_goes_to_the_first_valid_silence_after_the_intro(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, SILENCE)
    run_job(e)
    r = e.fx.requests[0]
    assert r["cortinilla"] == {"at": 5.5, "duration": 3.6, "color": "#DA2E09", "title": "", "kicker": ""}
    assert r["duration"] == 7.0 and "inicio a los 5.5 s del clip" in log(e) and "vídeo de 13.1 s" in log(e)
    assert e.clip.render_state is RenderState.DRAFT and e.clip.render_error is None


def test_a_manual_position_snaps_to_a_valid_silence(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True, cortinilla_at=5.0)
    with_silences(e, SILENCE)
    run_job(e)
    assert e.fx.requests[0]["cortinilla"]["at"] == 5.5


def test_no_valid_silence_skips_the_initial_cortinilla_with_a_warning(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, [])
    run_job(e)
    assert "cortinilla" not in e.fx.requests[0] and "outro" in e.fx.requests[0]
    assert e.clip.render_state is RenderState.DRAFT and e.clip.render_error.startswith("Aviso: no hay un silencio válido")


def test_template_values_feed_both_cortinillas_and_are_clamped(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, SILENCE)
    t = BrandTemplate(user_id=e.user.id, name="m", sfx=False, colors={"primary": "#112233"},
                      cortinilla={"title": "Spain Facts", "kicker": "ESPAÑA EN DATOS", "duration": 99, "handle": "@micanal",
                                  "outro_text": "Parte 2 en el canal", "outro_duration": "x", "like": "LIKE", "color": "rojo"})
    e.db.add(t)
    e.db.commit()
    e.clip.template_id = t.id
    e.db.commit()
    run_job(e)
    r = e.fx.requests[0]
    assert r["cortinilla"] == {"at": 5.5, "duration": 10.0, "color": "#112233", "title": "Spain Facts", "kicker": "ESPAÑA EN DATOS"}
    assert r["outro"] == {"duration": 2.5, "color": "#112233", "handle": "@micanal", "text": "Parte 2 en el canal", "like": "LIKE", "subscribe": "SUSCRÍBETE"}
    assert r["sfx"] is False


def test_the_logo_orbits_only_if_it_exists_on_disk(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, SILENCE)
    logo = storage.project_dir(e.user.id, e.project.id) / "logo.png"
    logo.write_bytes(b"png")
    t = BrandTemplate(user_id=e.user.id, name="m", logo_path=storage.rel(logo))
    e.db.add(t)
    e.db.commit()
    e.clip.template_id = t.id
    e.db.commit()
    run_job(e)
    assert e.fx.requests[0]["cortinilla"]["orbit"] == storage.rel(logo)
    logo.unlink()
    run_job(e)
    assert "orbit" not in e.fx.requests[1]["cortinilla"]


def test_the_thumbnail_never_falls_inside_the_cortinilla(client, tmp_path, monkeypatch, source_file):
    from app.pipeline import ffops

    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, [{"start": 1.0, "end": 1.6}, {"start": 5.6, "end": 6.4}])
    seen = []
    real = ffops.make_thumbnail
    monkeypatch.setattr(ffops, "make_thumbnail", lambda *a, **k: (seen.append(k["at"]), real(*a, **k))[1])
    run_job(e)
    at = e.fx.requests[0]["cortinilla"]["at"]
    assert seen and not (at <= seen[0] < at + 3.6)


def test_fallback_says_that_cortinillas_were_left_out(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, fx="unavailable", intro_enabled=True)
    with_silences(e, SILENCE)
    run_job(e)
    assert "sin cortinillas" in e.clip.render_error and e.clip.render_error.startswith("Aviso:")


def test_graphics_are_scheduled_and_sent_to_the_service(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file, intro_enabled=True)
    with_silences(e, SILENCE)  # cortinilla de inicio a 5,5 s del clip
    e.clip.graphics_json = [{"type": "keyword", "at": 3.0, "text": "Indultos"},
                            {"type": "keyword", "at": 5.0, "text": "Pisa la cortinilla"},   # ventana 4,5–7,0 cruza los 5,5 s: se recorta
                            {"type": "keyword", "at": 1.0, "text": "Choca con el gancho"},
                            {"type": "foo", "at": 4.0}]
    e.db.commit()
    run_job(e)
    sent = e.fx.requests[0]["graphics"]
    assert [(g["text"], g["at"]) for g in sent] == [("Indultos", 3.0), ("Pisa la cortinilla", 5.0)] or [g["text"] for g in sent] == ["Indultos"]
    assert all(g["lead"] >= 0.3 for g in sent)
    text = log(e)
    assert "Gráfico descartado (choca con el gancho)" in text and "motivo desconocido" in text
    assert e.clip.render_state is RenderState.DRAFT


def test_no_graphics_means_no_graphics_key(client, tmp_path, monkeypatch, source_file):
    e = setup(client, tmp_path, monkeypatch, source_file)
    run_job(e)
    assert "graphics" not in e.fx.requests[0]
