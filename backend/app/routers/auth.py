from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ratelimit
from app.auth.deps import CSRF_COOKIE, SESSION_COOKIE, current_user
from app.auth.security import SESSION_TTL, hash_password, make_session_token, new_csrf, verify_password
from app.config import get_settings
from app.db import get_db
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Hash de relleno: login con email inexistente tarda lo mismo que con uno real.
_DUMMY_HASH = hash_password("relleno-para-igualar-tiempos")


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class RegisterIn(Credentials):
    name: str = Field(default="", max_length=120)


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str


def _set_session(response: Response, user: User) -> None:
    csrf = new_csrf()
    secure = get_settings().public_base_url.startswith("https")
    response.set_cookie(
        SESSION_COOKIE, make_session_token(user.id, csrf), max_age=SESSION_TTL,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    # La lee el JS para mandarla en X-CSRF-Token, asi que NO es httpOnly.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_TTL, httponly=False, samesite="lax", secure=secure, path="/")


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    is_first = db.scalar(select(func.count()).select_from(User)) == 0
    if not is_first and not get_settings().allow_registration:
        raise HTTPException(403, "Registro cerrado")
    user = User(
        email=body.email.lower(), password_hash=hash_password(body.password), name=body.name,
        role="admin" if is_first else "user",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ese email ya esta registrado")
    _set_session(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    email, ip = body.email.lower(), ratelimit.client_ip(request)
    ratelimit.check(db, email, ip)                       # bloqueado: ni se comprueba la contraseña
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        ratelimit.record_failure(db, email, ip)
        raise HTTPException(401, "Email o contrasena incorrectos")
    ratelimit.clear_email(db, email)
    _set_session(response, user)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
