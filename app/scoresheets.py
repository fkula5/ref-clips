"""Scoresheet ("Protokół") files of a match: photos or PDFs, stored under generated names in
`scoresheets/`. The type comes from the file's first bytes, never from the extension or the client's
Content-Type, and every file is served with the stored type, so nothing uploaded can be rendered as HTML.
SVG is deliberately not allowed.
"""
from __future__ import annotations

import logging
import re
import secrets
import shutil
import time
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, uploads
from app.models import Match, MatchScoresheet, User
from app.storage import storage

log = logging.getLogger("scoresheets")

PREFIX = "scoresheets"
HEAD_BYTES = 1024
FILENAME_MAX = 150
# ISO base media "major brands" of HEIC/HEIF stills (not AVIF).
HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs"}
HEIF_BRANDS = {b"mif1", b"msf1", b"heif"}


@dataclass(frozen=True)
class Kind:
    content_type: str
    extensions: tuple[str, ...]  # the first one is used when the user's file name has none of them
    inline: bool  # whether the page shows it itself (browsers other than Safari cannot show HEIC)


KINDS = {k.content_type: k for k in (
    Kind("application/pdf", ("pdf",), True),
    Kind("image/jpeg", ("jpg", "jpeg"), True),
    Kind("image/png", ("png",), True),
    Kind("image/webp", ("webp",), True),
    Kind("image/heic", ("heic",), False),
    Kind("image/heif", ("heif", "heic"), False),
)}
ACCEPT = ",".join([*KINDS, *(f".{e}" for k in KINDS.values() for e in k.extensions)])
ALLOWED_TEXT = "PDF, JPEG, PNG, WebP, HEIC/HEIF"


class ScoresheetError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def detect(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in HEIC_BRANDS:
            return "image/heic"
        if brand in HEIF_BRANDS:
            return "image/heif"
    return None


def _base_name(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(" " if unicodedata.category(c).startswith(("C", "Z")) else c for c in name)
    return re.sub(r"\s+", " ", name).strip(" .") or "protokol"


def clean_filename(name: str, content_type: str) -> str:
    """Display and download name: no directories or control characters, a bounded length and an
    extension that matches the real type (a JPEG named `.pdf` must not download as a PDF).
    """
    name = _base_name(name)
    extensions = KINDS[content_type].extensions
    stem, dot, ext = name.rpartition(".")
    if dot and stem and ext.lower() in extensions:
        return stem[:FILENAME_MAX - len(ext) - 1].rstrip() + "." + ext
    return name[:FILENAME_MAX - len(extensions[0]) - 1].rstrip() + "." + extensions[0]


def plural_files(n: int) -> str:
    if n == 1:
        return "1 plik"
    return f"{n} {'pliki' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'plików'}"


@dataclass
class Incoming:
    filename: str
    file: BinaryIO


def _measure(file: BinaryIO) -> tuple[int, bytes]:
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    head = file.read(HEAD_BYTES)
    file.seek(0)
    return size, head


def add_files(db: Session, user: User, match: Match, incoming: list[Incoming]) -> list[MatchScoresheet]:
    """All or nothing: one rejected file rejects the whole batch, so the user fixes the selection once."""
    if not incoming:
        raise ScoresheetError("Wybierz co najmniej jeden plik.")
    free_slots = max(0, config.SCORESHEET_MAX_FILES - len(match.scoresheets))
    if len(incoming) > free_slots:
        raise ScoresheetError(
            f"Do meczu można dodać najwyżej {plural_files(config.SCORESHEET_MAX_FILES)} protokołu "
            f"(zostało miejsca na: {free_slots}).")
    checked: list[tuple[Incoming, Kind, int]] = []
    for item in incoming:
        label = f"„{_base_name(item.filename)[:60]}”"
        size, head = _measure(item.file)
        if size == 0:
            raise ScoresheetError(f"{label}: plik jest pusty.")
        if size > config.SCORESHEET_MAX_BYTES:
            raise ScoresheetError(
                f"{label}: plik jest za duży (maksymalnie {config.SCORESHEET_MAX_BYTES // 1024 // 1024} MB).", 413)
        content_type = detect(head)
        if content_type is None:
            raise ScoresheetError(f"{label}: niedozwolony typ pliku. Dozwolone: {ALLOWED_TEXT}.", 415)
        checked.append((item, KINDS[content_type], size))
    try:
        uploads.check_space(db, sum(size for _, _, size in checked), user, "protokół")
    except uploads.UploadError as exc:
        raise ScoresheetError(exc.message, exc.status_code) from None

    written: list[str] = []
    rows: list[MatchScoresheet] = []
    try:
        for item, kind, size in checked:
            key = f"{PREFIX}/{secrets.token_hex(16)}.{kind.extensions[0]}"
            with storage.open_write(key) as out:
                written.append(key)
                shutil.copyfileobj(item.file, out)
            rows.append(MatchScoresheet(
                match_id=match.id, path=key, content_type=kind.content_type, size_bytes=size,
                original_filename=clean_filename(item.filename, kind.content_type), uploaded_by=user.id))
        db.add_all(rows)
        db.commit()
    except BaseException:
        db.rollback()
        for key in written:
            storage.delete(key)
        raise
    return rows


def remove(db: Session, scoresheet: MatchScoresheet) -> None:
    key = scoresheet.path
    db.delete(scoresheet)
    db.commit()
    storage.delete(key)  # after the commit: a failed delete leaves an orphan for the cleanup, never a dead row


def cleanup_orphans(db: Session, min_age_seconds: float | None = None) -> int:
    """A fresh file may belong to an upload that has not stored its row yet."""
    if min_age_seconds is None:
        min_age_seconds = config.ORPHAN_MIN_AGE_SECONDS
    cutoff = time.time() - min_age_seconds
    candidates = [key for key, _size, mtime in storage.iter_files(PREFIX) if mtime < cutoff]
    if not candidates:
        return 0
    used = set(db.scalars(select(MatchScoresheet.path)))
    removed = 0
    for key in candidates:
        if key in used:
            continue
        try:
            storage.delete(key)
            removed += 1
        except OSError:
            log.warning("Nie udało się usunąć osieroconego pliku protokołu %s", key)
    if removed:
        log.info("Usunięto osierocone pliki protokołów: %d", removed)
    return removed
