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
        # duration of the video stream alone (unaffected by longer audio, edit lists or start_time)
        "video_duration": float(video.get("duration") or duration or 0) or None,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": avg_fps or nominal_fps,
        # the largest of the declared frame rates (phone recordings are often VFR: 30 average, 60
        # nominal)
        "max_fps": max(avg_fps or 0.0, nominal_fps or 0.0) or None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def build_transcode_command(ffmpeg: str, src: Path, dst: Path, src_fps: float | None = None,
                            preset: str = "veryfast") -> list[str]:
    """H.264/AAC, max 720p and 30 fps (a lower frame rate is not raised), keyframe every second,
    +faststart. `src_fps` is the source's largest frame rate.
    """
    filters = ["scale=-2:'min(720,ih)'"]
    if src_fps and src_fps > config.TRANSCODE_MAX_FPS + 0.5:
        filters.append(f"fps={config.TRANSCODE_MAX_FPS}")
    filters.append("format=yuv420p")
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?", *STRIP_METADATA,
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", preset, "-crf", "23",
        "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        "-f", "mp4", str(dst),
    ]


def verify_tolerance(duration: float) -> float:
    return max(config.VERIFY_MIN_SECONDS, config.VERIFY_RELATIVE * duration)


def verify_conversion(source: dict, proxy: Path) -> dict:
    """Compares video-track durations, not container formats, because phone recordings have audio longer
    than video, edit lists and a start_time other than 0. A truncated result is rejected. Returns the
    draft's probe or raises FFmpegError.
    """
    result = probe(proxy)
    expected, actual = source.get("video_duration"), result.get("video_duration")
    if not expected or not actual:
        raise FFmpegError("Nie udało się odczytać czasu trwania — wyniku nie można zweryfikować")
    if abs(actual - expected) > verify_tolerance(expected):
        raise FFmpegError(
            f"Czas trwania wideo wersji roboczej ({actual:.1f} s) różni się od oryginału "
            f"({expected:.1f} s)")
    return result


# Source metadata (title, GPS location, recording date, stream names) must not reach the results: clips
# can be shared by link without an account, so they may reveal nothing beyond picture and sound.
STRIP_METADATA = ["-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1",
                  "-map_chapters", "-1"]


def build_cut_command(ffmpeg: str, src: Path, dst: Path, start: float, duration: float) -> list[str]:
    """-ss before -i plus re-encode is frame-accurate"""
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?", *STRIP_METADATA,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-f", "mp4", str(dst),
    ]


def _low_priority(cmd: list[str]) -> list[str]:
    nice = shutil.which("nice")
    return [nice, "-n", str(config.FFMPEG_NICE), *cmd] if nice and config.FFMPEG_NICE else cmd


_PROGRESS_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)$")
_OUT_TIME_RE = re.compile(r"^out_time_(?:us|ms)=(.*)$")
_POLL_SECONDS = 0.5


class FFmpegStalled(FFmpegError):
    pass


# Running ffmpeg processes (each in its own process group); the worker kills them on SIGTERM.
_active: set[subprocess.Popen] = set()
_active_lock = threading.Lock()


def _kill_group(proc: subprocess.Popen) -> None:
    """Kills the whole process group, so `nice` and ffmpeg are not orphaned."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if proc.poll() is None:
            proc.kill()


def _reap(proc: subprocess.Popen) -> None:
    """A process in state D (e.g. on a hung disk) ignores even SIGKILL; the worker must not hang on it."""
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        log.warning("Proces ffmpeg (pid %s) nie kończy się po SIGKILL — porzucony", proc.pid)


def terminate_active() -> None:
    with _active_lock:
        procs = list(_active)
    for proc in procs:
        _kill_group(proc)


def _spawn(cmd: list[str]) -> subprocess.Popen:
    # Own session = own process group: ffmpeg can be killed with one signal, and Ctrl+C in the worker's
    # terminal does not break a conversion midway (the job returns to the queue at start).
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
    """Stdout is read by a separate thread (reads block and a hung ffmpeg may print nothing); the
    calling thread's loop checks when `out_time` last changed. After `stall` seconds without change
    (or without any data) the whole process group is killed and FFmpegStalled raised. `on_progress`
    is called in the calling thread (a DB session is not thread-safe).
    """
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
                    # out_time_us and out_time_ms are both in microseconds in ffmpeg
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
        _release(proc)  # also on exception, worker SIGTERM and interruption: nothing is left running


def transcode_to_proxy(src: Path, dst: Path, duration: float | None,
                       on_progress: Callable[[float], None] | None = None,
                       src_fps: float | None = None, stall_seconds: float | None = None) -> None:
    """Writes to a temp file first; it is removed on any error."""
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
