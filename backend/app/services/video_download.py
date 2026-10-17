"""Descarga de YouTube con yt-dlp. Solo hosts de YouTube: la URL la manda el usuario."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}

FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b"


class DownloadError(RuntimeError):
    pass


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and (parsed.hostname or "").lower() in YOUTUBE_HOSTS


class _Logger:
    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log

    def debug(self, msg: str) -> None:  # yt-dlp manda tambien las lineas de progreso por aqui
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.log(f"[yt-dlp] {msg}")

    def error(self, msg: str) -> None:
        self.log(f"[yt-dlp] {msg}")


def probe(url: str, log: Callable[[str], None]) -> dict:
    opts = {"quiet": True, "noplaylist": True, "logger": _Logger(log), "skip_download": True}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(f"No se pudo leer el vídeo: {exc}") from exc
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise DownloadError("No se admiten directos ni estrenos pendientes")
    return info


def download(
    url: str, out_dir: Path, log: Callable[[str], None], on_progress: Callable[[float], None]
) -> Path:
    """Descarga a out_dir/source.mp4. `on_progress` recibe 0..1 y puede lanzar para cancelar."""

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "logger": _Logger(log),
        "progress_hooks": [hook],
        "retries": 5,
    }
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except DownloadError:
        raise
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "Cancelled":
            raise
        raise DownloadError(f"Fallo de descarga: {exc}") from exc
    video = out_dir / "source.mp4"
    if not video.exists():
        found = sorted(out_dir.glob("source.*"))
        if not found:
            raise DownloadError("yt-dlp no generó ningún fichero")
        video = found[0]
    return video


def extract_audio(video: Path, audio: Path) -> Path:
    """Audio mono 16 kHz de bitrate bajo: lo que necesita la transcripción, sube rápido."""
    cmd = ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not audio.exists():
        raise DownloadError(f"ffmpeg no pudo extraer el audio: {proc.stderr[-400:]}")
    return audio
