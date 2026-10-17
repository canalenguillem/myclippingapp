from typing import TypeVar

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.db.models import User

from .security import csrf_ok, read_session_token

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    claims = read_session_token(token) if token else None
    if not claims:
        raise HTTPException(401, "No autenticado")
    if request.method not in SAFE_METHODS and not csrf_ok(
        request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token"), claims.get("csrf", "")
    ):
        raise HTTPException(403, "CSRF invalido")
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "No autenticado")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Solo admin")
    return user


T = TypeVar("T")


def get_owned(db: Session, model: type[T], obj_id: int, user: User) -> T:
    """Devuelve el recurso solo si es del usuario; si no, 404 (no revela que existe)."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user.id:
        raise HTTPException(404, "No encontrado")
    return obj
