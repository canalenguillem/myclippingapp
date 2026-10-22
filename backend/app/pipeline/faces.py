"""Detección de caras por CPU con onnxruntime (modelo Ultra-Light-Fast-Generic-Face-Detector, ~1,5 MB, se descarga una vez a
`MEDIA_DIR/_models`). Devuelve las caras de un fotograma como cajas en fracciones del cuadro."""
from __future__ import annotations

import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services import storage

MODEL_NAME = "face-rfb-640.onnx"
MODEL_URL = "https://github.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB/raw/master/models/onnx/version-RFB-640.onnx"
MODEL_MIN_BYTES = 1_000_000
IN_W, IN_H = 640, 480
SCORE = 0.7
IOU = 0.3

_lock = threading.Lock()


class FaceError(RuntimeError):
    pass


def model_path() -> Path:
    return storage.media_root() / "_models" / MODEL_NAME


def ensure_model() -> Path:
    target = model_path()
    if target.is_file() and target.stat().st_size >= MODEL_MIN_BYTES:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as resp, part.open("wb") as out:  # noqa: S310 - URL fija
            out.write(resp.read())
        if part.stat().st_size < MODEL_MIN_BYTES:
            raise FaceError("El modelo de caras descargado está incompleto")
        part.replace(target)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise FaceError(f"No se pudo descargar el modelo de caras: {exc}") from exc
    return target


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(str(ensure_model()), sess_options=options, providers=["CPUExecutionProvider"])


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_o = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        order = order[1:][inter / (area_i + area_o - inter + 1e-9) <= IOU]
    return keep


def detect(frame: np.ndarray) -> list[dict]:
    """Caras de un fotograma RGB (alto, ancho, 3) como [{x, y, w, h, score}] en fracciones del cuadro (x, y = esquina)."""
    from PIL import Image

    h, w = frame.shape[:2]
    scale = min(IN_W / w, IN_H / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    canvas = np.full((IN_H, IN_W, 3), 127, dtype=np.uint8)
    resized = np.asarray(Image.fromarray(frame).resize((nw, nh), Image.BILINEAR))
    canvas[:nh, :nw] = resized                                          # sin deformar: se rellena abajo/derecha
    x = ((canvas.astype(np.float32) - 127.0) / 128.0).transpose(2, 0, 1)[None]
    with _lock:
        session = _session()
        scores, boxes = session.run(None, {session.get_inputs()[0].name: x})
    scores, boxes = scores[0][:, 1], boxes[0]
    mask = scores >= SCORE
    if not mask.any():
        return []
    boxes, scores = boxes[mask], scores[mask]
    keep = _nms(boxes, scores)
    out = []
    for i in keep:
        x1, y1, x2, y2 = boxes[i]
        # coordenadas normalizadas sobre el lienzo → sobre la imagen real
        fx1, fx2 = x1 * IN_W / nw, x2 * IN_W / nw
        fy1, fy2 = y1 * IN_H / nh, y2 * IN_H / nh
        fx1, fy1, fx2, fy2 = max(0.0, fx1), max(0.0, fy1), min(1.0, fx2), min(1.0, fy2)
        if fx2 > fx1 and fy2 > fy1:
            out.append({"x": float(fx1), "y": float(fy1), "w": float(fx2 - fx1), "h": float(fy2 - fy1), "score": float(scores[i])})
    return out
