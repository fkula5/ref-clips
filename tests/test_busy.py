from datetime import timedelta

from app import busy
from app.models import Clip, Job, UploadSession, Video
from app.timeutil import utcnow
from tests.helpers import make_match, make_ready_video

GB = busy.GB


def _upload(db, user, *, offset, size=2 * GB, minutes_ago=1, name="IMG_2056.MOV", uid="u1"):
    db.add(UploadSession(id=uid, user_id=user.id, filename=name, size_bytes=size, offset_bytes=offset,
                         reserved_bytes=size, updated_at=utcnow() - timedelta(minutes=minutes_ago)))
    db.commit()


def test_empty_database_is_idle(db):
    assert busy.busy_items(db) == []


def test_active_upload_blocks_with_a_description(db, admin):
    _upload(db, admin[1], offset=int(1.6 * GB), size=int(2.7 * GB), minutes_ago=2)
    assert busy.busy_items(db) == [
        "upload IMG_2056.MOV — 1,6 GB/2,7 GB, ostatnia aktywność 2 min temu"]


def test_upload_without_activity_does_not_block_but_is_counted(db, admin):
    _upload(db, admin[1], offset=GB, minutes_ago=30)
    assert busy.busy_items(db) == []
    assert busy.idle_uploads(db) == 1


def test_finished_upload_does_not_block(db, admin):
    _upload(db, admin[1], offset=2 * GB, size=2 * GB)
    assert busy.busy_items(db) == []


def test_upload_just_before_the_threshold(db, admin):
    _upload(db, admin[1], offset=100, size=1000, minutes_ago=busy.ACTIVE_UPLOAD_MINUTES - 1)
    assert len(busy.busy_items(db)) == 1
    assert "100 B" not in busy.busy_items(db)[0]


def test_running_conversion_with_progress(db, admin):
    match = make_match(db)
    video = Video(match_id=match.id, label="Całość", status="processing", original_filename="mecz.mp4")
    db.add(video)
    db.commit()
    db.add(Job(type="transcode", status="running", progress=0.43, video_id=video.id))
    db.commit()
    assert busy.busy_items(db) == [f"konwersja nagrania #{video.id} (mecz.mp4) — 43%"]


def test_queued_jobs_are_counted(db, admin):
    match = make_match(db)
    v1 = Video(match_id=match.id, status="queued")
    v2 = Video(match_id=match.id, status="queued")
    db.add_all([v1, v2])
    db.commit()
    db.add_all([Job(type="transcode", status="pending", video_id=v1.id),
                Job(type="transcode", status="pending", video_id=v2.id)])
    db.commit()
    assert busy.busy_items(db) == ["w kolejce: 2 zadania (konwersja ×2)"]


def test_finished_and_failed_jobs_do_not_block(db, admin):
    match = make_match(db)
    video = Video(match_id=match.id, status="error")
    db.add(video)
    db.commit()
    db.add_all([Job(type="transcode", status="done", video_id=video.id),
                Job(type="transcode", status="error", video_id=video.id)])
    db.commit()
    assert busy.busy_items(db) == []


def test_cut_of_an_errored_or_deleted_recording_does_not_block(db, admin):
    match = make_match(db)
    video = make_ready_video(db, match)
    clip = Clip(match_id=match.id, video_id=video.id, time_sec=10.0, status="new")
    db.add(clip)
    db.commit()
    db.add(Job(type="cut", status="pending", clip_id=clip.id))
    db.commit()
    assert busy.busy_items(db) == ["w kolejce: 1 zadanie (wycinanie klipu ×1)"]
    video.status = "error"
    db.commit()
    assert busy.busy_items(db) == []
    video.status, video.purged_at = "ready", utcnow()
    db.commit()
    assert busy.busy_items(db) == []


def test_cli_exit_codes_and_messages(db, admin, capsys):
    assert busy.main() == 0
    assert "Wolne" in capsys.readouterr().out
    _upload(db, admin[1], offset=GB, minutes_ago=0)
    assert busy.main() == 1
    out = capsys.readouterr().out
    assert out.startswith("ZAJĘTE") and "IMG_2056.MOV" in out and "przed chwilą" in out


def test_cli_database_error_is_code_2(db, monkeypatch, capsys):
    def boom():
        raise RuntimeError("baza niedostępna")
    monkeypatch.setattr(busy, "SessionLocal", boom)
    assert busy.main() == 2
    assert "BŁĄD" in capsys.readouterr().err


def test_job_noun_inflection():
    assert [busy._zadan(n) for n in (1, 2, 5, 12, 22)] == ["zadanie", "zadania", "zadań", "zadań", "zadania"]
