"""The file grows in `uploads/tus-<id>.part`; after the last byte a Video and a conversion job are
created and the file gets its final name. The session row stays until cleanup (24 h), so a client
that missed the reply to the last PATCH sees the full size via HEAD.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets
import time
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import config, permissions, services
from app.models import Match, UploadRejection, UploadSession, User, Video
from app.storage import storage
from app.textutil import safe_filename
from app.timeutil import utcnow

log = logging.getLogger("uploads")

NO_SPACE_MESSAGE = "Brak miejsca na serwerze, spróbuj później."


class UploadError(Exception):
    def __init__(self, status_code: int, message: str, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code, self.message, self.headers = status_code, message, headers or {}


def part_key(upload_id: str) -> str:
    return f"uploads/tus-{upload_id}.part"


def is_complete(up: UploadSession) -> bool:
    return up.offset_bytes >= up.size_bytes


def expires_at(up: UploadSession):
    return up.updated_at + timedelta(hours=config.UPLOAD_STALE_HOURS)


def is_stale(up: UploadSession) -> bool:
    return utcnow() > expires_at(up)


def meta(up: UploadSession) -> dict:
    try:
        return json.loads(up.metadata_json or "{}")
    except ValueError:
        return {}


def parse_metadata(header: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in (header or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, value = pair.partition(" ")
        try:
            result[key] = base64.b64decode(value.strip(), validate=True).decode("utf-8") if value.strip() else ""
        except (binascii.Error, UnicodeDecodeError):
            raise UploadError(400, "Nieprawidłowy nagłówek Upload-Metadata") from None
    return result


def active_upload(db: Session, user_id: int) -> UploadSession | None:
    return db.scalar(select(UploadSession).where(
        UploadSession.user_id == user_id, UploadSession.offset_bytes < UploadSession.size_bytes))


def reserved_bytes(db: Session) -> int:
    """Space already promised: unwritten bytes of active uploads (incl. room for the draft) plus drafts
    of originals waiting for or in conversion.
    """
    pending = db.scalar(select(func.coalesce(func.sum(
        UploadSession.reserved_bytes - UploadSession.offset_bytes), 0)).where(
        UploadSession.offset_bytes < UploadSession.size_bytes)) or 0
    converting = db.scalar(select(func.count()).select_from(Video).where(
        Video.original_path.is_not(None), Video.status.in_(("queued", "processing")))) or 0
    return int(pending) + converting * config.DRAFT_RESERVE_BYTES


def check_space(db: Session, size: int, user: User | None = None, filename: str = "") -> None:
    """A rejection is stored (time, size, user) so the admin panel can warn about a full disk."""
    need = size + config.DRAFT_RESERVE_BYTES + config.DISK_SAFETY_BYTES + reserved_bytes(db)
    free = storage.free_bytes()
    if free < need:
        log.warning("Odrzucono upload %d B: wolne %d B, potrzeba %d B", size, free, need)
        db.add(UploadRejection(created_at=utcnow(), user_id=user.id if user else None,
                               filename=filename[:255], size_bytes=size, free_bytes=free))
        db.commit()
        raise UploadError(507, NO_SPACE_MESSAGE)


def prune_rejections(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=config.REJECTION_KEEP_DAYS)
    removed = db.execute(delete(UploadRejection).where(UploadRejection.created_at < cutoff)).rowcount
    db.commit()
    return removed


def discard(db: Session, up: UploadSession) -> None:
    storage.delete(part_key(up.id))
    db.delete(up)
    db.commit()


def create_session(db: Session, user: User, match: Match, size: int, filename: str,
                   label: str, content: str) -> UploadSession:
    """One unfinished upload per user: the same file (match, name, size) restarts, a different one gives
    an error with the upload to cancel.
    """
    previous = active_upload(db, user.id)
    if previous is not None:
        if (previous.match_id, previous.filename, previous.size_bytes) == (match.id, filename, size):
            discard(db, previous)
        else:
            raise UploadError(
                409, f"Masz niedokończone wgrywanie pliku „{previous.filename}”. Dokończ je (wybierz "
                     "ten sam plik) albo je przerwij.", {"X-Active-Upload": f"/uploads/{previous.id}"})
    check_space(db, size, user, filename)
    up = UploadSession(
        id=secrets.token_hex(16), user_id=user.id, match_id=match.id, filename=filename,
        size_bytes=size, offset_bytes=0, reserved_bytes=size + config.DRAFT_RESERVE_BYTES,
        metadata_json=json.dumps({"label": label, "content": content}), updated_at=utcnow())
    db.add(up)
    db.commit()
    storage.open_update(part_key(up.id)).close()
    return up


def finish(db: Session, up: UploadSession) -> Video | None:
    info = meta(up)
    if info.get("video_id"):  # already finished (the recording may have been deleted)
        return db.get(Video, info["video_id"])
    if not up.match_id or db.get(Match, up.match_id) is None:
        discard(db, up)
        raise UploadError(410, "Mecz został usunięty")
    if storage.size(part_key(up.id)) != up.size_bytes:
        raise UploadError(500, "Rozmiar zapisanego pliku nie zgadza się z zadeklarowanym")
    video = Video(match_id=up.match_id, label=info.get("label", ""), original_filename=up.filename,
                  status="queued", size_bytes=up.size_bytes, created_by=up.user_id,
                  expires_at=services.video_expiry(db))
    db.add(video)
    db.flush()
    key = f"uploads/{video.id}_{safe_filename(up.filename, 'nagranie')}"
    storage.local_path(part_key(up.id)).replace(storage.local_path(key))
    video.original_path = key
    services.set_content(db, video, info.get("content", "full"))
    services.queue_transcode(db, video)
    info["video_id"] = video.id
    apply_notes(db, up, video, info)
    up.metadata_json = json.dumps(info)
    up.updated_at = utcnow()
    db.commit()
    return video


def set_notes(db: Session, up: UploadSession, text: str) -> None:
    """A separate request after the session is created (tus headers have size limits). If the file is
    already uploaded (a small file outran the request), the clips are created at once.
    """
    try:
        text = services.clean_notes(text)
    except services.NotesTooLong as exc:
        raise UploadError(413, str(exc)) from None
    info = meta(up)
    if info.get("notes_applied") is not None:
        raise UploadError(409, "Notatki z tego wgrywania zostały już zamienione na klipy — "
                               "dodaj kolejne przyciskiem „Wklej notatki” przy nagraniu")
    up.notes = text
    video = db.get(Video, info["video_id"]) if info.get("video_id") else None
    if video is not None:
        apply_notes(db, up, video, info)
        up.metadata_json = json.dumps(info)
    db.commit()


def apply_notes(db: Session, up: UploadSession, video: Video, info: dict) -> int:
    """Clips are undescribed; referee and category are set if the parser recognised them. Cutting waits
    for the draft; a moment outside the recording (length known only after conversion) ends as a clip
    error. Idempotent (flag in metadata).
    """
    if info.get("notes_applied") is not None or not up.notes.strip():
        return 0
    user = db.get(User, up.user_id)
    if user is None or not permissions.can_manage_clips(user, video.match):
        log.warning("Pominięto notatki uploadu %s: brak uprawnień autora do klipów meczu", up.id)
        info["notes_applied"] = 0
        return 0
    created = 0
    for row in services.parse_for_match(db, video.match, up.notes):
        if not row.ok:
            continue
        category = services.category_by_name(db, row.category)
        services.create_clip(db, video, user, time_sec=row.time_sec, official_id=row.referee_id,
                             category_id=category.id if category else None, description=row.description)
        created += 1
    info["notes_applied"] = created
    return created


def cleanup_stale(db: Session) -> int:
    cutoff = utcnow() - timedelta(hours=config.UPLOAD_STALE_HOURS)
    removed = 0
    for up in db.scalars(select(UploadSession).where(UploadSession.updated_at < cutoff)):
        storage.delete(part_key(up.id))
        db.delete(up)
        removed += 1
    db.commit()
    known = set(db.scalars(select(UploadSession.id)))
    orphan_cutoff = time.time() - config.UPLOAD_STALE_HOURS * 3600
    for path in (config.DATA_DIR / "uploads").glob("tus-*.part"):
        upload_id = path.name[len("tus-"):-len(".part")]
        if upload_id not in known and path.stat().st_mtime < orphan_cutoff:
            path.unlink(missing_ok=True)
    if removed:
        log.info("Usunięto nieaktywne uploady: %d", removed)
    return removed
