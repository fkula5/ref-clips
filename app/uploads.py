"""Wgrywanie wznawialne (tus): sesje uploadu, rezerwacja miejsca, kończenie i sprzątanie.

Warstwa HTTP protokołu tus jest w `app/routers/uploads.py`. Plik rośnie w
`uploads/tus-<id>.part`; po dopisaniu ostatniego bajtu powstaje nagranie (Video) i zadanie
konwersji, a plik dostaje docelową nazwę. Wiersz sesji zostaje do sprzątania (24 h), żeby
klient, który nie dostał odpowiedzi na ostatni PATCH, zobaczył po HEAD pełny rozmiar.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import secrets
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, services
from app.models import Match, UploadSession, User, Video
from app.storage import storage
from app.textutil import safe_filename
from app.timeutil import utcnow

log = logging.getLogger("uploads")

NO_SPACE_MESSAGE = "Brak miejsca na serwerze, spróbuj później."


class UploadError(Exception):
    """Błąd protokołu lub reguły wgrywania: kod HTTP + komunikat po polsku."""

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
    """Upload-Metadata: pary „klucz base64(wartość)” rozdzielone przecinkami."""
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


# --- rezerwacja miejsca ---------------------------------------------------------
def active_upload(db: Session, user_id: int) -> UploadSession | None:
    """Niedokończony upload użytkownika (najwyżej jeden)."""
    return db.scalar(select(UploadSession).where(
        UploadSession.user_id == user_id, UploadSession.offset_bytes < UploadSession.size_bytes))


def reserved_bytes(db: Session) -> int:
    """Miejsce już obiecane: niedopisane bajty aktywnych uploadów z miejscem na wersję roboczą
    oraz wersje robocze oryginałów czekających na konwersję lub konwertowanych teraz."""
    pending = db.scalar(select(func.coalesce(func.sum(
        UploadSession.reserved_bytes - UploadSession.offset_bytes), 0)).where(
        UploadSession.offset_bytes < UploadSession.size_bytes)) or 0
    converting = db.scalar(select(func.count()).select_from(Video).where(
        Video.original_path.is_not(None), Video.status.in_(("queued", "processing")))) or 0
    return int(pending) + converting * config.DRAFT_RESERVE_BYTES


def check_space(db: Session, size: int) -> None:
    """Przyjmuje upload tylko, gdy po uwzględnieniu rezerwacji zostanie miejsce na plik,
    wersję roboczą i zapas."""
    need = size + config.DRAFT_RESERVE_BYTES + config.DISK_SAFETY_BYTES + reserved_bytes(db)
    free = storage.free_bytes()
    if free < need:
        log.warning("Odrzucono upload %d B: wolne %d B, potrzeba %d B", size, free, need)
        raise UploadError(507, NO_SPACE_MESSAGE)


# --- tworzenie, kończenie, usuwanie ---------------------------------------------
def discard(db: Session, up: UploadSession) -> None:
    storage.delete(part_key(up.id))
    db.delete(up)
    db.commit()


def create_session(db: Session, user: User, match: Match, size: int, filename: str,
                   label: str, content: str) -> UploadSession:
    """Nowy upload. Jeden niedokończony na użytkownika: ten sam plik (mecz, nazwa, rozmiar)
    zaczyna się od nowa, inny daje błąd z adresem uploadu do przerwania."""
    previous = active_upload(db, user.id)
    if previous is not None:
        if (previous.match_id, previous.filename, previous.size_bytes) == (match.id, filename, size):
            discard(db, previous)
        else:
            raise UploadError(
                409, f"Masz niedokończone wgrywanie pliku „{previous.filename}”. Dokończ je (wybierz "
                     "ten sam plik) albo je przerwij.", {"X-Active-Upload": f"/uploads/{previous.id}"})
    check_space(db, size)
    up = UploadSession(
        id=secrets.token_hex(16), user_id=user.id, match_id=match.id, filename=filename,
        size_bytes=size, offset_bytes=0, reserved_bytes=size + config.DRAFT_RESERVE_BYTES,
        metadata_json=json.dumps({"label": label, "content": content}), updated_at=utcnow())
    db.add(up)
    db.commit()
    storage.open_update(part_key(up.id)).close()
    return up


def finish(db: Session, up: UploadSession) -> Video:
    """Kończy upload: nagranie w kolejce do konwersji, plik pod docelową nazwą. Idempotentne."""
    info = meta(up)
    if info.get("video_id") and (video := db.get(Video, info["video_id"])) is not None:
        return video
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
    up.metadata_json = json.dumps(info)
    up.updated_at = utcnow()
    db.commit()
    return video


# --- sprzątanie -----------------------------------------------------------------
def cleanup_stale(db: Session) -> int:
    """Usuwa uploady bez aktywności dłużej niż UPLOAD_STALE_HOURS (plik i wiersz) oraz
    osierocone pliki .part (np. po usunięciu meczu). Zwraca liczbę usuniętych uploadów."""
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
