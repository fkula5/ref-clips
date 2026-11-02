"""Oceny szkoleniowców i komentarze: walidacja treści, zapis oceny (jedna na parę klip–szkoleniowiec),
liczniki do tabeli klipów. Reguły uprawnień są w `permissions`, trasy w `routers/feedback.py`."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config
from app.models import RATING_VERDICTS, Clip, Comment, Rating
from app.timeutil import utcnow


class FeedbackError(Exception):
    """Błąd walidacji treści oceny lub komentarza (HTTP 422); komunikat trafia do formularza."""
    status_code = 422


def clean_text(raw: str, *, label: str, required: bool) -> str:
    """Treść po usunięciu białych znaków z brzegów, z ujednoliconymi końcami linii; limit znaków
    liczymy po normalizacji (przeglądarka wysyła nową linię jako \\r\\n)."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if required and not text:
        raise FeedbackError(f"{label}: wpisz treść.")
    if len(text) > config.TEXT_MAX_CHARS:
        raise FeedbackError(f"{label}: najwyżej {config.TEXT_MAX_CHARS} znaków (jest {len(text)}).")
    return text


def clean_verdict(raw: str) -> str:
    verdict = raw.strip()
    if verdict not in RATING_VERDICTS:
        raise FeedbackError("Ocena: wybierz prawidłowa, nieprawidłowa albo dyskusyjna.")
    return verdict


# --- komentarze -----------------------------------------------------------------
def comments_of(db: Session, *, clip_id: int | None = None, match_id: int | None = None) -> list[Comment]:
    """Komentarze klipu albo meczu od najstarszego, z autorami (bez N+1)."""
    column = Comment.clip_id if clip_id is not None else Comment.match_id
    return list(db.scalars(select(Comment).options(selectinload(Comment.author))
                           .where(column == (clip_id if clip_id is not None else match_id))
                           .order_by(Comment.id)))


def create_comment(db: Session, author_id: int, body: str, *, clip_id: int | None = None,
                   match_id: int | None = None) -> Comment:
    comment = Comment(clip_id=clip_id, match_id=match_id, author_id=author_id,
                      body=clean_text(body, label="Komentarz", required=True))
    db.add(comment)
    db.flush()
    return comment


def edit_comment(comment: Comment, body: str) -> None:
    """Zmienia treść; `edited_at` ustawiamy tylko, gdy treść faktycznie się zmieniła."""
    text = clean_text(body, label="Komentarz", required=True)
    if text != comment.body:
        comment.body = text
        comment.edited_at = utcnow()


# --- oceny ----------------------------------------------------------------------
def ratings_of(db: Session, clip: Clip) -> list[Rating]:
    return list(db.scalars(select(Rating).options(selectinload(Rating.coach))
                           .where(Rating.clip_id == clip.id).order_by(Rating.id)))


def _own_rating(db: Session, clip_id: int, coach_id: int) -> Rating | None:
    return db.scalar(select(Rating).where(Rating.clip_id == clip_id, Rating.coach_id == coach_id))


def edit_rating(rating: Rating, verdict: str, comment: str) -> None:
    """Zmiana oceny. Autor (`coach_id`) zostaje bez zmian także wtedy, gdy edytuje administrator;
    `updated_at` ruszamy tylko przy faktycznej zmianie, bo na nim opiera się „zmieniona”."""
    verdict = clean_verdict(verdict)
    comment = clean_text(comment, label="Komentarz do oceny", required=False)
    if (verdict, comment) != (rating.verdict, rating.comment):
        rating.verdict, rating.comment = verdict, comment
        rating.updated_at = utcnow()


def save_own_rating(db: Session, clip: Clip, coach_id: int, verdict: str, comment: str) -> Rating:
    """Własna ocena szkoleniowca: nowa albo aktualizacja istniejącej (jedna na parę klip–szkoleniowiec).
    Wyścig dwóch żądań kończy się naruszeniem unikalności przy `flush`; wtedy wczytujemy ocenę
    założoną przez drugie żądanie i ją aktualizujemy (bez duplikatu i bez błędu 500)."""
    verdict = clean_verdict(verdict)
    comment = clean_text(comment, label="Komentarz do oceny", required=False)
    rating = _own_rating(db, clip.id, coach_id)
    if rating is None:
        now = utcnow()
        rating = Rating(clip_id=clip.id, coach_id=coach_id, verdict=verdict, comment=comment,
                        created_at=now, updated_at=now)
        db.add(rating)
        try:
            db.flush()
            return rating
        except IntegrityError:
            db.rollback()
            rating = _own_rating(db, clip.id, coach_id)
            if rating is None:
                raise
    edit_rating(rating, verdict, comment)
    return rating


def is_edited(rating: Rating) -> bool:
    return rating.updated_at > rating.created_at


# --- liczniki do tabeli klipów (dwa zapytania na całą listę) ------------------------
def rating_counts(db: Session, clip_ids: Iterable[int]) -> dict[int, list[tuple[str, int]]]:
    """Klip -> [(werdykt, liczba)] w stałej kolejności prawidłowa, nieprawidłowa, dyskusyjna."""
    ids = list(clip_ids)
    counts: dict[int, dict[str, int]] = {}
    if ids:
        for clip_id, verdict, n in db.execute(
                select(Rating.clip_id, Rating.verdict, func.count()).where(Rating.clip_id.in_(ids))
                .group_by(Rating.clip_id, Rating.verdict)):
            counts.setdefault(clip_id, {})[verdict] = n
    return {cid: [(v, per[v]) for v in RATING_VERDICTS if v in per] for cid, per in counts.items()}


def comment_counts(db: Session, clip_ids: Iterable[int]) -> dict[int, int]:
    ids = list(clip_ids)
    if not ids:
        return {}
    return dict(db.execute(select(Comment.clip_id, func.count()).where(Comment.clip_id.in_(ids))
                           .group_by(Comment.clip_id)).all())
