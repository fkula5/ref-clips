"""Pomocnicze funkcje tekstowe: normalizacja polskich znaków, slugi, formaty czasu."""
import re
import unicodedata

_EXTRA = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "đ": "d"})


def strip_diacritics(text: str) -> str:
    text = text.translate(_EXTRA)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Małe litery, bez polskich znaków, pojedyncze spacje."""
    return re.sub(r"\s+", " ", strip_diacritics(text).casefold()).strip()


def slugify(text: str, default: str = "") -> str:
    """Bezpieczny fragment nazwy pliku (ASCII, litery/cyfry/myślnik)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", strip_diacritics(text)).strip("-")
    return slug or default


def safe_filename(name: str, default: str = "plik") -> str:
    """Nazwa wgrywanego pliku bez ścieżek i dziwnych znaków (rozszerzenie zachowane)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = slugify(stem, default)
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8]
    return f"{stem}.{ext}" if ext else stem


def format_clock(seconds: float | None) -> str:
    """174 -> '2:54', 3735 -> '1:02:15'."""
    if seconds is None:
        return ""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
