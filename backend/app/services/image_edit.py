"""Editor de imágenes de la librería: quitar el fondo (segmentación con onnxruntime, modelo u2net_human_seg de rembg) y
voltear, rotar y recortar en rectángulo, óvalo o círculo. Todo con Pillow/numpy; el modelo (~170 MB) se baja una vez a
`MEDIA_DIR/_models`. Funciones puras salvo la descarga del modelo; `segment` es la única que toca el modelo (los tests la sustituyen)."""
from __future__ import annotations

import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from . import storage

MODEL_NAME = "u2net_human_seg.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx"
MODEL_MIN_BYTES = 100 * 1024 * 1024
SIZE = 320                      # lado de entrada del modelo
SUPERSAMPLE = 4                 # antialias de la máscara de óvalo
PREVIEW_SIDE = 640

_lock = threading.Lock()        # un solo uso del modelo a la vez (RAM y CPU)


class EditError(ValueError):
    pass


def model_path() -> Path:
    return storage.media_root() / "_models" / MODEL_NAME


def ensure_model() -> Path:
    """Descarga el modelo la primera vez (atómico: .part y renombrar)."""
    target = model_path()
    if target.is_file() and target.stat().st_size >= MODEL_MIN_BYTES:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as resp, part.open("wb") as out:  # noqa: S310 - URL fija
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        if part.stat().st_size < MODEL_MIN_BYTES:
            raise EditError("El modelo descargado está incompleto")
        part.replace(target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise EditError(f"No se pudo descargar el modelo para quitar el fondo: {exc}") from exc
    return target


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(ensure_model()), sess_options=options, providers=["CPUExecutionProvider"])


def segment(rgb: Image.Image) -> Image.Image:
    """Máscara «persona» (modo L, mismo tamaño) de una imagen RGB."""
    arr = np.asarray(rgb.resize((SIZE, SIZE), Image.LANCZOS), dtype=np.float32)
    arr = arr / max(float(arr.max()), 1e-6)
    arr = (arr - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    with _lock:
        session = _session()
        pred = session.run(None, {session.get_inputs()[0].name: arr.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    pred = (pred - pred.min()) / (pred.max() - pred.min() + 1e-8)
    return Image.fromarray((pred * 255).astype("uint8")).resize(rgb.size, Image.LANCZOS)


def remove_background(img: Image.Image) -> Image.Image:
    """RGBA con el fondo transparente. Lo que ya era transparente se mantiene."""
    rgba = img.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat.alpha_composite(rgba)
    mask = segment(flat.convert("RGB"))
    out = rgba.copy()
    out.putalpha(ImageChops.multiply(rgba.getchannel("A"), mask))
    return out


def _ellipse_mask(size: tuple[int, int]) -> Image.Image:
    w, h = size
    big = Image.new("L", (w * SUPERSAMPLE, h * SUPERSAMPLE), 0)
    ImageDraw.Draw(big).ellipse((0, 0, w * SUPERSAMPLE - 1, h * SUPERSAMPLE - 1), fill=255)
    return big.resize((w, h), Image.LANCZOS)


def apply_edits(img: Image.Image, *, flip_h: bool = False, flip_v: bool = False, rotate: float = 0.0,
                crop: dict | None = None, shape: str = "rect") -> Image.Image:
    """Orden fijo: voltear → rotar (el lienzo crece, esquinas transparentes) → recortar (fracciones 0–1 de la imagen ya
    girada) → forma (rect | ellipse | circle: el círculo recorta un cuadrado centrado en la caja)."""
    if shape not in ("rect", "ellipse", "circle"):
        raise EditError(f"Forma no válida: {shape!r}")
    out = img.convert("RGBA")
    if flip_h:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_v:
        out = out.transpose(Image.FLIP_TOP_BOTTOM)
    if rotate % 360:
        out = out.rotate(-rotate, resample=Image.BICUBIC, expand=True)    # sentido horario para ángulos positivos, como en pantalla
    if crop:
        x, y, w, h = (float(crop[k]) for k in ("x", "y", "w", "h"))
        if not (0 <= x < 1 and 0 <= y < 1 and 0.02 <= w <= 1 and 0.02 <= h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
            raise EditError("La caja de recorte no es válida")
        left, top = round(x * out.width), round(y * out.height)
        right, bottom = min(out.width, left + max(1, round(w * out.width))), min(out.height, top + max(1, round(h * out.height)))
        out = out.crop((left, top, right, bottom))
    if shape == "circle":
        side = min(out.size)
        left, top = (out.width - side) // 2, (out.height - side) // 2
        out = out.crop((left, top, left + side, top + side))
    if shape in ("ellipse", "circle"):
        out.putalpha(ImageChops.multiply(out.getchannel("A"), _ellipse_mask(out.size)))
    return out


def thumbnail(img: Image.Image, side: int = PREVIEW_SIDE) -> Image.Image:
    out = img.copy()
    out.thumbnail((side, side), Image.LANCZOS)
    return out
