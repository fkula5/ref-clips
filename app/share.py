"""People with a link see only the video, the league (`Match.level`) and the decision category
(`Clip.category_label`). Referee names, teams, dates, descriptions, ratings and comments are never
read here, so they cannot reach the page, file name or ZIP.
The link code is `security.new_token()` (256 bits); only its SHA-256 hash is stored.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config, permissions, services
from app.models import Clip, ShareLink, ShareLinkClip, User
from app.security import hash_token, new_token
from app.storage import storage
from app.textutil import format_clock
from app.timeutil import utcnow

CODE_FORMAT = re.compile(r"^[A-Za-z0-9_-]{43}$")  # token_urlsafe(32); other shapes never reach the DB
LISTED_MAX = 5


class ShareError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def parse_days(raw: str | None) -> int:
    try:
        days = int((raw or "").strip())
    except ValueError:
        days = 0
    if days not in config.SHARE_DAYS:
        options = ", ".join(str(d) for d in config.SHARE_DAYS[:-1]) + f" albo {config.SHARE_DAYS[-1]}"
        raise ShareError(f"Wybierz ważność linku: {options} dni.")
    return days


def parse_clip_ids(raw: list[str]) -> list[int]:
    ids: list[int] = []
    for value in raw:
        value = value.strip()
        if not (value.isascii() and value.isdecimal()) or len(value) > 12:
            raise ShareError("Niepoprawna lista klipów — odśwież stronę i zaznacz klipy jeszcze raz.")
        if (n := int(value)) not in ids:
            ids.append(n)
    if not ids:
        raise ShareError("Zaznacz co najmniej jeden klip do udostępnienia.")
    if len(ids) > config.SHARE_MAX_CLIPS:
        raise ShareError(f"W jednym linku może być najwyżej {config.SHARE_MAX_CLIPS} klipów "
                         f"(zaznaczono {len(ids)}).")
    return ids


def has_file(clip: Clip) -> bool:
    """A clip being re-cut does not count: its status is not the cut one."""
    return clip.status == "cut" and bool(clip.clip_path) and storage.exists(clip.clip_path)


def _label(clip: Clip) -> str:
    return f"{clip.match.title} · {format_clock(clip.time_sec)}"


def _listed(clips: list[Clip]) -> str:
    text = "; ".join(_label(c) for c in clips[:LISTED_MAX])
    return text + (f" i {len(clips) - LISTED_MAX} inne" if len(clips) > LISTED_MAX else "")


def create_link(db: Session, user: User, clip_ids: list[str], days: str) -> tuple[ShareLink, str]:
    """Returns the link with the plain code (the only time it exists). All or nothing: one disallowed or
    uncut clip rejects the whole form.
    """
    valid_days = parse_days(days)
    ids = parse_clip_ids(clip_ids)
    found = {c.id: c for c in db.scalars(select(Clip).where(Clip.id.in_(ids)))}
    if len(found) != len(ids):
        raise ShareError("Część zaznaczonych klipów już nie istnieje — odśwież listę i zaznacz je jeszcze raz.", 404)
    clips = sorted(found.values(), key=lambda c: (c.match_id, *services.clip_order_key(c)))
    denied = [c for c in clips if not permissions.can_share_clip(user, c)]
    if denied:
        raise ShareError("Nie możesz udostępnić klipów: " + _listed(denied) + ". Linki mogą tworzyć "
                         "administratorzy, szkoleniowcy oraz autorzy znaczników. Nic nie zostało udostępnione.", 403)
    uncut = [c for c in clips if not has_file(c)]
    if uncut:
        raise ShareError("Te klipy nie są wycięte (jeszcze się wycinają albo cięcie się nie udało): "
                         + _listed(uncut) + ". Odznacz je albo poczekaj. Nic nie zostało udostępnione.", 409)
    code = new_token()
    link = ShareLink(token_hash=hash_token(code), created_by=user.id,
                     expires_at=utcnow() + timedelta(days=valid_days),
                     items=[ShareLinkClip(clip_id=c.id, position=i) for i, c in enumerate(clips, start=1)])
    db.add(link)
    try:
        db.commit()
    except IntegrityError:  # clip deleted between the check and the write
        db.rollback()
        raise ShareError("Któryś z klipów został właśnie usunięty — spróbuj jeszcze raz.", 409) from None
    return link, code


def offerable(user: User, clip: Clip) -> bool:
    """The server rechecks everything on creation, including the file on disk."""
    return clip.status == "cut" and bool(clip.clip_path) and permissions.can_share_clip(user, clip)


def public_url(request: Request, code: str) -> str:
    return f"{config.PUBLIC_URL or str(request.base_url).rstrip('/')}/s/{code}"


def active_links(db: Session, clip_id: int, now: datetime | None = None) -> list[ShareLink]:
    return list(db.scalars(
        select(ShareLink).join(ShareLinkClip).where(
            ShareLinkClip.clip_id == clip_id, ShareLink.revoked_at.is_(None),
            ShareLink.expires_at > (now or utcnow()))
        .options(selectinload(ShareLink.creator), selectinload(ShareLink.items))
        .order_by(ShareLink.expires_at.desc(), ShareLink.id.desc())))


def revoke(db: Session, link: ShareLink) -> None:
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        db.commit()


def public_title(clip: Clip) -> str:
    return " · ".join(p for p in (clip.match.level.strip(), clip.category_label.strip()) if p)


@dataclass
class SharedClip:
    position: int
    clip: Clip
    level: str
    category: str
    filename: str  # without the referee's name


@dataclass
class SharedView:
    link: ShareLink
    clips: list[SharedClip]

    @property
    def single(self) -> bool:
        return len(self.clips) == 1

    def clip_at(self, position: str) -> SharedClip | None:
        if not position.isascii() or not position.isdecimal():
            return None
        return next((c for c in self.clips if c.position == int(position)), None)


def open_link(db: Session, code: str, now: datetime | None = None) -> SharedView | None:
    """Missing, expired, revoked and empty links all give None, so the response does not reveal which."""
    if not CODE_FORMAT.match(code):
        return None
    link = db.scalar(select(ShareLink).where(ShareLink.token_hash == hash_token(code)).options(
        selectinload(ShareLink.items).selectinload(ShareLinkClip.clip).selectinload(Clip.match)))
    if link is None or link.revoked_at is not None or link.expires_at <= (now or utcnow()):
        return None
    clips = [SharedClip(item.position, item.clip, item.clip.match.level.strip(), item.clip.category_label.strip(),
                        services.clip_filename(item.clip, with_referee=False))
             for item in link.items if has_file(item.clip)]
    return SharedView(link, clips) if clips else None


def count_view(db: Session, link_id: int) -> None:
    """Atomic UPDATE, so parallel visits are not lost."""
    db.execute(update(ShareLink).where(ShareLink.id == link_id).values(view_count=ShareLink.view_count + 1))
    db.commit()


class ZipBusy(Exception):
    pass


class ZipNoSpace(Exception):
    pass


_zip_lock = threading.Lock()
_zips_running = 0


@contextmanager
def zip_slot() -> Iterator[None]:
    """When taken, ZipBusy at once (no queueing)."""
    global _zips_running
    with _zip_lock:
        if _zips_running >= config.SHARE_ZIP_MAX_PARALLEL:
            raise ZipBusy
        _zips_running += 1
    try:
        yield
    finally:
        with _zip_lock:
            _zips_running -= 1


def build_zip(clips: list[SharedClip]) -> Path:
    """ZIP (no compression, no CSV or metadata) in `DATA_DIR/tmp`. The caller deletes the file after
    sending; on a build error it is removed here; leftovers after a crash are cleaned by the worker
    (`retention.cleanup_tmp`). Dates in the archive are fixed so they do not reveal the cut time.
    """
    with zip_slot():
        needed = sum(storage.size(c.clip.clip_path) for c in clips)
        if storage.free_bytes() < needed + config.DISK_SAFETY_BYTES:
            raise ZipNoSpace
        names = services.unique_filenames(c.filename for c in clips)
        fd, name = tempfile.mkstemp(prefix="share-", suffix=".zip", dir=config.DATA_DIR / "tmp")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as archive:
                for entry, member in zip(clips, names):
                    source = storage.local_path(entry.clip.clip_path)
                    info = zipfile.ZipInfo(member, date_time=(2000, 1, 1, 0, 0, 0))
                    info.compress_type, info.external_attr, info.file_size = zipfile.ZIP_STORED, 0o644 << 16, source.stat().st_size
                    with source.open("rb") as src, archive.open(info, "w") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
