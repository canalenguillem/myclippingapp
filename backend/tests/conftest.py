import os

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123456")
os.environ.setdefault("APP_ENCRYPTION_KEY", "3RBkGCEr0Sg3KoUfT_4vwsyGE9NJdxP9RfX5BsAh6SY=")  # clave Fernet solo para tests
if os.environ.get("RUN_MARIADB_TESTS") != "1":  # las pruebas de carrera necesitan la MariaDB real
    os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.db import models  # noqa: F401
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        c.session_factory = Session
        yield c
    app.dependency_overrides.clear()
