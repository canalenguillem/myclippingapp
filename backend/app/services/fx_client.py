"""Cliente del servicio de render (fx_worker, HyperFrames).

Manda un render, sigue su progreso y permite cancelarlo. Distingue dos clases de fallo porque el job de render
reacciona igual a ambas (cae al camino ASS de ffmpeg) pero conviene dejar claro en el log qué pasó:
  - FxUnavailable: no se pudo hablar con el servicio (sin URL, conexión rehusada, 5xx, se perdió el render…).
  - FxRenderFailed: el servicio contestó pero el render falló o rechazó la petición.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.config import get_settings


class FxError(RuntimeError):
    pass


class FxUnavailable(FxError):
    pass


class FxRenderFailed(FxError):
    pass


@dataclass
class FxResult:
    seconds: float | None


class FxClient:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        poll_interval: float = 1.0,
        busy_wait: float = 120.0,
        max_seconds: float = 1800.0,
        max_poll_errors: int = 5,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.http = client or httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))
        self.poll_interval, self.busy_wait, self.max_seconds = poll_interval, busy_wait, max_seconds
        self.max_poll_errors, self.sleep, self.clock = max_poll_errors, sleep, clock

    def health(self) -> bool:
        try:
            r = self.http.get(f"{self.base}/health", timeout=httpx.Timeout(5.0, connect=2.0))
            return r.status_code == 200 and bool(r.json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    # --- API ----------------------------------------------------------------------------------------
    def preview(self, request: dict) -> dict:
        """Vista previa de una plantilla: {html, duration}. No ocupa el carril de render."""
        try:
            r = self.http.post(f"{self.base}/previews", json=request, timeout=httpx.Timeout(20.0, connect=3.0))
        except httpx.HTTPError as exc:
            raise FxUnavailable(f"No se puede hablar con el servicio de render ({type(exc).__name__})") from exc
        if r.status_code >= 500:
            raise FxUnavailable(f"El servicio de render respondió {r.status_code}")
        if r.status_code != 200:
            raise FxRenderFailed(f"Petición de vista previa rechazada ({r.status_code}): {r.text[:300]}")
        return r.json()

    def render(
        self,
        request: dict,
        *,
        on_progress: Callable[[float], None] | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> FxResult:
        """Lanza el render y espera a que termine. `on_progress` recibe 0..1. `cancel_check` puede lanzar para
        cancelar: el render se cancela también en el servicio."""
        render_id = self._start(request, cancel_check)
        return self._wait(render_id, on_progress, cancel_check)

    def _start(self, request: dict, cancel_check: Callable[[], None] | None) -> str:
        deadline = self.clock() + self.busy_wait
        while True:
            try:
                r = self.http.post(f"{self.base}/renders", json=request)
            except httpx.HTTPError as exc:
                raise FxUnavailable(f"No se puede hablar con el servicio de render ({type(exc).__name__})") from exc
            if r.status_code == 202:
                return r.json()["id"]
            if r.status_code == 409:  # ocupado: un render anterior que aún no ha acabado
                if self.clock() >= deadline:
                    raise FxUnavailable("El servicio de render sigue ocupado")
                if cancel_check:
                    cancel_check()
                self.sleep(2.0)
                continue
            if r.status_code >= 500:
                raise FxUnavailable(f"El servicio de render respondió {r.status_code}")
            raise FxRenderFailed(f"El servicio rechazó la petición ({r.status_code}): {r.text[:300]}")

    def _wait(self, render_id: str, on_progress, cancel_check) -> FxResult:
        started, errors = self.clock(), 0
        while True:
            if cancel_check:
                try:
                    cancel_check()
                except BaseException:
                    self._cancel(render_id)
                    raise
            try:
                r = self.http.get(f"{self.base}/renders/{render_id}")
                errors = 0
            except httpx.HTTPError as exc:
                errors += 1
                if errors >= self.max_poll_errors:
                    raise FxUnavailable("El servicio de render dejó de responder durante el render") from exc
                self.sleep(self.poll_interval)
                continue
            if r.status_code == 404:
                raise FxUnavailable("El servicio de render perdió el render (¿se reinició?)")
            if r.status_code != 200:
                raise FxUnavailable(f"El servicio de render respondió {r.status_code}")
            rec = r.json()
            status = rec.get("status")
            if status == "completed":
                return FxResult(seconds=rec.get("seconds"))
            if status == "failed":
                raise FxRenderFailed(rec.get("error") or "El render falló en el servicio")
            if status == "cancelled":
                raise FxRenderFailed("El servicio canceló el render")
            if on_progress:
                on_progress(max(0.0, min(1.0, float(rec.get("progress", 0)) / 100)))
            if self.clock() - started > self.max_seconds:
                self._cancel(render_id)
                raise FxUnavailable("El render superó el tiempo máximo")
            self.sleep(self.poll_interval)

    def _cancel(self, render_id: str) -> None:
        try:
            self.http.delete(f"{self.base}/renders/{render_id}", timeout=httpx.Timeout(5.0, connect=2.0))
        except httpx.HTTPError:
            pass  # el servicio ya no responde: no hay nada más que cancelar


def make_fx_client() -> FxClient | None:
    """None si no hay servicio configurado (FX_WORKER_URL vacío): el render usa directamente el camino ASS."""
    url = get_settings().fx_worker_url
    return FxClient(url) if url else None
