from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import feedback, services
from app.models import PERIODS, RATING_VERDICTS, Clip, MatchOfficial, Rating, Video

TEAM = "team"
NO_PERIOD = "none"
DESCRIBED_YES, DESCRIBED_NO = "1", "0"
RATING_ANY, RATING_NONE = "any", "none"
# A verdict means "has at least one such rating".
RATING_CHOICES = [(RATING_ANY, "z oceną (dowolną)"),
                  *((v, f"ma ocenę: {label}") for v, label in RATING_VERDICTS.items()),
                  (RATING_NONE, "bez ocen")]


def _int(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


@dataclass
class ClipFilters:
    match_id: int | None = None
    video_id: int | None = None
    person: str = ""  # "u<account id>", "n<normalised name>" or "team"
    category_id: int | None = None
    period: str = ""
    described: str = ""
    rating: str = ""

    def pairs(self, *, scope: bool) -> list[tuple[str, str]]:
        pairs = [("person", self.person),
                 ("category_id", str(self.category_id) if self.category_id else ""),
                 ("period", self.period), ("described", self.described), ("rating", self.rating)]
        if scope:
            pairs = [("match_id", str(self.match_id) if self.match_id else ""),
                     ("video_id", str(self.video_id) if self.video_id else ""), *pairs]
        return [(k, v) for k, v in pairs if v]

    def query(self, *, scope: bool = True) -> str:
        """`scope=False` omits match and recording (match-tab and clip-navigation filters only)."""
        return urlencode(self.pairs(scope=scope))

    @property
    def active(self) -> bool:
        return bool(self.pairs(scope=False))


def parse_filters(params: Mapping[str, str]) -> ClipFilters:
    period = (params.get("period") or "").strip()
    described = (params.get("described") or "").strip()
    rating = (params.get("rating") or "").strip()
    return ClipFilters(
        match_id=_int(params.get("match_id")), video_id=_int(params.get("video_id")),
        person=(params.get("person") or "").strip()[:200],
        category_id=_int(params.get("category_id")),
        period=period if period in PERIODS or period == NO_PERIOD else "",
        described=described if described in (DESCRIBED_YES, DESCRIBED_NO) else "",
        rating=rating if rating in (RATING_ANY, RATING_NONE, *RATING_VERDICTS) else "")


def query_clips(db: Session, *, match_id=None, video_id=None, person=None, category_id=None,
                period=None, described=None, rating=None, ids=None, with_comments=False) -> list[Clip]:
    stmt = (select(Clip)
            .options(selectinload(Clip.video).selectinload(Video.marks),
                     selectinload(Clip.official).selectinload(MatchOfficial.user))
            .order_by(Clip.match_id.desc(), Clip.video_id, Clip.time_sec, Clip.id))
    if with_comments:
        stmt = stmt.options(selectinload(Clip.comments))
    if match_id:
        stmt = stmt.where(Clip.match_id == match_id)
    if video_id:
        stmt = stmt.where(Clip.video_id == video_id)
    if category_id:
        stmt = stmt.where(Clip.category_id == category_id)
    if ids:
        stmt = stmt.where(Clip.id.in_(ids))
    if described == DESCRIBED_YES:
        stmt = stmt.where(Clip.described_at.is_not(None))
    elif described == DESCRIBED_NO:
        stmt = stmt.where(Clip.described_at.is_(None))
    if rating == RATING_NONE:
        stmt = stmt.where(~Clip.ratings.any())
    elif rating == RATING_ANY:
        stmt = stmt.where(Clip.ratings.any())
    elif rating:
        stmt = stmt.where(Clip.ratings.any(Rating.verdict == rating))
    if person == TEAM:
        stmt = stmt.where(Clip.whole_team.is_(True))
    elif person:
        accounts = services.account_names(db)
        official_ids = [oid for oid, user_id, name in db.execute(
            select(MatchOfficial.id, MatchOfficial.user_id, MatchOfficial.name))
            if services.person_key(user_id, name, accounts) == person]
        stmt = stmt.where(Clip.official_id.in_(official_ids))
    clips = list(db.scalars(stmt))
    if period:  # period is derived from markers, so filter in Python
        wanted = "" if period == NO_PERIOD else period
        clips = [c for c in clips if (services.period_for(c.video.marks, c.time_sec) or "") == wanted]
    return clips


def select_clips(db: Session, filters: ClipFilters, *, match_id: int | None = None) -> list[Clip]:
    return query_clips(db, match_id=match_id or filters.match_id, video_id=filters.video_id,
                       person=filters.person or None, category_id=filters.category_id,
                       period=filters.period or None, described=filters.described or None,
                       rating=filters.rating or None)


@dataclass
class ClipStats:
    ratings: list[tuple[str, int]]
    comments: int


def clip_stats(db: Session, clips: list[Clip]) -> dict[int, ClipStats]:
    ids = [c.id for c in clips]
    ratings, comments = feedback.rating_counts(db, ids), feedback.comment_counts(db, ids)
    return {i: ClipStats(ratings.get(i, []), comments.get(i, 0)) for i in ids}


def match_people(db: Session, match) -> list[tuple[str, str]]:
    accounts = services.account_names(db)
    return [(services.person_key(o.user_id, o.name, accounts), o.label) for o in match.officials]
