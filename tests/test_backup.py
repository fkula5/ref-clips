import importlib.util
import os
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "backup_snapshot.py"
spec = importlib.util.spec_from_file_location("backup_snapshot", SCRIPT)
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)


@pytest.fixture()
def data(tmp_path):
    root = tmp_path / "data"
    for sub in ("clips", "proxies", "uploads", "tmp"):
        (root / sub).mkdir(parents=True)
    con = sqlite3.connect(root / "ref-clips.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO t (v) VALUES ('jeden')")
    con.commit()
    con.close()
    (root / "clips" / "1_v1.mp4").write_bytes(b"klip1")
    (root / "clips" / "2_v1.mp4").write_bytes(b"klip22")
    (root / "clips" / "3_v1.part.mp4").write_bytes(b"niedokonczony")
    (root / "proxies" / "7.mp4").write_bytes(b"pelne nagranie")
    (root / "uploads" / "abc.part").write_bytes(b"upload")
    return root


def test_snapshot_contains_db_and_clips_only(data, tmp_path):
    out = snap.snapshot(data, tmp_path / "bk", keep=14, today=date(2026, 11, 6))
    assert out.name == "2026-11-06"
    assert sorted(p.name for p in out.iterdir()) == ["INFO.txt", "clips", "ref-clips.db"]
    assert sorted(p.name for p in (out / "clips").iterdir()) == ["1_v1.mp4", "2_v1.mp4"]
    con = sqlite3.connect(out / "ref-clips.db")
    assert con.execute("SELECT v FROM t").fetchall() == [("jeden",)]
    con.close()


def test_snapshot_consistent_while_database_is_being_written(data, tmp_path):
    stop = threading.Event()
    errors = []

    def writer():
        con = sqlite3.connect(data / "ref-clips.db", timeout=30)
        try:
            while not stop.is_set():
                con.execute("INSERT INTO t (v) VALUES (hex(randomblob(2000)))")
                con.commit()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            con.close()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        out = snap.snapshot(data, tmp_path / "bk", today=date(2026, 11, 6))
    finally:
        stop.set()
        thread.join()
    assert not errors
    con = sqlite3.connect(out / "ref-clips.db")
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_unchanged_clips_are_hardlinked_and_new_ones_copied(data, tmp_path):
    root = tmp_path / "bk"
    first = snap.snapshot(data, root, today=date(2026, 11, 5))
    (data / "clips" / "4_v1.mp4").write_bytes(b"nowy")
    second = snap.snapshot(data, root, today=date(2026, 11, 6))
    assert os.path.samefile(first / "clips" / "1_v1.mp4", second / "clips" / "1_v1.mp4")
    assert not os.path.samefile(first / "clips" / "1_v1.mp4", data / "clips" / "1_v1.mp4")
    assert (second / "clips" / "4_v1.mp4").read_bytes() == b"nowy"
    assert "skopiowane 1, dowiązane 2" in (second / "INFO.txt").read_text(encoding="utf-8")
    assert not (first / "clips" / "4_v1.mp4").exists()


def test_deleted_clip_disappears_from_next_snapshot(data, tmp_path):
    root = tmp_path / "bk"
    snap.snapshot(data, root, today=date(2026, 11, 5))
    (data / "clips" / "2_v1.mp4").unlink()
    second = snap.snapshot(data, root, today=date(2026, 11, 6))
    assert [p.name for p in (second / "clips").iterdir()] == ["1_v1.mp4"]


def test_retention_keeps_newest_snapshots(data, tmp_path):
    root = tmp_path / "bk"
    first_day = date(2026, 10, 1)
    for i in range(20):
        snap.snapshot(data, root, keep=14, today=first_day + timedelta(days=i))
    names = [p.name for p in snap.list_snapshots(root)]
    assert len(names) == 14
    assert names[0] == "2026-10-07" and names[-1] == "2026-10-20"
    assert (root / "2026-10-07" / "clips" / "1_v1.mp4").read_bytes() == b"klip1"


def test_second_run_same_day_replaces_snapshot(data, tmp_path):
    root = tmp_path / "bk"
    snap.snapshot(data, root, today=date(2026, 11, 6))
    (data / "clips" / "4_v1.mp4").write_bytes(b"nowy")
    out = snap.snapshot(data, root, today=date(2026, 11, 6))
    assert (out / "clips" / "4_v1.mp4").exists()
    assert [p.name for p in root.iterdir()] == ["2026-11-06"]


def test_failed_snapshot_leaves_previous_intact_and_no_temp(data, tmp_path):
    root = tmp_path / "bk"
    good = snap.snapshot(data, root, today=date(2026, 11, 5))
    (data / "ref-clips.db").write_bytes(b"to nie jest baza sqlite, tylko smieci" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        snap.snapshot(data, root, today=date(2026, 11, 6))
    assert [p.name for p in root.iterdir()] == [good.name]


def test_missing_database_is_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        snap.snapshot(tmp_path, tmp_path / "bk")


def test_scoresheet_files_are_copied_and_hardlinked(data, tmp_path):
    root = tmp_path / "bk"
    (data / "scoresheets").mkdir()
    (data / "scoresheets" / "a.pdf").write_bytes(b"%PDF-1.4")
    first = snap.snapshot(data, root, today=date(2026, 11, 5))
    (data / "scoresheets" / "b.png").write_bytes(b"png")
    second = snap.snapshot(data, root, today=date(2026, 11, 6))
    assert (first / "scoresheets" / "a.pdf").read_bytes() == b"%PDF-1.4"
    assert os.path.samefile(first / "scoresheets" / "a.pdf", second / "scoresheets" / "a.pdf")
    assert sorted(p.name for p in (second / "scoresheets").iterdir()) == ["a.pdf", "b.png"]
    assert "protokoły: 2" in (second / "INFO.txt").read_text(encoding="utf-8")
