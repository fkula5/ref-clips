import os
import shutil
import tempfile

# Test data in a temp dir: must be set before the app is imported.
_TMP = tempfile.mkdtemp(prefix="refclips-test-")
os.environ["REFCLIPS_DATA_DIR"] = _TMP

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import accounts, config  # noqa: E402
from app import video as vid  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from tests.helpers import make_user, seed_sheet_elements  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not vid.ffmpeg_available(), reason="brak ffmpeg/ffprobe")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for sub in ("uploads", "proxies", "clips", "scoresheets"):
        for path in (config.DATA_DIR / sub).glob("*"):
            path.unlink(missing_ok=True)
    with SessionLocal() as session:
        seed(session)
        seed_sheet_elements(session)
        yield session


@pytest.fixture()
def mailbox(monkeypatch):
    """In-memory outbox and a configured public address; nothing is ever sent."""
    from app import mail
    monkeypatch.setattr(config, "MAIL_MODE", "memory")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://klipy.example.pl")
    monkeypatch.setattr(config, "MAIL_FROM", "klipy@example.pl")
    mail.OUTBOX.clear()
    mail._logged.clear()
    yield mail.OUTBOX
    mail.OUTBOX.clear()
    mail._logged.clear()


@pytest.fixture()
def anon_client(db):
    """No context manager: lifespan (migrations) is not started; migrations are tested separately."""
    return TestClient(app)


def login_client(db, user) -> TestClient:
    token = accounts.create_session(db, user)
    client = TestClient(app)
    client.cookies.set(config.SESSION_COOKIE, token)
    client.headers["X-CSRF-Token"] = accounts.get_session(db, token).csrf_token
    return client


@pytest.fixture()
def make_client(db):
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
    return admin[0]
