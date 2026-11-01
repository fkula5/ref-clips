"""Czas w UTC jako „naiwny” datetime (tak zapisuje go SQLite)."""
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
