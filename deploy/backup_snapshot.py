"""Migawka kopii zapasowej ref-clips: spójna kopia bazy SQLite + klipy (twarde dowiązania do
niezmienionych plików z poprzedniej migawki, więc kolejne dni prawie nie zajmują miejsca).

Uruchamiana w kontenerze aplikacji przez deploy/backup.sh (tylko biblioteka standardowa):
    python - /data /backup 14 < deploy/backup_snapshot.py

Co jest kopiowane: baza (API kopii zapasowej SQLite — spójna przy działającej aplikacji, bez
instalowania sqlite3 na serwerze) i katalog `clips/`. Pełnych nagrań (`proxies/`), oryginałów
i niedokończonych uploadów (`uploads/`, `tmp/`) NIE kopiujemy — są tymczasowe.
Kolejność: najpierw baza, potem klipy; klip dodany w międzyczasie jest w kopii bez wiersza
w bazie (sprzątnie go zadanie cleanup), a odwrotna sytuacja (wiersz bez pliku) nie wystąpi.
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
    """Kopia przez API SQLite (nie zwykłe cp pliku, który przy WAL bywa niespójny)."""
    src = sqlite3.connect(source, timeout=60)  # tylko odczyt; plik istnieje (sprawdza snapshot)
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
    """Kopiuje klipy; plik taki sam jak w poprzedniej migawce (rozmiar i czas) tylko dowiązuje.
    Zwraca (liczba plików, skopiowane, dowiązane). Pomija niedokończone `*.part.mp4`."""
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
    """Tworzy migawkę `backup_root/RRRR-MM-DD` i zostawia `keep` najnowszych. Zwraca jej ścieżkę."""
    today = today or date.today()
    day = today.isoformat()
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        raise FileNotFoundError(f"Brak bazy: {db_path}")
    backup_root.mkdir(parents=True, exist_ok=True)

    final = backup_root / day
    work = backup_root / f".tmp-{day}-{os.getpid()}"
    for leftover in backup_root.glob(".tmp-*"):  # po przerwanym przebiegu
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
    if final.exists():  # drugi przebieg tego samego dnia zastępuje pierwszy
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
