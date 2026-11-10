import os
import time
from datetime import timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app import config, retention, services, worker
from app.models import Clip, Job, Setting, Video
from app.storage import storage
from app.timeutil import utcnow
from tests.helpers import make_match, make_ready_video, mark_periods


def ready(db, *, expires_in_days=-1.0, match=None, **kw):
    video = make_ready_video(db, match or make_match(db))
    video.expires_at = utcnow() + timedelta(days=expires_in_days)
    for field, value in kw.items():
        setattr(video, field, value)
    db.commit()
    return video


def clip_for(db, video, status="cut", **kw):
    clip = Clip(match_id=video.match_id, video_id=video.id, time_sec=50, status=status, **kw)
    db.add(clip)
    db.commit()
    return clip


def fresh(db, model, id_):
    db.expire_all()
    return db.get(model, id_)


def test_retention_page_shows_setting_and_default(client, db):
    page = client.get("/admin/retention").text
    assert 'name="days"' in page and 'value="30"' in page and "przelicz termin" in page


@pytest.mark.parametrize("raw", ["0", "366", "-5", "abc", "", "1.5", "99999999999999999999"])
def test_retention_days_validation(client, db, raw):
    r = client.post("/admin/retention", data={"days": raw})
    assert r.status_code == 422 and "Liczba dni retencji" in r.text
    assert services.retention_days(db) == 30


def test_retention_days_bounds_accepted(client, db):
    for value in ("1", "365", " 14 "):
        assert client.post("/admin/retention", data={"days": value}).status_code == 200
    assert services.retention_days(db) == 14


def test_changing_days_does_not_touch_existing_videos_by_default(client, db):
    video = ready(db, expires_in_days=20)
    before = video.expires_at
    r = client.post("/admin/retention", data={"days": "5"})
    assert r.status_code == 200 and "dotyczy nowych nagrań" in r.text
    assert fresh(db, Video, video.id).expires_at == before
    assert services.retention_days(db) == 5
    assert timedelta(days=4, hours=23) < services.video_expiry(db) - utcnow() <= timedelta(days=5)


def test_recalculate_sets_upload_date_plus_days(client, db):
    old = ready(db, expires_in_days=25)
    old.created_at = utcnow() - timedelta(days=10)
    purged = ready(db, expires_in_days=25)
    purged.purged_at = utcnow()
    purged_expiry = purged.expires_at
    db.commit()
    r = client.post("/admin/retention", data={"days": "7", "recalculate": "1"})
    assert r.status_code == 200 and "Przeliczono termin 1 istniejących" in r.text
    old = fresh(db, Video, old.id)
    assert old.expires_at == old.created_at + timedelta(days=7)
    assert fresh(db, Video, purged.id).expires_at == purged_expiry
    old.created_at = utcnow() - timedelta(days=40)
    db.commit()
    r = client.post("/admin/retention", data={"days": "7", "recalculate": "1"})
    assert "1 jest już po nowym terminie" in r.text


def test_run_retention_removes_expired_draft_and_keeps_clips(db):
    video = ready(db, expires_in_days=-1)
    key = video.proxy_path
    clip_key = "clips/9_v1.mp4"
    with storage.open_write(clip_key) as fh:
        fh.write(b"klip")
    clip = clip_for(db, video, clip_path=clip_key)
    result = retention.run_retention(db)
    assert result.purged == [video.id] and not result.skipped
    video = fresh(db, Video, video.id)
    assert video.purged_at is not None and video.proxy_path is None and not storage.exists(key)
    assert storage.exists(clip_key) and fresh(db, Clip, clip.id).clip_path == clip_key


def test_run_retention_leaves_videos_before_deadline_and_without_deadline(db):
    future = ready(db, expires_in_days=3)
    none = ready(db)
    none.expires_at = None
    db.commit()
    assert retention.run_retention(db).purged == []
    assert fresh(db, Video, future.id).purged_at is None and fresh(db, Video, none.id).purged_at is None
    assert storage.exists(future.proxy_path)


def test_run_retention_skips_videos_in_conversion_and_with_pending_cuts(db):
    converting = ready(db, status="processing", original_path="uploads/x.mp4")
    queued_clip = ready(db)
    clip_for(db, queued_clip, status="queued")
    new_clip = ready(db)
    clip_for(db, new_clip, status="new")
    cut_ok = ready(db)
    clip_for(db, cut_ok, status="cut")
    failed_clip = ready(db)
    clip_for(db, failed_clip, status="error")
    result = retention.run_retention(db)
    assert sorted(result.purged) == sorted([cut_ok.id, failed_clip.id])
    assert {v for v, _ in result.skipped} == {converting.id, queued_clip.id, new_clip.id}
    for video in (converting, queued_clip, new_clip):
        assert fresh(db, Video, video.id).purged_at is None
    assert storage.exists(queued_clip.proxy_path)
    clip = db.query(Clip).filter_by(video_id=queued_clip.id).one()
    clip.status = "cut"
    db.commit()
    assert retention.run_retention(db).purged == [queued_clip.id]


def test_run_retention_is_idempotent(db):
    video = ready(db, expires_in_days=-1)
    first = retention.run_retention(db)
    stamp = fresh(db, Video, video.id).purged_at
    second = retention.run_retention(db)
    assert first.purged == [video.id] and second.purged == [] and not second.skipped
    assert fresh(db, Video, video.id).purged_at == stamp


def test_run_retention_purges_failed_video_with_leftover_original_and_fails_stuck_clips(db):
    video = ready(db, status="error", original_path="uploads/zly.mp4")
    video.proxy_path = None
    with storage.open_write("uploads/zly.mp4") as fh:
        fh.write(b"oryginal")
    clip = clip_for(db, video, status="queued")
    db.add(Job(type="cut", status="pending", video_id=video.id, clip_id=clip.id))
    db.commit()
    assert retention.run_retention(db).purged == [video.id]
    assert not storage.exists("uploads/zly.mp4")
    clip = fresh(db, Clip, clip.id)
    assert clip.status == "error" and "usunięte przed wycięciem" in clip.error
    assert db.query(Job).one().status == "error"


def test_run_if_due_runs_once_per_interval_and_not_after_restart(db):
    video = ready(db, expires_in_days=-1)
    now = utcnow()
    first = retention.run_if_due(db, now)
    assert first is not None and first.purged == [video.id]
    assert db.get(Setting, retention.LAST_RUN_KEY).value == now.strftime(retention.TIME_FORMAT)
    late = ready(db, expires_in_days=-1)
    assert retention.run_if_due(db, now + timedelta(hours=1)) is None
    assert retention.run_if_due(db, now + timedelta(hours=23, minutes=59)) is None
    assert fresh(db, Video, late.id).purged_at is None
    again = retention.run_if_due(db, now + timedelta(hours=24, seconds=1))
    assert again.purged == [late.id]
    when, summary = retention.last_run(db)
    assert when is not None and summary == "usunięto: 1"


def test_run_if_due_is_atomic_between_two_workers(db):
    ready(db, expires_in_days=-1)
    now = utcnow()
    assert retention.run_if_due(db, now) is not None
    assert retention.run_if_due(db, now) is None


def test_worker_maintenance_runs_retention_and_survives_failures(db, monkeypatch):
    video = ready(db, expires_in_days=-1)
    worker.run_maintenance()
    assert fresh(db, Video, video.id).purged_at is not None
    monkeypatch.setattr(worker.uploads, "cleanup_stale", lambda db: 1 / 0)
    other = ready(db, expires_in_days=-1)
    db.get(Setting, retention.LAST_RUN_KEY).value = ""
    db.commit()
    worker.run_maintenance()
    assert fresh(db, Video, other.id).purged_at is not None


def test_cut_job_for_purged_video_fails_with_clear_message(db):
    video = ready(db, expires_in_days=-1)
    clip = clip_for(db, video, status="queued")
    video.purged_at, video.proxy_path = utcnow(), None
    job = Job(type="cut", status="pending", video_id=video.id, clip_id=clip.id)
    db.add(job)
    db.commit()
    with pytest.raises(FileNotFoundError):
        worker.run_cut(db, job)
    worker.process_job(db, job)
    assert fresh(db, Clip, clip.id).status == "error" and "usunięte" in fresh(db, Clip, clip.id).error


def test_purge_commit_failure_keeps_files_and_video_untouched(db, monkeypatch):
    video = ready(db, expires_in_days=-1)
    key = video.proxy_path
    clip = clip_for(db, video, status="cut")
    db.expire_all()
    video = db.get(Video, video.id)

    def broken_commit():
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(db, "commit", broken_commit)
    with pytest.raises(OperationalError):
        retention.purge_video(db, video)
    monkeypatch.undo()
    assert storage.exists(key)
    video = fresh(db, Video, video.id)
    assert video.purged_at is None and video.proxy_path == key and fresh(db, Clip, clip.id).status == "cut"


def test_run_retention_skips_video_when_commit_fails_and_retries_later(db, monkeypatch):
    first, second = ready(db, expires_in_days=-2), ready(db, expires_in_days=-1)
    first_key, second_key = first.proxy_path, second.proxy_path
    real_commit, calls = db.commit, []

    def flaky_commit():
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    result = retention.run_retention(db)
    monkeypatch.undo()
    assert result.purged == [second.id] and [v for v, _ in result.skipped] == [first.id]
    assert storage.exists(first_key) and not storage.exists(second_key)
    assert retention.run_retention(db).purged == [first.id]


def test_purge_file_delete_failure_is_only_a_warning_and_orphan_is_cleaned_later(db, monkeypatch, caplog):
    video = ready(db, expires_in_days=-1)
    key = video.proxy_path
    real_delete = storage.delete

    def broken_delete(k):
        raise PermissionError("brak uprawnień")

    monkeypatch.setattr(storage, "delete", broken_delete)
    with caplog.at_level("WARNING", logger="retention"):
        result = retention.run_retention(db)
    monkeypatch.setattr(storage, "delete", real_delete)
    assert result.purged == [video.id] and not result.skipped
    assert any("Nie udało się usunąć pliku" in r.message for r in caplog.records)
    video = fresh(db, Video, video.id)
    assert video.purged_at is not None and video.proxy_path is None and video.proxy_bytes is None
    assert storage.exists(key)
    # a fresh orphan stays (it may be in use), an old one goes
    assert retention.cleanup_orphan_videos(db) == 0
    old = time.time() - config.ORPHAN_MIN_AGE_SECONDS - 60
    os.utime(storage.local_path(key), (old, old))
    assert retention.cleanup_orphan_videos(db) == 1 and not storage.exists(key)


def test_manual_purge_route_survives_file_delete_failure(client, db, monkeypatch):
    video = ready(db, expires_in_days=20)
    monkeypatch.setattr(storage, "delete", lambda k: (_ for _ in ()).throw(OSError("dysk")))
    r = client.post(f"/admin/videos/{video.id}/purge", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/retention"
    assert fresh(db, Video, video.id).purged_at is not None


def test_manual_purge_removes_draft_and_keeps_clips(client, db):
    video = ready(db, expires_in_days=20)
    key = video.proxy_path
    clip = clip_for(db, video)
    page = client.get("/admin/retention").text
    assert "Usuń pełne nagranie teraz" in page and f'action="/admin/videos/{video.id}/purge"' in page
    r = client.post(f"/admin/videos/{video.id}/purge")
    assert r.status_code == 200 and "Usunięto pełne nagranie" in r.text and "Klipy zostają" in r.text
    video = fresh(db, Video, video.id)
    assert video.purged_at is not None and video.proxy_path is None and not storage.exists(key)
    assert fresh(db, Clip, clip.id) is not None
    assert f'action="/admin/videos/{video.id}/purge"' not in client.get("/admin/retention").text
    r = client.post(f"/admin/videos/{video.id}/purge")
    assert r.status_code == 409 and "już usunięte" in r.text
    assert client.post("/admin/videos/9999/purge").status_code == 404


def test_manual_purge_refused_during_conversion_and_with_pending_cuts(client, db):
    converting = ready(db, status="processing", original_path="uploads/a.mp4")
    waiting = ready(db)
    clip_for(db, waiting, status="queued")
    clip_for(db, waiting, status="new")
    r = client.post(f"/admin/videos/{converting.id}/purge")
    assert r.status_code == 409 and "konwertowane" in r.text
    r = client.post(f"/admin/videos/{waiting.id}/purge")
    assert r.status_code == 409 and "2 klipy czekają na wycięcie" in r.text
    for video in (converting, waiting):
        assert fresh(db, Video, video.id).purged_at is None
    assert storage.exists(waiting.proxy_path)
    page = client.get("/admin/retention").text
    assert f'action="/admin/videos/{waiting.id}/purge"' not in page and "nie teraz" in page


def test_retention_admin_posts_redirect_and_flash_once(client, db):
    video = ready(db, expires_in_days=20)
    r = client.post("/admin/retention", data={"days": "14"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/retention"
    page = client.get("/admin/retention").text
    assert 'id="admin-notice"' in page and "14 dni" in page
    assert 'id="admin-notice"' not in client.get("/admin/retention").text
    assert services.retention_days(db) == 14
    r = client.post(f"/admin/videos/{video.id}/purge", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/retention"
    assert "Usunięto pełne nagranie" in client.get("/admin/retention").text
    r = client.post("/admin/retention", data={"days": "0"}, follow_redirects=False)
    assert r.status_code == 422 and 'value="0"' in r.text
    r = client.post(f"/admin/videos/{video.id}/purge", follow_redirects=False)
    assert r.status_code == 409


def test_write_routes_on_purged_video_return_clear_errors(client, db):
    video = mark_periods(db, ready(db))
    mark = video.marks[0]
    clip = clip_for(db, video, status="cut")
    assert client.post(f"/admin/videos/{video.id}/purge").status_code == 200
    expected = [
        client.post(f"/api/videos/{video.id}/markers", json={"time_sec": 5}),
        client.post(f"/api/videos/{video.id}/markers/undo"),
        client.post(f"/api/videos/{video.id}/quick-clip", json={"time_sec": 5, "text": "x"}),
        client.post(f"/api/videos/{video.id}/marks", json={"time_sec": 5}),
        client.delete(f"/api/marks/{mark.id}"),
        client.get(f"/videos/{video.id}/notes"),
        client.post(f"/videos/{video.id}/notes/preview", data={"text": "1:00 CC kroki"}),
        client.post(f"/videos/{video.id}/notes/commit", data={"count": "0"}),
        client.get(f"/videos/{video.id}/stream"),
        client.post(f"/clips/{clip.id}/recut"),
    ]
    for r in expected:
        assert r.status_code == 409, (r.request.method, r.request.url, r.status_code, r.text[:100])
        assert "usunięte" in r.text or "nie ma już" in r.text, r.text[:200]
    assert fresh(db, Clip, clip.id) is not None and len(fresh(db, Video, video.id).marks) == 4
    page = client.get(f"/videos/{video.id}").text
    assert 'id="purged-banner"' in page and "<video" not in page
    edit = client.get(f"/videos/{video.id}/edit").text
    assert "zamrożone" in edit and "content_kind" not in edit
    r = client.post(f"/videos/{video.id}/update", data={"label": "Nowa", "content_kind": "Q1"}, follow_redirects=False)
    assert r.status_code == 303
    video = fresh(db, Video, video.id)
    assert video.label == "Nowa" and video.content == "full" and len(video.marks) == 4


def test_clip_of_purged_video_still_plays_and_can_be_described(client, db):
    video = ready(db)
    clip_key = "clips/1_v1.mp4"
    with storage.open_write(clip_key) as fh:
        fh.write(b"klip")
    clip = clip_for(db, video, clip_path=clip_key, clip_version=1)
    client.post(f"/admin/videos/{video.id}/purge")
    assert client.get(f"/clips/{clip.id}/file").status_code == 200
    page = client.get(f"/clips/{clip.id}").text
    assert "kwarta nieustalona" in page and "klipu nie można opisać" not in page
    official = db.query(Clip).get(clip.id).match.official("CC")
    r = client.post(f"/clips/{clip.id}/update", data={"official": str(official.id), "category_id": "1"}, follow_redirects=False)
    assert r.status_code == 303 and fresh(db, Clip, clip.id).is_described


def write_clip_file(key, age_seconds=0):
    with storage.open_write(key) as fh:
        fh.write(b"x" * 10)
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(storage.local_path(key), (old, old))


def test_orphan_clip_files_are_removed_only_when_old_and_unused(db):
    video = ready(db)
    used = clip_for(db, video, clip_path="clips/1_v2.mp4")
    write_clip_file("clips/1_v2.mp4", age_seconds=7200)  # used, old: stays
    write_clip_file("clips/1_v1.mp4", age_seconds=7200)  # an old version of a clip that already has v2: orphan
    write_clip_file("clips/77_v1.mp4", age_seconds=7200)  # a clip without a DB row
    write_clip_file("clips/5_v1.part.mp4", age_seconds=7200)  # unfinished cut
    write_clip_file("clips/88_v1.mp4", age_seconds=60)  # fresh (the cut is still writing the path): stays
    write_clip_file("clips/notatka.txt", age_seconds=7200)  # not a clip file: stays
    assert retention.cleanup_orphan_clips(db) == 3
    assert storage.exists("clips/1_v2.mp4") and storage.exists("clips/88_v1.mp4") and storage.exists("clips/notatka.txt")
    assert not storage.exists("clips/1_v1.mp4") and not storage.exists("clips/77_v1.mp4")
    assert not storage.exists("clips/5_v1.part.mp4")
    assert retention.cleanup_orphan_clips(db) == 0
    assert fresh(db, Clip, used.id).clip_path == "clips/1_v2.mp4"


def test_maintenance_cleans_orphan_clip_files(db):
    write_clip_file("clips/123_v1.mp4", age_seconds=config.ORPHAN_MIN_AGE_SECONDS + 60)
    worker.run_maintenance()
    assert not storage.exists("clips/123_v1.mp4")


def test_orphan_video_files_are_removed_only_when_old_unused_and_not_converting(db):
    old_age = config.ORPHAN_MIN_AGE_SECONDS + 600
    ok = ready(db, original_path="uploads/1_zachowany.mp4")  # files known to the DB
    ok.proxy_path = "proxies/1.mp4"
    converting = ready(db, status="processing", original_path="uploads/2_w_konwersji.mp4")
    db.commit()
    for key in (ok.original_path, ok.proxy_path, converting.original_path):
        write_clip_file(key, age_seconds=old_age)
    write_clip_file(f"proxies/{converting.id}.part.mp4", age_seconds=old_age)  # conversion in progress
    write_clip_file("proxies/501.mp4", age_seconds=old_age)  # recording deleted: orphan
    write_clip_file("proxies/502.part.mp4", age_seconds=old_age)  # orphan of an interrupted conversion
    write_clip_file("uploads/503_stary_oryginal.mp4", age_seconds=old_age)  # orphan
    write_clip_file("proxies/504.mp4", age_seconds=60)  # fresh: stays
    write_clip_file("uploads/tus-abc.part", age_seconds=old_age)  # running upload: not ours
    write_clip_file("uploads/notatka.txt", age_seconds=old_age)  # foreign file: stays
    assert retention.cleanup_orphan_videos(db) == 3
    for key in (ok.original_path, ok.proxy_path, converting.original_path, f"proxies/{converting.id}.part.mp4",
                "proxies/504.mp4", "uploads/tus-abc.part", "uploads/notatka.txt"):
        assert storage.exists(key), key
    for key in ("proxies/501.mp4", "proxies/502.part.mp4", "uploads/503_stary_oryginal.mp4"):
        assert not storage.exists(key), key
    assert retention.cleanup_orphan_videos(db) == 0


def test_maintenance_cleans_orphan_video_files(db):
    write_clip_file("proxies/777.mp4", age_seconds=config.ORPHAN_MIN_AGE_SECONDS + 60)
    worker.run_maintenance()
    assert not storage.exists("proxies/777.mp4")


def test_days_left_and_note(db):
    now = utcnow()
    video = ready(db, expires_in_days=0)
    for days, note in [(30, None), (7.2, None), (6.5, "pełne nagranie dostępne jeszcze 7 dni"),
                       (2.1, "pełne nagranie dostępne jeszcze 3 dni"), (0.4, "pełne nagranie dostępne jeszcze 1 dzień"),
                       (-0.5, "pełne nagranie zostanie usunięte w najbliższym sprzątaniu")]:
        video.expires_at = now + timedelta(days=days)
        assert retention.expiry_note([video], now) == note, days
    video.purged_at = now
    assert retention.expiry_note([video], now) is None
    video.purged_at, video.proxy_path = None, None
    assert retention.expiry_note([video], now) is None


def test_expiry_note_in_match_list_match_page_panel_and_player(client, db):
    soon = ready(db, expires_in_days=3.5)
    far = ready(db, expires_in_days=25)
    assert "dostępne jeszcze 4 dni" in client.get("/").text
    page = client.get(f"/matches/{soon.match_id}").text
    assert 'id="expiry-note"' in page and "pełne nagranie dostępne jeszcze 4 dni" in page
    assert "Pełne nagranie dostępne jeszcze 4 dni" in page
    assert 'id="expiry-banner"' in client.get(f"/videos/{soon.id}").text
    far_page = client.get(f"/matches/{far.match_id}").text
    assert 'id="expiry-note"' not in far_page and "Pełne nagranie dostępne do" in far_page
    assert 'id="expiry-banner"' not in client.get(f"/videos/{far.id}").text
    client.post(f"/admin/videos/{soon.id}/purge")
    after = client.get(f"/matches/{soon.match_id}").text
    assert 'id="expiry-note"' not in after and "pełne nagranie usunięte" in after
