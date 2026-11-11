from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config, notify
from app.models import RATING_VERDICTS, Clip, Comment, Rating
from app.timeutil import utcnow


class FeedbackError(Exception):
    status_code = 422


def clean_text(raw: str, *, label: str, required: bool) -> str:
    """The character limit is counted after normalising line endings (browsers send CRLF)."""
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


def comments_of(db: Session, *, clip_id: int | None = None, match_id: int | None = None,
                before: int | None = None, everything: bool = False) -> tuple[list[Comment], int | None]:
    """The newest `COMMENT_PAGE_SIZE` comments older than `before`, oldest first, and the id to pass as
    `before` for the next older batch (None when there is none).
    """
    column = Comment.clip_id if clip_id is not None else Comment.match_id
    stmt = (select(Comment).options(selectinload(Comment.author))
            .where(column == (clip_id if clip_id is not None else match_id)).order_by(Comment.id.desc()))
    if before is not None:
        stmt = stmt.where(Comment.id < before)
    if everything:
        return list(reversed(db.scalars(stmt).all())), None
    found = list(db.scalars(stmt.limit(config.COMMENT_PAGE_SIZE + 1)))
    older = len(found) > config.COMMENT_PAGE_SIZE
    shown = list(reversed(found[:config.COMMENT_PAGE_SIZE]))
    return shown, shown[0].id if older else None


def has_comments(db: Session, **scope: int) -> bool:
    (name, value), = scope.items()
    return db.scalar(select(Comment.id).where(getattr(Comment, name) == value).limit(1)) is not None


def create_comment(db: Session, author_id: int, body: str, *, clip_id: int | None = None,
                   match_id: int | None = None) -> Comment:
    comment = Comment(clip_id=clip_id, match_id=match_id, author_id=author_id,
                      body=clean_text(body, label="Komentarz", required=True))
    db.add(comment)
    db.flush()
    notify.comment_added(db, comment)
    return comment


def edit_comment(comment: Comment, body: str) -> None:
    """`edited_at` changes only when the text really changed."""
    text = clean_text(body, label="Komentarz", required=True)
    if text != comment.body:
        comment.body = text
        comment.edited_at = utcnow()


def ratings_of(db: Session, clip: Clip) -> list[Rating]:
    return list(db.scalars(select(Rating).options(selectinload(Rating.coach))
                           .where(Rating.clip_id == clip.id).order_by(Rating.id)))


def _own_rating(db: Session, clip_id: int, coach_id: int) -> Rating | None:
    return db.scalar(select(Rating).where(Rating.clip_id == clip_id, Rating.coach_id == coach_id))


def edit_rating(db: Session, rating: Rating, verdict: str, comment: str, actor_id: int) -> None:
    """The author (`coach_id`) stays unchanged even when an admin edits; `updated_at` moves only on a
    real change because "changed" relies on it. Only a changed verdict is announced, not a reworded comment.
    """
    verdict = clean_verdict(verdict)
    comment = clean_text(comment, label="Komentarz do oceny", required=False)
    if (verdict, comment) != (rating.verdict, rating.comment):
        verdict_changed = verdict != rating.verdict
        rating.verdict, rating.comment = verdict, comment
        rating.updated_at = utcnow()
        if verdict_changed:
            notify.rating_saved(db, rating, actor_id, changed=True)


def save_own_rating(db: Session, clip: Clip, coach_id: int, verdict: str, comment: str) -> Rating:
    """A race between two requests ends in a uniqueness violation on flush; the rating created by the
    other request is then loaded and updated (no duplicate, no 500).
    """
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
        except IntegrityError:
            db.rollback()
            rating = _own_rating(db, clip.id, coach_id)
            if rating is None:
                raise
        else:
            notify.rating_saved(db, rating, coach_id, changed=False)
            return rating
    edit_rating(db, rating, verdict, comment, coach_id)
    return rating


def is_edited(rating: Rating) -> bool:
    return rating.updated_at > rating.created_at


def rating_counts(db: Session, clip_ids: Iterable[int]) -> dict[int, list[tuple[str, int]]]:
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
