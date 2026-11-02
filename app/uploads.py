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


def check_space(db: Session, size: int, user: User | None = None, filename: str = "") -> None:
    """Przyjmuje upload tylko, gdy po uwzględnieniu rezerwacji zostanie miejsce na plik,
    wersję roboczą i zapas. Odrzucenie zostaje zapisane (czas, rozmiar, użytkownik), żeby panel
    admina mógł ostrzec o zapełnionym dysku."""
    need = size + config.DRAFT_RESERVE_BYTES + config.DISK_SAFETY_BYTES + reserved_bytes(db)
    free = storage.free_bytes()
    if free < need:
        log.warning("Odrzucono upload %d B: wolne %d B, potrzeba %d B", size, free, need)
        db.add(UploadRejection(created_at=utcnow(), user_id=user.id if user else None,
                               filename=filename[:255], size_bytes=size, free_bytes=free))
        db.commit()
        raise UploadError(507, NO_SPACE_MESSAGE)


def prune_rejections(db: Session) -> int:
    """Usuwa stare wpisy o odrzuconych uploadach (po `REJECTION_KEEP_DAYS`)."""
    cutoff = utcnow() - timedelta(days=config.REJECTION_KEEP_DAYS)
    removed = db.execute(delete(UploadRejection).where(UploadRejection.created_at < cutoff)).rowcount
    db.commit()
    return removed


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
    """Kończy upload: nagranie w kolejce do konwersji, plik pod docelową nazwą. Idempotentne."""
    info = meta(up)
    if info.get("video_id"):  # już zakończone (nagranie mogło zostać usunięte)
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


# --- notatki przy wgrywaniu -------------------------------------------------------
def set_notes(db: Session, up: UploadSession, text: str) -> None:
    """Zapisuje notatki do uploadu (osobne żądanie po utworzeniu sesji; nie w nagłówkach tus,
    które mają limity rozmiaru). Notatki zamieniają się w klipy po zakończeniu wgrywania; jeśli
    plik jest już wgrany (mały plik wyprzedził żądanie), klipy powstają od razu."""
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
    """Klipy z notatek uploadu: nieopisane (opis zatwierdza się później), z sędzią i kategorią,
    jeśli parser je rozpoznał. Cięcie czeka na gotową wersję roboczą; moment poza nagraniem
    (długość znana dopiero po konwersji) kończy się błędem klipu. Idempotentne (flaga w metadanych)."""
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
