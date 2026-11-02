"""Notatki przy wgrywaniu: podgląd przed wysłaniem, zapis razem z uploadem, klipy po zakończeniu
wgrywania, moment poza nagraniem, limity i dostęp."""
import pytest
from sqlalchemy import select

from app import config, services, uploads, worker
from app.models import Clip, Job, UploadSession, Video
from app.storage import storage
from tests.conftest import needs_ffmpeg
from tests.helpers import TUS, make_match, make_user, tus_create, tus_patch, tus_upload
from tests.test_video import _make_source

DATA = bytes(range(256)) * 40
NOTES = "2:54 Filip PTS\n3:17 U1 dlaczego nie blok?\n4:10 CC faul techniczny\nbez czasu na początku\n"


def parse(client, match_id, text):
    return client.post(f"/api/matches/{match_id}/notes/parse", json={"text": text})


def post_notes(client, url, text):
    return client.post(f"{url}/notes", json={"text": text})


def latest_video(db):
    db.expire_all()
    return db.scalars(select(Video).order_by(Video.id.desc())).first()


def clips(db):
    db.expire_all()
    return db.scalars(select(Clip).order_by(Clip.time_sec)).all()


# --- podgląd przed wysłaniem ------------------------------------------------------------------
def test_preview_uses_match_crew_and_category_dictionary(client, db):
    match = make_match(db)
    rows = parse(client, match.id, NOTES).json()
    assert [r["line_no"] for r in rows] == [1, 2, 3, 4]
    assert [r["time_sec"] for r in rows] == [174, 197, 250, None]
    assert rows[0]["official"] == "Filip Kowalski" and rows[0]["category"] is None   # PTS nie jest zgadywane
    assert rows[1]["official"] == "Kasia Żółć" and rows[1]["category"] == "blok / szarża"
    assert rows[2]["category"] == "techniczny" and rows[2]["clock"] == "4:10"
    assert rows[3]["ok"] is False and rows[3]["warnings"]
    assert all(r["description"] for r in rows)


def test_preview_warns_about_unknown_referee_and_works_again_after_edit(client, db):
    match = make_match(db)
    rows = parse(client, match.id, "1:00 Zenek kroki").json()
    assert any("Nieznany sędzia" in w for w in rows[0]["warnings"])
    rows = parse(client, match.id, "1:00 CC kroki").json()
    assert rows[0]["warnings"] == [] and rows[0]["official"] == "Filip Kowalski"
    assert parse(client, match.id, "").json() == []


def test_preview_permissions_and_limits(make_client, db):
    ref_client, ref = make_client("referee")
    match = make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć")))
    assert parse(ref_client, match.id, "1:00 CC kroki").status_code == 200
    outsider, _ = make_client("referee")
    assert parse(outsider, match.id, "1:00 CC kroki").status_code == 403
    assert parse(ref_client, match.id + 100, "x").status_code == 404
    too_long = "1:00 CC kroki\n" * 40 + "x" * config.NOTES_MAX_CHARS
    r = parse(ref_client, match.id, too_long)
    assert r.status_code == 413 and "za długie" in r.json()["detail"]
    r = parse(ref_client, match.id, "\n".join(["1:00 CC kroki"] * (config.NOTES_MAX_LINES + 1)))
    assert r.status_code == 413 and "za dużo linii" in r.json()["detail"]
    assert parse(ref_client, match.id, "\n".join(["1:00 CC kroki"] * config.NOTES_MAX_LINES)).status_code == 200


# --- zapis razem z uploadem -------------------------------------------------------------------
def test_notes_are_stored_with_the_session_and_become_clips_after_finish(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA), content="Q1,Q2").headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    r = post_notes(client, url, NOTES)
    assert r.status_code == 200 and r.json() == {"saved": True, "lines": 4}
    assert db.get(UploadSession, upload_id).notes == NOTES.rstrip()
    assert clips(db) == []                                # klipy dopiero po zakończeniu wgrywania
    assert tus_patch(client, url, 0, DATA).status_code == 204

    video = latest_video(db)
    found = clips(db)
    assert [c.time_sec for c in found] == [174, 197, 250]   # linia bez czasu jest pomijana
    assert all(c.video_id == video.id and c.described_at is None and c.status == "queued" for c in found)
    assert all((c.margin_before, c.margin_after) == (15, 15) and c.author_id for c in found)
    cc, u1 = match.official("CC"), match.official("U1")
    assert found[0].official_id == cc.id and found[0].category_id is None
    assert found[1].official_id == u1.id and found[1].category.name == "blok / szarża"
    assert found[2].official_id == cc.id and found[2].category.name == "techniczny"
    assert found[0].description == "2:54 Filip PTS"
    jobs = db.scalars(select(Job).where(Job.type == "cut")).all()
    assert len(jobs) == 3
    # cięcie czeka na wersję roboczą
    assert worker.claim_next(db).type == "transcode"
    assert worker.claim_next(db) is None
    # kwarta nieustalona do czasu ustawienia znaczników; po ustawieniu liczy się z nich
    assert services.period_position(video.marks, 174) is None
    db.expire_all()
    assert db.get(UploadSession, upload_id).notes == NOTES.rstrip()


def test_notes_sent_after_a_tiny_file_finished_still_become_clips(client, db):
    match = make_match(db)
    url = tus_upload(client, match.id, DATA)
    assert clips(db) == []
    assert post_notes(client, url, "1:00 CC kroki").status_code == 200
    found = clips(db)
    assert len(found) == 1 and found[0].time_sec == 60 and found[0].category.name == "kroki"
    # kolejne wysłanie po zamianie na klipy nie dubluje
    r = post_notes(client, url, "2:00 CC aut")
    assert r.status_code == 409 and "zostały już zamienione" in r.json()["detail"]
    assert len(clips(db)) == 1


def test_sending_notes_again_before_finish_replaces_them(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    post_notes(client, url, "1:00 CC kroki")
    post_notes(client, url, "2:00 U1 aut\n3:00 U1 aut")
    tus_patch(client, url, 0, DATA)
    assert [c.time_sec for c in clips(db)] == [120, 180]


def test_upload_without_notes_creates_no_clips(client, db):
    tus_upload(client, make_match(db).id, DATA)
    assert clips(db) == []


def test_unparseable_only_notes_create_no_clips(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    post_notes(client, url, "to nie jest moment\n\n# komentarz")
    tus_patch(client, url, 0, DATA)
    assert clips(db) == []


def test_notes_length_limit(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    r = post_notes(client, url, "1:00 CC kroki\n" + "x" * config.NOTES_MAX_CHARS)
    assert r.status_code == 413
    r = post_notes(client, url, "\n".join(["1:00 CC kroki"] * (config.NOTES_MAX_LINES + 1)))
    assert r.status_code == 413
    assert db.get(UploadSession, upload_id).notes == ""
    r = client.post(f"{url}/notes", json={"text": "x" * (5 * config.NOTES_MAX_CHARS)})
    assert r.status_code == 413
    ok = "\n".join(["1:00 CC kroki"] * config.NOTES_MAX_LINES)
    assert post_notes(client, url, ok).status_code == 200


def test_other_users_upload_session_is_404_for_notes(make_client, db):
    owner, _ = make_client("coach")
    other, _ = make_client("coach")
    admin_client, _ = make_client("admin")
    match = make_match(db)
    url = tus_create(owner, match.id, len(DATA)).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    assert post_notes(other, url, "1:00 CC kroki").status_code == 404
    assert post_notes(admin_client, url, "1:00 CC kroki").status_code == 404
    assert post_notes(owner, "/uploads/nie-ma", "1:00 CC kroki").status_code == 404
    assert db.get(UploadSession, upload_id).notes == ""


def test_notes_permissions_follow_the_crew(make_client, db):
    ref_client, ref = make_client("referee")
    match = make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć")))
    url = tus_create(ref_client, match.id, len(DATA)).headers["Location"]
    assert post_notes(ref_client, url, "1:00 CC kroki").status_code == 200
    match.officials = [o for o in match.officials if o.user_id != ref.id]   # wypadł z obsady
    db.commit()
    assert post_notes(ref_client, url, "2:00 CC kroki").status_code == 403


def test_notes_endpoint_requires_csrf_token_and_login(client, anon_client, db):
    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    token = client.headers.pop("X-CSRF-Token")
    assert client.post(f"{url}/notes", json={"text": "1:00 CC kroki"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert anon_client.post(f"{url}/notes", json={"text": "x"}).status_code == 401


def test_finish_skips_notes_when_author_lost_access(make_client, db):
    ref_client, ref = make_client("referee")
    match = make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć")))
    url = tus_create(ref_client, match.id, len(DATA)).headers["Location"]
    post_notes(ref_client, url, "1:00 CC kroki")
    match.officials = [o for o in match.officials if o.user_id != ref.id]
    db.commit()
    # wgranie nie przejdzie (403 w PATCH), więc kończymy sesję wprost
    up = db.get(UploadSession, url.rsplit("/", 1)[1])
    up.offset_bytes = up.size_bytes
    with storage.open_update(uploads.part_key(up.id)) as fh:
        fh.write(DATA)
    db.commit()
    uploads.finish(db, up)
    assert clips(db) == [] and latest_video(db) is not None


# --- moment poza nagraniem (po konwersji) ----------------------------------------------------------
def test_clip_outside_recording_ends_in_error_state(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    post_notes(client, url, "1:00 CC kroki\n99:00 U1 aut")
    tus_patch(client, url, 0, DATA)
    video = latest_video(db)
    video.status, video.duration, video.proxy_path = "ready", 300.0, f"proxies/{video.id}.mp4"
    with storage.open_write(video.proxy_path) as fh:
        fh.write(b"nie-wideo")
    db.commit()
    outside = next(c for c in clips(db) if c.time_sec == 5940)
    job = db.scalar(select(Job).where(Job.clip_id == outside.id))
    worker.process_job(db, db.get(Job, job.id))
    db.expire_all()
    outside = db.get(Clip, outside.id)
    assert outside.status == "error" and "moment poza nagraniem" in outside.error.lower()
    assert outside.clip_path is None
    assert "Moment poza nagraniem" in client.get(f"/clips/{outside.id}").text


@needs_ffmpeg
def test_real_flow_notes_make_cut_clips_and_out_of_range_error(client, db, tmp_path):
    source = _make_source(tmp_path / "src.mp4", seconds=6, brightness_steps=False)
    match = make_match(db)
    url = tus_create(client, match.id, source.stat().st_size, content="Q1,Q2").headers["Location"]
    post_notes(client, url, "0:02 CC kroki\n0:50 U1 aut")
    offset = 0
    data = source.read_bytes()
    assert tus_patch(client, url, offset, data).status_code == 204
    assert worker.run_once() is True               # konwersja
    for _ in range(2):                              # dwa cięcia
        assert worker.run_once() is True
    found = {c.time_sec: c for c in clips(db)}
    good, outside = found[2], found[50]
    assert good.status == "cut" and storage.exists(good.clip_path) and good.described_at is None
    assert outside.status == "error" and "poza nagraniem" in outside.error.lower()
    assert good.category.name == "kroki" and good.official.function == "CC"
