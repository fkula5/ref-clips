"""Parser notatek: czysta funkcja zamieniająca blok tekstu na listę decyzji.

Przykładowe linie (sędzia: imię, nazwisko albo funkcja CC/U1/U2; kategoria ze słownika):
    2:54 Filip kroki
    3:17 U1 dlaczego nie blok?
    1:02:15 CC faul techniczny na ławce
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
    id: int  # id pozycji w obsadzie meczu
    name: str
    function: str = ""  # CC / U1 / U2


@dataclass(frozen=True)
class CategoryDef:
    name: str
    aliases: tuple[str, ...] = ()


@dataclass
class ParsedLine:
    line_no: int
    raw: str
    time_sec: float | None = None
    referee_id: int | None = None
    referee_name: str | None = None
    category: str | None = None
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
    function = normalize(_clean_token(words[0]))
    for r in referees:  # funkcja w obsadzie: CC / U1 / U2
        if r.function and normalize(r.function) == function:
            return r, 1, False
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


def find_categories(text: str, categories: list[CategoryDef]) -> list[str]:
    """Znajduje kategorie ze słownika (nazwa kategorii jest też aliasem), w kolejności słownika."""
    norm = f" {normalize(text)} "
    original_words = set(_WORD.findall(text))
    found: dict[str, int] = {}
    entries: list[tuple[str, str, bool]] = []  # (alias, kategoria, wielkość liter ma znaczenie)
    for category in categories:
        for alias in (category.name, *category.aliases):
            if len(alias) <= 2 and alias.isalpha():
                entries.append((alias, category.name, True))  # np. U, T, D tylko wielką literą
            elif normalize(alias):
                entries.append((normalize(alias), category.name, False))
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
    order = {c.name: i for i, c in enumerate(categories)}
    return sorted(found, key=lambda n: order.get(n, 999))


def _strip_leading_category(words: list[str], category: CategoryDef) -> list[str] | None:
    """Słowa po odcięciu nazwy/aliasu kategorii stojącego na samym początku; None, gdy tekst nie
    zaczyna się od żadnego z nich. Dopasowanie tak jak w `find_categories` (bez polskich znaków i wielkości
    liter, krótkie aliasy typu T/U/D tylko wielką literą), z pominięciem interpunkcji przy słowach."""
    entries = sorted((a for a in (category.name, *category.aliases) if normalize(a)),
                     key=lambda a: -len(normalize(a)))
    for alias in entries:
        if len(alias) <= 2 and alias.isalpha():
            if words and _clean_token(words[0]) == alias:
                return words[1:]
            continue
        parts = normalize(alias).split()
        if len(words) >= len(parts) and all(
                normalize(_clean_token(w)) == part for w, part in zip(words, parts)):
            return words[len(parts):]
    return None


def _leftover_description(words: list[str], category: CategoryDef | None, referee_found: bool) -> str:
    """Opis klipu z notatki: to, co zostaje po odcięciu sędziego (już w `words`), czasu i kategorii.

    Kategorię odcinamy tylko wtedy, gdy stoi na początku reszty (konwencja „czas sędzia kategoria uwagi”,
    np. „CC kroki za późno” -> „za późno”). Gdy alias trafia się w środku albo na końcu swobodnego
    zdania („Dlaczego nie blok?”), zdanie zostaje w całości — wycięcie słowa zrobiłoby z niego
    bezsensowny ułamek. Nierozpoznane pierwsze słowo (nieznany albo niejednoznaczny sędzia) zostaje
    w opisie, a kategorię szukamy zaraz za nim."""
    if category is not None:
        starts = [0] if referee_found else [0, 1]
        for start in starts:
            left = _strip_leading_category(words[start:], category)
            if left is not None:
                words = words[:start] + left
                break
    return " ".join(words).strip(" \t,;:-–—")


def parse_line(line_no: int, raw: str, referees: list[RefereeDef],
               categories: list[CategoryDef]) -> ParsedLine:
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
        result.description = ""
        return result

    words = rest.split()
    referee, used, ambiguous = _match_referee(words, referees)
    if referee:
        result.referee_id, result.referee_name = referee.id, referee.name
        rest = " ".join(words[used:])
        words = words[used:]
    elif ambiguous:
        result.warnings.append(f"Niejednoznaczny sędzia: „{_clean_token(words[0])}”")
    else:
        first = words[0]
        if find_categories(first, categories):
            result.warnings.append("Brak sędziego w linii")
        else:
            result.warnings.append(f"Nieznany sędzia: „{_clean_token(first)}”")

    found = find_categories(rest, categories)
    if found:
        result.category = found[0]
    if len(found) > 1:
        result.warnings.append(f"Kilka kategorii ({', '.join(found)}) — wybrano pierwszą")
    # Opis = reszta linii bez czasu, rozpoznanego sędziego i kategorii (te są w osobnych polach).
    chosen = next((c for c in categories if c.name == result.category), None)
    result.description = _leftover_description(words, chosen, referee is not None)
    return result


def parse_notes(text: str, referees: list[RefereeDef],
                categories: list[CategoryDef]) -> list[ParsedLine]:
    """Parsuje cały blok notatek. Puste linie i linie zaczynające się od '#' są pomijane."""
    results = []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        results.append(parse_line(i, raw, referees, categories))
    return results
