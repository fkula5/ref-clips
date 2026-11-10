from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import retention, services
from app.models import Clip, Match, MatchOfficial, Video

PAGE_SIZE = 25


@dataclass
class MatchFilters:
    date_from: date | None = None
    date_to: date | None = None
    level: str = ""
    person: str = ""  # "u<id>" or "n<name>" key from services.people
    mine: bool = False
    page: int = 1
    errors: list[str] = field(default_factory=list)

    def query(self, page: int | None = None) -> str:
        pairs = [("date_from", self.date_from.isoformat() if self.date_from else ""),
                 ("date_to", self.date_to.isoformat() if self.date_to else ""),
                 ("level", self.level), ("person", self.person), ("mine", "1" if self.mine else ""),
                 ("page", str(page) if page and page > 1 else "")]
        return urlencode([(k, v) for k, v in pairs if v])


def _parse_date(raw: str, label: str, errors: list[str]) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.append(f"Niepoprawna data „{label}” — filtr pominięty.")
        return None


def parse_filters(params: Mapping[str, str]) -> MatchFilters:
    errors: list[str] = []
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1
    return MatchFilters(
        date_from=_parse_date(params.get("date_from", ""), "od", errors),
        date_to=_parse_date(params.get("date_to", ""), "do", errors),
        level=params.get("level", "").strip(), person=params.get("person", "").strip(),
        mine=params.get("mine", "") in ("1", "on", "true"), page=page, errors=errors)


@dataclass
class MatchRow:
    match: Match
    state: services.MatchState
    clips: int
    undescribed: int
    expiry: str | None = None


@dataclass
class MatchPage:
    rows: list[MatchRow]
    total: int
    page: int
    pages: int

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages


def _person_match_ids(db: Session, person: str) -> list[int]:
    accounts = services.account_names(db)
    return [match_id for match_id, user_id, name in db.execute(
        select(MatchOfficial.match_id, MatchOfficial.user_id, MatchOfficial.name))
        if services.person_key(user_id, name, accounts) == person]


def list_matches(db: Session, filters: MatchFilters, user_id: int,
                 page_size: int = PAGE_SIZE) -> MatchPage:
    stmt = select(Match)
    if filters.date_from:
        stmt = stmt.where(Match.date >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Match.date <= filters.date_to)
    if filters.level:
        stmt = stmt.where(Match.level == filters.level)
    if filters.person:
        stmt = stmt.where(Match.id.in_(_person_match_ids(db, filters.person)))
    if filters.mine:
        own_crew = select(MatchOfficial.match_id).where(MatchOfficial.user_id == user_id)
        stmt = stmt.where(or_(Match.created_by == user_id, Match.id.in_(own_crew)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    pages = max(1, -(-total // page_size))
    page = min(filters.page, pages)
    matches = db.scalars(
        stmt.options(selectinload(Match.officials).selectinload(MatchOfficial.user),
                     selectinload(Match.videos).selectinload(Video.marks))
        .order_by(Match.date.desc(), Match.id.desc())
        .limit(page_size).offset((page - 1) * page_size)).all()

    ids = [m.id for m in matches]
    counts = {match_id: (n, undescribed or 0) for match_id, n, undescribed in db.execute(
        select(Clip.match_id, func.count(),
               func.sum(case((Clip.described_at.is_(None), 1), else_=0)))
        .where(Clip.match_id.in_(ids)).group_by(Clip.match_id))}
    queue = services.transcode_queue(db)
    rows = [MatchRow(m, services.match_state(m.videos, queue), *counts.get(m.id, (0, 0)),
                     expiry=retention.expiry_note(m.videos))
            for m in matches]
    return MatchPage(rows, total, page, pages)
