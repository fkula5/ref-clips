"""Jednorazowe czyszczenie metadanych w już wyciętych klipach (bez przekodowania obrazu).

Klipy sprzed wprowadzenia linków udostępniających mogą nieść metadane pliku źródłowego (tytuł,
lokalizację GPS, datę nagrania). Nowe klipy ich nie dostają (`video.STRIP_METADATA`). Uruchomienie na
serwerze, raz po wdrożeniu: `python -m app.strip_metadata` (idempotentne; plik podmieniany atomowo)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from app import config
from app.db import SessionLocal
from app.models import Clip
from app.storage import storage
from app.video import STRIP_METADATA


def strip_file(ffmpeg: str, path: Path) -> None:
    """Przepisuje kontener bez metadanych (`-c copy`); w razie błędu oryginał zostaje nietknięty."""
    tmp = path.with_name(path.stem + ".strip.mp4")
    try:
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
                        "-map", "0", "-c", "copy", *STRIP_METADATA, "-movflags", "+faststart",
                        "-f", "mp4", str(tmp)], check=True, capture_output=True, timeout=600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    ffmpeg = config.resolve_binary(config.FFMPEG_PATH)
    if not ffmpeg:
        print(config.FFMPEG_MISSING_MESSAGE, file=sys.stderr)
        return 1
    done = failed = 0
    with SessionLocal() as db:
        for clip_id, key in db.execute(select(Clip.id, Clip.clip_path).where(Clip.clip_path.is_not(None))):
            if not storage.exists(key):
                continue
            try:
                strip_file(ffmpeg, storage.local_path(key))
                done += 1
            except (subprocess.SubprocessError, OSError) as exc:
                failed += 1
                print(f"Klip {clip_id}: nie udało się wyczyścić metadanych ({exc.__class__.__name__})",
                      file=sys.stderr)
    print(f"Wyczyszczono metadane: {done}, błędy: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
