"""Parser notatek: czysta funkcja zamieniająca blok tekstu na listę decyzji.

Przykładowe linie:
    2:54 Filip PTS
    3:17 Filip Dlaczego nie blok?
    1:02:15 Kasia kroki białe błąd
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.textutil import normalize

# m:ss, mm:ss lub h:mm:ss; separatorem może być ':', '.' albo ','.
_TIME_AT_START = re.compile(r"^\s*(\d{1,3})[:.,](\d{2})(?:[:.,](\d{2}))?(?=[\s\-–—:)]|$)")
_TIME_FULL = re.compile(r"^\s*(\d{1,3})[:.,](\d{2})(?:[:.,](\d{2}))?\s*$")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class RefereeDef:
    id: int
    name: str


@dataclass(frozen=True)
class TagDef:
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamDef:
    key: str  # "a" / "b"
    keywords: tuple[str, ...]  # nazwa drużyny, kolor ("białe") itp.


@dataclass
class ParsedLine:
    line_no: int
    raw: str
    time_sec: float | None = None
    referee_id: int | None = None
    referee_name: str | None = None
    tags: list[str] = field(default_factory=list)
    team: str | None = None
    description: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.time_sec is not None


def _seconds(a: str, b: str, c: str | None) -> float | None:
    """Składa czas z grup regexa; None, gdy wartości są poza zakresem."""
    if c is None:
        minutes, secs = int(a), int(b)
        return float(minutes * 60 + secs) if secs < 60 else None
    hours, minutes, secs = int(a), int(b), int(c)
    if minutes >= 60 or secs >= 60:
        return None
    return float(hours * 3600 + minutes * 60 + secs)


def parse_time(text: str) -> float | None:
    """Parsuje samodzielny zapis czasu ('2:54', '2.54', '1:02:15'); None gdy niepoprawny."""
    m = _TIME_FULL.match(text or "")
    return _seconds(*m.groups()) if m else None


def _loose_equal(a: str, b: str, min_len: int) -> bool:
    """Równość z tolerancją na końcówki fleksyjne (Kasia/Kasi, Filip/Filipa, białe/białych)."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(long_) - len(short) > 2:
        return False
    if len(short) >= min_len and long_.startswith(short):
        return True
    if len(short) >= 5:
        common = 0
        for x, y in zip(a, b):
            if x != y:
                break
            common += 1
        return common >= len(short) - 1
    return False


def _clean_token(token: str) -> str:
    return token.strip(",.;:!?()[]\"'")


def _match_referee(words: list[str], referees: list[RefereeDef]) -> tuple[RefereeDef | None, int, bool]:
    """Zwraca (sędzia, liczba zużytych słów, czy niejednoznaczne)."""
    if not words or not referees:
        return None, 0, False
    # pełne imię i nazwisko (dwa słowa)
    if len(words) >= 2:
        pair = normalize(f"{_clean_token(words[0])} {_clean_token(words[1])}")
        full = [r for r in referees if normalize(r.name) == pair]
        if len(full) == 1:
            return full[0], 2, False
    token = normalize(_clean_token(words[0]))
    if not token:
        return None, 0, False
    name_tokens = {r.id: normalize(r.name).split() for r in referees}
    for min_len, exact in ((0, True), (3, False)):
        found = [
            r for r in referees
            if any((t == token) if exact else _loose_equal(t, token, min_len) for t in name_tokens[r.id])
        ]
        if len(found) == 1:
            return found[0], 1, False
        if len(found) > 1:
            return None, 0, True
    return None, 0, False


def find_tags(text: str, tags: list[TagDef]) -> list[str]:
    """Znajduje tagi ze słownika (nazwa tagu jest też aliasem), w kolejności słownika."""
    norm = f" {normalize(text)} "
    original_words = set(_WORD.findall(text))
    found: dict[str, int] = {}
    entries: list[tuple[str, str, bool]] = []  # (alias znormalizowany/surowy, tag, wielkość liter ma znaczenie)
    for tag in tags:
        for alias in (tag.name, *tag.aliases):
            if len(alias) <= 2 and alias.isalpha():
                entries.append((alias, tag.name, True))  # np. U, T, D tylko wielką literą
            elif normalize(alias):
                entries.append((normalize(alias), tag.name, False))
    for alias, name, case_sensitive in entries:
        if case_sensitive and alias in original_words:
            found.setdefault(name, 0)
    # dłuższe aliasy najpierw, żeby "brak gwizdka" wygrał z krótszymi
    for alias, name, case_sensitive in sorted(entries, key=lambda e: -len(e[0])):
        if case_sensitive:
            continue
        pattern = re.compile(rf"(?<![0-9a-z]){re.escape(alias)}(?![0-9a-z])")
        if pattern.search(norm):
            found.setdefault(name, 0)
            norm = pattern.sub(" ", norm)
    order = {t.name: i for i, t in enumerate(tags)}
    return sorted(found, key=lambda n: order.get(n, 999))


def find_team(text: str, teams: list[TeamDef]) -> tuple[str | None, bool]:
    """Zwraca (klucz drużyny, czy niejednoznaczne)."""
    words = normalize(text).split()
    matched: set[str] = set()
    for team in teams:
        for keyword in team.keywords:
            kw = normalize(keyword)
            if not kw:
                continue
            kw_words = kw.split()
            if len(kw_words) > 1 and f" {kw} " in f" {' '.join(words)} ":
                matched.add(team.key)
            for kw_word in kw_words:
                if len(kw_word) >= 3 and any(_loose_equal(w, kw_word, 4) for w in words):
                    matched.add(team.key)
    if len(matched) == 1:
        return next(iter(matched)), False
    return None, len(matched) > 1


def parse_line(line_no: int, raw: str, referees: list[RefereeDef], tags: list[TagDef],
               teams: list[TeamDef]) -> ParsedLine:
    line = raw.strip()
    result = ParsedLine(line_no=line_no, raw=line, description=line)
    m = _TIME_AT_START.match(line)
    if not m:
        result.warnings.append("Nie rozpoznano czasu na początku linii")
        return result
    time_sec = _seconds(*m.groups())
    if time_sec is None:
        result.warnings.append(f"Niepoprawny czas: {m.group(0).strip()}")
        return result
    result.time_sec = time_sec

    rest = line[m.end():].lstrip(" \t-–—:)").strip()
    if not rest:
        result.warnings.append("Brak opisu po czasie")
        return result

    words = rest.split()
    referee, used, ambiguous = _match_referee(words, referees)
    if referee:
        result.referee_id, result.referee_name = referee.id, referee.name
        rest = " ".join(words[used:])
    elif ambiguous:
        result.warnings.append(f"Niejednoznaczny sędzia: „{_clean_token(words[0])}”")
    else:
        first = words[0]
        looks_like_keyword = bool(find_tags(first, tags)) or find_team(first, teams)[0] is not None
        if looks_like_keyword:
            result.warnings.append("Brak sędziego w linii")
        else:
            result.warnings.append(f"Nieznany sędzia: „{_clean_token(first)}”")

    result.tags = find_tags(rest, tags)
    team, team_ambiguous = find_team(rest, teams)
    result.team = team
    if team_ambiguous:
        result.warnings.append("Niejednoznaczna drużyna (pasują obie)")
    return result


def parse_notes(text: str, referees: list[RefereeDef], tags: list[TagDef],
                teams: list[TeamDef] | None = None) -> list[ParsedLine]:
    """Parsuje cały blok notatek. Puste linie i linie zaczynające się od '#' są pomijane."""
    teams = teams or []
    results = []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        results.append(parse_line(i, raw, referees, tags, teams))
    return results
