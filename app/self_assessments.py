"""Referee self-assessment ("Arkusz samooceny"). The header is read from the match, or typed by the author
on a standalone sheet (a match that is not in the system, `match_id` NULL). A clip row keeps text snapshots
of the clip's time and name, taken when the clip is added and refreshed on every save of a draft, so a
submitted sheet stays readable if the clip is later deleted. A manual row has no clip and its time and
name are the author's own text, never refreshed. Posted fields that are missing are left untouched, so a
stale form can never wipe stored text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import config, notify, permissions, services
from app.models import Clip, Match, SelfAssessment, SelfAssessmentClip, User
from app.pagination import Page, paginate
from app.textutil import format_clock, slugify
from app.timeutil import utcnow

MIN_CLIPS = 3
LABEL_MAX = 200
# The wording is the Excel sheet's, including "opinię" in the first question.
QUESTIONS = (
    ("opinion", "Co uważam o swoim sędziowaniu? (ogólne opinię o swoim sędziowaniu)"),
    ("good", "Co było dobre w tym meczu i co chciałbym zachować na kolejne mecze?"),
    ("bad", "Co było złe w tym meczu i co chciałbym zmienić w kolejnych meczach?"),
)
ASSISTANTS = ("U1", "U2")
# Typed header of a standalone sheet: (field, label, required)
HEADER_FIELDS = (
    ("league", "Liga", True), ("home_team", "Gospodarze", True), ("away_team", "Goście", True),
    ("main_referee", "Sędzia główny", True), ("assistant_referees", "Sędzia pomocniczy", False),
)


class SelfAssessmentError(Exception):
    status_code = 422

    def __init__(self, *errors: str, saved: bool = False):
        super().__init__(" ".join(errors))
        self.errors = list(errors)
        self.saved = saved  # the draft content was stored although the action failed


@dataclass(frozen=True)
class Header:
    level: str
    date: str
    team_a: str
    team_b: str
    main_referee: str
    assistants: str


def header(sa: SelfAssessment) -> Header:
    match = sa.match
    if match is None:
        return Header(
            level=sa.league, date=sa.match_date.strftime("%d.%m.%Y") if sa.match_date else "",
            team_a=sa.home_team, team_b=sa.away_team, main_referee=sa.main_referee,
            assistants=sa.assistant_referees)

    def name(function: str) -> str:
        official = match.official(function)
        return official.display_name if official else ""

    return Header(
        level=match.level, date=match.date.strftime("%d.%m.%Y"),
        team_a=match.team_a_name or match.team_a_color, team_b=match.team_b_name or match.team_b_color,
        main_referee=name("CC"), assistants=", ".join(n for n in map(name, ASSISTANTS) if n))


def clip_labels(clip: Clip) -> tuple[str, str]:
    """(time, name) as the app labels the clip: the recording and the time in it, plus the quarter and the
    time since its start when marks exist; the category (the custom one when it has a name).
    """
    time = f"{clip.video.display_name}, {format_clock(clip.time_sec)}"
    position = services.period_position(clip.video.marks, clip.time_sec)
    if position:
        time += f" ({position[0]} · {format_clock(position[1])})"
    return time[:LABEL_MAX], (clip.category_label or "bez kategorii")[:LABEL_MAX]


def match_clips(db: Session, match: Match) -> list[Clip]:
    return list(db.scalars(
        select(Clip).where(Clip.match_id == match.id).order_by(Clip.video_id, Clip.time_sec, Clip.id)
        .options(selectinload(Clip.category))))


def available_clips(db: Session, sa: SelfAssessment) -> list[tuple[Clip, str, str]]:
    """The match's clips not yet on the sheet, with their labels; none for a standalone sheet."""
    if sa.match is None:
        return []
    used = {row.clip_id for row in sa.rows}
    return [(clip, *clip_labels(clip)) for clip in match_clips(db, sa.match) if clip.id not in used]


def visible_to(user: User, match: Match) -> list[SelfAssessment]:
    found = [s for s in match.self_assessments if permissions.can_view_self_assessment(user, s)]
    return sorted(found, key=lambda s: (s.user_id != user.id, s.submitted_at or s.created_at, s.id))


def own_in(match: Match, user: User) -> SelfAssessment | None:
    return next((s for s in match.self_assessments if s.user_id == user.id), None)


def get_or_create(db: Session, match: Match, user: User) -> tuple[SelfAssessment, bool]:
    """The unique constraint (match, user) decides a race of two requests: the loser gets the winner's sheet."""
    existing = db.scalar(select(SelfAssessment).where(
        SelfAssessment.match_id == match.id, SelfAssessment.user_id == user.id))
    if existing is not None:
        return existing, False
    now = utcnow()
    sa = SelfAssessment(match_id=match.id, user_id=user.id, created_at=now, updated_at=now)
    db.add(sa)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalars(select(SelfAssessment).where(
            SelfAssessment.match_id == match.id, SelfAssessment.user_id == user.id)).one(), False
    return sa, True


def create_standalone(db: Session, user: User) -> SelfAssessment:
    now = utcnow()
    sa = SelfAssessment(match_id=None, user_id=user.id, created_at=now, updated_at=now)
    db.add(sa)
    db.flush()
    return sa


def desc_key(row: SelfAssessmentClip) -> str:
    return f"desc_{row.id}"


def time_key(row: SelfAssessmentClip) -> str:
    return f"time_{row.id}"


def name_key(row: SelfAssessmentClip) -> str:
    return f"name_{row.id}"


def form_values(sa: SelfAssessment) -> dict[str, str]:
    values = {key: getattr(sa, key) for key, _ in QUESTIONS}
    values.update({desc_key(row): row.description for row in sa.rows})
    for row in sa.rows:
        if row.is_manual:
            values[time_key(row)], values[name_key(row)] = row.time_label, row.name_label
    if sa.is_standalone:
        values.update({key: getattr(sa, key) for key, _, _ in HEADER_FIELDS})
        values["match_date"] = sa.match_date.isoformat() if sa.match_date else ""
    return values


def ordered(sa: SelfAssessment, order: list[int] | None) -> list[SelfAssessmentClip]:
    """Rows in the order the user's form showed them; rows the form did not know keep their place after."""
    if not order:
        return list(sa.rows)
    rank = {row_id: i for i, row_id in enumerate(order)}
    return sorted(sa.rows, key=lambda r: (rank.get(r.id, len(rank) + r.position), r.id))


def _text(raw: str | None, label: str, errors: list[str]) -> str | None:
    if raw is None:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > config.TEXT_MAX_CHARS:
        errors.append(f"{label}: najwyżej {config.TEXT_MAX_CHARS} znaków (jest {len(text)}).")
    return text


def _line(raw: str | None, label: str, errors: list[str]) -> str | None:
    """A one-line field (header, time, name): line breaks become spaces."""
    if raw is None:
        return None
    text = " ".join(raw.split())
    if len(text) > LABEL_MAX:
        errors.append(f"{label}: najwyżej {LABEL_MAX} znaków (jest {len(text)}).")
    return text


def _renumber(sa: SelfAssessment, rows: list[SelfAssessmentClip]) -> None:
    for position, row in enumerate(rows):
        row.position = position
    sa.rows[:] = rows


def _apply(sa: SelfAssessment, fields: dict[str, str], order: list[int]) -> None:
    """Raises SelfAssessmentError listing every problem (nothing is changed)."""
    errors: list[str] = []
    clean: dict[str, str] = {}
    for number, (key, _) in enumerate(QUESTIONS, start=1):
        value = _text(fields.get(key), f"Pytanie {number}", errors)
        if value is not None:
            clean[key] = value
    for position, row in enumerate(ordered(sa, order), start=1):
        value = _text(fields.get(desc_key(row)), f"Klip {position}, opis", errors)
        if value is not None:
            clean[desc_key(row)] = value
        if row.is_manual:
            for key, label in ((time_key(row), "czas z nagrania"), (name_key(row), "nazwa klipu")):
                value = _line(fields.get(key), f"Klip {position}, {label}", errors)
                if value is not None:
                    clean[key] = value
    match_date = sa.match_date
    if sa.is_standalone:
        for key, label, _ in HEADER_FIELDS:
            value = _line(fields.get(key), label, errors)
            if value is not None:
                clean[key] = value
        raw_date = fields.get("match_date")
        if raw_date is not None:
            try:
                match_date = date.fromisoformat(raw_date.strip()) if raw_date.strip() else None
            except ValueError:
                errors.append("Data meczu: wpisz poprawną datę.")
    if errors:
        raise SelfAssessmentError(*errors)
    changed = False
    if sa.is_standalone:
        for key, _, _ in HEADER_FIELDS:
            if key in clean and getattr(sa, key) != clean[key]:
                setattr(sa, key, clean[key])
                changed = True
        if match_date != sa.match_date:
            sa.match_date = match_date
            changed = True
    for key, _ in QUESTIONS:
        if key in clean and getattr(sa, key) != clean[key]:
            setattr(sa, key, clean[key])
            changed = True
    rows = ordered(sa, order)
    for row in rows:
        if desc_key(row) in clean and row.description != clean[desc_key(row)]:
            row.description = clean[desc_key(row)]
            changed = True
        if row.is_manual:
            for key, attr in ((time_key(row), "time_label"), (name_key(row), "name_label")):
                if key in clean and getattr(row, attr) != clean[key]:
                    setattr(row, attr, clean[key])
                    changed = True
        elif row.clip is not None:
            row.time_label, row.name_label = clip_labels(row.clip)
    if [r.id for r in rows] != [r.id for r in sa.rows]:
        changed = True
    _renumber(sa, rows)
    if changed:
        sa.updated_at = utcnow()


def _add(db: Session, sa: SelfAssessment, clip_id: int) -> None:
    clip = db.get(Clip, clip_id)
    if sa.match_id is None or clip is None or clip.match_id != sa.match_id:
        raise SelfAssessmentError("Tego klipu nie ma w tym meczu.")
    if any(row.clip_id == clip.id for row in sa.rows):
        raise SelfAssessmentError("Ten klip jest już w samoocenie.")
    time, name = clip_labels(clip)
    # Copied once, now: later changes of the clip's description never reach the sheet.
    sa.rows.append(SelfAssessmentClip(clip_id=clip.id, position=len(sa.rows), description=clip.description or "",
                                      time_label=time, name_label=name))
    sa.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        raise SelfAssessmentError("Ten klip jest już w samoocenie.") from None


def _add_manual(sa: SelfAssessment) -> None:
    sa.rows.append(SelfAssessmentClip(clip_id=None, is_manual=True, position=len(sa.rows)))
    sa.updated_at = utcnow()


def _row(sa: SelfAssessment, row_id: str) -> SelfAssessmentClip | None:
    return next((r for r in sa.rows if str(r.id) == row_id), None)


def _remove(sa: SelfAssessment, row_id: str) -> None:
    row = _row(sa, row_id)
    if row is not None:
        sa.rows.remove(row)
        _renumber(sa, list(sa.rows))
        sa.updated_at = utcnow()


def _move(sa: SelfAssessment, row_id: str, step: int) -> None:
    row = _row(sa, row_id)
    rows = list(sa.rows)
    if row is None:
        return
    index = rows.index(row)
    target = index + step
    if 0 <= target < len(rows):
        rows[index], rows[target] = rows[target], rows[index]
        _renumber(sa, rows)
        sa.updated_at = utcnow()


def problems(sa: SelfAssessment) -> list[str]:
    """What stops the sheet from being submitted."""
    found = []
    if sa.is_standalone:
        for key, label, required in HEADER_FIELDS:
            if required and not getattr(sa, key).strip():
                found.append(f"{label}: wpisz wartość.")
        if sa.match_date is None:
            found.append("Data meczu: wybierz datę.")
    if len(sa.rows) < MIN_CLIPS:
        found.append(f"Dodaj co najmniej {MIN_CLIPS} klipy — teraz jest ich {len(sa.rows)}.")
    for number, row in enumerate(sa.rows, start=1):
        if row.is_manual:
            for text, label in ((row.time_label, "czas z nagrania"), (row.name_label, "nazwa klipu"),
                                (row.description, "opis")):
                if not text.strip():
                    found.append(f"Klip {number}: wpisz {label}.")
        elif not row.description.strip():
            found.append(f"Klip {number} ({row.name_label}): wpisz opis.")
    for number, (key, _) in enumerate(QUESTIONS, start=1):
        if not getattr(sa, key).strip():
            found.append(f"Pytanie {number}: wpisz odpowiedź.")
    return found


def save(db: Session, sa: SelfAssessment, fields: dict[str, str], order: list[int], action: str = "save") -> bool:
    """`action` is save, submit, add:<clip id>, manual (a new manual row), remove:<row id>, up:<row id> or
    down:<row id>. A row action
    stores the typed text first, so nothing typed is lost. Returns whether the sheet was submitted.
    """
    _apply(sa, fields, order)
    verb, _, target = action.partition(":")
    if verb == "add":
        try:
            _add(db, sa, int(target))
        except ValueError:
            raise SelfAssessmentError("Tego klipu nie ma w tym meczu.") from None
    elif verb == "manual":
        _add_manual(sa)
    elif verb == "remove":
        _remove(sa, target)
    elif verb in ("up", "down"):
        _move(sa, target, -1 if verb == "up" else 1)
    elif verb == "submit":
        found = problems(sa)
        if found:
            raise SelfAssessmentError(*found, saved=True)
        now = utcnow()
        sa.status, sa.submitted_at, sa.updated_at = "submitted", now, now
        db.flush()
        notify.self_assessment_submitted(db, sa)
        return True
    db.flush()
    return False


def reopen(sa: SelfAssessment) -> None:
    """`submitted_at` stays, so it keeps showing when the sheet was first sent."""
    sa.status = "draft"
    sa.updated_at = utcnow()


def clip_hint(sa: SelfAssessment) -> dict[int, str]:
    """Row id -> the clip's current description, for the "insert the clip's description" button."""
    return {row.id: row.clip.description for row in sa.rows if row.clip is not None and row.clip.description}


def listing(db: Session, user: User, requested: int) -> tuple[list[SelfAssessment], Page, list[SelfAssessment]]:
    """(submitted sheets the user may see, their pager, the user's own sheets with drafts)."""
    load = (selectinload(SelfAssessment.match), selectinload(SelfAssessment.author))
    mine = list(db.scalars(select(SelfAssessment).where(SelfAssessment.user_id == user.id).options(*load)
                           .order_by(SelfAssessment.updated_at.desc(), SelfAssessment.id.desc())))
    submitted: list[SelfAssessment] = []
    pager = paginate(0, 1, config.SELF_ASSESSMENT_PAGE_SIZE)
    if permissions.can_view_submitted_self_assessments(user):
        total = db.scalar(select(func.count()).select_from(SelfAssessment)
                          .where(SelfAssessment.status == "submitted")) or 0
        pager = paginate(total, requested, config.SELF_ASSESSMENT_PAGE_SIZE)
        submitted = list(db.scalars(
            select(SelfAssessment).where(SelfAssessment.status == "submitted").options(*load)
            .order_by(SelfAssessment.submitted_at.desc(), SelfAssessment.id.desc())
            .limit(pager.size).offset(pager.offset)))
    return submitted, pager, mine


def pdf_filename(sa: SelfAssessment) -> str:
    """samoocena_date_teams_function.pdf, e.g. samoocena_2026-10-28_Legia-Wisla_CC.pdf (ASCII only). The
    function, not the name, like the recording downloads; a referee no longer in the crew gets none, and a
    standalone sheet never has one.
    """
    match = sa.match
    names = (match.team_a_name, match.team_b_name) if match else (sa.home_team, sa.away_team)
    teams = "-".join(part for part in (slugify(name)[:40].strip("-") for name in names) if part)
    day = match.date if match else sa.match_date
    # A standalone sheet has no crew slot, so no function.
    function = next((o.function for o in match.officials if o.user_id == sa.user_id), "") if match else ""
    return "_".join(part for part in ("samoocena", day.isoformat() if day else "", teams, function) if part) + ".pdf"
