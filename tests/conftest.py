import os
import shutil
import tempfile

# Dane testowe w katalogu tymczasowym — musi być ustawione przed importem aplikacji.
_TMP = tempfile.mkdtemp(prefix="refclips-test-")
os.environ["REFCLIPS_DATA_DIR"] = _TMP

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import video as vid  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

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
def client(db):
    # bez context managera: nie uruchamia lifespan (migracje testujemy osobno)
    return TestClient(app)
