"""Wrappery ffprobe/ffmpeg: odczyt metadanych, konwersja do wersji roboczej, wycinanie klipów."""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app import config

log = logging.getLogger("video")


class FFmpegMissing(RuntimeError):
    pass


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str | None:
    return config.resolve_binary(config.FFMPEG_PATH)


def ffprobe_bin() -> str | None:
    return config.resolve_binary(config.FFPROBE_PATH)


def ffmpeg_available() -> bool:
    return ffmpeg_bin() is not None and ffprobe_bin() is not None


def _require() -> tuple[str, str]:
    ff, fp = ffmpeg_bin(), ffprobe_bin()
    if not ff or not fp:
        raise FFmpegMissing(config.FFMPEG_MISSING_MESSAGE)
    return ff, fp


def _parse_fraction(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    num, den = value.split("/", 1)
    try:
        return float(num) / float(den) if float(den) else None
    except ValueError:
        return None


def probe(path: Path) -> dict:
    """Zwraca {'duration', 'width', 'height', 'fps', 'has_audio'} z ffprobe."""
    _, ffprobe = _require()
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe: {proc.stderr.strip()[-500:]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFmpegError("Plik nie zawiera ścieżki wideo")
    duration = data.get("format", {}).get("duration") or video.get("duration")
    avg_fps, nominal_fps = _parse_fraction(video.get("avg_frame_rate")), _parse_fraction(video.get("r_frame_rate"))
    return {
        "duration": float(duration) if duration else None,
        # czas trwania samej ścieżki wideo (bez wpływu dłuższego audio, edit list ani start_time)
        "video_duration": float(video.get("duration") or duration or 0) or None,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": avg_fps or nominal_fps,
        # największa z deklarowanych liczb klatek (nagrania z telefonów bywają VFR: średnio 30, nominalnie 60)
        "max_fps": max(avg_fps or 0.0, nominal_fps or 0.0) or None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def build_transcode_command(ffmpeg: str, src: Path, dst: Path, src_fps: float | None = None,
                            preset: str = "veryfast") -> list[str]:
    """Wersja robocza: H.264/AAC, maks. 720p i 30 kl./s (niższej liczby klatek nie podnosimy),
    klatka kluczowa co sekundę, +faststart. `src_fps` to największa liczba klatek źródła."""
    filters = ["scale=-2:'min(720,ih)'"]
    if src_fps and src_fps > config.TRANSCODE_MAX_FPS + 0.5:
        filters.append(f"fps={config.TRANSCODE_MAX_FPS}")
    filters.append("format=yuv420p")
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", preset, "-crf", "23",
        "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        "-f", "mp4", str(dst),
    ]


def verify_tolerance(duration: float) -> float:
    """Dopuszczalna różnica czasu trwania: większa z VERIFY_MIN_SECONDS i VERIFY_RELATIVE długości."""
    return max(config.VERIFY_MIN_SECONDS, config.VERIFY_RELATIVE * duration)


def verify_conversion(source: dict, proxy: Path) -> dict:
    """Sprawdza wynik konwersji: wersja robocza ma ścieżkę wideo, a czas trwania jej ścieżki wideo
    zgadza się z oryginałem (porównujemy ścieżki wideo, nie formaty, bo nagrania z telefonów mają
    audio dłuższe od wideo, edit listy i start_time różny od 0). Ucięty wynik jest odrzucany.
    Zwraca probe wersji roboczej albo rzuca FFmpegError."""
    result = probe(proxy)  # rzuca FFmpegError bez ścieżki wideo
    expected, actual = source.get("video_duration"), result.get("video_duration")
    if not expected or not actual:
        raise FFmpegError("Nie udało się odczytać czasu trwania — wyniku nie można zweryfikować")
    if abs(actual - expected) > verify_tolerance(expected):
        raise FFmpegError(
            f"Czas trwania wideo wersji roboczej ({actual:.1f} s) różni się od oryginału "
            f"({expected:.1f} s)")
    return result


def build_cut_command(ffmpeg: str, src: Path, dst: Path, start: float, duration: float) -> list[str]:
    """Dokładne wycięcie z przekodowaniem (-ss przed -i + re-encode daje precyzję co do klatki)."""
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-f", "mp4", str(dst),
    ]


def _low_priority(cmd: list[str]) -> list[str]:
    """Polecenie uruchamiane z obniżonym priorytetem (nice), żeby konwersja nie dusiła strony."""
    nice = shutil.which("nice")
    return [nice, "-n", str(config.FFMPEG_NICE), *cmd] if nice and config.FFMPEG_NICE else cmd


_PROGRESS_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)$")
_OUT_TIME_RE = re.compile(r"^out_time_(?:us|ms)=(.*)$")
_POLL_SECONDS = 0.5


class FFmpegStalled(FFmpegError):
    """ffmpeg przestał zgłaszać postęp (albo przekroczył limit czasu) i został zabity."""


# Uruchomione teraz procesy ffmpeg (każdy we własnej grupie procesów) — worker zabija je przy SIGTERM.
_active: set[subprocess.Popen] = set()
_active_lock = threading.Lock()


def _kill_group(proc: subprocess.Popen) -> None:
    """Zabija cały proces razem z potomkami (grupa procesów; `nice` i ffmpeg nie zostają osierocone)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if proc.poll() is None:
            proc.kill()


def _reap(proc: subprocess.Popen) -> None:
    """Czeka na zakończenie zabitego procesu, ale nie dłużej niż chwilę (proces w stanie D, np. na
    zawieszonym dysku, nie reaguje nawet na SIGKILL — worker nie może przez to stanąć)."""
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        log.warning("Proces ffmpeg (pid %s) nie kończy się po SIGKILL — porzucony", proc.pid)


def terminate_active() -> None:
    """Zabija wszystkie trwające procesy ffmpeg (wywoływane przy zatrzymaniu workera)."""
    with _active_lock:
        procs = list(_active)
    for proc in procs:
        _kill_group(proc)


def _spawn(cmd: list[str]) -> subprocess.Popen:
    # Własna sesja = własna grupa procesów: można zabić cały ffmpeg jednym sygnałem, a Ctrl+C
    # w terminalu workera nie rozwala konwersji w pół drogi (zadanie wraca do kolejki przy starcie).
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    with _active_lock:
        _active.add(proc)
    return proc


def _release(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        _kill_group(proc)
    _reap(proc)
    with _active_lock:
        _active.discard(proc)
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


def _stall_text(seconds: float) -> str:
    return f"{seconds / 60:.0f} min" if seconds >= 60 else f"{seconds:.0f} s"


def _run_watched(cmd: list[str], stall: float, on_progress: Callable[[float], None] | None,
                 duration: float | None) -> tuple[int, str]:
    """Uruchamia ffmpeg z `-progress pipe:1` i pilnuje postępu. Zwraca (kod wyjścia, stderr).

    Stdout czyta osobny wątek (czytanie blokuje, a zawieszony ffmpeg może nic nie wypisać), a pętla
    w wątku wywołującym co chwilę sprawdza, kiedy ostatnio `out_time` się zmienił. Gdy minie `stall`
    sekund bez zmiany (albo bez żadnych danych), cała grupa procesów jest zabijana i rzucany
    `FFmpegStalled`. `on_progress` jest wołane w wątku wywołującym (sesja bazy nie jest wątkowo-bezpieczna)."""
    proc = _spawn(cmd)
    lines: queue.Queue[str | None] = queue.Queue()
    stderr_parts: list[str] = []

    def read_stdout() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                lines.put(line)
        except (ValueError, OSError):
            pass
        finally:
            lines.put(None)

    def read_stderr() -> None:
        try:
            for chunk in iter(lambda: proc.stderr.read(4096), ""):  # type: ignore[union-attr]
                stderr_parts.append(chunk)
        except (ValueError, OSError):
            pass

    threads = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        poll = max(0.05, min(_POLL_SECONDS, stall / 4)) if stall > 0 else _POLL_SECONDS
        last_change, last_value, eof = time.monotonic(), None, False
        while True:
            try:
                line = lines.get(timeout=poll)
            except queue.Empty:
                line = ""
            if line is None:
                eof = True
            elif line:
                text = line.strip()
                if (m := _OUT_TIME_RE.match(text)) and m.group(1) != last_value:
                    last_value, last_change = m.group(1), time.monotonic()
                if (m := _PROGRESS_RE.match(text)) and duration and on_progress:
                    # out_time_us i out_time_ms w ffmpeg są podawane w mikrosekundach
                    on_progress(min(0.99, int(m.group(1)) / 1_000_000 / duration))
            if eof and proc.poll() is not None:
                break
            if stall > 0 and time.monotonic() - last_change > stall:
                _kill_group(proc)
                _reap(proc)
                raise FFmpegStalled(
                    f"Konwersja przerwana: ffmpeg nie zgłosił postępu przez {_stall_text(stall)} "
                    "(proces zabity). Oryginał zostaje — można ponowić.")
        for thread in threads:
            thread.join(timeout=5)
        return proc.returncode, "".join(stderr_parts)
    finally:
        _release(proc)  # także przy wyjątku, SIGTERM workera i przerwaniu: nic nie zostaje w tle


def transcode_to_proxy(src: Path, dst: Path, duration: float | None,
                       on_progress: Callable[[float], None] | None = None,
                       src_fps: float | None = None, stall_seconds: float | None = None) -> None:
    """Konwertuje do wersji roboczej; zapisuje najpierw do pliku tymczasowego. Gdy ffmpeg przez
    `stall_seconds` (domyślnie `config.FFMPEG_STALL_SECONDS`) nie zgłosi postępu, jest zabijany
    i rzucany jest `FFmpegStalled`; plik tymczasowy znika w każdym przypadku błędu."""
    ffmpeg, _ = _require()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    stall = config.FFMPEG_STALL_SECONDS if stall_seconds is None else stall_seconds
    try:
        code, stderr = _run_watched(_low_priority(build_transcode_command(ffmpeg, src, tmp, src_fps)),
                                    stall, on_progress, duration)
        if code != 0:
            raise FFmpegError(f"ffmpeg: {stderr.strip()[-800:]}")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dst)


def cut_timeout(duration: float) -> float:
    """Limit czasu cięcia klipu o danej długości (s)."""
    return max(float(config.CUT_TIMEOUT_MIN_SECONDS), config.CUT_TIMEOUT_PER_CLIP_SECOND * duration)


def cut_clip(src: Path, dst: Path, start: float, duration: float, timeout: float | None = None) -> None:
    ffmpeg, _ = _require()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    limit = cut_timeout(duration) if timeout is None else timeout
    proc = _spawn(_low_priority(build_cut_command(ffmpeg, src, tmp, start, duration)))
    try:
        try:
            _, stderr = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise FFmpegStalled(f"Cięcie klipu przerwane: ffmpeg nie skończył w {_stall_text(limit)} "
                                "(proces zabity).") from None
        if proc.returncode != 0:
            raise FFmpegError(f"ffmpeg: {stderr.strip()[-800:]}")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        _release(proc)
    tmp.replace(dst)
