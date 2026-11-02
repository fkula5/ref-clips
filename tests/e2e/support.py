"""Pomocnicze elementy testów interfejsu: prawdziwy serwer + worker, konta, dane i pliki wideo.

Serwer (uvicorn) i worker (python -m app.worker) działają w osobnych procesach na losowym wolnym
porcie z tymczasowym REFCLIPS_DATA_DIR. Konta zakłada kod aplikacji (`accounts`), a dane testowe
(mecze, nagrania) powstają wprost w bazie — przez te same modele co w aplikacji.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import accounts
from app.models import Match, MatchOfficial, User, Video

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "E2e-haslo-12345"
CHUNK_KB = 256  # kawałek tus w trybie testowym (REFCLIPS_TEST_UPLOAD_CHUNK_KB)

# Konta testowe: klucz -> (e-mail, imię i nazwisko, role)
USERS = {
    "admin": ("admin@example.com", "Adam Admin", ["admin"]),
    "coach": ("trener@example.com", "Cezary Trener", ["coach"]),
    "referee": ("roman@example.com", "Roman Sędzia", ["referee"]),       # w obsadzie meczów testowych
    "outsider": ("olek@example.com", "Olek Obcy", ["referee"]),          # sędzia spoza obsady
    "second": ("ula@example.com", "Ula Druga", ["referee"]),             # druga osoba do formularza obsady
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_sample_video(path: Path, seconds: int = 50) -> Path:
    """Krótkie wideo 640x360 z dźwiękiem i licznikiem czasu na obrazie; klatka kluczowa co sekundę
    i faststart — takie jak wersja robocza z workera."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", "-g", "25",
         "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(path)],
        check=True)
    return path


class Server:
    """Uruchomiona aplikacja z kontami testowymi i pomocnikami do przygotowania danych."""

    def __init__(self, workdir: Path, sample: Path):
        self.workdir = workdir
        self.data_dir = workdir / "data"
        self.logs = workdir / "logs"
        self.sample = sample
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.procs: dict[str, subprocess.Popen] = {}
        self.engine = None
        self.session_factory = None
        self.users: dict[str, int] = {}
        self._duration: float | None = None

    # --- cykl życia ---------------------------------------------------------------
    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("REFCLIPS_") and k != "DATABASE_URL"}
        env.update(REFCLIPS_DATA_DIR=str(self.data_dir), REFCLIPS_FFMPEG_NICE="0",
                   REFCLIPS_TEST_UPLOAD_CHUNK_KB=str(CHUNK_KB), PYTHONUNBUFFERED="1")
        return env

    def start(self) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "app.initdb"], cwd=ROOT, env=self.env(), check=True,
                       stdout=(self.logs / "initdb.log").open("w"), stderr=subprocess.STDOUT)
        self.engine = create_engine(f"sqlite:///{self.data_dir / 'ref-clips.db'}",
                                    connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def _pragmas(conn, _rec):  # jak w app/db.py
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self._create_users()
        self.procs["server"] = self._spawn(
            "server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                       "--port", str(self.port), "--log-level", "info"])
        self.procs["worker"] = self._spawn("worker", [sys.executable, "-m", "app.worker"])
        self._wait_until_up()

    def _spawn(self, name: str, cmd: list[str]) -> subprocess.Popen:
        log = (self.logs / f"{name}.log").open("w")
        return subprocess.Popen(cmd, cwd=ROOT, env=self.env(), stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)

    def _wait_until_up(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for name, proc in self.procs.items():
                if proc.poll() is not None:
                    raise RuntimeError(f"Proces {name} zakończył się kodem {proc.returncode}:\n{self.log_tail(name)}")
            try:
                with urllib.request.urlopen(self.base_url + "/login", timeout=2) as res:
                    if res.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        raise RuntimeError(f"Serwer nie wystartował w {timeout:.0f} s:\n{self.log_tail('server')}")

    def stop(self) -> None:
        for proc in self.procs.values():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in self.procs.values():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        if self.engine is not None:
            self.engine.dispose()

    def log_tail(self, name: str, lines: int = 60) -> str:
        path = self.logs / f"{name}.log"
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:]) if path.exists() else ""

    def copy_logs(self, target: Path) -> None:
        for log in self.logs.glob("*.log"):
            shutil.copy(log, target / f"serwer-{log.name}")

    # --- dane -----------------------------------------------------------------------
    @contextmanager
    def db(self):
        with self.session_factory() as session:
            yield session

    def _create_users(self) -> None:
        with self.db() as db:
            for key, (email, name, roles) in USERS.items():
                if key == "admin":
                    user, _ = accounts.ensure_admin(db, email=email, name=name, password=PASSWORD)
                else:
                    user = accounts.create_user(db, email=email, name=name, roles=roles, password=PASSWORD)
                self.users[key] = user.id

    def user_name(self, key: str) -> str:
        return USERS[key][1]

    def make_match(self, *, officials=(("CC", "referee"), ("U1", "Kasia Żółć")), level="II liga",
                   team_a="Legia", team_b="Wisła", day: date | None = None, created_by: str | None = "admin") -> int:
        """Mecz z obsadą: pozycja to (funkcja, klucz konta testowego albo wpisane nazwisko)."""
        with self.db() as db:
            match = Match(date=day or date(2026, 10, 28), level=level, team_a_name=team_a, team_a_color="białe",
                          team_b_name=team_b, team_b_color="ciemne",
                          created_by=self.users[created_by] if created_by else None)
            for function, who in officials:
                if who in self.users:
                    match.officials.append(MatchOfficial(function=function, user_id=self.users[who]))
                else:
                    match.officials.append(MatchOfficial(function=function, name=who))
            db.add(match)
            db.commit()
            return match.id

    def sample_duration(self) -> float:
        if self._duration is None:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "json", str(self.sample)], check=True, capture_output=True, text=True).stdout
            self._duration = float(json.loads(out)["format"]["duration"])
        return self._duration

    def make_ready_video(self, match_id: int, *, content: str = "full", label: str = "Całość") -> int:
        """Nagranie już po konwersji: plik próbny skopiowany jako wersja robocza (bez czekania na
        workera). Cięcie klipów robi prawdziwy worker."""
        with self.db() as db:
            video = Video(match_id=match_id, label=label, original_filename="mecz.mp4", status="ready",
                          duration=self.sample_duration(), fps=25.0, content=content,
                          size_bytes=self.sample.stat().st_size)
            db.add(video)
            db.commit()
            key = f"proxies/{video.id}.mp4"
            target = self.data_dir / key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(self.sample, target)
            video.proxy_path = key
            db.commit()
            return video.id

    def set_mark(self, video_id: int, period: str, time_sec: float) -> None:
        from app.models import PeriodMark
        with self.db() as db:
            db.add(PeriodMark(video_id=video_id, period=period, time_sec=time_sec))
            db.commit()

    def create_clip(self, video_id: int, time_sec: float, author: str = "admin") -> int:
        """Nieopisany klip ze znacznika (jak „Zaznacz”): zadanie cięcia podejmie prawdziwy worker."""
        from app import services
        with self.db() as db:
            video = db.get(Video, video_id)
            clip = services.create_clip(db, video, db.get(User, self.users[author]), time_sec=time_sec)
            db.commit()
            return clip.id

    def insert_clip(self, video_id: int, time_sec: float, *, author: str = "admin", official: str | None = None,
                    category: str | None = None, custom: str | None = None, whole_team: bool = False,
                    description: str = "", described: bool = False, status: str = "cut",
                    error: str | None = None, margin: float = 15.0) -> int:
        """Klip wprost w bazie, bez zadania cięcia (worker go nie dotknie): dowolny stan, sędzia (funkcja
        z obsady meczu), kategoria (nazwa), opis. Do testów list, filtrów i ekranu opisywania."""
        from datetime import datetime
        from app.models import Category, Clip
        with self.db() as db:
            video = db.get(Video, video_id)
            official_row = next((o for o in video.match.officials if o.function == official), None) if official else None
            cat = db.scalar(select(Category).where(Category.name == category)) if category else None
            clip = Clip(match_id=video.match_id, video_id=video_id, author_id=self.users[author], time_sec=time_sec,
                        official_id=official_row.id if official_row else None, whole_team=whole_team,
                        category_id=cat.id if cat else None, custom_category=custom, description=description,
                        described_at=datetime(2026, 10, 29, 12, 0) if described else None, status=status,
                        error=error, margin_before=margin, margin_after=margin)
            db.add(clip)
            db.commit()
            return clip.id

    def clip(self, clip_id: int):
        from app.models import Clip
        with self.db() as db:
            clip = db.get(Clip, clip_id)
            if clip is not None:
                db.refresh(clip)
                db.expunge(clip)
            return clip

    def clips_of(self, video_id: int):
        from app.models import Clip
        with self.db() as db:
            return list(db.scalars(select(Clip).where(Clip.video_id == video_id).order_by(Clip.time_sec)))

    def marks_of(self, video_id: int) -> dict[str, float]:
        from app.models import PeriodMark
        with self.db() as db:
            return {m.period: m.time_sec for m in db.scalars(select(PeriodMark).where(PeriodMark.video_id == video_id))}

    def user_by_email(self, email: str) -> User | None:
        with self.db() as db:
            return db.scalar(select(User).where(User.email == email))


def wait_until(page, condition, timeout: float = 20.0, message: str = "warunek nie został spełniony") -> None:
    """Czeka na warunek po stronie testu (np. liczba żądań), przetwarzając zdarzenia strony."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"Po {timeout:.0f} s: {message}")


# Zapisuje w sessionStorage kolejne stany paska postępu wgrywania (przeżywa odświeżenie strony
# po zakończeniu uploadu, więc test widzi także krótkotrwałe stany typu „100%” i „gotowe”).
RECORD_UPLOAD_PROGRESS = """
(() => {
  const KEY = '__upload_states';
  const rec = () => {
    const box = document.getElementById('upload-progress');
    if (!box) return;
    const bar = box.querySelector('progress'), pct = box.querySelector('.pct');
    if (!bar || !pct) return;
    const value = bar.value + '|' + pct.textContent;
    const log = JSON.parse(sessionStorage.getItem(KEY) || '[]');
    if (log[log.length - 1] !== value) { log.push(value); sessionStorage.setItem(KEY, JSON.stringify(log)); }
  };
  new MutationObserver(rec).observe(document, {subtree: true, childList: true, characterData: true});
})();
"""
