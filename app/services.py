from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import config
from app.models import (OFFICIAL_FUNCTIONS, PERIODS, Category, Clip, Job, Match, MatchOfficial,
                        PeriodMark, Setting, User, Video)
from app.notes_parser import CategoryDef, ParsedLine, RefereeDef, parse_notes
from app.storage import storage
from app.textutil import format_clock, normalize, slugify
from app.timeutil import utcnow


class MatchFormError(ValueError):
    status_code = 422


class MatchForbiddenError(MatchFormError):
    """HTTP 403, but shown in the form"""
    status_code = 403


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def retention_days(db: Session) -> int:
    try:
        return max(1, int(get_setting(db, "retention_days", "30")))
    except ValueError:
        return 30


def video_expiry(db: Session):
    return utcnow() + timedelta(days=retention_days(db))


Identity = tuple[str, object]


def account_names(db: Session) -> dict[str, int]:
    """Two accounts with the same name (even inactive) are left out, so a typed name cannot be assigned
    to either.
    """
    found: dict[str, int | None] = {}
    for user_id, name in db.execute(select(User.id, User.name)):
        key = normalize(name)
        found[key] = None if key in found else user_id
    return {key: user_id for key, user_id in found.items() if user_id is not None}


def identity(user_id: int | None, name: str | None, accounts: Mapping[str, int]) -> Identity:
    """A typed name matching a unique account's name is the SAME person as the account (a referee typed
    by hand who later got an account).
    """
    if user_id:
        return ("u", user_id)
    key = normalize(name or "")
    return ("u", accounts[key]) if key in accounts else ("n", key)


def person_key(user_id: int | None, name: str | None, accounts: Mapping[str, int]) -> str:
    """Person key: "u<account id>" or "n<normalised name>" (for filters)."""
    kind, value = identity(user_id, name, accounts)
    return f"{kind}{value}"


def people(db: Session) -> list[tuple[str, str]]:
    accounts = account_names(db)
    user_names = {uid: name for uid, name in db.execute(select(User.id, User.name))}
    found: dict[str, str] = {}
    for user_id, name in db.execute(select(MatchOfficial.user_id, MatchOfficial.name)):
        kind, value = identity(user_id, name, accounts)
        found.setdefault(f"{kind}{value}", user_names[value] if kind == "u" else name)
    return sorted(found.items(), key=lambda kv: normalize(kv[1]))


def referee_candidates(db: Session) -> list[User]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return [u for u in users if "referee" in u.roles]


def officials_from_form(db: Session, form: dict[str, str]) -> list[tuple[str, int | None, str | None]]:
    """Reads `<fn>_user` / `<fn>_name` (fn = cc, u1, u2) from the match form; returns (function,
    user_id, typed name) for filled slots.
    An account takes precedence over a typed name. CC and U1 are required, U2 optional. The same
    person cannot hold two slots (same account, same normalised typed name, or an account plus a
    typed name of that same person).
    """
    allowed = {u.id for u in referee_candidates(db)}
    accounts = account_names(db)
    result: list[tuple[str, int | None, str | None]] = []
    seen: dict[Identity, tuple[str, bool]] = {}
    for function in OFFICIAL_FUNCTIONS:
        key = function.lower()
        raw_user = (form.get(f"{key}_user") or "").strip()
        name = " ".join((form.get(f"{key}_name") or "").split())[:100]
        if raw_user.isdigit():
            user_id, name = int(raw_user), None
            if user_id not in allowed:
                raise MatchFormError(f"{function}: wybrane konto nie jest aktywnym kontem sędziego.")
        elif name:
            user_id = None
        elif function != "U2":
            raise MatchFormError(f"Uzupełnij obsadę: brakuje pozycji {function}.")
        else:
            continue
        who = identity(user_id, name, accounts)
        if who in seen:
            first, first_is_account = seen[who]
            if user_id and first_is_account:
                raise MatchFormError("To samo konto nie może zajmować dwóch pozycji w obsadzie.")
            raise MatchFormError(
                f"{first} i {function}: to ta sama osoba ({name or 'konto sędziego'}) — "
                "jedna osoba nie może zajmować dwóch pozycji w obsadzie.")
        seen[who] = (function, bool(user_id))
        result.append((function, user_id, name))
    return result


def set_officials(db: Session, match: Match, officials: list[tuple[str, int | None, str | None]]) -> None:
    """Replaces the crew while keeping clips linked to the PERSON, not the slot.

    Existing slots are matched by identity (account or name; a typed name matching a unique account
    is the same person, both ways). A person who stays keeps their clips even when the function
    changes (e.g. CC and U1 swap) or the way they are recorded (name -> account); a new person is a
    new slot; a removed person loses the slot and their clips stay unassigned (official_id = NULL).
    (match, function) uniqueness holds: slots changing function are deleted first (clips remembered),
    then recreated.
    """
    accounts = account_names(db)
    incoming = {identity(user_id, name, accounts): (function, user_id, name)
                for function, user_id, name in officials}
    # fetch the clips before deleting slots: the deletion (autoflush) sets official_id to NULL in the DB
    clips_of: dict[int, list[int]] = {}
    old_ids = [o.id for o in match.officials if o.id is not None]
    if old_ids:
        for clip_id, official_id in db.execute(
                select(Clip.id, Clip.official_id).where(Clip.official_id.in_(old_ids))):
            clips_of.setdefault(official_id, []).append(clip_id)
    moved: list[tuple[int, tuple[str, int | None, str | None]]] = []
    removed = False
    for official in list(match.officials):
        target = incoming.pop(identity(official.user_id, official.name, accounts), None)
        if target is None:
            match.officials.remove(official)
            removed = True
        elif target[0] == official.function:
            official.user_id, official.name = target[1], target[2]
        else:
            moved.append((official.id, target))
            match.officials.remove(official)
    if moved or removed:
        db.flush()  # freed functions before inserting new ones (uniqueness is checked per statement)
    created: list[tuple[int, MatchOfficial]] = []
    for old_id, (function, user_id, name) in moved:
        fresh = MatchOfficial(function=function, user_id=user_id, name=name)
        match.officials.append(fresh)
        created.append((old_id, fresh))
    for function, user_id, name in incoming.values():
        match.officials.append(MatchOfficial(function=function, user_id=user_id, name=name))
    if moved:
        db.flush()
        for old_id, fresh in created:
            if clips_of.get(old_id):
                db.execute(update(Clip).where(Clip.id.in_(clips_of[old_id])).values(official_id=fresh.id))


MATCH_STATES = {
    "none": "brak nagrania",
    "uploading": "wgrywanie",
    "converting": "konwersja",
    "error": "błąd konwersji",
    "no_marks": "brak znaczników kwart",
    "ready": "gotowy",
    "purged": "pełne nagranie usunięte",
}
FULL_MATCH_PERIODS = PERIODS[:4]


@dataclass(frozen=True)
class MatchState:
    code: str
    detail: str = ""

    @property
    def label(self) -> str:
        return MATCH_STATES[self.code]


def declared_periods(content: str | None) -> list[str] | None:
    """A missing declaration counts as the whole match."""
    found = [p.strip().upper() for p in (content or "").split(",")]
    found = [p for p in PERIODS if p in found]
    return found or None


def normalize_content(raw: str | None) -> str:
    """"full" or comma-separated quarters in match order ("Q1", "Q2,Q3"). An unknown quarter is a
    MatchFormError.
    """
    tokens = [t.strip().upper() for t in (raw or "").split(",") if t.strip()]
    if not tokens or tokens == ["FULL"]:
        return "full"
    unknown = [t for t in tokens if t not in PERIODS]
    if unknown:
        raise MatchFormError(f"Nieznana kwarta w deklaracji zawartości: {unknown[0]}")
    return ",".join(p for p in PERIODS if p in tokens)


def content_from_form(kind: str, periods: Iterable[str]) -> str:
    if kind == "multi":
        content = normalize_content(",".join(periods))
        if content == "full" or len(content.split(",")) < 2:
            raise MatchFormError("Dla kilku kwart zaznacz co najmniej dwie.")
        return content
    content = normalize_content(kind)
    if len(content.split(",")) > 1:
        raise MatchFormError("Nieprawidłowa deklaracja zawartości.")
    return content


def content_label(content: str | None) -> str:
    declared = declared_periods(content)
    if declared is None:
        return "cały mecz"
    return f"kwarta {declared[0]}" if len(declared) == 1 else f"kwarty {', '.join(declared)}"


def allowed_periods(content: str | None) -> list[str]:
    """Whole match: Q1-Q4 and OT1-OT3; otherwise only the declared ones."""
    declared = declared_periods(content)
    return list(PERIODS) if declared is None else declared


def required_periods(content: str | None) -> list[str]:
    """Whole match: Q1-Q4; several quarters: all declared; one quarter: none (it starts at 0:00 by
    default).
    """
    declared = declared_periods(content)
    if declared is None:
        return list(FULL_MATCH_PERIODS)
    return declared if len(declared) > 1 else []


def missing_periods(content: str | None, marked: Iterable[str]) -> list[str]:
    have = set(marked)
    return [p for p in required_periods(content) if p not in have]


@dataclass
class ContentChange:
    add_default: str | None = None
    removed: list[PeriodMark] = field(default_factory=list)
    renamed: list[tuple[PeriodMark, str]] = field(default_factory=list)
    dropped_default: list[PeriodMark] = field(default_factory=list)  # automatic 0:00, no warning

    @property
    def needs_confirmation(self) -> bool:
        """Warns about losing markers; renaming the only marker (keeping its time) and the automatic
        0:00 need no confirmation.
        """
        return bool(self.removed)

    @property
    def token(self) -> str:
        """The confirmation applies to exactly these markers."""
        return ",".join(sorted(f"x{m.id}" for m in self.removed))

    def warnings(self) -> list[str]:
        return [f"{m.period} (początek w {format_clock(m.time_sec)}) — znacznik zostanie usunięty"
                for m in self.removed]


def plan_content_change(video: Video, content: str) -> ContentChange:
    """One quarter: that quarter's marker stays (otherwise the earliest, renamed), the rest go; without
    markers a 0:00 is created. Whole match / several quarters: markers outside the declaration go; a
    lone automatic 0:00 left from a one-quarter file stays only for the first quarter of the new
    declaration (otherwise it would block setting earlier quarters).
    """
    content = normalize_content(content)
    old, new = declared_periods(video.content), declared_periods(content)
    marks = sorted(video.marks, key=lambda m: m.time_sec)
    change = ContentChange()
    if new is not None and len(new) == 1:
        target = new[0]
        keep = next((m for m in marks if m.period == target), marks[0] if marks else None)
        if keep is None:
            change.add_default = target
            return change
        change.removed = [m for m in marks if m is not keep]
        if keep.period != target:
            change.renamed.append((keep, target))
        return change
    allowed = allowed_periods(content)
    first = allowed[0] if new is not None else FULL_MATCH_PERIODS[0]
    auto_default = old is not None and len(old) == 1 and len(marks) == 1 and marks[0].time_sec == 0
    for mark in marks:
        if auto_default:
            if mark.period != first:
                change.dropped_default.append(mark)
        elif mark.period not in allowed:
            change.removed.append(mark)
    return change


def set_content(db: Session, video: Video, content: str) -> None:
    """A one-quarter file gets a 0:00 start marker right away (the marker is optional, default 0:00, can
    be moved), so its clips' quarter is known without manual markers.
    """
    content = normalize_content(content)
    change = plan_content_change(video, content)
    video.content = content
    for mark in [*change.removed, *change.dropped_default]:
        video.marks.remove(mark)
    db.flush()  # deleted periods before renaming (video + quarter uniqueness)
    for mark, period in change.renamed:
        mark.period = period
    if change.add_default:
        video.marks.append(PeriodMark(period=change.add_default, time_sec=0.0))


def match_state(videos: Iterable[Video], queue: Mapping[int, int] | None = None) -> MatchState:
    """Order: error, uploading/converting, no quarter markers, ready. Recordings whose full version was
    removed are ignored; if all are, the match is in the "full recording removed" state.
    """
    videos = list(videos)
    if not videos:
        return MatchState("none")
    active = [v for v in videos if v.purged_at is None]
    if not active:
        return MatchState("purged")
    if any(v.status == "error" for v in active):
        return MatchState("error")
    busy = [v for v in active if v.status in ("queued", "processing")]
    if busy:
        if any(v.status == "processing" for v in busy):
            return MatchState("converting", "w toku")
        positions = [queue[v.id] for v in busy if queue and v.id in queue]
        return MatchState("converting", f"pozycja w kolejce: {min(positions)}" if positions else "")
    if any(v.status == "uploading" for v in active):
        return MatchState("uploading")
    if any(v.status == "ready" and missing_periods(v.content, (m.period for m in v.marks))
           for v in active):
        return MatchState("no_marks")
    return MatchState("ready")


def transcode_queue(db: Session) -> dict[int, int]:
    rows = db.execute(select(Job.video_id).where(
        Job.type == "transcode", Job.status.in_(("pending", "running")), Job.video_id.is_not(None))
        .order_by(Job.status.desc(), Job.id))  # running before pending
    queue: dict[int, int] = {}
    for (video_id,) in rows:
        queue.setdefault(video_id, len(queue) + 1)
    return queue


def known_levels(db: Session) -> list[str]:
    levels = {lv.strip() for lv in db.scalars(select(Match.level).distinct()) if lv and lv.strip()}
    return sorted(levels, key=lambda lv: (normalize(lv), lv))


def period_for(marks: list[PeriodMark], time_sec: float) -> str | None:
    current = None
    for mark in sorted(marks, key=lambda m: m.time_sec):
        if mark.time_sec <= time_sec + 0.001:
            current = mark.period
    return current


def period_position(marks: list[PeriodMark], time_sec: float) -> tuple[str, float] | None:
    current = None
    for mark in sorted(marks, key=lambda m: m.time_sec):
        if mark.time_sec <= time_sec + 0.001:
            current = mark
    return (current.period, max(0.0, time_sec - current.time_sec)) if current else None


def period_label(marks: list[PeriodMark], time_sec: float) -> str:
    """Recording time since the quarter start, not the game clock."""
    pos = period_position(marks, time_sec)
    if pos is None:
        return "kwarta nieustalona (brak znaczników kwart)"
    return f"{pos[0]} · {format_clock(pos[1])} od początku kwarty (czas nagrania)"


def period_short(marks: list[PeriodMark], time_sec: float) -> str:
    pos = period_position(marks, time_sec)
    return "nieustalona" if pos is None else f"{pos[0]} · {format_clock(pos[1])}"


def next_period(marks: list[PeriodMark], content: str | None = "full") -> str | None:
    """Next quarter without a marker per the declaration: whole match Q1 -> Q2 -> Q3 -> Q4 -> OT1 ...;
    several quarters only the declared ones in order; one quarter only that one (Q moves its marker).
    None when all allowed quarters have a marker.
    """
    used = {m.period for m in marks}
    allowed = allowed_periods(content)
    for period in allowed:
        if period not in used:
            return period
    return allowed[0] if len(allowed) == 1 else None


class PeriodMarkError(ValueError):
    pass


def check_period_mark(content: str | None, marks: Iterable[PeriodMark], period: str, time_sec: float,
                      duration: float | None = None) -> None:
    """Allowed by the declaration, within the recording, chronological (Q2 cannot start before Q1). A
    marker of the same quarter is skipped (moving).
    """
    if period not in PERIODS:
        raise PeriodMarkError("Nieznana kwarta.")
    allowed = allowed_periods(content)
    if period not in allowed:
        raise PeriodMarkError(
            f"Kwarta {period} nie pasuje do deklaracji zawartości pliku ({content_label(content)}). "
            "Jeśli plik zawiera tę kwartę, zmień deklarację (Edytuj przy nagraniu).")
    if time_sec < 0 or (duration and time_sec > duration + config.CUT_OUTSIDE_TOLERANCE):
        raise PeriodMarkError("Czas znacznika jest poza nagraniem.")
    index = PERIODS.index(period)
    for other in marks:
        if other.period == period or other.period not in PERIODS:
            continue
        before = PERIODS.index(other.period) < index
        if before and time_sec <= other.time_sec:
            raise PeriodMarkError(
                f"{period} nie może zaczynać się przed {other.period} ({format_clock(other.time_sec)}) — "
                "kwarty muszą następować po sobie w kolejności.")
        if not before and time_sec >= other.time_sec:
            raise PeriodMarkError(
                f"{period} nie może zaczynać się po {other.period} ({format_clock(other.time_sec)}) — "
                "kwarty muszą następować po sobie w kolejności.")


def clip_bounds(time_sec: float, before: float, after: float,
                duration: float | None) -> tuple[float, float]:
    start = max(0.0, time_sec - before)
    end = time_sec + after
    if duration is not None:
        end = min(end, duration)
        start = min(start, max(0.0, duration - 0.5))
    return start, max(end, start + 0.1)


def clip_range(clip: Clip) -> tuple[float, float]:
    return clip_bounds(clip.time_sec, clip.margin_before, clip.margin_after, clip.video.duration)


FILENAME_PART_MAX = 40  # league and custom category names can be long; shortened in the file name


def _filename_part(text: str) -> str:
    return slugify(text)[:FILENAME_PART_MAX].strip("-")


def clip_filename(clip: Clip, *, with_referee: bool = True) -> str:
    """category-of-competition_surname_decision.mp4, e.g. III-liga_Kowalski_blok-szarza.mp4 (surname =
    last word of the referee's name, "zespol" for whole-team clips; empty parts are skipped; ASCII
    only; computed on the fly, so after a description change the downloaded file already has the new
    name). `with_referee=False` (links without account) omits the referee and does not even read the
    crew: III-liga_blok-szarza.mp4. Names may repeat; ZIPs are numbered by `unique_filenames`.
    """
    referee = ""
    if with_referee:
        referee = "zespol" if clip.whole_team else ""
        if clip.official and not clip.whole_team:
            referee = " ".join(clip.official.display_name.split()[-1:])
    parts = (_filename_part(value) for value in (clip.match.level, referee, clip.category_label))
    return ("_".join(part for part in parts if part) or "klip") + ".mp4"


def unique_filenames(names: Iterable[str]) -> list[str]:
    """Later duplicates get _2, _3 before the extension."""
    used: set[str] = set()
    result = []
    for name in names:
        candidate, n = name, 1
        while candidate in used:
            n += 1
            candidate = f"{name[:-4]}_{n}.mp4"
        used.add(candidate)
        result.append(candidate)
    return result


def active_categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).where(Category.is_active.is_(True))
                           .order_by(Category.sort, Category.name)))


def category_groups(categories: Iterable[Category]) -> list[tuple[str, list[Category]]]:
    groups: list[tuple[str, list[Category]]] = []
    for category in categories:
        if not groups or groups[-1][0] != category.group_name:
            groups.append((category.group_name, []))
        groups[-1][1].append(category)
    return groups


def categories_for(db: Session, clip: Clip) -> list[Category]:
    """Active ones plus the clip's current category when it is inactive."""
    found = active_categories(db)
    if clip.category is not None and not clip.category.is_active:
        found = sorted([*found, clip.category], key=lambda c: (c.sort, c.name))
    return found


def all_categories(db: Session) -> list[Category]:
    """Includes inactive ones, so old clips can be found."""
    return list(db.scalars(select(Category).order_by(Category.sort, Category.name)))


def category_defs(db: Session) -> list[CategoryDef]:
    return [CategoryDef(c.name, tuple(c.alias_list)) for c in active_categories(db)]


def referee_defs(match: Match) -> list[RefereeDef]:
    return [RefereeDef(o.id, o.display_name, o.function) for o in match.officials]


class NotesTooLong(ValueError):
    pass


def clean_notes(text: str | None) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    if len(text) > config.NOTES_MAX_CHARS:
        raise NotesTooLong(f"Notatki są za długie (maksymalnie {config.NOTES_MAX_CHARS} znaków).")
    if text.count("\n") + 1 > config.NOTES_MAX_LINES:
        raise NotesTooLong(f"Notatki mają za dużo linii (maksymalnie {config.NOTES_MAX_LINES}).")
    return text


def parse_for_match(db: Session, match: Match, text: str) -> list[ParsedLine]:
    return parse_notes(text, referee_defs(match), category_defs(db))


def category_by_name(db: Session, name: str | None) -> Category | None:
    if not name:
        return None
    return db.scalar(select(Category).where(Category.name == name))


def enqueue(db: Session, job_type: str, *, video_id: int | None = None,
            clip_id: int | None = None) -> Job:
    job = Job(type=job_type, status="pending", video_id=video_id, clip_id=clip_id)
    db.add(job)
    db.flush()
    return job


def queue_cut(db: Session, clip: Clip) -> None:
    """Removes the clip's older pending cut jobs."""
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


def create_clip(db: Session, video: Video, author: User | None, *, time_sec: float,
                official_id: int | None = None, category_id: int | None = None,
                description: str = "",
                margin_before: float = config.DEFAULT_MARGIN_BEFORE,
                margin_after: float = config.DEFAULT_MARGIN_AFTER,
                cut: bool = True) -> Clip:
    if official_id is not None and not any(o.id == official_id for o in video.match.officials):
        official_id = None
    clip = Clip(
        match_id=video.match_id, video_id=video.id, author_id=author.id if author else None,
        official_id=official_id, category_id=category_id, time_sec=time_sec,
        description=description, margin_before=margin_before, margin_after=margin_after,
        status="new", created_at=utcnow())  # with microseconds: protection against a double click
    db.add(clip)
    db.flush()
    if cut:
        queue_cut(db, clip)
    return clip


MARKER_LOCK = threading.Lock()  # double-click check + write in one step


def recent_clip(db: Session, video: Video, user: User) -> Clip | None:
    since = utcnow() - timedelta(seconds=config.MARKER_DEBOUNCE_SECONDS)
    return db.scalar(select(Clip).where(
        Clip.video_id == video.id, Clip.author_id == user.id, Clip.created_at > since)
        .order_by(Clip.id.desc()))


def add_marker(db: Session, video: Video, user: User, time_sec: float) -> tuple[Clip, bool]:
    """A second marker by the same author within a second is ignored: returns (clip, created)."""
    with MARKER_LOCK:
        recent = recent_clip(db, video, user)
        if recent is not None:
            return recent, False
        clip = create_clip(db, video, user, time_sec=clamp_time(time_sec, video.duration))
        db.commit()
        return clip, True


def clamp_time(time_sec: float, duration: float | None) -> float:
    time_sec = max(0.0, time_sec)
    return min(time_sec, duration) if duration else time_sec


def undo_marker(db: Session, video: Video, user: User) -> Clip | None:
    clip = db.scalar(select(Clip).where(
        Clip.video_id == video.id, Clip.author_id == user.id, Clip.described_at.is_(None))
        .order_by(Clip.id.desc()))
    if clip is None:
        return None
    remove_clip_files(clip)
    db.delete(clip)
    db.commit()
    return clip


def remove_clip_files(clip: Clip) -> None:
    storage.delete(clip.clip_path)


def remove_video_files(video: Video) -> None:
    storage.delete(video.original_path)
    storage.delete(video.proxy_path)
    for clip in video.clips:
        remove_clip_files(clip)


CUSTOM_CATEGORY_MAX = 100
DESCRIPTION_MAX = 2000


class ClipDescribeError(ValueError):
    status_code = 422


@dataclass(frozen=True)
class DescribeBlock:
    message: str
    url: str | None = None
    link_text: str = ""


class ClipBlockedError(ClipDescribeError):
    def __init__(self, block: DescribeBlock):
        super().__init__(block.message)
        self.block = block


def describe_block(clip: Clip) -> DescribeBlock | None:
    """A clip from a recording that needs quarter markers but has none cannot be described (spec). This
    also covers the moment before the first quarter starts.
    """
    video = clip.video
    if video.purged_at is not None:
        # The full recording is gone, so quarter starts cannot be set; blocking would leave the clip
        # undescribed forever. The quarter is still computed from existing markers (period_marks), or
        # shows as unknown without them, but the clip can be described.
        return None
    marks = video.marks
    missing = missing_periods(video.content, (m.period for m in marks))
    if not missing and period_position(marks, clip.time_sec) is not None:
        return None
    fixable = video.status == "ready"
    url = f"/videos/{video.id}#poczatki-kwart" if fixable else None
    if missing:
        message = (f"Kwarta tego klipu jest nieustalona: nagranie „{video.display_name}” nie ma ustawionych "
                   f"początków kwart (brakuje: {', '.join(missing)}), więc klipu nie można opisać.")
    else:
        message = (f"Kwarta tego klipu jest nieustalona: moment {format_clock(clip.time_sec)} wypada przed "
                   "początkiem pierwszej kwarty, więc klipu nie można opisać. Przesuń początek pierwszej kwarty "
                   "albo usuń ten znacznik.")
    return DescribeBlock(message, url, "Ustaw początki kwart w odtwarzaczu" if url else "")


def describe_clip(db: Session, clip: Clip, user: User, *, official: str, category_id: str, custom_category: str,
                  description: str) -> None:
    """`described_at` and `described_by_id` are set once (first approval) and do not change on edits. An error is a
    ClipDescribeError and nothing is changed.
    """
    block = describe_block(clip)
    if block is not None:
        raise ClipBlockedError(block)
    official = official.strip()
    valid_officials = {str(o.id) for o in clip.match.officials}
    if official != "team" and official not in valid_officials:
        raise ClipDescribeError("Wybierz sędziego (CC, U1, U2) albo „cały zespół”.")
    category = db.get(Category, int(category_id)) if category_id.strip().isdigit() else None
    if category is None:
        raise ClipDescribeError("Wybierz kategorię.")
    if not category.is_active and category.id != clip.category_id:
        raise ClipDescribeError("Ta kategoria jest nieaktywna — wybierz inną.")
    custom = " ".join(custom_category.split())
    if category.is_custom:
        if not custom:
            raise ClipDescribeError("Dla kategorii „własna” wpisz jej nazwę.")
        if len(custom) > CUSTOM_CATEGORY_MAX:
            raise ClipDescribeError(f"Nazwa własnej kategorii: najwyżej {CUSTOM_CATEGORY_MAX} znaków.")
    description = description.strip()
    if len(description) > DESCRIPTION_MAX:
        raise ClipDescribeError(f"Opis: najwyżej {DESCRIPTION_MAX} znaków.")
    clip.whole_team = official == "team"
    clip.official_id = None if clip.whole_team else int(official)
    clip.category_id = category.id
    clip.custom_category = custom if category.is_custom else None
    clip.description = description
    if clip.described_at is None:
        clip.described_at = utcnow()
        clip.described_by_id = user.id


def clip_order_key(clip: Clip) -> tuple[int, float, int]:
    return clip.video_id, clip.time_sec, clip.id


def undescribed_queue(db: Session, match_id: int, video_id: int | None = None) -> list[Clip]:
    stmt = select(Clip).where(Clip.match_id == match_id, Clip.described_at.is_(None))
    if video_id:
        stmt = stmt.where(Clip.video_id == video_id)
    return sorted(db.scalars(stmt), key=clip_order_key)


def next_in_queue(queue: Iterable[Clip], current: Clip | None) -> Clip | None:
    """Wraps from the last clip to the first of the rest; `current` is never returned."""
    others = sorted((c for c in queue if current is None or c.id != current.id), key=clip_order_key)
    if not others:
        return None
    if current is not None:
        key = clip_order_key(current)
        for clip in others:
            if clip_order_key(clip) > key:
                return clip
    return others[0]


def neighbours(clips: Iterable[Clip], current: Clip) -> tuple[Clip | None, Clip | None]:
    """`current` need not be in the list (e.g. an edit made it stop matching the filter)."""
    key = clip_order_key(current)
    ordered = sorted((c for c in clips if c.id != current.id), key=clip_order_key)
    before = [c for c in ordered if clip_order_key(c) < key]
    after = [c for c in ordered if clip_order_key(c) > key]
    return (before[-1] if before else None), (after[0] if after else None)


def is_proposal(clip: Clip) -> bool:
    return not clip.is_described and bool(clip.official_id or clip.category_id)
