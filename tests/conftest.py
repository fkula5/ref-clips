import os
import shutil
import tempfile

# Dane testowe w katalogu tymczasowym — musi być ustawione przed importem aplikacji.
_TMP = tempfile.mkdtemp(prefix="refclips-test-")
os.environ["REFCLIPS_DATA_DIR"] = _TMP

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, config  # noqa: E402
from app import video as vid  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from tests.helpers import make_user  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not vid.ffmpeg_available(), reason="brak ffmpeg/ffprobe")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
        yield session


@pytest.fixture()
def anon_client(db):
    """Klient bez sesji. Bez context managera: nie uruchamia lifespan (migracje testujemy osobno)."""
    return TestClient(app)


def login_client(db, user) -> TestClient:
    """Klient zalogowany jako `user` (sesja założona wprost w bazie) z tokenem CSRF w nagłówku."""
    token = accounts.create_session(db, user)
    client = TestClient(app)
    client.cookies.set(config.SESSION_COOKIE, token)
    client.headers["X-CSRF-Token"] = accounts.get_session(db, token).csrf_token
    return client


@pytest.fixture()
def make_client(db):
    """Fabryka: make_client("coach", "referee") -> (zalogowany klient, użytkownik)."""
    counter = iter(range(1, 1000))

    def factory(*roles, name=None, email=None):
        n = next(counter)
        user = make_user(db, roles, email=email or f"user{n}@example.com", name=name or f"Użytkownik {n}")
        return login_client(db, user), user

    return factory


@pytest.fixture()
def admin(make_client):
    return make_client("admin", name="Admin Testowy", email="admin@example.com")


@pytest.fixture()
def client(admin):
    """Domyślny klient testów API: zalogowany administrator (pełne uprawnienia)."""
    return admin[0]
