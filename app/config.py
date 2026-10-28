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

DEFAULT_MARGIN_BEFORE = 10.0
DEFAULT_MARGIN_AFTER = 10.0
MAX_MARGIN = 120.0

FFMPEG_MISSING_MESSAGE = "Brak ffmpeg — uruchom: sudo apt install ffmpeg"


def resolve_binary(configured: str) -> str | None:
    """Zwraca pełną ścieżkę do programu lub None, gdy go nie ma."""
    return shutil.which(configured)


def ensure_dirs() -> None:
    for sub in ("uploads", "proxies", "clips", "tmp"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
