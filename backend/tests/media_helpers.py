"""Medios sintéticos y lecturas de fotogramas para los tests con ffmpeg real."""
import json
import subprocess
from pathlib import Path

from PIL import Image


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def probe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def frame_at(video, t, tmp_path, name="f"):
    png = Path(tmp_path) / f"{name}_{t}.png"
    run("ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(png))
    return Image.open(png).convert("RGB")


def make_source(path, seconds=8, size="1280x720", audio=True):
    """Vídeo horizontal liso y oscuro (sin píxeles blancos que confundan al análisis) con audio opcional."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x203040:s={size}:r=25:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    run(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return Path(path)
