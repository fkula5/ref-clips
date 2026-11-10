import json
import threading
from datetime import timedelta

import pytest

from app import config, health, worker
from app.db import SessionLocal
from app.models import Setting
from app.storage import storage
from app.timeutil import utcnow


@pytest.fixture()
def beat(db):
    health.record_heartbeat(db)


def test_healthy_stack_returns_200_and_only_status(anon_client, beat):
    r = anon_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["cache-control"] == "no-store"


def test_health_needs_no_login_or_csrf(anon_client, beat):
    r = anon_client.get("/health", follow_redirects=False)
    assert r.status_code == 200
    assert "set-cookie" not in r.headers
    assert anon_client.head("/health").status_code == 200


def test_missing_worker_heartbeat_is_503(anon_client, db):
    r = anon_client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "checks": {"db": "ok", "worker": "missing", "disk": "ok"}}
    assert r.headers["cache-control"] == "no-store"


def test_old_heartbeat_is_stale(anon_client, db):
    health.record_heartbeat(db, utcnow() - timedelta(seconds=config.HEALTH_WORKER_STALE_SECONDS + 5))
    r = anon_client.get("/health")
    assert r.status_code == 503
    assert r.json()["checks"] == {"db": "ok", "worker": "stale", "disk": "ok"}


def test_heartbeat_just_before_the_threshold_is_ok(anon_client, db):
    health.record_heartbeat(db, utcnow() - timedelta(seconds=config.HEALTH_WORKER_STALE_SECONDS - 5))
    assert anon_client.get("/health").status_code == 200


def test_unreadable_heartbeat_is_stale(anon_client, db):
    db.add(Setting(key=health.HEARTBEAT_KEY, value="wczoraj"))
    db.commit()
    assert anon_client.get("/health").json()["checks"]["worker"] == "stale"


def test_database_unavailable(anon_client, beat, monkeypatch):
    def boom():
        raise RuntimeError("sqlite3.OperationalError: unable to open database file /data/ref-clips.db")
    monkeypatch.setattr(health, "SessionLocal", boom)
    r = anon_client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "checks": {"db": "error", "worker": "unknown", "disk": "ok"}}
    assert "sqlite" not in r.text and "/data" not in r.text


def test_low_disk_space(anon_client, beat, monkeypatch):
    monkeypatch.setattr(storage, "free_bytes", lambda: config.HEALTH_DISK_MIN_BYTES - 1)
    r = anon_client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "checks": {"db": "ok", "worker": "ok", "disk": "low"}}
    monkeypatch.setattr(storage, "free_bytes", lambda: config.HEALTH_DISK_MIN_BYTES)
    assert anon_client.get("/health").status_code == 200


def test_disk_read_error(anon_client, beat, monkeypatch):
    def boom():
        raise OSError("/data: Input/output error")
    monkeypatch.setattr(storage, "free_bytes", boom)
    r = anon_client.get("/health")
    assert r.json()["checks"]["disk"] == "error"
    assert "/data" not in r.text


def test_response_contains_no_details(anon_client, db, monkeypatch):
    monkeypatch.setattr(storage, "free_bytes", lambda: 0)
    text = anon_client.get("/health").text
    assert set(json.loads(text)) == {"status", "checks"}
    for forbidden in (str(config.DATA_DIR), "bytes", "version", "Traceback", "ref-clips.db"):
        assert forbidden not in text


def test_health_is_not_browser_navigation(client, beat):
    assert "/health" not in client.get("/").text


def test_heartbeat_write_updates_a_single_row(db):
    for _ in range(3):
        health.record_heartbeat(db)
    rows = db.query(Setting).filter(Setting.key == health.HEARTBEAT_KEY).count()
    assert rows == 1


def test_worker_cli_exit_code(db, capsys):
    assert health.main(["health", "worker"]) == 1
    health.record_heartbeat(db)
    assert health.main(["health", "worker"]) == 0
    assert health.main(["health"]) == 2


def test_heartbeat_loop_writes_and_survives_an_error(db, monkeypatch):
    stop = threading.Event()
    calls = []
    real = health.record_heartbeat

    def flaky(session, now=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        real(session, now)
        if len(calls) >= 3:
            stop.set()

    monkeypatch.setattr(health, "record_heartbeat", flaky)
    t = threading.Thread(target=worker.heartbeat_loop, args=(stop, 0.01), daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive()
    assert len(calls) >= 3
    with SessionLocal() as s:
        assert health.worker_state(s) == "ok"


def test_version_in_footer_only_for_logged_in_users_and_not_in_health(client, anon_client, beat, monkeypatch):
    from app import web
    monkeypatch.setitem(web.env.globals, "app_version", "v9.8.7")
    assert 'class="app-version">ref-clips v9.8.7' in client.get("/").text
    assert "v9.8.7" not in anon_client.get("/login").text
    assert "v9.8.7" not in anon_client.get("/health").text
    assert config.VERSION == "dev"
