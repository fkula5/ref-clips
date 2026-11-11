"""In-app notifications. The creating functions never commit: they run in the transaction of the event, so a
notification exists exactly when the event does. Nobody is notified about their own action, and only
active accounts that may see the target get one (a set, so a person who is both crew and author gets one).
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app import config, permissions
from app.models import Clip, Comment, Match, Notification, Rating, Sheet, TrainingGroup, User, Video
from app.timeutil import utcnow


def _crew(match: Match) -> set[int]:
    return {o.user_id for o in match.officials if o.user_id is not None}


def _commenters(db: Session, scope) -> set[int]:
    return set(db.scalars(select(Comment.author_id).where(scope).distinct()))


def _deliver(db: Session, recipients: Iterable[int | None], *, actor_id: int, kind: str, match: Match | None,
             clip: Clip | None = None, sheet: Sheet | None = None, group: TrainingGroup | None = None,
             verdict: str | None = None,
             may_see: Callable[[User], bool] = permissions.can_view) -> None:
    wanted = {r for r in recipients if r is not None} - {actor_id}
    if not wanted:
        return
    now = utcnow()
    for user in db.scalars(select(User).where(User.id.in_(wanted)).order_by(User.id)):
        if may_see(user):
            db.add(Notification(
                recipient_id=user.id, kind=kind, actor_id=actor_id, match_id=match.id if match else None,
                clip_id=clip.id if clip else None, sheet_id=sheet.id if sheet else None,
                group_id=group.id if group else None, verdict=verdict, created_at=now))
    db.flush()


def rating_saved(db: Session, rating: Rating, actor_id: int, *, changed: bool) -> None:
    clip = rating.clip
    _deliver(db, [*_crew(clip.match), clip.author_id, *_commenters(db, Comment.clip_id == clip.id)],
             actor_id=actor_id, kind="rating_changed" if changed else "rating", match=clip.match, clip=clip,
             verdict=rating.verdict)


def comment_added(db: Session, comment: Comment) -> None:
    if comment.clip_id is not None:
        clip = comment.clip
        _deliver(db, [*_crew(clip.match), clip.author_id, *_commenters(db, Comment.clip_id == clip.id)],
                 actor_id=comment.author_id, kind="clip_comment", match=clip.match, clip=clip)
    else:
        match = comment.match
        _deliver(db, [*_crew(match), match.created_by, *_commenters(db, Comment.match_id == match.id)],
                 actor_id=comment.author_id, kind="match_comment", match=match)


def sheet_published(db: Session, sheet: Sheet) -> None:
    _deliver(db, _crew(sheet.match), actor_id=sheet.coach_id, kind="sheet_published", match=sheet.match,
             sheet=sheet, may_see=lambda user: permissions.can_view_sheet(user, sheet))


def group_added(db: Session, group: TrainingGroup, user_id: int, actor_id: int) -> None:
    _deliver(db, [user_id], actor_id=actor_id, kind="group_added", match=None, group=group)


def unread_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == user_id, Notification.read_at.is_(None))) or 0


def bell_label(count: int) -> str:
    if count <= 0:
        return "Powiadomienia"
    few = count == 1 or (2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14)
    return f"Powiadomienia: {count} {'nowe' if few else 'nowych'}"


def recent(db: Session, user_id: int, limit: int) -> list[Notification]:
    return list(db.scalars(
        select(Notification).where(Notification.recipient_id == user_id)
        .options(selectinload(Notification.actor), selectinload(Notification.match),
                 selectinload(Notification.group),
                 selectinload(Notification.clip).selectinload(Clip.video).selectinload(Video.marks))
        .order_by(Notification.id.desc()).limit(limit)))


def mark_read(notification: Notification) -> None:
    if notification.read_at is None:
        notification.read_at = utcnow()


def mark_all_read(db: Session, user_id: int) -> None:
    db.execute(update(Notification).where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))


def target_url(notification: Notification) -> str:
    match notification.kind:
        case "rating" | "rating_changed":
            return f"/clips/{notification.clip_id}#oceny"
        case "clip_comment":
            return f"/clips/{notification.clip_id}#komentarze"
        case "match_comment":
            return f"/matches/{notification.match_id}#komentarze"
        case "group_added":
            return "/groups"
        case _:
            return f"/sheets/{notification.sheet_id}"


def prune_notifications(db: Session) -> int:
    now = utcnow()
    removed = db.execute(delete(Notification).where(or_(
        Notification.created_at < now - timedelta(days=config.NOTIFICATION_UNREAD_KEEP_DAYS),
        (Notification.read_at.is_not(None))
        & (Notification.created_at < now - timedelta(days=config.NOTIFICATION_READ_KEEP_DAYS))))).rowcount
    db.commit()
    return removed
