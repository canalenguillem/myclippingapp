import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import media_sign, storage

router = APIRouter(tags=["media"])

# Defensa en profundidad: aunque la ruta esté bien firmada, solo se sirven medios (nunca words.json, .lock, etc.).
ALLOWED = {".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".webp"}


@router.get("/api/media/{path:path}")
def serve_media(path: str, exp: int, sig: str):
    """Sirve un fichero de MEDIA_DIR con soporte de Range (necesario para saltar en el vídeo)."""
    if not media_sign.verify(path, exp, sig):
        raise HTTPException(403, "Firma inválida o caducada")
    try:
        file = storage.absolute(path)
    except ValueError:
        raise HTTPException(404, "No encontrado")
    if file.suffix.lower() not in ALLOWED or not file.is_file():
        raise HTTPException(404, "No encontrado")
    return FileResponse(file, media_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                        headers={"Cache-Control": "private, max-age=300"})
