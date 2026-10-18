"""Imágenes de la librería: se validan, se normalizan a PNG y se recortan al contenido. Funciones puras, sin BD."""
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000        # límite de píxeles de la imagen original (protege la memoria frente a «bombas» de descompresión)
MAX_SIDE = 1200                # el lado mayor se reduce a esto: de sobra para un gráfico de 1080 px y barato de renderizar
ALLOWED = {"PNG", "JPEG", "WEBP"}


class AssetError(ValueError):
    pass


def process_upload(data: bytes) -> tuple[bytes, int, int]:
    """Devuelve (png, ancho, alto). Lanza AssetError con un mensaje para el usuario si la imagen no vale."""
    if not data:
        raise AssetError("El fichero está vacío")
    if len(data) > MAX_BYTES:
        raise AssetError(f"La imagen pesa más de {MAX_BYTES // (1024 * 1024)} MB")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        if fmt not in ALLOWED:
            raise AssetError("Solo se admiten imágenes PNG, JPG o WebP")
        if probe.width * probe.height > MAX_PIXELS:
            raise AssetError("La imagen tiene demasiados píxeles")
        img = Image.open(io.BytesIO(data))
        img.load()
    except AssetError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise AssetError("No se pudo leer la imagen (¿está dañada?)") from exc
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] < 255:                      # tiene transparencia: recortar al contenido visible
        box = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
        if box is None:
            raise AssetError("La imagen es totalmente transparente")
        pad = max(2, round(0.02 * max(box[2] - box[0], box[3] - box[1])))
        img = img.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad)))
    if max(img.size) > MAX_SIDE:
        scale = MAX_SIDE / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)                  # PNG nuevo: sin metadatos (EXIF, GPS…) del original
    return out.getvalue(), img.width, img.height
