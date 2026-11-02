"""Retencja pełnych nagrań i sprzątanie plików (segment 7).

Wersja robocza pełnego nagrania znika po `retention_days` od wgrania (`Video.expires_at`); klipy
zostają. Usuwanie działa tak samo dla zadania w workerze (`run_if_due`) i dla ręcznego „Usuń
pełne nagranie teraz” w panelu admina (`purge_video`) — wspólne są też reguły, kiedy nie wolno
usuwać (`purge_blocker`).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config, services
from app.models import Clip, Job, Setting, Video
from app.storage import storage
from app.timeutil import utcnow

log = logging.getLogger("retention")

LAST_RUN_KEY = "retention_last_run"          # kiedy zadanie ostatnio ruszyło (UTC, napis do porównań)
LAST_SUMMARY_KEY = "retention_last_summary"  # krótki wynik ostatniego uruchomienia
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
PENDING_CLIP = ("new", "queued")             # klip czeka na wycięcie z wersji roboczej
BUSY_VIDEO = ("uploading", "queued", "processing")


class PurgeError(Exception):
    """Nagrania nie wolno (teraz) usunąć — komunikat po polsku."""


class RetentionError(ValueError):
    """Niepoprawne ustawienie retencji (komunikat po polsku; HTTP 422)."""


# --- termin i oznaczenie w interfejsie ---------------------------------------------------
def days_left(video: Video, now: datetime | None = None) -> int | None:
    """Pełne dni do usunięcia wersji roboczej (zaokrąglone w górę; <= 0 = po terminie, czeka na
    sprzątanie). None, gdy nie ma czego usuwać albo nagranie nie ma terminu."""
    if video.purged_at is not None or video.expires_at is None or not video.proxy_path:
        return None
    seconds = (video.expires_at - (now or utcnow())).total_seconds()
    return math.ceil(seconds / 86400) if seconds > 0 else 0


def days_phrase(days: int) -> str:
    return "1 dzień" if days == 1 else f"{days} dni"


def expiry_note(videos, now: datetime | None = None) -> str | None:
    """„pełne nagranie dostępne jeszcze X dni” na `config.EXPIRY_WARN_DAYS` dni przed terminem
    (dla najbliższego terminu spośród nagrań meczu); inaczej None."""
    now = now or utcnow()
    left = [d for v in videos if (d := days_left(v, now)) is not None]
    if not left or min(left) > config.EXPIRY_WARN_DAYS:
        return None
    soonest = min(left)
    if soonest <= 0:
        return "pełne nagranie zostanie usunięte w najbliższym sprzątaniu"
    return f"pełne nagranie dostępne jeszcze {days_phrase(soonest)}"


def video_expiry_note(video: Video, now: datetime | None = None) -> str | None:
    return expiry_note([video], now)


# --- usuwanie pełnego nagrania -----------------------------------------------------------
def pending_clips(db: Session, video: Video) -> int:
    return db.scalar(select(func.count()).select_from(Clip).where(
        Clip.video_id == video.id, Clip.status.in_(PENDING_CLIP))) or 0


def purge_blocker(db: Session, video: Video, pending: int | None = None) -> str | None:
    """Powód, dla którego nagrania nie wolno teraz usunąć (None = można). Nie usuwamy nagrania
    w trakcie wgrywania i konwersji ani dopóki klipy z niego czekają na cięcie — usunięcie
    zostawiłoby je w kolejce na zawsze. Klipy po błędzie cięcia nie blokują."""
    if video.purged_at is not None:
        return "Pełne nagranie zostało już usunięte."
    if video.status in BUSY_VIDEO:
        return "Nagranie jest wgrywane albo konwertowane — poczekaj na koniec konwersji."
    # Nagranie w błędzie nigdy nie wytnie klipów, więc ich kolejka go nie blokuje.
    if video.status != "ready":
        return None
    pending = pending_clips(db, video) if pending is None else pending
    if pending:
        if pending == 1:
            waiting = "1 klip czeka"
        elif 2 <= pending % 10 <= 4 and not 12 <= pending % 100 <= 14:
            waiting = f"{pending} klipy czekają"
        else:
            waiting = f"{pending} klipów czeka"
        return f"{waiting} na wycięcie z tego nagrania — poczekaj, aż worker je wytnie."
    return None


def abandon_pending_clips(db: Session, video: Video) -> int:
    """Klipy czekające na cięcie z nagrania, którego już nie ma, dostają stan błędu (zamiast
    wisieć w kolejce); ich oczekujące zadania cięcia są zamykane. Zwraca liczbę klipów."""
    message = "Pełne nagranie zostało usunięte przed wycięciem klipu."
    clips = list(db.scalars(select(Clip).where(Clip.video_id == video.id, Clip.status.in_(PENDING_CLIP))))
    for clip in clips:
        clip.status, clip.error = "error", message
    if clips:
        db.execute(update(Job).where(Job.clip_id.in_([c.id for c in clips]), Job.type == "cut",
                                     Job.status == "pending").values(status="error", error=message))
    return len(clips)


def purge_video(db: Session, video: Video, now: datetime | None = None) -> None:
    """Usuwa pliki wersji roboczej (i oryginału, jeśli został po błędzie konwersji) i ustawia
    `purged_at`. Klipy zostają. Błąd reguł albo dysku to PurgeError, a nagranie zostaje bez zmian."""
    blocker = purge_blocker(db, video)
    if blocker:
        raise PurgeError(blocker)
    try:
        storage.delete(video.original_path)
        storage.delete(video.proxy_path)
    except OSError as exc:
        raise PurgeError(f"Nie udało się usunąć plików nagrania: {exc}") from exc
    video.original_path = video.proxy_path = video.proxy_bytes = None
    video.purged_at = now or utcnow()
    abandon_pending_clips(db, video)  # klip dodany tuż przed usunięciem (wyścig z „Zaznacz”)
    db.commit()


@dataclass
class RetentionResult:
    purged: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = f"usunięto: {len(self.purged)}"
        return text + (f", pominięto: {len(self.skipped)}" if self.skipped else "")


def run_retention(db: Session, now: datetime | None = None) -> RetentionResult:
    """Usuwa wersje robocze nagrań po terminie. Nagrania w konwersji i z klipami czekającymi na
    cięcie są pomijane (wrócą przy następnym uruchomieniu). Idempotentne: usunięte mają `purged_at`."""
    now = now or utcnow()
    result = RetentionResult()
    due = db.scalars(select(Video).where(
        Video.purged_at.is_(None), Video.expires_at.is_not(None), Video.expires_at < now)
        .order_by(Video.expires_at, Video.id)).all()
    for video in due:
        try:
            purge_video(db, video, now)
        except PurgeError as exc:
            db.rollback()
            result.skipped.append((video.id, str(exc)))
            log.info("Retencja: pominięto nagranie %s: %s", video.id, exc)
        else:
            result.purged.append(video.id)
            log.info("Retencja: usunięto pełne nagranie %s (termin %s)", video.id, video.expires_at)
    return result


def run_if_due(db: Session, now: datetime | None = None) -> RetentionResult | None:
    """Uruchamia retencję, jeśli ostatnie uruchomienie było ponad `RETENTION_INTERVAL_HOURS` temu
    (albo nigdy). Czas zapisujemy atomowym UPDATE-em w `settings`: restart workera w ciągu doby
    i kilka workerów naraz nie uruchomią zadania drugi raz. Zwraca None, gdy nie była to ta chwila."""
    now = now or utcnow()
    if db.get(Setting, LAST_RUN_KEY) is None:
        try:
            db.add(Setting(key=LAST_RUN_KEY, value=""))
            db.commit()
        except IntegrityError:  # drugi worker założył wiersz w tej samej chwili
            db.rollback()
    cutoff = (now - timedelta(hours=config.RETENTION_INTERVAL_HOURS)).strftime(TIME_FORMAT)
    claimed = db.execute(update(Setting).where(
        Setting.key == LAST_RUN_KEY, or_(Setting.value == "", Setting.value < cutoff))
        .values(value=now.strftime(TIME_FORMAT)))
    db.commit()
    if not claimed.rowcount:
        return None
    result = run_retention(db, now)
    services.set_setting(db, LAST_SUMMARY_KEY, result.summary)
    db.commit()
    log.info("Retencja: %s", result.summary)
    return result


def last_run(db: Session) -> tuple[datetime | None, str]:
    """(czas ostatniego uruchomienia, krótki wynik) do panelu admina."""
    raw = services.get_setting(db, LAST_RUN_KEY)
    try:
        when = datetime.strptime(raw, TIME_FORMAT) if raw else None
    except ValueError:
        when = None
    return when, services.get_setting(db, LAST_SUMMARY_KEY)


# --- ustawienie retention_days -----------------------------------------------------------
def parse_retention_days(raw: str) -> int:
    low, high = config.RETENTION_DAYS_MIN, config.RETENTION_DAYS_MAX
    try:
        days = int((raw or "").strip())
    except ValueError:
        raise RetentionError(f"Liczba dni retencji musi być liczbą całkowitą od {low} do {high}.") from None
    if not low <= days <= high:
        raise RetentionError(f"Liczba dni retencji musi mieścić się w zakresie {low}–{high}.")
    return days


@dataclass
class RetentionChange:
    days: int
    recalculated: int = 0   # nagrania z przeliczonym terminem
    overdue: int = 0        # z nich: po nowym terminie (zostaną usunięte przy najbliższym sprzątaniu)


def set_retention_days(db: Session, days: int, recalculate: bool, now: datetime | None = None) -> RetentionChange:
    """Zapisuje `retention_days`. Domyślnie dotyczy tylko nowych nagrań. Z `recalculate` termin
    istniejących, jeszcze nieusuniętych nagrań staje się: data wgrania + `days`."""
    now = now or utcnow()
    services.set_setting(db, "retention_days", str(days))
    change = RetentionChange(days)
    if recalculate:
        for video in db.scalars(select(Video).where(Video.purged_at.is_(None))):
            video.expires_at = video.created_at + timedelta(days=days)
            change.recalculated += 1
            change.overdue += video.expires_at < now
    db.commit()
    return change


# --- osierocone pliki klipów -------------------------------------------------------------
def cleanup_orphan_clips(db: Session, min_age_seconds: float | None = None) -> int:
    """Usuwa z katalogu klipów pliki .mp4 (także niedokończone .part.mp4), do których nie prowadzi
    `clip_path` żadnego klipu, starsze niż `ORPHAN_MIN_AGE_SECONDS` (świeży plik może być właśnie
    zapisywany przez cięcie, które jeszcze nie zapisało ścieżki). Zostają po usunięciu znacznika
    w trakcie cięcia. Zwraca liczbę usuniętych plików."""
    if min_age_seconds is None:
        min_age_seconds = config.ORPHAN_MIN_AGE_SECONDS
    used = set(db.scalars(select(Clip.clip_path).where(Clip.clip_path.is_not(None))))
    cutoff = time.time() - min_age_seconds
    removed = 0
    for key, _size, mtime in storage.iter_files("clips"):
        if key in used or mtime >= cutoff or not key.endswith(".mp4"):
            continue
        try:
            storage.delete(key)
            removed += 1
        except OSError:
            log.warning("Nie udało się usunąć osieroconego pliku klipu %s", key)
    if removed:
        log.info("Usunięto osierocone pliki klipów: %d", removed)
    return removed
