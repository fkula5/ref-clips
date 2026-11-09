"""Czuwanie nad ffmpeg: zawieszona konwersja jest zabijana, zadanie kończy się błędem, kolejka rusza dalej.
Prawdziwego ffmpeg nie potrzeba — udaje go skrypt powłoki, który wypisuje postęp i milknie."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app import config, services, video as vid, worker
from app.models import Clip, Job, Video
from app.storage import storage
from tests.helpers import make_match, make_ready_video

# Zachowanie skryptu wybiera zmienna FAKE_MODE (dziedziczona przez nice -> ffmpeg).
# Potomek `sleep` zapisuje pid, żeby test sprawdził, że po zabiciu nic nie zostało w tle.
FAKE_FFMPEG = r"""#!/bin/sh
for a; do last=$a; done
sleep 600 & echo $! > "$FAKE_PIDFILE"
child=$!
case "$FAKE_MODE" in
  silent)    wait ;;
  stuck)     echo "partial" > "$last"; echo out_time_us=1000000; echo progress=continue; wait ;;
  spinning)  echo "partial" > "$last"
             while :; do echo out_time_us=2000000; echo progress=continue; sleep 0.1; done ;;
  slow_ok)   kill $child
             i=1
             while [ $i -le 8 ]; do echo out_time_us=$((i * 500000)); echo progress=continue; sleep 0.3; i=$((i + 1)); done
             echo "video" > "$last"; echo progress=end; exit 0 ;;
  hang_by_name) case "$*" in
                  *hang*) echo "partial" > "$last"; wait ;;
                  *) kill $child; echo out_time_us=500000; echo "video" > "$last"; echo progress=end; exit 0 ;;
                esac ;;
  fail)      kill $child; echo "boom: zepsuty plik" >&2; exit 1 ;;
esac
"""


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    script = tmp_path / "fake-ffmpeg.sh"
    script.write_text(FAKE_FFMPEG)
    script.chmod(0o755)
    pidfile = tmp_path / "child.pid"
    monkeypatch.setattr(vid, "ffmpeg_bin", lambda: str(script))
    monkeypatch.setattr(vid, "ffprobe_bin", lambda: str(script))
    monkeypatch.setenv("FAKE_PIDFILE", str(pidfile))

    class Fake:
        path = script
        pids = pidfile

        @staticmethod
        def mode(name):
            monkeypatch.setenv("FAKE_MODE", name)

        @staticmethod
        def child_pid() -> int | None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if pidfile.exists() and pidfile.read_text().strip():
                    return int(pidfile.read_text())
                time.sleep(0.05)
            return None

    yield Fake
    # sprzątanie na wypadek błędu testu: nic nie może zostać w tle
    vid.terminate_active()
    if pidfile.exists() and pidfile.read_text().strip():
        try:
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


def wait_dead(pid: int, seconds: float = 3) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


def transcode(tmp_path, **kw):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    dst = tmp_path / "out" / "proxy.mp4"
    started = time.monotonic()
    try:
        vid.transcode_to_proxy(src, dst, 10.0, **kw)
        error = None
    except vid.FFmpegError as exc:
        error = exc
    return dst, error, time.monotonic() - started


# --- konwersja: zawieszenia ------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["stuck", "silent", "spinning"])
def test_stalled_transcode_is_killed_with_clear_error(fake, tmp_path, mode):
    """Postęp i cisza, brak jakiegokolwiek wyjścia oraz ffmpeg wypisujący wciąż ten sam `out_time`."""
    fake.mode(mode)
    dst, error, elapsed = transcode(tmp_path, stall_seconds=1.0)
    assert isinstance(error, vid.FFmpegStalled)
    assert "nie zgłosił postępu" in str(error) and "można ponowić" in str(error)
    assert 0.9 < elapsed < 8, elapsed                      # nie przedwcześnie i nie w nieskończoność
    assert not dst.exists()
    assert not list(dst.parent.glob("*.part*"))            # plik tymczasowy posprzątany
    pid = fake.child_pid()
    assert pid is not None and wait_dead(pid), "po zabiciu został proces-sierota"
    assert not vid._active


def test_default_stall_threshold_comes_from_config(fake, tmp_path, monkeypatch):
    fake.mode("silent")
    monkeypatch.setattr(config, "FFMPEG_STALL_SECONDS", 1.0)
    _, error, elapsed = transcode(tmp_path)
    assert isinstance(error, vid.FFmpegStalled) and elapsed < 8


def test_normal_slow_transcode_is_not_a_false_alarm(fake, tmp_path):
    """Postęp rusza co 0,3 s przez ok. 2,5 s: dłużej niż próg 1 s, ale wciąż się zmienia."""
    fake.mode("slow_ok")
    seen = []
    dst, error, elapsed = transcode(tmp_path, stall_seconds=1.0, on_progress=seen.append)
    assert error is None and dst.read_text() == "video\n"
    assert elapsed > 2 and seen and seen == sorted(seen) and seen[-1] <= 0.99
    assert not list(dst.parent.glob("*.part*"))


def test_stall_watch_can_be_disabled(fake, tmp_path):
    fake.mode("slow_ok")
    dst, error, _ = transcode(tmp_path, stall_seconds=0)
    assert error is None and dst.exists()


def test_ordinary_ffmpeg_failure_still_reports_stderr(fake, tmp_path):
    fake.mode("fail")
    dst, error, _ = transcode(tmp_path, stall_seconds=5)
    assert type(error) is vid.FFmpegError and "boom: zepsuty plik" in str(error)
    assert not dst.exists() and not vid._active


# --- cięcie: zwykły limit czasu --------------------------------------------------------------
def test_cut_timeout_scales_with_clip_length():
    assert vid.cut_timeout(10) == config.CUT_TIMEOUT_MIN_SECONDS
    assert vid.cut_timeout(100) == 100 * config.CUT_TIMEOUT_PER_CLIP_SECOND


def test_hanging_cut_is_killed_after_timeout(fake, tmp_path):
    fake.mode("stuck")
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    dst = tmp_path / "clips" / "c.mp4"
    started = time.monotonic()
    with pytest.raises(vid.FFmpegStalled, match="Cięcie klipu przerwane"):
        vid.cut_clip(src, dst, 0, 5, timeout=1.0)
    assert time.monotonic() - started < 8
    assert not dst.exists() and not list(dst.parent.glob("*.part*"))
    pid = fake.child_pid()
    assert pid is not None and wait_dead(pid)


# --- zatrzymanie workera ---------------------------------------------------------------------
def test_terminate_active_kills_running_ffmpeg(fake, tmp_path):
    fake.mode("silent")
    import threading
    result = {}

    def run():
        result["dst"], result["error"], _ = transcode(tmp_path, stall_seconds=600)

    thread = threading.Thread(target=run)
    thread.start()
    pid = fake.child_pid()
    assert pid is not None
    vid.terminate_active()
    thread.join(10)
    assert not thread.is_alive() and isinstance(result["error"], vid.FFmpegError)
    assert wait_dead(pid)


def test_sigterm_to_worker_kills_ffmpeg(fake, tmp_path):
    """Prawdziwy SIGTERM do procesu z handlerem workera: ffmpeg i jego potomek znikają."""
    fake.mode("silent")
    data = tmp_path / "data"
    data.mkdir()
    code = (
        "import signal, sys\n"
        "from pathlib import Path\n"
        "from app import video as vid, worker\n"
        f"vid.ffmpeg_bin = vid.ffprobe_bin = lambda: {str(fake.path)!r}\n"
        "signal.signal(signal.SIGTERM, worker._on_sigterm)\n"
        f"src = Path({str(tmp_path / 'in.mp4')!r}); src.write_bytes(b'x')\n"
        f"vid.transcode_to_proxy(src, Path({str(tmp_path / 'o' / 'p.mp4')!r}), 10.0, stall_seconds=600)\n"
    )
    env = {**os.environ, "REFCLIPS_DATA_DIR": str(data), "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    proc = subprocess.Popen([sys.executable, "-c", code], env=env)
    try:
        pid = fake.child_pid()
        assert pid is not None and alive(pid)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 128 + signal.SIGTERM
        assert wait_dead(pid), "ffmpeg przeżył SIGTERM workera"
    finally:
        if proc.poll() is None:
            proc.kill()


# --- worker: błąd zadania i kolejne zadanie ----------------------------------------------------
def _queue_transcode(db, match, name):
    key = f"uploads/{name}.mp4"
    storage.local_path(key).parent.mkdir(parents=True, exist_ok=True)
    storage.local_path(key).write_bytes(b"x")
    video = Video(match_id=match.id, label=name, status="queued", original_path=key)
    db.add(video)
    db.flush()
    services.enqueue(db, "transcode", video_id=video.id)
    db.commit()
    return video


@pytest.fixture()
def stubbed_probe(monkeypatch):
    monkeypatch.setattr(vid, "probe", lambda path: {"duration": 10.0, "video_duration": 10.0, "fps": 25,
                                                    "max_fps": 25, "width": 1, "height": 1})
    monkeypatch.setattr(vid, "verify_conversion", lambda info, proxy: info)
    monkeypatch.setattr(vid, "ffmpeg_available", lambda: True)


def test_worker_records_stall_error_and_takes_next_job(db, fake, stubbed_probe, monkeypatch):
    fake.mode("hang_by_name")
    monkeypatch.setattr(config, "FFMPEG_STALL_SECONDS", 1.0)
    match = make_match(db)
    hung = _queue_transcode(db, match, "hang")
    good = _queue_transcode(db, match, "good")

    assert worker.run_once() is True                       # pierwsze zadanie: zawieszone
    db.expire_all()
    assert hung.status == "error" and "nie zgłosił postępu" in hung.error
    job = db.scalars(select(Job).where(Job.video_id == hung.id)).one()
    assert job.status == "error" and job.error == hung.error and job.finished_at is not None
    assert not list(storage.local_path("proxies").glob("*.part*"))
    assert good.status == "queued"                         # drugie jeszcze czeka

    assert worker.run_once() is True                       # worker wziął kolejne zadanie
    db.expire_all()
    assert good.status == "ready" and good.proxy_path
    assert hung.status == "error" and not vid._active


def test_worker_marks_hanging_cut_as_error(db, fake, monkeypatch):
    fake.mode("stuck")
    monkeypatch.setattr(vid, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(config, "CUT_TIMEOUT_MIN_SECONDS", 1)
    monkeypatch.setattr(config, "CUT_TIMEOUT_PER_CLIP_SECOND", 0)
    match = make_match(db)
    video = make_ready_video(db, match)
    clip = services.create_clip(db, video, None, time_sec=30)
    db.commit()
    assert worker.run_once() is True
    db.expire_all()
    clip = db.get(Clip, clip.id)
    assert clip.status == "error" and "Cięcie klipu przerwane" in clip.error
    assert not list(storage.local_path("clips").glob("*.part*"))
    pid = fake.child_pid()
    assert pid is not None and wait_dead(pid)
