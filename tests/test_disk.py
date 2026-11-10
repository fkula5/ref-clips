from datetime import timedelta

import pytest

from app import config, disk, uploads
from app.models import UploadRejection, UploadSession, Video
from app.storage import storage
from app.timeutil import local, utcnow
from tests.helpers import make_match, make_ready_video, tus_create
from tests.test_retention import clip_for, ready


@pytest.fixture()
def fixed_space(monkeypatch):
    monkeypatch.setattr(config, "DRAFT_RESERVE_BYTES", 1000)
    monkeypatch.setattr(config, "DISK_SAFETY_BYTES", 500)

    def set_free(value):
        monkeypatch.setattr(storage, "free_bytes", lambda: value)
    return set_free


def test_usage_sums_database_sizes_and_clip_files(db, admin, fixed_space):
    fixed_space(1_000_000)
    a = ready(db, expires_in_days=5, proxy_bytes=4000)
    ready(db, expires_in_days=9, proxy_bytes=6000)
    done = ready(db, expires_in_days=9, proxy_bytes=9999)
    done.purged_at = utcnow()
    converting = ready(db, status="processing", original_path="uploads/x.mp4", size_bytes=7000)
    converting.proxy_path = None
    db.add(UploadSession(id="u1", user_id=admin[1].id, filename="a.mp4", size_bytes=900, offset_bytes=300, reserved_bytes=900))
    db.commit()
    for name, size in (("clips/1_v1.mp4", 100), ("clips/2_v1.mp4", 250)):
        with storage.open_write(name) as fh:
            fh.write(b"x" * size)
    usage = disk.usage(db)
    assert usage.drafts == 10_000 and usage.originals == 7000 and usage.partial == 300
    assert usage.clips == 350 and usage.clip_files == 2 and usage.free == 1_000_000
    assert usage.reserved == uploads.reserved_bytes(db) > 0
    assert usage.acceptable == 1_000_000 - usage.reserved - 500 - 1000


def test_proxy_sizes_are_filled_lazily_once(db):
    video = ready(db, expires_in_days=3)
    assert video.proxy_bytes is None
    disk.fill_proxy_sizes(db)
    db.refresh(video)
    assert video.proxy_bytes == storage.size(video.proxy_path)
    video.proxy_bytes = 5
    db.commit()
    disk.fill_proxy_sizes(db)
    db.refresh(video)
    assert video.proxy_bytes == 5


def test_rows_sorted_by_deadline_without_deadline_last_and_without_purged(db):
    late = ready(db, expires_in_days=20)
    soon = ready(db, expires_in_days=2)
    none = ready(db)
    none.expires_at = None
    gone = ready(db, expires_in_days=1)
    gone.purged_at = utcnow()
    db.commit()
    rows = disk.video_rows(db)
    assert [r.video.id for r in rows] == [soon.id, late.id, none.id]
    clip_for(db, soon, status="queued")
    row = disk.video_rows(db)[0]
    assert row.clips == 1 and row.pending == 1 and "czeka na wycięcie" in row.blocker


def test_retention_page_lists_videos_with_size_match_and_dates(client, db):
    video = ready(db, expires_in_days=4, proxy_bytes=3 * 1024 * 1024)
    page = client.get("/admin/retention").text
    assert video.match.title in page and "3,0 MB" in page and "Zajętość dysku" in page
    for ident in ("u-drafts", "u-originals", "u-clips", "u-free", "u-reserved"):
        assert f'id="{ident}"' in page
    assert local(video.expires_at, "%d.%m.%Y") in page and "za 4 dni" in page


def test_rejected_upload_is_recorded_and_shown_as_banner(client, admin, db, fixed_space):
    match = make_match(db)
    fixed_space(5000 + 1000 + 500 - 1)
    r = tus_create(client, match.id, 5000, filename="duzy mecz.mp4")
    assert r.status_code == 507
    row = db.query(UploadRejection).one()
    assert row.size_bytes == 5000 and row.user_id == admin[1].id and row.filename == "duzy mecz.mp4"
    assert row.free_bytes == 6499 and abs(row.created_at - utcnow()) < timedelta(seconds=30)
    page = client.get("/admin/retention").text
    assert 'id="rejected-banner"' in page and "Brak miejsca na dysku" in page and "duzy mecz.mp4" in page
    assert admin[1].name in page
    for path in ("/admin/users", "/admin/categories"):
        assert 'id="rejected-banner"' in client.get(path).text
    fixed_space(10_000)
    assert tus_create(client, match.id, 5000).status_code == 201
    assert db.query(UploadRejection).count() == 1


def test_old_rejections_do_not_warn_and_are_pruned(client, db):
    db.add_all([UploadRejection(created_at=utcnow() - timedelta(days=8), size_bytes=1, free_bytes=0),
                UploadRejection(created_at=utcnow() - timedelta(days=config.REJECTION_KEEP_DAYS + 1), size_bytes=2, free_bytes=0)])
    db.commit()
    assert 'id="rejected-banner"' not in client.get("/admin/retention").text
    assert disk.recent_rejections(db) == []
    assert uploads.prune_rejections(db) == 1
    assert db.query(UploadRejection).count() == 1


def test_no_banner_without_rejections(client, db):
    for path in ("/admin/users", "/admin/categories", "/admin/retention"):
        assert 'id="rejected-banner"' not in client.get(path).text


def test_deleted_user_keeps_rejection_record(db, make_client):
    _, user = make_client("coach")
    db.add(UploadRejection(created_at=utcnow(), user_id=user.id, size_bytes=1, free_bytes=0))
    db.commit()
    db.delete(user)
    db.commit()
    assert db.query(UploadRejection).one().user_id is None


def test_human_bytes_filter():
    from app.web import human_bytes
    assert [human_bytes(v) for v in (None, 0, 1023, 1024, 1536, 5 * 1024 ** 3)] == [
        "—", "0 B", "1023 B", "1,0 KB", "1,5 KB", "5,0 GB"]


def test_video_row_size_counts_original_when_present(db):
    video = ready(db, expires_in_days=2, proxy_bytes=100, size_bytes=900, original_path="uploads/a.mp4")
    assert disk.video_rows(db)[0].size == 1000
    assert isinstance(video, Video)
