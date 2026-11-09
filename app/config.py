"""Konfiguracja aplikacji (zmienne środowiskowe)."""
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REFCLIPS_DATA_DIR", BASE_DIR / "data")).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'ref-clips.db'}")

# Strefa, w której pokazujemy daty i godziny (baza zawsze trzyma UTC). Nazwa IANA, np. Europe/Warsaw.
TIMEZONE = os.environ.get("REFCLIPS_TIMEZONE", "").strip() or "Europe/Warsaw"

# Ścieżki do ffmpeg/ffprobe: nazwa polecenia z PATH albo pełna ścieżka.
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "ffprobe")

DEFAULT_MARGIN_BEFORE = 15.0
DEFAULT_MARGIN_AFTER = 15.0
MAX_MARGIN = 120.0

# --- znaczniki i notatki -----------------------------------------------------------
MARKER_DEBOUNCE_SECONDS = 1.0    # dwa znaczniki tego samego autora w tym odstępie = podwójne kliknięcie
CUT_OUTSIDE_TOLERANCE = 1.0      # klip dalej niż tyle za końcem nagrania to błąd, a nie obcięcie
NOTES_MAX_CHARS = 20_000         # notatki przy wgrywaniu i na stronie notatek
NOTES_MAX_LINES = 300

# --- oceny i komentarze -------------------------------------------------------------
TEXT_MAX_CHARS = 5000            # komentarz do meczu/klipu i komentarz do oceny

# --- konta i sesje ----------------------------------------------------------------
SESSION_COOKIE = "rc_session"
CSRF_COOKIE = "rc_csrf"  # tylko dla formularzy bez sesji (logowanie, ustawienie hasła)
SESSION_DAYS = 30
INVITE_DAYS = 7
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15
MIN_PASSWORD_LENGTH = 10


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


# Secure ustawiaj za HTTPS (produkcja); lokalnie po http musi być wyłączone.
COOKIE_SECURE = _flag("REFCLIPS_COOKIE_SECURE")
# Adres, pod którym aplikacja jest widoczna (do linków zaproszeń); domyślnie z żądania.
PUBLIC_URL = os.environ.get("REFCLIPS_PUBLIC_URL", "").rstrip("/")
# Za reverse proxy (Caddy) adres klienta pochodzi z X-Forwarded-For.
TRUST_PROXY = _flag("REFCLIPS_TRUST_PROXY")
# Ukryte w MVP: korekta granic klipu i eksport ZIP (wracają w wersji 2).
ENABLE_V2_FEATURES = _flag("REFCLIPS_V2_FEATURES")

# --- wgrywanie (tus) i konwersja ----------------------------------------------------
GB = 1024 ** 3


def _gb(name: str, default: float) -> int:
    try:
        return int(float(os.environ.get(name, default)) * GB)
    except ValueError:
        return int(default * GB)


UPLOAD_MAX_BYTES = _gb("REFCLIPS_UPLOAD_MAX_GB", 8)           # maks. rozmiar jednego pliku
DRAFT_RESERVE_BYTES = _gb("REFCLIPS_DRAFT_RESERVE_GB", 1.5)    # miejsce na wersję roboczą
DISK_SAFETY_BYTES = _gb("REFCLIPS_DISK_SAFETY_GB", 3)          # zapas wolnego miejsca po uploadzie
UPLOAD_STALE_HOURS = 24                                        # nieaktywny upload jest usuwany
UPLOAD_CLEANUP_SECONDS = 3600                                  # co ile worker sprząta uploady
# Rozmiar kawałka tus w przeglądarce. Tylko do testów interfejsu (E2E): mały kawałek pozwala przerwać
# wgrywanie krótkiego pliku w połowie. Bez zmiennej (produkcja) zostaje 50 MB.
UPLOAD_CHUNK_BYTES = 50 * 1024 * 1024
try:
    UPLOAD_CHUNK_BYTES = int(os.environ.get("REFCLIPS_TEST_UPLOAD_CHUNK_KB", "")) * 1024 or UPLOAD_CHUNK_BYTES
except ValueError:
    pass
TRANSCODE_MAX_FPS = 30

# --- monitoring (/health) -------------------------------------------------------------
WORKER_HEARTBEAT_SECONDS = 30                                  # co ile worker odnawia znacznik życia
try:
    HEALTH_WORKER_STALE_SECONDS = int(os.environ.get("REFCLIPS_HEALTH_WORKER_STALE_SECONDS", "180"))
except ValueError:
    HEALTH_WORKER_STALE_SECONDS = 180                          # starszy znacznik = worker nie działa
# Poniżej tej ilości wolnego miejsca /health zgłasza błąd; domyślnie zapas wgrywania (DISK_SAFETY),
# bo poniżej niego aplikacja i tak odrzuca każdy nowy upload.
HEALTH_DISK_MIN_BYTES = _gb("REFCLIPS_HEALTH_DISK_MIN_GB", DISK_SAFETY_BYTES / GB)

# --- retencja i sprzątanie (segment 7) ------------------------------------------------
RETENTION_DAYS_MIN, RETENTION_DAYS_MAX = 1, 365   # zakres ustawienia `retention_days`
EXPIRY_WARN_DAYS = 7                    # tyle dni przed terminem mecz pokazuje „dostępne jeszcze X dni”
RETENTION_INTERVAL_HOURS = 24           # zadanie `retention` raz na dobę (z zapisem czasu uruchomienia)
ORPHAN_MIN_AGE_SECONDS = 3600           # plik klipu bez klipu w bazie sprzątamy po godzinie
REJECTION_WARN_DAYS = 7                 # baner o odrzuconych uploadach: ostatnie 7 dni
REJECTION_KEEP_DAYS = 30                # wpisy o odrzuconych uploadach są usuwane po 30 dniach
# Weryfikacja konwersji: czas wideo wyniku może różnić się od oryginału o max(2 s, 1% długości).
VERIFY_MIN_SECONDS = float(os.environ.get("REFCLIPS_VERIFY_MIN_SECONDS", "2"))
VERIFY_RELATIVE = float(os.environ.get("REFCLIPS_VERIFY_RELATIVE", "0.01"))
try:
    FFMPEG_NICE = int(os.environ.get("REFCLIPS_FFMPEG_NICE", "10"))  # 0 = bez obniżania priorytetu
except ValueError:
    FFMPEG_NICE = 10

FFMPEG_MISSING_MESSAGE = "Brak ffmpeg — uruchom: sudo apt install ffmpeg"


def resolve_binary(configured: str) -> str | None:
    """Zwraca pełną ścieżkę do programu lub None, gdy go nie ma."""
    return shutil.which(configured)


def ensure_dirs() -> None:
    for sub in ("uploads", "proxies", "clips", "tmp"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
