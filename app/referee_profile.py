"""A referee's profile: matches, clips, coach ratings and comments.
Nothing here has its own visibility rules: every viewer who may open the app already sees all matches,
clips, ratings and clip comments in the lists, so the profile reads them through the same filters
(`clip_list._filtered`, `services.person_officials`). Sheets and self-assessments are deliberately left
out (they have their own, stricter rules). The group list is the one thing that depends on the viewer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import clip_list, config, permissions, services
from app.models import (RATING_VERDICTS, Category, Clip, Comment, GroupMember, Match, MatchOfficial, Rating,
                        TrainingGroup, User)
from app.pagination import Page, paginate
from app.timeutil import local_tz

PERIODS = {"season": "ten sezon", "30": "ostatnie 30 dni", "90": "ostatnie 90 dni", "all": "cały czas"}
DEFAULT_PERIOD = "season"
SEASON_START_MONTH = 8  # the season runs from August to July
RECENT_LIMIT = 8


def parse_period(raw: str | None) -> str:
    raw = (raw or "").strip()
    return raw if raw in PERIODS else DEFAULT_PERIOD


def period_start(period: str, today: date | None = None) -> date | None:
    today = today or datetime.now(local_tz()).date()
    if period == "season":
        return date(today.year if today.month >= SEASON_START_MONTH else today.year - 1, SEASON_START_MONTH, 1)
    if period in ("30", "90"):
        return date.fromordinal(today.toordinal() - int(period))
    return None


def person_key(user: User) -> str:
    return f"u{user.id}"


def clips_link(person: str, since: date | None = None, **params) -> str:
    """Address in the clip list; `since` makes it show the same period as the profile's numbers."""
    wanted = ("match_id", "category_id", "rating")
    pairs = [("person", person), *((k, str(params[k])) for k in wanted if params.get(k)),
             *([("since", since.isoformat())] if since else [])]
    return "/clips?" + urlencode(pairs)


@dataclass
class Tally:
    """Counts of clips, not of ratings: a clip counts once under each verdict it has at least one rating
    of (the same meaning as the clip list's rating filter, so the numbers match the links).
    """
    clips: int = 0
    rated: int = 0
    verdicts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(RATING_VERDICTS, 0))

    def add(self, verdicts: set[str]) -> None:
        self.clips += 1
        self.rated += bool(verdicts)
        for verdict in verdicts:
            self.verdicts[verdict] += 1

    @property
    def unrated(self) -> int:
        return self.clips - self.rated


@dataclass
class MatchRow:
    match: Match
    function: str
    tally: Tally


@dataclass
class CategoryRow:
    category: Category
    tally: Tally


@dataclass
class Profile:
    person: User
    period: str
    since: date | None
    groups: list[TrainingGroup]
    match_count: int
    total: Tally
    categorised: Tally
    uncategorised: int
    categories: list[CategoryRow]
    matches: list[MatchRow]
    pager: Page
    clips: list[Clip]
    clip_stats: dict
    ratings: list[Rating]
    comments: list[Comment]


def referee_or_none(db: Session, user_id: int) -> User | None:
    user = db.get(User, user_id)
    return user if user is not None and permissions.REFEREE in user.roles else None


def visible_groups(db: Session, viewer: User, person: User) -> list[TrainingGroup]:
    """Group membership is only shown where the viewer may open the group page (admin or a coach of the
    group); elsewhere that page answers 404 to keep the list of referees private.
    """
    groups = db.scalars(select(TrainingGroup).join(GroupMember).where(
        GroupMember.user_id == person.id, GroupMember.role == "referee")
        .order_by(func.lower(TrainingGroup.name), TrainingGroup.id))
    return [g for g in groups if permissions.can_view_group(viewer, g)]


def build(db: Session, viewer: User, person: User, period: str, requested_page: int) -> Profile:
    key = person_key(person)
    since = period_start(period)
    filters = dict(person=key, since=since)
    slots = services.person_officials(db, key)
    function_of = {match_id: function for _, match_id, function in slots}

    base = clip_list._filtered(db, **filters)
    clip_ids = base.with_only_columns(Clip.id)
    clip_rows = list(db.execute(base.with_only_columns(Clip.id, Clip.match_id, Clip.category_id)))
    verdicts: dict[int, set[str]] = {}
    for clip_id, verdict in db.execute(select(Rating.clip_id, Rating.verdict).where(Rating.clip_id.in_(clip_ids))):
        verdicts.setdefault(clip_id, set()).add(verdict)
    total, categorised, per_match, per_category = Tally(), Tally(), {}, {}
    for clip_id, match_id, category_id in clip_rows:
        found = verdicts.get(clip_id, set())
        total.add(found)
        per_match.setdefault(match_id, Tally()).add(found)
        if category_id:
            categorised.add(found)
            per_category.setdefault(category_id, Tally()).add(found)
    categories = [CategoryRow(c, per_category[c.id]) for c in services.all_categories(db) if c.id in per_category]

    match_stmt = select(Match).where(Match.id.in_(list(function_of)))
    if since:
        match_stmt = match_stmt.where(Match.date >= since)
    count = db.scalar(select(func.count()).select_from(match_stmt.subquery())) or 0
    pager = paginate(count, requested_page, config.MATCH_PAGE_SIZE)
    matches = db.scalars(match_stmt.options(selectinload(Match.officials).selectinload(MatchOfficial.user))
                         .order_by(Match.date.desc(), Match.id.desc()).limit(pager.size).offset(pager.offset))
    rows = [MatchRow(m, function_of[m.id], per_match.get(m.id, Tally())) for m in matches]

    recent = clip_list.recent_clips(db, RECENT_LIMIT, **filters)
    ratings = list(db.scalars(
        select(Rating).where(Rating.clip_id.in_(clip_ids))
        .options(selectinload(Rating.coach), selectinload(Rating.clip).selectinload(Clip.match),
                 selectinload(Rating.clip).selectinload(Clip.official))
        .order_by(Rating.created_at.desc(), Rating.id.desc()).limit(RECENT_LIMIT)))
    comments = list(db.scalars(
        select(Comment).where(Comment.clip_id.in_(clip_ids))
        .options(selectinload(Comment.author), selectinload(Comment.clip).selectinload(Clip.match),
                 selectinload(Comment.clip).selectinload(Clip.official))
        .order_by(Comment.id.desc()).limit(RECENT_LIMIT)))
    return Profile(person, period, since, visible_groups(db, viewer, person), count, total, categorised,
                   total.clips - categorised.clips, categories, rows, pager, recent, clip_list.clip_stats(db, recent), ratings, comments)
