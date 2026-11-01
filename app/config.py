"""Konfiguracja aplikacji (zmienne środowiskowe)."""
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REFCLIPS_DATA_DIR", BASE_DIR / "data")).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'ref-clips.db'}")

# Ścieżki do ffmpeg/ffprobe: nazwa polecenia z PATH albo pełna ścieżka.
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "ffprobe")

DEFAULT_MARGIN_BEFORE = 15.0
DEFAULT_MARGIN_AFTER = 15.0
MAX_MARGIN = 120.0

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
TRANSCODE_MAX_FPS = 30
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
