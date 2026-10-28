"""Wrappery ffprobe/ffmpeg: odczyt metadanych, konwersja do wersji roboczej, wycinanie klipów."""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from app import config


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
    return {
        "duration": float(duration) if duration else None,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _parse_fraction(video.get("avg_frame_rate")) or _parse_fraction(video.get("r_frame_rate")),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def build_transcode_command(ffmpeg: str, src: Path, dst: Path) -> list[str]:
    """Wersja robocza: H.264/AAC, maks. 720p, klatka kluczowa co sekundę, +faststart."""
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=-2:'min(720,ih)',format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        "-f", "mp4", str(dst),
    ]


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


_PROGRESS_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)$")


def transcode_to_proxy(src: Path, dst: Path, duration: float | None,
                       on_progress: Callable[[float], None] | None = None) -> None:
    """Konwertuje do wersji roboczej; zapisuje najpierw do pliku tymczasowego."""
    ffmpeg, _ = _require()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        build_transcode_command(ffmpeg, src, tmp),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        m = _PROGRESS_RE.match(line.strip())
        if m and duration and on_progress:
            # out_time_us i out_time_ms w ffmpeg są podawane w mikrosekundach
            on_progress(min(0.99, int(m.group(1)) / 1_000_000 / duration))
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise FFmpegError(f"ffmpeg: {stderr.strip()[-800:]}")
    tmp.replace(dst)


def cut_clip(src: Path, dst: Path, start: float, duration: float) -> None:
    ffmpeg, _ = _require()
    tmp = dst.with_name(dst.stem + ".part.mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(build_cut_command(ffmpeg, src, tmp, start, duration),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise FFmpegError(f"ffmpeg: {proc.stderr.strip()[-800:]}")
    tmp.replace(dst)
