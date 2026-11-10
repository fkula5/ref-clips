"""The DB always holds UTC as a naive datetime (how SQLite stores it); the local timezone is only for
display.
"""
from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import config

DEFAULT_LOCAL_FORMAT = "%d.%m.%Y %H:%M"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@lru_cache(maxsize=8)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A bad name in REFCLIPS_TIMEZONE must not break pages: fall back to the default zone.
        return ZoneInfo("Europe/Warsaw")


def local_tz() -> ZoneInfo:
    return _zone(config.TIMEZONE)


def to_local(value: datetime) -> datetime:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(local_tz())


def local(value: datetime | date | None, fmt: str = DEFAULT_LOCAL_FORMAT) -> str:
    """A plain `date` (e.g. the match date) has no time, so it is not converted."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = to_local(value)
    return value.strftime(fmt)
