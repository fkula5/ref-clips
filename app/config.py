import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("REFCLIPS_DATA_DIR", BASE_DIR / "data")).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'ref-clips.db'}")

# Set by the Docker image (build-arg REFCLIPS_VERSION); "dev" locally.
VERSION = os.environ.get("REFCLIPS_VERSION", "").strip() or "dev"

# Display timezone (IANA name); the database always stores UTC.
TIMEZONE = os.environ.get("REFCLIPS_TIMEZONE", "").strip() or "Europe/Warsaw"

FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "ffprobe")

DEFAULT_MARGIN_BEFORE = 15.0
DEFAULT_MARGIN_AFTER = 15.0
MAX_MARGIN = 120.0

MARKER_DEBOUNCE_SECONDS = 1.0
CUT_OUTSIDE_TOLERANCE = 1.0  # a clip further than this past the end of the recording is an error, not a trim
NOTES_MAX_CHARS = 20_000
NOTES_MAX_LINES = 300

TEXT_MAX_CHARS = 5000

SHEET_RESULT_MAX_CHARS = 50
SHEET_ELEMENT_NAME_MAX_CHARS = 100

SESSION_COOKIE = "rc_session"
CSRF_COOKIE = "rc_csrf"  # only for forms without a session (login, set-password)
SESSION_DAYS = 30
INVITE_DAYS = 7
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15
MIN_PASSWORD_LENGTH = 10


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


# Secure cookies need HTTPS; must be off for local http.
COOKIE_SECURE = _flag("REFCLIPS_COOKIE_SECURE")
PUBLIC_URL = os.environ.get("REFCLIPS_PUBLIC_URL", "").rstrip("/")
# Behind a reverse proxy (Caddy) the client address comes from X-Forwarded-For.
TRUST_PROXY = _flag("REFCLIPS_TRUST_PROXY")
# Hidden in the MVP: clip boundary editing and ZIP export.
ENABLE_V2_FEATURES = _flag("REFCLIPS_V2_FEATURES")

GB = 1024 ** 3


def _gb(name: str, default: float) -> int:
    try:
        return int(float(os.environ.get(name, default)) * GB)
    except ValueError:
        return int(default * GB)


UPLOAD_MAX_BYTES = _gb("REFCLIPS_UPLOAD_MAX_GB", 8)
DRAFT_RESERVE_BYTES = _gb("REFCLIPS_DRAFT_RESERVE_GB", 1.5)
DISK_SAFETY_BYTES = _gb("REFCLIPS_DISK_SAFETY_GB", 3)
UPLOAD_STALE_HOURS = 24
UPLOAD_CLEANUP_SECONDS = 3600
# tus chunk size in the browser. E2E only: a small chunk lets tests interrupt a short upload midway.
# Production keeps 50 MB.
UPLOAD_CHUNK_BYTES = 50 * 1024 * 1024
try:
    UPLOAD_CHUNK_BYTES = int(os.environ.get("REFCLIPS_TEST_UPLOAD_CHUNK_KB", "")) * 1024 or UPLOAD_CHUNK_BYTES
except ValueError:
    pass
TRANSCODE_MAX_FPS = 30

WORKER_HEARTBEAT_SECONDS = 30
try:
    HEALTH_WORKER_STALE_SECONDS = int(os.environ.get("REFCLIPS_HEALTH_WORKER_STALE_SECONDS", "180"))
except ValueError:
    HEALTH_WORKER_STALE_SECONDS = 180
# Below this much free space /health reports an error; defaults to DISK_SAFETY, under which every new
# upload is rejected anyway.
HEALTH_DISK_MIN_BYTES = _gb("REFCLIPS_HEALTH_DISK_MIN_GB", DISK_SAFETY_BYTES / GB)

SHARE_DAYS = (1, 7, 30)  # allowed validity in days; permanent links do not exist
SHARE_DEFAULT_DAYS = 7
SHARE_MAX_CLIPS = 30
SHARE_ZIP_MAX_PARALLEL = 2  # concurrent ZIP builds; extra requests get 503

RETENTION_DAYS_MIN, RETENTION_DAYS_MAX = 1, 365
EXPIRY_WARN_DAYS = 7
RETENTION_INTERVAL_HOURS = 24
ORPHAN_MIN_AGE_SECONDS = 3600
REJECTION_WARN_DAYS = 7
REJECTION_KEEP_DAYS = 30
NOTIFICATION_READ_KEEP_DAYS = 30
NOTIFICATION_UNREAD_KEEP_DAYS = 90
NOTIFICATION_LIST_LIMIT = 100
# Conversion check: the result's duration may differ from the original by max(2 s, 1% of its length).
VERIFY_MIN_SECONDS = float(os.environ.get("REFCLIPS_VERIFY_MIN_SECONDS", "2"))
VERIFY_RELATIVE = float(os.environ.get("REFCLIPS_VERIFY_RELATIVE", "0.01"))
try:
    FFMPEG_NICE = int(os.environ.get("REFCLIPS_FFMPEG_NICE", "10"))  # 0 disables lowering the priority
except ValueError:
    FFMPEG_NICE = 10

# Conversion watchdog: if ffmpeg reports no progress for this many seconds (no data, or `out_time`
# stuck), the process is killed and the task fails. 0 disables it.
try:
    FFMPEG_STALL_SECONDS = float(os.environ.get("REFCLIPS_FFMPEG_STALL_SECONDS", "900"))
except ValueError:
    FFMPEG_STALL_SECONDS = 900.0
# Cutting reports no progress, so it gets a plain timeout: the larger of a fixed minimum and a multiple
# of the clip length.
CUT_TIMEOUT_MIN_SECONDS = 300
CUT_TIMEOUT_PER_CLIP_SECOND = 20

FFMPEG_MISSING_MESSAGE = "Brak ffmpeg — uruchom: sudo apt install ffmpeg"


def resolve_binary(configured: str) -> str | None:
    return shutil.which(configured)


def ensure_dirs() -> None:
    for sub in ("uploads", "proxies", "clips", "tmp"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
