"""Límite de intentos de login: ventana deslizante por email y por IP, guardada en la BD (sobrevive a reinicios).

- Un fallo se cuenta igual exista o no el email (no se revela si una cuenta existe) y también si la cuenta está desactivada.
- Un login correcto borra los fallos de ese email. El bloqueo es temporal: caduca solo cuando los fallos salen de la ventana.
- IP real del cliente: detrás del proxy llega en `X-Forwarded-For`, pero esa cabecera la puede falsear quien llega de fuera.
  Solo se confía en las direcciones de la red privada (los proxies propios): se recorre la cadena de derecha a izquierda y
  la primera dirección NO privada es el cliente; si todas son privadas, el cliente es de la LAN y vale la primera.
"""
from __future__ import annotations

import ipaddress
import math
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import LoginFailure

PURGE_AFTER = timedelta(hours=24)


# Redes de CONFIANZA (los proxies propios): loopback, redes privadas, enlace local y CGNAT (VPN tipo Tailscale). No se usa
# `ipaddress.is_private`: incluye rangos de documentación y reservados que no son de nadie de confianza.
TRUSTED_NETWORKS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10",
)]


def _is_private(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_NETWORKS)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "desconocida"
    if not _is_private(peer):                      # sin proxy delante: la cabecera no vale nada
        return peer
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    valid = [p for p in chain if _is_valid_ip(p)]
    for candidate in reversed(valid):
        if not _is_private(candidate):
            return candidate
    return valid[0] if valid else peer


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _wait_seconds(times: list[datetime], maximum: int, window: int, now: datetime) -> int:
    """Segundos hasta que el número de fallos en la ventana baje de `maximum` (0 si no está bloqueado)."""
    if len(times) < maximum:
        return 0
    times = sorted(times)
    frees_at = times[len(times) - maximum] + timedelta(seconds=window)
    return max(1, math.ceil((frees_at - now).total_seconds()))


def _recent(db: Session, column, value: str, since: datetime) -> list[datetime]:
    return list(db.scalars(select(LoginFailure.created_at).where(column == value, LoginFailure.created_at > since)).all())


def check(db: Session, email: str, ip: str, *, now: datetime | None = None) -> None:
    """Lanza 429 (con Retry-After) si el email o la IP han agotado sus intentos."""
    s = get_settings()
    now = now or datetime.utcnow()
    since = now - timedelta(seconds=s.login_window_seconds)
    wait = max(
        _wait_seconds(_recent(db, LoginFailure.email, email, since), s.login_max_per_email, s.login_window_seconds, now),
        _wait_seconds(_recent(db, LoginFailure.ip, ip, since), s.login_max_per_ip, s.login_window_seconds, now),
    )
    if wait:
        minutes = math.ceil(wait / 60)
        raise HTTPException(429, f"Demasiados intentos fallidos. Espera {minutes} minuto{'s' if minutes != 1 else ''} e inténtalo de nuevo.",
                            headers={"Retry-After": str(wait)})


def record_failure(db: Session, email: str, ip: str, *, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    db.add(LoginFailure(email=email[:255], ip=ip[:45], created_at=now))
    db.execute(delete(LoginFailure).where(LoginFailure.created_at < now - PURGE_AFTER))   # limpieza oportunista
    db.commit()


def clear_email(db: Session, email: str) -> None:
    db.execute(delete(LoginFailure).where(LoginFailure.email == email))
    db.commit()


def failures_in_window(db: Session, email: str, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    since = now - timedelta(seconds=get_settings().login_window_seconds)
    return db.scalar(select(func.count()).select_from(LoginFailure).where(LoginFailure.email == email, LoginFailure.created_at > since)) or 0
