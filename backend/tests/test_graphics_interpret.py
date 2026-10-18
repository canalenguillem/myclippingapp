import pytest
from fastapi.testclient import TestClient

from app.routers import graphics as graphics_router
from app.services import graphics_interpret as gi
from tests.test_clips_api import _login, _project


@pytest.mark.parametrize("text,entry,effect,style", [
    ("el guante da un golpe y explota", "punch", "explode", None),
    ("Entra con un puñetazo y se vaporiza", "punch", "vaporize", None),
    ("cae desde arriba y se parte en dos", "drop", "break", None),
    ("entra desde la izquierda", "slide_left", None, None),
    ("sale por la derecha y estalla", "slide_right", "explode", None),
    ("la hucha se desintegra como polvo", None, "vaporize", None),
    ("tarjeta de papel que revienta", None, "explode", "card"),
    ("en silueta, se rompe", None, "break", "silhouette"),
    ("rojo de marca", None, None, "red"),
    ("EXPLOTA", None, "explode", None),
    ("un golpe desde la izquierda", "punch", None, None),           # el golpe manda sobre el deslizamiento
    ("Aparece sin más", None, None, None),
])
def test_keywords_cover_the_common_spanish_phrasings(text, entry, effect, style):
    r = gi.interpret(text, llm=None)
    assert (r["entry"], r["effect"], r["style"]) == (entry, effect, style)


def test_understood_text_names_the_pieces_in_spanish():
    r = gi.interpret("el guante da un golpe y explota", llm=None)
    assert r["source"] == "keywords" and r["understood"] == "entra de un golpe · explota"
    none = gi.interpret("algo raro", llm=None)
    assert none["source"] == "none" and none["understood"] == "nada reconocido"
    assert gi.interpret("", llm=None)["source"] == "none"


def test_the_model_is_asked_only_when_the_keywords_find_nothing_and_its_answer_is_validated():
    calls = []

    def fake(text):
        calls.append(text)
        return {"entry": "drop", "effect": "volar", "style": "card", "extra": 1}      # «volar» no existe: se descarta; «extra» se ignora

    r = gi.interpret("que se desplome con elegancia sobre la pantalla", llm=fake)
    assert calls and r["source"] == "llm" and (r["entry"], r["effect"], r["style"]) == ("drop", None, "card")
    calls.clear()
    assert gi.interpret("explota", llm=fake)["source"] == "keywords" and not calls         # con palabras clave no se llama al modelo
    junk = gi.interpret("frase sin sentido", llm=lambda t: {"entry": "teletransporte"})
    assert junk["source"] == "none" and junk["entry"] is None
    assert gi.interpret("frase sin sentido", llm=lambda t: None)["source"] == "none"
    assert gi.interpret("frase sin sentido", llm=lambda t: "no es un dict")["source"] == "none"


def test_default_llm_without_a_key_or_on_failure_returns_none(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    assert gi.default_llm("hola") is None
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-falsa")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **k: (_ for _ in ()).throw(RuntimeError("sin red")))
    assert gi.default_llm("hola") is None


def test_endpoint_needs_login_and_limits_the_text(client, tmp_path, monkeypatch):
    h, db, p = _project(client, tmp_path, monkeypatch)
    monkeypatch.setattr(graphics_router.graphics_interpret, "default_llm", lambda text: None)
    r = client.post("/api/graphics/interpret", json={"text": "golpe y explota"}, headers=h)
    assert r.status_code == 200 and (r.json()["entry"], r.json()["effect"]) == ("punch", "explode")
    assert client.post("/api/graphics/interpret", json={"text": "x" * 301}, headers=h).status_code == 422
    assert client.post("/api/graphics/interpret", json={"text": "a", "otro": 1}, headers=h).status_code == 422
    assert TestClient(client.app).post("/api/graphics/interpret", json={"text": "a"}).status_code in (401, 403)
