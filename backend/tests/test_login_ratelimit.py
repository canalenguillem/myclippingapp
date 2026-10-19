from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import ratelimit
from app.config import get_settings
from app.db.models import LoginFailure

PW = "una-clave-larga-1"


def request(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


# --- IP real ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("peer,xff,expected", [
    ("172.18.0.5", "203.0.113.9", "203.0.113.9"),                    # nginx del frontend + cliente de Internet
    ("172.18.0.5", "203.0.113.9, 192.168.1.10", "203.0.113.9"),      # y su proxy de la LAN añadido a la derecha
    ("172.18.0.5", "6.6.6.6, 203.0.113.9, 192.168.1.10", "203.0.113.9"),   # el atacante falsea «6.6.6.6» a la izquierda: no vale
    ("172.18.0.5", "192.168.1.30", "192.168.1.30"),                  # cliente de la LAN
    ("172.18.0.5", "192.168.1.30, 192.168.1.10", "192.168.1.30"),    # todo privado: el primero
    ("172.18.0.5", None, "172.18.0.5"),                              # sin cabecera: el vecino
    ("172.18.0.5", "basura, no-es-ip", "172.18.0.5"),
    ("203.0.113.50", "1.2.3.4", "203.0.113.50"),                     # llegada directa desde fuera: la cabecera se ignora
    ("127.0.0.1", "2001:db8::1", "2001:db8::1"),
])
def test_client_ip_trusts_only_private_proxies(peer, xff, expected):
    assert ratelimit.client_ip(request(peer, xff)) == expected


# --- ventana deslizante ----------------------------------------------------------------------------

def fails(db, email, ip, ages):
    now = datetime(2026, 1, 1, 12, 0, 0)
    for age in ages:
        db.add(LoginFailure(email=email, ip=ip, created_at=now - timedelta(seconds=age)))
    db.commit()
    return now


def test_blocks_after_the_limit_and_unblocks_when_old_failures_leave_the_window(client):
    db = client.session_factory()
    now = fails(db, "a@x.com", "1.1.1.1", [10, 60, 120, 300, 600])          # 5 fallos, el más viejo de hace 10 min
    with pytest.raises(HTTPException) as exc:
        ratelimit.check(db, "a@x.com", "1.1.1.1", now=now)
    assert exc.value.status_code == 429 and exc.value.headers["Retry-After"] == "300"      # 900 − 600 s hasta que salga el más viejo
    assert "5 minutos" in exc.value.detail
    ratelimit.check(db, "a@x.com", "1.1.1.1", now=now + timedelta(seconds=301))            # ya no bloquea
    ratelimit.check(db, "otro@x.com", "2.2.2.2", now=now)                                  # otro email y otra IP, no
    ratelimit.check(db, "a@x.com", "9.9.9.9", now=now + timedelta(seconds=301))


def test_four_failures_do_not_block_and_old_ones_do_not_count(client):
    db = client.session_factory()
    now = fails(db, "a@x.com", "1.1.1.1", [10, 20, 30, 40, 2000])          # 4 recientes + 1 fuera de ventana
    ratelimit.check(db, "a@x.com", "1.1.1.1", now=now)


def test_the_ip_limit_is_looser_but_still_exists(client):
    db = client.session_factory()
    now = fails(db, "x@x.com", "5.5.5.5", [1] * 19)
    ratelimit.check(db, "y@x.com", "5.5.5.5", now=now)                      # 19 de 20
    db.add(LoginFailure(email="z@x.com", ip="5.5.5.5", created_at=now - timedelta(seconds=2)))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        ratelimit.check(db, "nuevo@x.com", "5.5.5.5", now=now)              # ya es el vigésimo: bloquea aunque el email sea otro
    assert exc.value.status_code == 429


# --- a través de la API ----------------------------------------------------------------------------

def proxied(client):
    """Cliente cuyo vecino TCP es el nginx de Docker (IP privada): solo así se tiene en cuenta X-Forwarded-For."""
    return TestClient(client.app, client=("172.18.0.5", 50000))


def register(client, email="a@x.com"):
    assert client.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201


def login(c, email="a@x.com", password=PW, ip="203.0.113.7"):
    return c.post("/api/auth/login", json={"email": email, "password": password}, headers={"X-Forwarded-For": ip})


def test_five_wrong_passwords_lock_the_account_even_for_the_right_one_then_it_recovers(client):
    register(client)
    c = proxied(client)
    for _ in range(5):
        assert login(c, password="otra-clave-larga").status_code == 401
    r = login(c)                                                             # la contraseña BUENA, pero está bloqueado
    assert r.status_code == 429 and "Demasiados intentos" in r.json()["detail"] and int(r.headers["Retry-After"]) > 0
    db = client.session_factory()
    db.query(LoginFailure).update({"created_at": datetime.utcnow() - timedelta(minutes=16)})   # pasa el tiempo
    db.commit()
    assert login(c).status_code == 200


def test_a_successful_login_resets_the_counter(client):
    register(client)
    c = proxied(client)
    for _ in range(4):
        login(c, password="otra-clave-larga")
    assert login(c).status_code == 200
    for _ in range(4):
        assert login(c, password="otra-clave-larga").status_code == 401     # vuelve a empezar de cero: no se llega a 5
    assert login(c).status_code == 200


def test_unknown_emails_are_limited_the_same_way_and_leak_nothing(client):
    register(client)
    c = proxied(client)
    codes = [login(c, email="nadie@x.com", password="otra-clave-larga").status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    real = login(c, email="a@x.com", password="otra-clave-larga")           # el real responde igual que el inexistente
    assert real.status_code == 401 and real.json() == {"detail": "Email o contrasena incorrectos"}


def test_one_ip_cannot_try_many_emails_forever_and_a_forged_header_does_not_help(client):
    register(client)
    c = proxied(client)
    get_settings().login_max_per_ip, old = 6, get_settings().login_max_per_ip
    try:
        for i in range(6):
            login(c, email=f"u{i}@x.com", password="otra-clave-larga", ip="198.51.100.4")
        assert login(c, email="a@x.com", ip="198.51.100.4").status_code == 429
        # el cliente falsea una IP a la izquierda, pero la que cuenta es la que añade el proxy a la derecha
        forged = c.post("/api/auth/login", json={"email": "a@x.com", "password": PW}, headers={"X-Forwarded-For": "7.7.7.7, 198.51.100.4"})
        assert forged.status_code == 429
        assert login(c, email="a@x.com", ip="198.51.100.99").status_code == 200   # otra IP distinta sí entra
    finally:
        get_settings().login_max_per_ip = old


def test_a_deactivated_account_counts_as_a_failure(client):
    register(client)
    from app.db.models import User
    db = client.session_factory()
    db.query(User).update({"is_active": False})
    db.commit()
    c = proxied(client)
    assert [login(c).status_code for _ in range(6)] == [401] * 5 + [429]


def test_old_failures_are_purged(client):
    db = client.session_factory()
    db.add(LoginFailure(email="viejo@x.com", ip="1.1.1.1", created_at=datetime.utcnow() - timedelta(days=3)))
    db.commit()
    ratelimit.record_failure(db, "nuevo@x.com", "2.2.2.2")
    assert db.query(LoginFailure).count() == 1


def test_a_direct_connection_cannot_choose_its_own_ip(client):
    register(client)
    direct = TestClient(client.app, client=("203.0.113.77", 40000))          # llega de fuera, sin proxy
    for i in range(5):
        assert direct.post("/api/auth/login", json={"email": "a@x.com", "password": "otra-clave-larga"}, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 401
    assert direct.post("/api/auth/login", json={"email": "a@x.com", "password": PW}, headers={"X-Forwarded-For": "10.9.9.9"}).status_code == 429
