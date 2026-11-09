"""Czas: w bazie zawsze UTC jako „naiwny” datetime (tak zapisuje go SQLite); strefa lokalna tylko do wyświetlania."""
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
        # Błędna nazwa w REFCLIPS_TIMEZONE nie może wywrócić stron — wracamy do domyślnej strefy.
        return ZoneInfo("Europe/Warsaw")


def local_tz() -> ZoneInfo:
    return _zone(config.TIMEZONE)


def to_local(value: datetime) -> datetime:
    """Chwila z bazy (UTC; naiwna traktowana jako UTC) w strefie z konfiguracji, z czasem letnim/zimowym."""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return aware.astimezone(local_tz())


def local(value: datetime | date | None, fmt: str = DEFAULT_LOCAL_FORMAT) -> str:
    """Filtr szablonów: `{{ x.created_at|local("%d.%m.%Y %H:%M") }}`. Pusta wartość daje pusty napis.
    Sama data (`date`, np. data meczu) nie ma godziny, więc nie jest przeliczana."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = to_local(value)
    return value.strftime(fmt)
