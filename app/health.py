"""The result has only names and states, no paths, sizes, versions or exception text, because the
endpoint is public.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.db import SessionLocal
from app.models import Setting
from app.storage import storage
from app.timeutil import utcnow

log = logging.getLogger("health")

HEARTBEAT_KEY = "worker_heartbeat"  # UTC string in TIME_FORMAT
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def record_heartbeat(db: Session, now: datetime | None = None) -> None:
    value = (now or utcnow()).strftime(TIME_FORMAT)
    if db.execute(update(Setting).where(Setting.key == HEARTBEAT_KEY).values(value=value)).rowcount == 0:
        try:
            db.add(Setting(key=HEARTBEAT_KEY, value=value))
            db.flush()
        except IntegrityError:  # a second worker created the row at the same moment
            db.rollback()
            db.execute(update(Setting).where(Setting.key == HEARTBEAT_KEY).values(value=value))
    db.commit()


def worker_state(db: Session, now: datetime | None = None) -> str:
    raw = db.scalar(select(Setting.value).where(Setting.key == HEARTBEAT_KEY))
    if not raw:
        return "missing"
    try:
        beat = datetime.strptime(raw, TIME_FORMAT)
    except ValueError:
        return "stale"
    age = ((now or utcnow()) - beat).total_seconds()
    return "ok" if age <= config.HEALTH_WORKER_STALE_SECONDS else "stale"


def disk_state() -> str:
    try:
        return "ok" if storage.free_bytes() >= config.HEALTH_DISK_MIN_BYTES else "low"
    except OSError:
        return "error"


def run_checks(now: datetime | None = None) -> dict[str, str]:
    checks = {"db": "ok", "worker": "unknown", "disk": disk_state()}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            checks["worker"] = worker_state(db, now)
    except Exception:  # noqa: BLE001 - details go to the log, not the response
        log.warning("Sprawdzenie bazy nie powiodło się", exc_info=True)
        checks["db"] = "error"
    return checks


def is_healthy(checks: dict[str, str]) -> bool:
    return all(state == "ok" for state in checks.values())


def main(argv: list[str]) -> int:
    if argv[1:] != ["worker"]:
        print("Użycie: python -m app.health worker", file=sys.stderr)
        return 2
    try:
        with SessionLocal() as db:
            state = worker_state(db)
    except Exception:  # noqa: BLE001
        return 1
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
