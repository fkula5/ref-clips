"""Training groups. Groups only organise views (activity, the rating queue, list filters); they never
restrict access to matches or clips.
A match belongs to a group when any account in its crew is a referee member of the group; clips follow
their match.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config, notify, permissions
from app.models import GROUP_ROLES, Clip, GroupMember, MatchOfficial, Rating, TrainingGroup, User, Video
from app.pagination import Page, paginate
from app.timeutil import utcnow

NAME_MAX = 100
DESCRIPTION_MAX = 1000
PERIOD_CHOICES = (7, 14, 30, 90)
DEFAULT_DAYS = 14


class GroupError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def match_ids(group_id: int):
    """Subquery of the ids of matches whose crew includes a referee member of the group."""
    return (select(MatchOfficial.match_id)
            .join(GroupMember, GroupMember.user_id == MatchOfficial.user_id)
            .where(GroupMember.group_id == group_id, GroupMember.role == "referee"))


def all_groups(db: Session) -> list[TrainingGroup]:
    return list(db.scalars(select(TrainingGroup).order_by(func.lower(TrainingGroup.name), TrainingGroup.id)))


def groups_of(db: Session, user: User) -> list[TrainingGroup]:
    """Everything an admin sees, otherwise the groups the user belongs to in either role."""
    if permissions.can_manage_users(user):
        return all_groups(db)
    mine = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    return list(db.scalars(select(TrainingGroup).where(TrainingGroup.id.in_(mine))
                           .order_by(func.lower(TrainingGroup.name), TrainingGroup.id)))


def _clean(name: str, description: str) -> tuple[str, str]:
    name, description = name.strip(), description.strip()
    if not name:
        raise GroupError("Podaj nazwę grupy.")
    if len(name) > NAME_MAX:
        raise GroupError(f"Nazwa grupy: najwyżej {NAME_MAX} znaków.")
    if len(description) > DESCRIPTION_MAX:
        raise GroupError(f"Opis grupy: najwyżej {DESCRIPTION_MAX} znaków.")
    return name, description


def create_group(db: Session, creator: User, name: str, description: str) -> TrainingGroup:
    name, description = _clean(name, description)
    group = TrainingGroup(name=name, description=description, created_by=creator.id)
    group.members.append(GroupMember(user_id=creator.id, role="coach"))
    db.add(group)
    db.commit()
    return group


def update_group(db: Session, group: TrainingGroup, name: str, description: str) -> None:
    group.name, group.description = _clean(name, description)
    db.commit()


def delete_group(db: Session, group: TrainingGroup) -> None:
    db.delete(group)
    db.commit()


def candidates(db: Session, group: TrainingGroup, role: str) -> list[User]:
    """Active accounts with the matching role who are not in the group yet (in either role)."""
    present = {m.user_id for m in group.members}
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name, User.id)).all()
    return [u for u in users if role in u.roles and u.id not in present]


def add_member(db: Session, group: TrainingGroup, user_id: str | int, role: str, actor: User) -> User:
    if role not in GROUP_ROLES:
        raise GroupError("Nieznana rola w grupie.")
    user = db.get(User, int(user_id)) if str(user_id).isdigit() else None
    if user is None:
        raise GroupError("Wybierz konto z listy.")
    if role not in user.roles or not user.is_active:
        raise GroupError(f"Konto {user.name} nie jest aktywnym kontem z rolą „{GROUP_ROLES[role]}”.")
    existing = next((m for m in group.members if m.user_id == user.id), None)
    if existing is not None:
        raise GroupError(f"{user.name} jest już w tej grupie (rola: {GROUP_ROLES[existing.role]}).")
    group.members.append(GroupMember(user_id=user.id, role=role))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise GroupError(f"{user.name} jest już w tej grupie.") from None
    notify.group_added(db, group, user.id, actor.id)
    db.commit()
    return user


def remove_referee(db: Session, group: TrainingGroup, user_id: int) -> User:
    member = next((m for m in group.members if m.user_id == user_id and m.role == "referee"), None)
    if member is None:
        raise GroupError("Tego sędziego nie ma w grupie.", 404)
    group.members.remove(member)
    db.commit()
    return member.user


def remove_coach(db: Session, group: TrainingGroup, user_id: int) -> User:
    """A group always keeps a coach (admins included), otherwise nobody but an admin could open it."""
    coaches = group.coaches
    member = next((m for m in coaches if m.user_id == user_id), None)
    if member is None:
        raise GroupError("Tego szkoleniowca nie ma w grupie.", 404)
    if len(coaches) == 1:
        raise GroupError(f"W grupie musi zostać co najmniej jeden szkoleniowiec. "
                         f"Dodaj innego, zanim usuniesz: {member.user.name}.")
    group.members.remove(member)
    db.commit()
    return member.user


@dataclass
class ActivityRow:
    user: User
    recordings: int
    markers: int
    described: int
    last: datetime | None

    @property
    def total(self) -> int:
        return self.recordings + self.markers + self.described


def parse_days(raw: str | None) -> int:
    return int(raw) if raw and raw.isdigit() and int(raw) in PERIOD_CHOICES else DEFAULT_DAYS


def activity(db: Session, group: TrainingGroup, days: int, now: datetime | None = None) -> list[ActivityRow]:
    """Three grouped queries for the whole group. "Last activity" ignores the period."""
    referees = group.referees
    ids = [m.user_id for m in referees]
    since = (now or utcnow()) - timedelta(days=days)

    def in_period(column):
        return func.coalesce(func.sum(case((column >= since, 1), else_=0)), 0)

    videos = {uid: (n, last) for uid, n, last in db.execute(
        select(Video.created_by, in_period(Video.created_at), func.max(Video.created_at))
        .where(Video.created_by.in_(ids)).group_by(Video.created_by))}
    markers = {uid: (n, last) for uid, n, last in db.execute(
        select(Clip.author_id, in_period(Clip.created_at), func.max(Clip.created_at))
        .where(Clip.author_id.in_(ids)).group_by(Clip.author_id))}
    described = {uid: (n, last) for uid, n, last in db.execute(
        select(Clip.described_by_id, in_period(Clip.described_at), func.max(Clip.described_at))
        .where(Clip.described_by_id.in_(ids)).group_by(Clip.described_by_id))}
    rows = []
    for member in referees:
        recordings, last_video = videos.get(member.user_id, (0, None))
        added, last_marker = markers.get(member.user_id, (0, None))
        done, last_described = described.get(member.user_id, (0, None))
        last = max((d for d in (last_video, last_marker, last_described) if d is not None), default=None)
        rows.append(ActivityRow(member.user, recordings, added, done, last))
    return sorted(rows, key=lambda r: r.user.name.lower())


def _unrated_clips(group: TrainingGroup, coach_id: int):
    """Described clips from the group's matches that `coach_id` has not rated; ratings by other coaches
    do not count.
    """
    return (Clip.match_id.in_(match_ids(group.id)), Clip.described_at.is_not(None),
            ~Clip.ratings.any(Rating.coach_id == coach_id))


def review_count(db: Session, group: TrainingGroup, coach_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Clip).where(*_unrated_clips(group, coach_id))) or 0


def review_queue(db: Session, group: TrainingGroup, coach_id: int, requested: int = 1) -> tuple[list[Clip], Page]:
    """Newest described first."""
    size = config.REVIEW_PAGE_SIZE
    pager = paginate(review_count(db, group, coach_id), requested, size)
    clips = list(db.scalars(
        select(Clip).where(*_unrated_clips(group, coach_id))
        .options(selectinload(Clip.video), selectinload(Clip.match), selectinload(Clip.official))
        .order_by(Clip.described_at.desc(), Clip.id.desc()).limit(size).offset(pager.offset)))
    return clips, pager
