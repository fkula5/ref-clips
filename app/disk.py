"""Zajętość dysku dla panelu admina: pełne nagrania, oryginały i niedokończone uploady, klipy,
wolne i zarezerwowane miejsce oraz lista nagrań z terminami usunięcia.

Rozmiary pochodzą z bazy (`Video.proxy_bytes`, `Video.size_bytes`, `UploadSession.offset_bytes`);
jedyne przejście po dysku to jeden odczyt katalogu klipów. Rozmiar wersji roboczej starszych
nagrań (sprzed migracji mvp0004) uzupełnia się leniwie przy pierwszym otwarciu panelu.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app import config, retention, uploads
from app.models import Clip, UploadRejection, UploadSession, Video
from app.storage import storage
from app.timeutil import utcnow


@dataclass
class DiskUsage:
    drafts: int          # wersje robocze pełnych nagrań
    originals: int       # oryginały czekające na konwersję lub po błędzie konwersji
    partial: int         # niedokończone uploady (pliki .part)
    clips: int           # pliki klipów
    clip_files: int
    free: int
    total: int
    reserved: int        # miejsce obiecane trwającym uploadom i konwersjom
    acceptable: int      # największy plik, jaki nowy upload mógłby teraz zająć


def fill_proxy_sizes(db: Session) -> None:
    """Uzupełnia `proxy_bytes` nagrań, które go nie mają (starsze wiersze); brak pliku zostawia puste."""
    changed = False
    for video in db.scalars(select(Video).where(Video.proxy_path.is_not(None), Video.proxy_bytes.is_(None))):
        if storage.exists(video.proxy_path):
            video.proxy_bytes = storage.size(video.proxy_path)
            changed = True
    if changed:
        db.commit()


def usage(db: Session) -> DiskUsage:
    fill_proxy_sizes(db)
    drafts = db.scalar(select(func.coalesce(func.sum(Video.proxy_bytes), 0)).where(
        Video.purged_at.is_(None), Video.proxy_path.is_not(None))) or 0
    originals = db.scalar(select(func.coalesce(func.sum(Video.size_bytes), 0)).where(
        Video.original_path.is_not(None))) or 0
    partial = db.scalar(select(func.coalesce(func.sum(UploadSession.offset_bytes), 0)).where(
        UploadSession.offset_bytes < UploadSession.size_bytes)) or 0
    clip_sizes = [size for _key, size, _mtime in storage.iter_files("clips")]
    free, reserved = storage.free_bytes(), uploads.reserved_bytes(db)
    acceptable = max(0, free - reserved - config.DISK_SAFETY_BYTES - config.DRAFT_RESERVE_BYTES)
    return DiskUsage(int(drafts), int(originals), int(partial), sum(clip_sizes), len(clip_sizes),
                     free, storage.total_bytes(), reserved, acceptable)


@dataclass
class VideoRow:
    video: Video
    clips: int
    pending: int
    days_left: int | None
    blocker: str | None

    @property
    def size(self) -> int:
        """Miejsce zajmowane przez nagranie: wersja robocza i ewentualny oryginał."""
        return (self.video.proxy_bytes or 0) + (self.video.size_bytes if self.video.original_path else 0)


def video_rows(db: Session, now: datetime | None = None) -> list[VideoRow]:
    """Nagrania z plikami na dysku (bez usuniętych), od najbliższego terminu usunięcia; bez terminu na końcu."""
    now = now or utcnow()
    videos = db.scalars(select(Video).where(Video.purged_at.is_(None)).options(
        selectinload(Video.match))).all()
    counts = {vid: (n, pending or 0) for vid, n, pending in db.execute(
        select(Clip.video_id, func.count(),
               func.sum(case((Clip.status.in_(retention.PENDING_CLIP), 1), else_=0)))
        .group_by(Clip.video_id))}
    rows = [VideoRow(v, counts.get(v.id, (0, 0))[0], counts.get(v.id, (0, 0))[1], retention.days_left(v, now),
                     retention.purge_blocker(db, v, pending=int(counts.get(v.id, (0, 0))[1])))
            for v in videos]
    far = datetime.max
    return sorted(rows, key=lambda r: (r.video.expires_at or far, r.video.id))


def recent_rejections(db: Session, now: datetime | None = None) -> list[UploadRejection]:
    """Uploady odrzucone z braku miejsca w ostatnich `REJECTION_WARN_DAYS` dniach, od najnowszego."""
    since = (now or utcnow()) - timedelta(days=config.REJECTION_WARN_DAYS)
    return list(db.scalars(select(UploadRejection).where(UploadRejection.created_at >= since)
                           .options(selectinload(UploadRejection.user))
                           .order_by(UploadRejection.created_at.desc(), UploadRejection.id.desc())))
