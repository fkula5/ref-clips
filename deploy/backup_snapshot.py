"""Consistent copy of the SQLite DB plus the clips (hard links to files unchanged since the previous
snapshot, so extra days take almost no space).
Run in the app container by deploy/backup.sh (standard library only):
    python - /data /backup 14 < deploy/backup_snapshot.py
Full recordings (`proxies/`), originals and unfinished uploads (`uploads/`, `tmp/`) are NOT copied:
they are temporary. Order: DB first, then clips; a clip added meanwhile is in the copy without a DB
row (the cleanup task removes it), while the reverse (row without file) cannot happen.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

DB_NAME = "ref-clips.db"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def backup_database(source: Path, target: Path) -> None:
    """SQLite backup API, not a plain cp: a WAL database copied that way can be inconsistent."""
    src = sqlite3.connect(source, timeout=60)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Kopia bazy nie przeszła integrity_check: {result}")
    finally:
        dst.close()
        src.close()


def copy_clips(source: Path, target: Path, previous: Path | None) -> tuple[int, int, int]:
    """A file identical to the previous snapshot (size and mtime) is only hard-linked. Skips unfinished
    `*.part.mp4`.
    """
    target.mkdir(parents=True, exist_ok=True)
    total = copied = linked = 0
    if not source.is_dir():
        return total, copied, linked
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_dir():
            (target / rel).mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file() or path.name.endswith(".part.mp4"):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        stat = path.stat()
        total += 1
        old = previous / "clips" / rel if previous else None
        if old is not None and old.is_file():
            old_stat = old.stat()
            if old_stat.st_size == stat.st_size and old_stat.st_mtime_ns == stat.st_mtime_ns:
                os.link(old, dest)
                linked += 1
                continue
        shutil.copy2(path, dest)
        copied += 1
    return total, copied, linked


def list_snapshots(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and DAY_RE.match(p.name))


def snapshot(data_dir: Path, backup_root: Path, keep: int = 14, today: date | None = None) -> Path:
    today = today or date.today()
    day = today.isoformat()
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        raise FileNotFoundError(f"Brak bazy: {db_path}")
    backup_root.mkdir(parents=True, exist_ok=True)

    final = backup_root / day
    work = backup_root / f".tmp-{day}-{os.getpid()}"
    for leftover in backup_root.glob(".tmp-*"):  # left over from an interrupted run
        shutil.rmtree(leftover, ignore_errors=True)
    previous = next((p for p in reversed(list_snapshots(backup_root)) if p.name != day), None)
    work.mkdir()
    try:
        backup_database(db_path, work / DB_NAME)
        total, copied, linked = copy_clips(data_dir / "clips", work / "clips", previous)
        (work / "INFO.txt").write_text(
            f"data: {day}\nbaza: {(work / DB_NAME).stat().st_size} B\n"
            f"klipy: {total} (skopiowane {copied}, dowiązane {linked})\n"
            f"poprzednia migawka: {previous.name if previous else '-'}\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if final.exists():  # a second run on the same day replaces the first
        old = backup_root / f".old-{day}-{os.getpid()}"
        final.rename(old)
        work.rename(final)
        shutil.rmtree(old, ignore_errors=True)
    else:
        work.rename(final)

    for stale in list_snapshots(backup_root)[:-keep] if keep > 0 else []:
        shutil.rmtree(stale)
    return final


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("Użycie: python - KATALOG_DANYCH KATALOG_KOPII [LICZBA_MIGAWEK]", file=sys.stderr)
        return 2
    keep = int(argv[2]) if len(argv) == 3 else 14
    final = snapshot(Path(argv[0]), Path(argv[1]), keep)
    print((final / "INFO.txt").read_text(encoding="utf-8"), end="")
    print(f"Kopia gotowa: {final.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
