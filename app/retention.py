from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import config, services
from app.models import Clip, Job, Setting, Video
from app.storage import storage
from app.timeutil import utcnow

log = logging.getLogger("retention")

LAST_RUN_KEY = "retention_last_run"
LAST_SUMMARY_KEY = "retention_last_summary"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
PENDING_CLIP = ("new", "queued")
BUSY_VIDEO = ("uploading", "queued", "processing")


class PurgeError(Exception):
    pass


class RetentionError(ValueError):
    pass


def days_left(video: Video, now: datetime | None = None) -> int | None:
    """Rounded up; <= 0 means overdue and waiting for cleanup."""
    if video.purged_at is not None or video.expires_at is None or not video.proxy_path:
        return None
    seconds = (video.expires_at - (now or utcnow())).total_seconds()
    return math.ceil(seconds / 86400) if seconds > 0 else 0


def days_phrase(days: int) -> str:
    return "1 dzień" if days == 1 else f"{days} dni"


def expiry_note(videos, now: datetime | None = None) -> str | None:
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


def pending_clips(db: Session, video: Video) -> int:
    return db.scalar(select(func.count()).select_from(Clip).where(
        Clip.video_id == video.id, Clip.status.in_(PENDING_CLIP))) or 0


def purge_blocker(db: Session, video: Video, pending: int | None = None) -> str | None:
    """Deleting during upload or conversion, or while clips still wait for cutting, would leave them
    queued forever. Clips after a cut error do not block.
    """
    if video.purged_at is not None:
        return "Pełne nagranie zostało już usunięte."
    if video.status in BUSY_VIDEO:
        return "Nagranie jest wgrywane albo konwertowane — poczekaj na koniec konwersji."
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
    message = "Pełne nagranie zostało usunięte przed wycięciem klipu."
    clips = list(db.scalars(select(Clip).where(Clip.video_id == video.id, Clip.status.in_(PENDING_CLIP))))
    for clip in clips:
        clip.status, clip.error = "error", message
    if clips:
        db.execute(update(Job).where(Job.clip_id.in_([c.id for c in clips]), Job.type == "cut",
                                     Job.status == "pending").values(status="error", error=message))
    return len(clips)


def purge_video(db: Session, video: Video, now: datetime | None = None) -> None:
    """Marks the recording purged first (`purged_at`, paths cleared; clips stay), then deletes the
    files. The order is deliberate: if the DB write fails the recording stays untouched; if a file
    delete fails it is only a log warning and `cleanup_orphan_videos` removes the orphan later. Only
    a PurgeError from the rules is swallowed; a DB error propagates and leaves the recording
    unchanged.
    """
    blocker = purge_blocker(db, video)
    if blocker:
        raise PurgeError(blocker)
    keys = [key for key in (video.original_path, video.proxy_path) if key]
    video.original_path = video.proxy_path = video.proxy_bytes = None
    video.purged_at = now or utcnow()
    abandon_pending_clips(db, video)  # race with a clip marked just before the purge
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    for key in keys:
        try:
            storage.delete(key)
        except (OSError, ValueError):
            log.warning("Nie udało się usunąć pliku %s po usunięciu nagrania %s — zostanie sprzątnięty "
                        "jako osierocony", key, video.id, exc_info=True)


@dataclass
class RetentionResult:
    purged: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = f"usunięto: {len(self.purged)}"
        return text + (f", pominięto: {len(self.skipped)}" if self.skipped else "")


def run_retention(db: Session, now: datetime | None = None) -> RetentionResult:
    """Skips recordings in conversion, with clips waiting for cutting, or whose DB write failed (retried
    next run); a failed file delete does not abort the run. Idempotent.
    """
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
        except SQLAlchemyError as exc:
            result.skipped.append((video.id, f"błąd bazy danych: {exc.__class__.__name__}"))
            log.warning("Retencja: nie zapisano usunięcia nagrania %s w bazie", video.id, exc_info=True)
        else:
            result.purged.append(video.id)
            log.info("Retencja: usunięto pełne nagranie %s (termin %s)", video.id, video.expires_at)
    return result


def run_if_due(db: Session, now: datetime | None = None) -> RetentionResult | None:
    """The run time is recorded with an atomic UPDATE on `settings`, so a worker restart within a day or
    several workers do not run it twice. Returns None when it was not due.
    """
    now = now or utcnow()
    if db.get(Setting, LAST_RUN_KEY) is None:
        try:
            db.add(Setting(key=LAST_RUN_KEY, value=""))
            db.commit()
        except IntegrityError:  # a second worker created the row at the same moment
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
    raw = services.get_setting(db, LAST_RUN_KEY)
    try:
        when = datetime.strptime(raw, TIME_FORMAT) if raw else None
    except ValueError:
        when = None
    return when, services.get_setting(db, LAST_SUMMARY_KEY)


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
    recalculated: int = 0
    overdue: int = 0


def set_retention_days(db: Session, days: int, recalculate: bool, now: datetime | None = None) -> RetentionChange:
    """Default affects only new recordings. With `recalculate`, existing unpurged recordings get upload
    date + `days`.
    """
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


def cleanup_orphan_clips(db: Session, min_age_seconds: float | None = None) -> int:
    """A fresh file may be written by a cut that has not stored the path yet. Orphans appear when a
    marker is deleted during cutting.
    """
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


def cleanup_tmp(db: Session | None = None, min_age_seconds: float | None = None) -> int:
    """Normally the file vanishes right after sending; leftovers come from crashes or aborted downloads.
    A longer download is fine: the file is already open. `db` is unused (uniform signature of the
    cleanup steps).
    """
    if min_age_seconds is None:
        min_age_seconds = config.ORPHAN_MIN_AGE_SECONDS
    cutoff = time.time() - min_age_seconds
    removed = 0
    for key, _size, mtime in storage.iter_files("tmp"):
        if not key.endswith(".zip") or mtime >= cutoff:
            continue
        try:
            storage.delete(key)
            removed += 1
        except OSError:
            log.warning("Nie udało się usunąć pliku tymczasowego %s", key)
    if removed:
        log.info("Usunięto pliki tymczasowe: %d", removed)
    return removed


VIDEO_FILE = re.compile(r"^(?:uploads/(?P<up>\d+)_.+|proxies/(?P<proxy>\d+)(?:\.part)?\.mp4)$")


def cleanup_orphan_videos(db: Session, min_age_seconds: float | None = None) -> int:
    """Orphans remain after a failed file delete in `purge_video` or after a match is deleted. Skips
    recordings being uploaded or converted (a fresh `.part.mp4` exists before `proxy_path` is stored)
    and running uploads (`uploads/tus-*.part` does not match the pattern; stale ones go through
    `uploads.cleanup_stale`).
    """
    if min_age_seconds is None:
        min_age_seconds = config.ORPHAN_MIN_AGE_SECONDS
    cutoff = time.time() - min_age_seconds
    candidates = []
    for prefix in ("uploads", "proxies"):
        for key, _size, mtime in storage.iter_files(prefix):
            match = VIDEO_FILE.match(key)
            if match and mtime < cutoff:
                candidates.append((key, int(match["up"] or match["proxy"])))
    if not candidates:
        return 0
    used = set(db.scalars(select(Video.original_path).where(Video.original_path.is_not(None))))
    used |= set(db.scalars(select(Video.proxy_path).where(Video.proxy_path.is_not(None))))
    busy = set(db.scalars(select(Video.id).where(Video.status.in_(BUSY_VIDEO))))
    removed = 0
    for key, video_id in candidates:
        if key in used or video_id in busy:
            continue
        try:
            storage.delete(key)
            removed += 1
        except OSError:
            log.warning("Nie udało się usunąć osieroconego pliku nagrania %s", key)
    if removed:
        log.info("Usunięto osierocone pliki nagrań: %d", removed)
    return removed
