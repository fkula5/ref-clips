"""Logika biznesowa: kwarty, granice klipów, nazwy plików, tworzenie decyzji, kolejka."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import (PERIODS, Decision, Job, Match, PeriodMark, Referee, Tag, User,
                        Video)
from app.notes_parser import ParsedLine, RefereeDef, TagDef, TeamDef, parse_notes
from app.storage import storage
from app.textutil import normalize, slugify


# --- użytkownik (etap 1: jeden domyślny) ---------------------------------------
def default_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        user = User(name="Ja", role="admin")
        db.add(user)
        db.commit()
    return user


# --- kwarty ---------------------------------------------------------------------
def period_for(marks: list[PeriodMark], time_sec: float) -> str | None:
    """Kwarta = ostatni znacznik początku, który wypada nie później niż czas decyzji."""
    current = None
    for mark in sorted(marks, key=lambda m: m.time_sec):
        if mark.time_sec <= time_sec + 0.001:
            current = mark.period
    return current


def next_period(marks: list[PeriodMark]) -> str:
    """Następna kwarta po ostatnio dodanej (Q1 -> Q2 ... -> Q4 -> OT1 ...)."""
    used = {m.period for m in marks}
    for p in PERIODS:
        if p not in used:
            return p
    return PERIODS[-1]


# --- granice klipu --------------------------------------------------------------
def clip_bounds(time_sec: float, before: float, after: float,
                duration: float | None) -> tuple[float, float]:
    """Początek i koniec klipu obcięte do granic nagrania."""
    start = max(0.0, time_sec - before)
    end = time_sec + after
    if duration is not None:
        end = min(end, duration)
        start = min(start, max(0.0, duration - 0.5))
    return start, max(end, start + 0.1)


def decision_bounds(decision: Decision) -> tuple[float, float]:
    return clip_bounds(decision.time_sec, decision.margin_before, decision.margin_after,
                       decision.video.duration)


# --- nazwy plików ---------------------------------------------------------------
def clip_filename(decision: Decision) -> str:
    """np. 2026-10-28_Q2_02m54s_Filip_PTS.mp4"""
    period = period_for(decision.video.marks, decision.time_sec) or "Qx"
    minutes, seconds = divmod(int(decision.time_sec), 60)
    parts = [decision.match.date.isoformat(), period, f"{minutes:02d}m{seconds:02d}s"]
    if decision.referee:
        parts.append(slugify(decision.referee.name.split()[0], "sedzia"))
    tags = "-".join(slugify(t.name) for t in decision.tags if slugify(t.name))
    if tags:
        parts.append(tags)
    return "_".join(parts) + ".mp4"


# --- słownik tagów i kontekst parsera -------------------------------------------
def tag_defs(db: Session) -> list[TagDef]:
    tags = db.scalars(select(Tag).order_by(Tag.sort, Tag.name)).all()
    return [TagDef(t.name, tuple(t.alias_list)) for t in tags]


def team_defs(match: Match) -> list[TeamDef]:
    return [
        TeamDef("a", tuple(k for k in (match.team_a_name, match.team_a_color) if k)),
        TeamDef("b", tuple(k for k in (match.team_b_name, match.team_b_color) if k)),
    ]


def referee_defs(match: Match) -> list[RefereeDef]:
    return [RefereeDef(mr.referee.id, mr.referee.name) for mr in match.referees]


def parse_for_match(db: Session, match: Match, text: str) -> list[ParsedLine]:
    return parse_notes(text, referee_defs(match), tag_defs(db), team_defs(match))


def resolve_tags(db: Session, names: list[str]) -> list[Tag]:
    """Zamienia nazwy/aliasy na tagi; nieznane nazwy tworzą nowe tagi."""
    result: list[Tag] = []
    all_tags = db.scalars(select(Tag)).all()
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        norm = normalize(name)
        tag = next((t for t in all_tags
                    if normalize(t.name) == norm or norm in [normalize(a) for a in t.alias_list]), None)
        if tag is None:
            tag = Tag(name=name, aliases="", sort=1000)
            db.add(tag)
            db.flush()
            all_tags.append(tag)
        if tag not in result:
            result.append(tag)
    return result


def get_or_create_referee(db: Session, name: str) -> Referee:
    name = " ".join(name.split())
    ref = db.scalar(select(Referee).where(func.lower(Referee.name) == name.lower()))
    if ref is None:
        ref = Referee(name=name)
        db.add(ref)
        db.flush()
    return ref


# --- kolejka zadań --------------------------------------------------------------
def enqueue(db: Session, job_type: str, *, video_id: int | None = None,
            decision_id: int | None = None) -> Job:
    job = Job(type=job_type, status="pending", video_id=video_id, decision_id=decision_id)
    db.add(job)
    db.flush()
    return job


def queue_cut(db: Session, decision: Decision) -> None:
    """Zleca (ponowne) wycięcie klipu; stare zadania cięcia tej decyzji są usuwane."""
    for job in db.scalars(select(Job).where(Job.decision_id == decision.id, Job.type == "cut",
                                            Job.status == "pending")):
        db.delete(job)
    decision.status = "queued"
    decision.error = None
    enqueue(db, "cut", video_id=decision.video_id, decision_id=decision.id)


def queue_transcode(db: Session, video: Video) -> None:
    video.status = "queued"
    video.error = None
    enqueue(db, "transcode", video_id=video.id)


# --- tworzenie decyzji ----------------------------------------------------------
def create_decision(db: Session, video: Video, author: User | None, *, time_sec: float,
                    referee_id: int | None = None, team: str | None = None,
                    tag_names: list[str] | None = None, description: str = "",
                    margin_before: float = config.DEFAULT_MARGIN_BEFORE,
                    margin_after: float = config.DEFAULT_MARGIN_AFTER,
                    cut: bool = True) -> Decision:
    decision = Decision(
        match_id=video.match_id, video_id=video.id, author_id=author.id if author else None,
        referee_id=referee_id, team=team, time_sec=time_sec, description=description,
        margin_before=margin_before, margin_after=margin_after, status="new",
    )
    decision.tags = resolve_tags(db, tag_names or [])
    db.add(decision)
    db.flush()
    if cut:
        queue_cut(db, decision)
    return decision


def remove_decision_files(decision: Decision) -> None:
    storage.delete(decision.clip_path)


def remove_video_files(video: Video) -> None:
    storage.delete(video.original_path)
    storage.delete(video.proxy_path)
    for decision in video.decisions:
        remove_decision_files(decision)
