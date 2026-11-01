"""Wgrywanie wznawialne: protokół tus 1.0.0 (core + creation, termination, expiration).

Upload tworzy POST /uploads/ (Upload-Length, Upload-Metadata: filename, match_id, content,
label), HEAD zwraca Upload-Offset, PATCH dopisuje bajty od offsetu, DELETE anuluje.
Każdy upload jest dostępny tylko dla właściciela. Plik jest zapisywany strumieniowo na dysk.
"""
from __future__ import annotations

import fcntl
from email.utils import format_datetime
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from starlette.requests import ClientDisconnect

from app import config, permissions, services, uploads
from app.auth import require
from app.db import get_db
from app.models import Match, UploadSession, User
from app.storage import storage
from app.timeutil import utcnow
from app.uploads import UploadError

router = APIRouter()

TUS_VERSION = "1.0.0"
EXTENSIONS = "creation,termination,expiration"
OFFSET_TYPE = "application/offset+octet-stream"
FLUSH_BYTES = 4 * 1024 * 1024

# Wgrywać może każdy, kto może założyć mecz; do konkretnego meczu — reguła z permissions.
uploader = require(permissions.can_create_match)


def _headers(**extra: str) -> dict[str, str]:
    return {"Tus-Resumable": TUS_VERSION, **extra}


def _fail(error: UploadError) -> HTTPException:
    return HTTPException(error.status_code, error.message, headers=_headers(**error.headers))


def _http_date(value) -> str:
    return format_datetime(value.replace(tzinfo=UTC), usegmt=True)


def _upload_headers(up: UploadSession) -> dict[str, str]:
    return _headers(**{"Upload-Offset": str(up.offset_bytes), "Upload-Length": str(up.size_bytes),
                       "Upload-Expires": _http_date(uploads.expires_at(up)),
                       "Cache-Control": "no-store"})


def tus_version(request: Request) -> None:
    """Klient musi znać wersję protokołu (nagłówek Tus-Resumable)."""
    if request.headers.get("tus-resumable") != TUS_VERSION:
        raise HTTPException(412, "Nieobsługiwana wersja protokołu tus",
                            headers={"Tus-Resumable": TUS_VERSION, "Tus-Version": TUS_VERSION})


def _own_upload(db: Session, user: User, upload_id: str) -> UploadSession:
    """Upload właściciela. Cudzy i nieistniejący wyglądają tak samo (404); nieaktywny > 24 h
    jest usuwany i zwraca 410."""
    up = db.get(UploadSession, upload_id)
    if up is None or up.user_id != user.id:
        raise _fail(UploadError(404, "Nie ma takiego wgrywania"))
    if uploads.is_stale(up):
        uploads.discard(db, up)
        raise _fail(UploadError(410, "Wgrywanie wygasło (brak aktywności przez 24 h) — zacznij od nowa"))
    return up


def _match_of(db: Session, user: User, up: UploadSession) -> Match:
    match = db.get(Match, up.match_id) if up.match_id else None
    if match is None or not permissions.can_upload_to_match(user, match):
        raise _fail(UploadError(403, "Brak uprawnień do wgrywania nagrań do tego meczu"))
    return match


@router.options("/uploads/")
def tus_options(user: User = require(permissions.can_view)):
    return Response(status_code=204, headers=_headers(**{
        "Tus-Version": TUS_VERSION, "Tus-Extension": EXTENSIONS,
        "Tus-Max-Size": str(config.UPLOAD_MAX_BYTES)}))


@router.post("/uploads/", dependencies=[Depends(tus_version)])
def create_upload(request: Request, db: Session = Depends(get_db), user: User = uploader):
    h = request.headers
    if "upload-defer-length" in h:
        raise _fail(UploadError(400, "Wgrywanie bez znanego rozmiaru nie jest obsługiwane"))
    length = h.get("upload-length", "")
    if not length.isdigit():
        raise _fail(UploadError(400, "Brak nagłówka Upload-Length"))
    size = int(length)
    if size <= 0:
        raise _fail(UploadError(400, "Pusty plik"))
    if size > config.UPLOAD_MAX_BYTES:
        raise _fail(UploadError(413, f"Plik jest za duży (maksymalnie {config.UPLOAD_MAX_BYTES / config.GB:g} GB)"))
    try:
        info = uploads.parse_metadata(h.get("upload-metadata"))
        match_id = info.get("match_id", "")
        match = db.get(Match, int(match_id)) if match_id.isdigit() else None
        if match is None:
            raise UploadError(400, "Brak meczu w metadanych uploadu (match_id)")
        if not permissions.can_upload_to_match(user, match):
            raise UploadError(403, "Brak uprawnień do wgrywania nagrań do tego meczu")
        try:
            content = services.normalize_content(info.get("content"))
        except services.MatchFormError as exc:
            raise UploadError(400, str(exc)) from None
        filename = (info.get("filename") or "nagranie").replace("\\", "/").rsplit("/", 1)[-1][:255]
        up = uploads.create_session(db, user, match, size, filename, info.get("label", "").strip()[:100],
                                    content)
    except UploadError as exc:
        raise _fail(exc) from None
    return Response(status_code=201, headers=_headers(**{
        "Location": f"/uploads/{up.id}", "Upload-Expires": _http_date(uploads.expires_at(up))}))


@router.head("/uploads/{upload_id}", dependencies=[Depends(tus_version)])
def upload_offset(upload_id: str, db: Session = Depends(get_db), user: User = uploader):
    up = _own_upload(db, user, upload_id)
    if uploads.is_complete(up):
        try:
            uploads.finish(db, up)  # na wypadek przerwania tuż po ostatnim bajcie
        except UploadError as exc:
            raise _fail(exc) from None
    return Response(status_code=200, headers=_upload_headers(up))


@router.delete("/uploads/{upload_id}", dependencies=[Depends(tus_version)])
def terminate_upload(upload_id: str, db: Session = Depends(get_db), user: User = uploader):
    up = db.get(UploadSession, upload_id)
    if up is None or up.user_id != user.id:
        raise _fail(UploadError(404, "Nie ma takiego wgrywania"))
    if uploads.is_complete(up) and uploads.meta(up).get("video_id"):
        raise _fail(UploadError(409, "Wgrywanie jest już zakończone"))
    uploads.discard(db, up)
    return Response(status_code=204, headers=_headers())


@router.patch("/uploads/{upload_id}", dependencies=[Depends(tus_version)])
async def append_upload(upload_id: str, request: Request, db: Session = Depends(get_db),
                        user: User = uploader):
    up = _own_upload(db, user, upload_id)
    _match_of(db, user, up)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != OFFSET_TYPE:
        raise _fail(UploadError(415, f"Content-Type musi być {OFFSET_TYPE}"))
    offset = request.headers.get("upload-offset", "")
    if not offset.isdigit():
        raise _fail(UploadError(400, "Brak nagłówka Upload-Offset"))
    if int(offset) != up.offset_bytes:
        raise _fail(UploadError(409, "Niezgodny offset — odpytaj o aktualny (HEAD) i wznów od niego",
                                {"Upload-Offset": str(up.offset_bytes)}))
    remaining = up.size_bytes - up.offset_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > remaining:
        raise _fail(UploadError(413, "Dane przekraczają zadeklarowany rozmiar pliku"))

    fh = storage.open_update(uploads.part_key(up.id))
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # jeden PATCH naraz dla uploadu
        except OSError:
            raise _fail(UploadError(409, "To wgrywanie jest właśnie dopisywane innym żądaniem")) from None
        fh.truncate(up.offset_bytes)  # odrzuca ewentualne resztki po przerwanym zapisie
        fh.seek(up.offset_bytes)
        overflow = disconnected = False
        buffer = bytearray()
        try:
            async for chunk in request.stream():
                if up.offset_bytes + len(buffer) + len(chunk) > up.size_bytes:
                    overflow = True
                    break
                buffer += chunk
                if len(buffer) >= FLUSH_BYTES:
                    await run_in_threadpool(_append, db, up, fh, bytes(buffer))
                    buffer.clear()
        except ClientDisconnect:
            disconnected = True
        finally:
            if buffer:  # zachowujemy też to, co już dotarło (wznowienie ruszy od tego miejsca)
                _append(db, up, fh, bytes(buffer))
    except OSError:
        raise _fail(UploadError(507, uploads.NO_SPACE_MESSAGE)) from None
    except StaleDataError:  # upload anulowany (DELETE) w trakcie dopisywania
        db.rollback()
        raise _fail(UploadError(404, "Wgrywanie zostało przerwane")) from None
    finally:
        fh.close()
    if overflow:
        raise _fail(UploadError(413, "Dane przekraczają zadeklarowany rozmiar pliku"))
    if disconnected:
        return Response(status_code=204, headers=_upload_headers(up))
    if uploads.is_complete(up):
        try:
            await run_in_threadpool(uploads.finish, db, up)
        except UploadError as exc:
            raise _fail(exc) from None
    return Response(status_code=204, headers=_upload_headers(up))


def _append(db: Session, up: UploadSession, fh, data: bytes) -> None:
    """Dopisuje dane na koniec pliku i zapisuje nowy offset (HEAD po zerwaniu zwróci prawdę)."""
    try:
        fh.write(data)
        fh.flush()
    except OSError:
        fh.truncate(up.offset_bytes)
        raise
    up.offset_bytes += len(data)
    up.updated_at = utcnow()
    db.commit()
