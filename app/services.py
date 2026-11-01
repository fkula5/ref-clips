"""Logika biznesowa: obsada, kwarty, granice klipów, nazwy plików, tworzenie klipów, kolejka."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import (OFFICIAL_FUNCTIONS, PERIODS, Category, Clip, Job, Match, MatchOfficial,
                        PeriodMark, Setting, User, Video)
from app.notes_parser import CategoryDef, ParsedLine, RefereeDef, parse_notes
from app.storage import storage
from app.textutil import format_clock, slugify
from app.timeutil import utcnow


class MatchFormError(ValueError):
    """Niepoprawna obsada w formularzu meczu (komunikat po polsku)."""


# --- ustawienia -----------------------------------------------------------------
def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row is not None else default


def retention_days(db: Session) -> int:
    try:
        return max(1, int(get_setting(db, "retention_days", "30")))
    except ValueError:
        return 30


def video_expiry(db: Session):
    """Koniec retencji pełnego nagrania wgranego teraz."""
    return utcnow() + timedelta(days=retention_days(db))


# --- obsada meczu -----------------------------------------------------------------
def referee_candidates(db: Session) -> list[User]:
    """Konta, które można wybrać w obsadzie: aktywne, z rolą sędziego."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return [u for u in users if "referee" in u.roles]


def officials_from_form(db: Session, form: dict[str, str]) -> list[tuple[str, int | None, str | None]]:
    """Czyta pola `<fn>_user` / `<fn>_name` (fn = cc, u1, u2) z formularza meczu.

    Zwraca listę (funkcja, user_id, wpisane imię i nazwisko) dla wypełnionych pozycji.
    Konto ma pierwszeństwo przed wpisanym imieniem. CC i U1 są wymagane, U2 opcjonalna.
    """
    allowed = {u.id for u in referee_candidates(db)}
    result: list[tuple[str, int | None, str | None]] = []
    seen_users: set[int] = set()
    for function in OFFICIAL_FUNCTIONS:
        key = function.lower()
        raw_user = (form.get(f"{key}_user") or "").strip()
        name = " ".join((form.get(f"{key}_name") or "").split())[:100]
        if raw_user.isdigit():
            user_id = int(raw_user)
            if user_id not in allowed:
                raise MatchFormError(f"{function}: wybrane konto nie jest aktywnym kontem sędziego.")
            if user_id in seen_users:
                raise MatchFormError("To samo konto nie może zajmować dwóch pozycji w obsadzie.")
            seen_users.add(user_id)
            result.append((function, user_id, None))
        elif name:
            result.append((function, None, name))
        elif function != "U2":
            raise MatchFormError(f"Uzupełnij obsadę: brakuje pozycji {function}.")
    return result


def set_officials(match: Match, officials: list[tuple[str, int | None, str | None]]) -> None:
    """Zastępuje obsadę meczu. Pozycje o tej samej funkcji są aktualizowane w miejscu,
    dzięki czemu klipy opisane wcześniej nie tracą powiązania z sędzią."""
    wanted = {function: (user_id, name) for function, user_id, name in officials}
    for official in list(match.officials):
        if official.function in wanted:
            official.user_id, official.name = wanted.pop(official.function)
        else:
            match.officials.remove(official)
    for function, (user_id, name) in wanted.items():
        match.officials.append(MatchOfficial(function=function, user_id=user_id, name=name))


# --- kwarty ---------------------------------------------------------------------
def period_for(marks: list[PeriodMark], time_sec: float) -> str | None:
    """Kwarta = ostatni znacznik początku, który wypada nie później niż czas klipu."""
    current = None
    for mark in sorted(marks, key=lambda m: m.time_sec):
        if mark.time_sec <= time_sec + 0.001:
            current = mark.period
    return current


def period_position(marks: list[PeriodMark], time_sec: float) -> tuple[str, float] | None:
    """(kwarta, sekundy od jej początku w czasie nagrania) albo None, gdy kwarta nieustalona."""
    current = None
    for mark in sorted(marks, key=lambda m: m.time_sec):
        if mark.time_sec <= time_sec + 0.001:
            current = mark
    return (current.period, max(0.0, time_sec - current.time_sec)) if current else None


def period_label(marks: list[PeriodMark], time_sec: float) -> str:
    """np. „Q2 · 4:12 od początku kwarty (czas nagrania)”. To nie jest zegar meczowy."""
    pos = period_position(marks, time_sec)
    if pos is None:
        return "kwarta nieustalona (brak znaczników kwart)"
    return f"{pos[0]} · {format_clock(pos[1])} od początku kwarty (czas nagrania)"


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


def clip_range(clip: Clip) -> tuple[float, float]:
    return clip_bounds(clip.time_sec, clip.margin_before, clip.margin_after, clip.video.duration)


# --- nazwy plików ---------------------------------------------------------------
def clip_filename(clip: Clip) -> str:
    """np. 2026-10-28_Q2_02m54s_CC_blok-szarza.mp4"""
    period = period_for(clip.video.marks, clip.time_sec) or "Qx"
    minutes, seconds = divmod(int(clip.time_sec), 60)
    parts = [clip.match.date.isoformat(), period, f"{minutes:02d}m{seconds:02d}s"]
    if clip.whole_team:
        parts.append("zespol")
    elif clip.official:
        parts.append(clip.official.function)
    category = slugify(clip.category_label)
    if category:
        parts.append(category)
    return "_".join(parts) + ".mp4"


# --- słownik kategorii i kontekst parsera ------------------------------------------
def active_categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).where(Category.is_active.is_(True))
                           .order_by(Category.sort, Category.name)))


def category_defs(db: Session) -> list[CategoryDef]:
    return [CategoryDef(c.name, tuple(c.alias_list)) for c in active_categories(db)]


def referee_defs(match: Match) -> list[RefereeDef]:
    return [RefereeDef(o.id, o.display_name, o.function) for o in match.officials]


def parse_for_match(db: Session, match: Match, text: str) -> list[ParsedLine]:
    return parse_notes(text, referee_defs(match), category_defs(db))


def category_by_name(db: Session, name: str | None) -> Category | None:
    if not name:
        return None
    return db.scalar(select(Category).where(Category.name == name))


# --- kolejka zadań --------------------------------------------------------------
def enqueue(db: Session, job_type: str, *, video_id: int | None = None,
            clip_id: int | None = None) -> Job:
    job = Job(type=job_type, status="pending", video_id=video_id, clip_id=clip_id)
    db.add(job)
    db.flush()
    return job


def queue_cut(db: Session, clip: Clip) -> None:
    """Zleca (ponowne) wycięcie klipu; stare oczekujące zadania cięcia tego klipu są usuwane."""
    for job in db.scalars(select(Job).where(Job.clip_id == clip.id, Job.type == "cut",
                                            Job.status == "pending")):
        db.delete(job)
    clip.status = "queued"
    clip.error = None
    enqueue(db, "cut", video_id=clip.video_id, clip_id=clip.id)


def queue_transcode(db: Session, video: Video) -> None:
    video.status = "queued"
    video.error = None
    enqueue(db, "transcode", video_id=video.id)


# --- tworzenie klipów -----------------------------------------------------------
def create_clip(db: Session, video: Video, author: User | None, *, time_sec: float,
                official_id: int | None = None, category_id: int | None = None,
                description: str = "",
                margin_before: float = config.DEFAULT_MARGIN_BEFORE,
                margin_after: float = config.DEFAULT_MARGIN_AFTER,
                cut: bool = True) -> Clip:
    """Klip ze znacznika. Jest „nieopisany” (described_at = None), dopóki ktoś go nie opisze."""
    if official_id is not None and not any(o.id == official_id for o in video.match.officials):
        official_id = None
    clip = Clip(
        match_id=video.match_id, video_id=video.id, author_id=author.id if author else None,
        official_id=official_id, category_id=category_id, time_sec=time_sec,
        description=description, margin_before=margin_before, margin_after=margin_after,
        status="new")
    db.add(clip)
    db.flush()
    if cut:
        queue_cut(db, clip)
    return clip


def remove_clip_files(clip: Clip) -> None:
    storage.delete(clip.clip_path)


def remove_video_files(video: Video) -> None:
    storage.delete(video.original_path)
    storage.delete(video.proxy_path)
    for clip in video.clips:
        remove_clip_files(clip)
