"""Logika biznesowa: obsada, kwarty, granice klipów, nazwy plików, tworzenie klipów, kolejka."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
    """Niepoprawne dane w formularzu meczu (komunikat po polsku); w formularzu to HTTP 422."""
    status_code = 422


class MatchForbiddenError(MatchFormError):
    """Odmowa reguły „sędzia musi być w obsadzie własnego meczu” (HTTP 403, ale w formularzu)."""
    status_code = 403


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


# --- tożsamość osób w obsadzie -----------------------------------------------------
Identity = tuple[str, object]


def account_names(db: Session) -> dict[str, int]:
    """Znormalizowane imię i nazwisko -> id konta, tylko gdy nazwa jest jednoznaczna.

    Dwa konta o tym samym imieniu i nazwisku (także nieaktywne) nie trafiają do słownika:
    wpisane nazwisko nie może wtedy być przypisane do żadnego z nich."""
    found: dict[str, int | None] = {}
    for user_id, name in db.execute(select(User.id, User.name)):
        key = normalize(name)
        found[key] = None if key in found else user_id
    return {key: user_id for key, user_id in found.items() if user_id is not None}


def identity(user_id: int | None, name: str | None, accounts: Mapping[str, int]) -> Identity:
    """Tożsamość osoby: konto albo znormalizowane wpisane nazwisko. Wpisane nazwisko zgodne
    z nazwą jednoznacznego konta to TA SAMA osoba co konto (sędzia wpisany ręcznie, który
    dostał później konto)."""
    if user_id:
        return ("u", user_id)
    key = normalize(name or "")
    return ("u", accounts[key]) if key in accounts else ("n", key)


def person_key(user_id: int | None, name: str | None, accounts: Mapping[str, int]) -> str:
    """Klucz osoby do filtrów: "u<id konta>" albo "n<znormalizowane imię i nazwisko>"."""
    kind, value = identity(user_id, name, accounts)
    return f"{kind}{value}"


def people(db: Session) -> list[tuple[str, str]]:
    """Sędziowie z obsad (konto albo wpisane nazwisko) do filtrów: (klucz, nazwa), alfabetycznie.
    Wpisane nazwisko zgodne z kontem jest tą samą osobą i pokazuje się pod nazwą konta."""
    accounts = account_names(db)
    user_names = {uid: name for uid, name in db.execute(select(User.id, User.name))}
    found: dict[str, str] = {}
    for user_id, name in db.execute(select(MatchOfficial.user_id, MatchOfficial.name)):
        kind, value = identity(user_id, name, accounts)
        found.setdefault(f"{kind}{value}", user_names[value] if kind == "u" else name)
    return sorted(found.items(), key=lambda kv: normalize(kv[1]))


# --- obsada meczu -----------------------------------------------------------------
def referee_candidates(db: Session) -> list[User]:
    """Konta, które można wybrać w obsadzie: aktywne, z rolą sędziego."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return [u for u in users if "referee" in u.roles]


def officials_from_form(db: Session, form: dict[str, str]) -> list[tuple[str, int | None, str | None]]:
    """Czyta pola `<fn>_user` / `<fn>_name` (fn = cc, u1, u2) z formularza meczu.

    Zwraca listę (funkcja, user_id, wpisane imię i nazwisko) dla wypełnionych pozycji.
    Konto ma pierwszeństwo przed wpisanym imieniem. CC i U1 są wymagane, U2 opcjonalna.
    Ta sama osoba nie może zająć dwóch pozycji: to samo konto, to samo wpisane nazwisko
    (po normalizacji) ani konto i wpisane nazwisko tej samej osoby.
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
    """Zastępuje obsadę meczu, zachowując powiązanie klipów z OSOBĄ, a nie z pozycją.

    Istniejące pozycje dopasowujemy po tożsamości (konto albo imię i nazwisko; wpisane
    nazwisko zgodne z jednoznacznym kontem to ta sama osoba, w obie strony). Osoba, która
    zostaje, zachowuje klipy także przy zmianie funkcji (np. zamiana CC z U1) i zmianie
    sposobu zapisu (nazwisko -> konto); nowa osoba to nowa pozycja; usunięta osoba traci
    pozycję, a jej klipy zostają bez przypisania (official_id = NULL). Unikalność (mecz,
    funkcja) jest zachowana: pozycje zmieniające funkcję są najpierw usuwane (z zapamiętaniem
    klipów), potem zakładane od nowa.
    """
    accounts = account_names(db)
    incoming = {identity(user_id, name, accounts): (function, user_id, name)
                for function, user_id, name in officials}
    # klipy pobieramy przed usuwaniem pozycji: usunięcie (autoflush) zeruje official_id w bazie
    clips_of: dict[int, list[int]] = {}
    old_ids = [o.id for o in match.officials if o.id is not None]
    if old_ids:
        for clip_id, official_id in db.execute(
                select(Clip.id, Clip.official_id).where(Clip.official_id.in_(old_ids))):
            clips_of.setdefault(official_id, []).append(clip_id)
    moved: list[tuple[int, tuple[str, int | None, str | None]]] = []  # (stare id pozycji, nowe dane)
    removed = False
    for official in list(match.officials):
        target = incoming.pop(identity(official.user_id, official.name, accounts), None)
        if target is None:
            match.officials.remove(official)          # osoba usunięta z obsady
            removed = True
        elif target[0] == official.function:
            official.user_id, official.name = target[1], target[2]  # ewentualnie konto zamiast nazwiska
        else:
            moved.append((official.id, target))
            match.officials.remove(official)
    if moved or removed:
        db.flush()  # zwolnione funkcje przed wstawieniem nowych (unikalność sprawdzana per instrukcja)
    created: list[tuple[int, MatchOfficial]] = []
    for old_id, (function, user_id, name) in moved:
        fresh = MatchOfficial(function=function, user_id=user_id, name=name)
        match.officials.append(fresh)
        created.append((old_id, fresh))
    for function, user_id, name in incoming.values():  # nowe osoby
        match.officials.append(MatchOfficial(function=function, user_id=user_id, name=name))
    if moved:
        db.flush()
        for old_id, fresh in created:
            if clips_of.get(old_id):
                db.execute(update(Clip).where(Clip.id.in_(clips_of[old_id])).values(official_id=fresh.id))


# --- stan meczu (lista meczów) --------------------------------------------------
MATCH_STATES = {
    "none": "brak nagrania",
    "uploading": "wgrywanie",
    "converting": "konwersja",
    "error": "błąd konwersji",
    "no_marks": "brak znaczników kwart",
    "ready": "gotowy",
    "purged": "pełne nagranie usunięte",
}
FULL_MATCH_PERIODS = PERIODS[:4]  # cały mecz = Q1–Q4 (dogrywki opcjonalne)


@dataclass(frozen=True)
class MatchState:
    code: str
    detail: str = ""

    @property
    def label(self) -> str:
        return MATCH_STATES[self.code]


def declared_periods(content: str | None) -> list[str] | None:
    """Zawartość pliku ("full" albo "Q1,Q2") jako lista kwart; None = cały mecz.
    Brak deklaracji (segment 3 jej jeszcze nie wymaga) traktujemy jak cały mecz."""
    found = [p.strip().upper() for p in (content or "").split(",")]
    found = [p for p in PERIODS if p in found]
    return found or None


def missing_periods(content: str | None, marked: Iterable[str]) -> list[str]:
    """Kwarty, którym brakuje znacznika początku. Plik z jedną kwartą nie wymaga znaczników
    (domyślnie zaczyna się od 0:00); cały mecz wymaga Q1–Q4, plik z kilkoma kwartami wszystkich
    zadeklarowanych."""
    declared = declared_periods(content)
    if declared is None:
        required = FULL_MATCH_PERIODS
    elif len(declared) > 1:
        required = declared
    else:
        return []
    have = set(marked)
    return [p for p in required if p not in have]


def match_state(videos: Iterable[Video], queue: Mapping[int, int] | None = None) -> MatchState:
    """Stan meczu wyliczany z nagrań (czysta funkcja). Kolejność: błąd, wgrywanie/konwersja,
    brak znaczników kwart, gotowy. Nagrania z usuniętą pełną wersją nie liczą się do stanu;
    gdy wszystkie są usunięte, mecz ma stan „pełne nagranie usunięte”.

    `queue` to pozycje zadań konwersji w kolejce (id nagrania -> numer od 1)."""
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
    """Pozycje w kolejce konwersji: id nagrania -> numer od 1 (trwające zadanie jest pierwsze)."""
    rows = db.execute(select(Job.video_id).where(
        Job.type == "transcode", Job.status.in_(("pending", "running")), Job.video_id.is_not(None))
        .order_by(Job.status.desc(), Job.id))  # „running” przed „pending”
    queue: dict[int, int] = {}
    for (video_id,) in rows:
        queue.setdefault(video_id, len(queue) + 1)
    return queue


def known_levels(db: Session) -> list[str]:
    """Ligi użyte wcześniej w meczach (bez powtórzeń, alfabetycznie) — podpowiedzi w formularzu."""
    levels = {lv.strip() for lv in db.scalars(select(Match.level).distinct()) if lv and lv.strip()}
    return sorted(levels, key=lambda lv: (normalize(lv), lv))


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


def period_short(marks: list[PeriodMark], time_sec: float) -> str:
    """Krótko do tabel: „Q2 · 4:12” (czas od początku kwarty w czasie nagrania) albo „nieustalona”."""
    pos = period_position(marks, time_sec)
    return "nieustalona" if pos is None else f"{pos[0]} · {format_clock(pos[1])}"


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
