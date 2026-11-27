"""The managed list of leagues. `Match.level` (and the standalone `SelfAssessment.league`) stay plain text
that is compared by exact value, so renaming or merging a league rewrites that text instead of following a key.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import League, Match, SelfAssessment
from app.textutil import normalize

NAME_MAX = 100


class LeagueError(ValueError):
    status_code = 422


class LeagueInUseError(LeagueError):
    status_code = 409


class LeagueExistsError(LeagueError):
    status_code = 409


@dataclass
class Renamed:
    league: League
    merged: bool = False
    moved_matches: int = 0


def ordered(db: Session, *, active_only: bool = False) -> list[League]:
    query = select(League).order_by(League.position, League.id)
    if active_only:
        query = query.where(League.is_active)
    return list(db.scalars(query))


def active_names(db: Session) -> list[str]:
    return [league.name for league in ordered(db, active_only=True)]


def usage_counts(db: Session) -> dict[str, int]:
    """Matches per exact level text."""
    return {level: n for level, n in db.execute(select(Match.level, func.count()).group_by(Match.level))}


def filter_levels(db: Session) -> list[str]:
    """Leagues in admin order (inactive too), then legacy match levels that are not in the list."""
    names = [league.name for league in ordered(db)]
    known = set(names)
    legacy = {lv.strip() for lv in db.scalars(select(Match.level).distinct()) if lv and lv.strip()} - known
    return [*names, *sorted(legacy, key=lambda lv: (normalize(lv), lv))]


def match_form_choices(db: Session, current: str) -> tuple[list[str], str | None]:
    """Active league names, and the match's stored level when it is not one of them (an inactive or legacy
    value), which the form keeps as an extra option so saving does not change it.
    """
    names = active_names(db)
    current = (current or "").strip()
    return names, (current if current and current not in names else None)


def allowed_for_match(db: Session, value: str, current: str) -> bool:
    value = value.strip()
    return not value or value == (current or "").strip() or value in active_names(db)


def renumber(db: Session) -> list[League]:
    """Gaps of 10, so swapping two neighbours is always possible."""
    items = ordered(db)
    for index, league in enumerate(items, start=1):
        league.position = index * 10
    db.flush()
    return items


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise LeagueError("Podaj nazwę ligi.")
    if len(name) > NAME_MAX:
        raise LeagueError(f"Nazwa ligi: najwyżej {NAME_MAX} znaków.")
    return name


def _same_name(db: Session, name: str, own_id: int | None) -> League | None:
    return next((other for other in ordered(db) if other.id != own_id and normalize(other.name) == normalize(name)),
                None)


def create(db: Session, name: str) -> League:
    name = _clean_name(name)
    if other := _same_name(db, name, None):
        raise LeagueExistsError(f"Liga „{other.name}” już istnieje "
                                "(nazwy porównujemy bez względu na wielkość liter i polskie znaki).")
    league = League(name=name, is_active=True, position=10 ** 6)
    db.add(league)
    db.flush()
    renumber(db)
    db.commit()
    return league


def merge_target(db: Session, league: League, name: str) -> League | None:
    """The other league that `name` would collide with, if any."""
    return _same_name(db, " ".join((name or "").split()), league.id)


def rename(db: Session, league: League, name: str, *, merge: bool = False) -> Renamed:
    """Matches and standalone self-assessments with the old name get the new one. When the new name belongs
    to another league, that needs `merge`: they move to the other league and this one is deleted.
    """
    name = _clean_name(name)
    old = league.name
    other = _same_name(db, name, league.id)
    if other is not None and not merge:
        raise LeagueExistsError(f"Liga „{other.name}” już istnieje — aby połączyć ligi, potwierdź scalenie.")
    target = other.name if other is not None else name
    moved = 0
    if target != old:
        moved = db.execute(update(Match).where(Match.level == old).values(level=target)).rowcount
        db.execute(update(SelfAssessment).where(SelfAssessment.league == old).values(league=target))
    if other is not None:
        db.delete(league)
        db.flush()
        renumber(db)
        result = Renamed(other, True, moved)
    else:
        league.name = name
        result = Renamed(league, False, moved)
    db.commit()
    return result


def set_active(db: Session, league: League, active: bool) -> None:
    league.is_active = active
    db.commit()


def delete(db: Session, league: League) -> None:
    """A league used by matches can only be deactivated."""
    used = usage_counts(db).get(league.name, 0)
    if used:
        raise LeagueInUseError(
            f"Liga „{league.name}” jest użyta w meczach ({used}) — nie można jej usunąć, tylko dezaktywować "
            "(znika z wyboru w formularzu meczu, a istniejące mecze dalej ją pokazują).")
    db.delete(league)
    db.flush()
    renumber(db)
    db.commit()


def move(db: Session, league: League, direction: str) -> None:
    if direction not in ("up", "down"):
        raise LeagueError("Nieznany kierunek przesunięcia.")
    items = renumber(db)
    index = items.index(league)
    other = index - 1 if direction == "up" else index + 1
    if 0 <= other < len(items):
        league.position, items[other].position = items[other].position, league.position
    db.commit()
