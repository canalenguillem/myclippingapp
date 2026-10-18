import httpx
import pytest

from app.config import get_settings
from app.services import fx_client
from app.services.fx_client import FxClient, FxRenderFailed, FxUnavailable, make_fx_client


class Clock:
    """Reloj falso: dormir avanza el tiempo, así los tests no esperan de verdad."""

    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def now(self):
        return self.t


def make(responses, **kw):
    """Cliente cuyo servicio responde con `responses` en orden; una excepción se lanza como fallo de red."""
    requests, queue = [], list(responses)

    def handler(request):
        requests.append(request)
        item = queue.pop(0) if len(queue) > 1 else queue[0]  # la última respuesta se repite
        if isinstance(item, Exception):
            raise item
        return item

    clock = Clock()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return FxClient("http://fx:3000/", client=http, sleep=clock.sleep, clock=clock.now, **kw), requests, clock


def json_resp(status, body):
    return httpx.Response(status, json=body)


ID = "00000000-0000-0000-0000-000000000001"
START = json_resp(202, {"id": ID})
DONE = json_resp(200, {"status": "completed", "progress": 100, "seconds": 12.5})


def test_happy_path_reports_progress_and_sends_the_request():
    c, reqs, _ = make([START, json_resp(200, {"status": "running", "progress": 10}), json_resp(200, {"status": "running", "progress": 60}), DONE])
    seen = []
    result = c.render({"video": "a.mp4"}, on_progress=seen.append)
    assert result.seconds == 12.5 and seen == [0.1, 0.6]
    assert reqs[0].method == "POST" and str(reqs[0].url) == "http://fx:3000/renders"  # la barra final de la URL base se normaliza
    assert httpx.Request("POST", "http://x", json={"video": "a.mp4"}).content == reqs[0].content


def test_a_busy_service_is_retried_and_then_gives_up():
    c, reqs, clock = make([json_resp(409, {"error": "busy"}), json_resp(409, {"error": "busy"}), START, DONE])
    assert c.render({}).seconds == 12.5
    assert clock.sleeps[:2] == [2.0, 2.0]
    stuck, _, _ = make([json_resp(409, {"error": "busy"})], busy_wait=10)
    with pytest.raises(FxUnavailable, match="ocupado"):
        stuck.render({})


@pytest.mark.parametrize("response,exc,text", [
    (json_resp(400, {"error": "invalid_request"}), FxRenderFailed, "rechazó"),
    (json_resp(422, {"error": "video_not_found"}), FxRenderFailed, "rechazó"),
    (json_resp(500, {"error": "x"}), FxUnavailable, "500"),
    (httpx.ConnectError("rehusada"), FxUnavailable, "No se puede hablar"),
    (httpx.ReadTimeout("lento"), FxUnavailable, "No se puede hablar"),
])
def test_errors_when_starting(response, exc, text):
    c, _, _ = make([response])
    with pytest.raises(exc, match=text):
        c.render({})


def test_failed_and_cancelled_renders_raise():
    c, _, _ = make([START, json_resp(200, {"status": "failed", "error": "Chrome se cayó"})])
    with pytest.raises(FxRenderFailed, match="Chrome se cayó"):
        c.render({})
    c, _, _ = make([START, json_resp(200, {"status": "cancelled"})])
    with pytest.raises(FxRenderFailed, match="canceló"):
        c.render({})


def test_a_lost_render_means_unavailable():
    c, _, _ = make([START, json_resp(404, {"error": "not_found"})])
    with pytest.raises(FxUnavailable, match="perdió"):
        c.render({})


def test_polling_tolerates_a_few_network_errors_but_not_five_in_a_row():
    ok, _, _ = make([START] + [httpx.ConnectError("x")] * 4 + [DONE])
    assert ok.render({}).seconds == 12.5
    dead, _, _ = make([START] + [httpx.ConnectError("x")] * 5 + [DONE])
    with pytest.raises(FxUnavailable, match="dejó de responder"):
        dead.render({})
    # los errores deben ser CONSECUTIVOS: un acierto entre medias reinicia la cuenta
    flaky, _, _ = make([START] + [httpx.ConnectError("x")] * 4 + [json_resp(200, {"status": "running", "progress": 5})] + [httpx.ConnectError("x")] * 4 + [DONE])
    assert flaky.render({}).seconds == 12.5


def test_cancel_check_cancels_the_remote_render_and_propagates():
    class Stop(Exception):
        pass

    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        if calls["n"] == 2:
            raise Stop()

    c, reqs, _ = make([START, json_resp(200, {"status": "running", "progress": 5}), json_resp(200, {"status": "running", "progress": 6})])
    with pytest.raises(Stop):
        c.render({}, cancel_check=cancel)
    assert [r.method for r in reqs] == ["POST", "GET", "DELETE"] and reqs[-1].url.path == f"/renders/{ID}"


def test_max_seconds_cancels_and_raises():
    c, reqs, _ = make([START, json_resp(200, {"status": "running", "progress": 1})], max_seconds=5, poll_interval=1.0)
    with pytest.raises(FxUnavailable, match="tiempo máximo"):
        c.render({})
    assert reqs[-1].method == "DELETE"


def test_progress_is_clamped_to_0_1():
    c, _, _ = make([START, json_resp(200, {"status": "running", "progress": 250}), json_resp(200, {"status": "running", "progress": -4}), DONE])
    seen = []
    c.render({}, on_progress=seen.append)
    assert seen == [1.0, 0.0]


def test_a_cancel_that_fails_does_not_hide_the_original_error():
    class Stop(Exception):
        pass

    def cancel():
        raise Stop()

    c, _, _ = make([START, httpx.ConnectError("el servicio murió")])
    with pytest.raises(Stop):
        c.render({}, cancel_check=cancel)


def test_health():
    assert make([json_resp(200, {"ok": True})])[0].health() is True
    assert make([json_resp(500, {})])[0].health() is False
    assert make([httpx.ConnectError("x")])[0].health() is False
    assert make([httpx.Response(200, text="no es json")])[0].health() is False


def test_make_fx_client_depends_on_the_configured_url(monkeypatch):
    monkeypatch.setattr(get_settings(), "fx_worker_url", "")
    assert make_fx_client() is None
    monkeypatch.setattr(get_settings(), "fx_worker_url", "http://fx_worker:3000/")
    c = make_fx_client()
    assert isinstance(c, FxClient) and c.base == "http://fx_worker:3000"
