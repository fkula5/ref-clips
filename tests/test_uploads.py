"""Wgrywanie wznawialne (tus): protokół, uprawnienia, limity, rezerwacja miejsca, sprzątanie,
deklaracja zawartości pliku."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import config, services, uploads
from app.models import Job, PeriodMark, UploadSession, Video
from app.storage import storage
from app.timeutil import utcnow
from tests.helpers import TUS, make_match, tus_create, tus_metadata, tus_patch, tus_upload

DATA = bytes(range(256)) * 400  # ~100 kB


def latest_video(db):
    db.expire_all()
    return db.scalars(select(Video).order_by(Video.id.desc())).first()


# --- protokół ----------------------------------------------------------------------
def test_options_announces_extensions_and_limit(client):
    r = client.options("/uploads/")
    assert r.status_code == 204
    assert r.headers["Tus-Version"] == "1.0.0" and r.headers["Tus-Resumable"] == "1.0.0"
    assert set(r.headers["Tus-Extension"].split(",")) == {"creation", "termination", "expiration"}
    assert int(r.headers["Tus-Max-Size"]) == config.UPLOAD_MAX_BYTES == 8 * 1024 ** 3


def test_create_head_patch_in_chunks_creates_video(client, db):
    match = make_match(db)
    r = tus_create(client, match.id, len(DATA), label="Całość")
    assert r.status_code == 201 and r.headers["Tus-Resumable"] == "1.0.0"
    assert "Upload-Expires" in r.headers
    url = r.headers["Location"]

    head = client.head(url, headers=TUS)
    assert head.status_code == 200 and head.headers["Upload-Offset"] == "0"
    assert head.headers["Upload-Length"] == str(len(DATA)) and head.headers["Cache-Control"] == "no-store"

    third = len(DATA) // 3
    r = tus_patch(client, url, 0, DATA[:third])
    assert r.status_code == 204 and r.headers["Upload-Offset"] == str(third)
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == str(third)
    assert db.scalar(select(Video)) is None  # nagranie powstaje dopiero po ostatnim bajcie

    r = tus_patch(client, url, third, DATA[third:2 * third])
    r = tus_patch(client, url, 2 * third, DATA[2 * third:])
    assert r.status_code == 204 and r.headers["Upload-Offset"] == str(len(DATA))

    video = latest_video(db)
    assert video.status == "queued" and video.label == "Całość" and video.content == "full"
    assert video.original_filename == "mecz.mp4" and video.size_bytes == len(DATA)
    assert video.expires_at is not None and video.created_by is not None
    assert storage.local_path(video.original_path).read_bytes() == DATA
    assert not storage.exists(uploads.part_key(url.rsplit("/", 1)[1]))
    job = db.scalar(select(Job))
    assert job.type == "transcode" and job.status == "pending" and job.video_id == video.id
    # po zakończeniu HEAD nadal pokazuje pełny rozmiar (klient, który nie dostał odpowiedzi)
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == str(len(DATA))
    assert db.scalar(select(Video).where(Video.id != video.id)) is None  # bez duplikatu


def test_expires_at_follows_retention_setting(client, db):
    from app.models import Setting
    db.merge(Setting(key="retention_days", value="7"))
    db.commit()
    tus_upload(client, make_match(db).id, DATA)
    video = latest_video(db)
    assert timedelta(days=6, hours=23) < video.expires_at - utcnow() <= timedelta(days=7)


def test_resume_after_interrupted_patch(client, db):
    """Przerwane połączenie: HEAD zwraca zapisany offset, kolejny PATCH idzie od niego."""
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:30000])
    # klient nie wie, ile dotarło: pyta HEAD i wznawia od tego miejsca
    offset = int(client.head(url, headers=TUS).headers["Upload-Offset"])
    assert offset == 30000
    assert tus_patch(client, url, offset, DATA[offset:]).status_code == 204
    assert storage.local_path(latest_video(db).original_path).read_bytes() == DATA


def test_wrong_offset_is_409_with_current_offset(client, db):
    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:1000])
    r = tus_patch(client, url, 500, DATA[500:1500])
    assert r.status_code == 409 and r.headers["Upload-Offset"] == "1000"
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == "1000"  # nic nie zapisano


def test_data_beyond_declared_length_is_413(client, db):
    url = tus_create(client, make_match(db).id, 1000).headers["Location"]
    r = tus_patch(client, url, 0, b"x" * 1001)
    assert r.status_code == 413
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == "0"


def test_patch_requires_offset_content_type(client, db):
    url = tus_create(client, make_match(db).id, 100).headers["Location"]
    r = client.patch(url, content=b"x" * 10, headers={**TUS, "Upload-Offset": "0",
                                                      "Content-Type": "application/octet-stream"})
    assert r.status_code == 415
    r = client.patch(url, content=b"x", headers={**TUS, "Content-Type": "application/offset+octet-stream"})
    assert r.status_code == 400  # brak Upload-Offset


def test_file_over_max_size_is_413(client, db, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 1000)
    match = make_match(db)
    assert tus_create(client, match.id, 1001).status_code == 413
    assert tus_create(client, match.id, 1000).status_code == 201


def test_missing_upload_length_or_match_is_400(client, db):
    match = make_match(db)
    r = client.post("/uploads/", headers={**TUS, "Upload-Metadata": tus_metadata(filename="a.mp4", match_id=match.id)})
    assert r.status_code == 400
    r = client.post("/uploads/", headers={**TUS, "Upload-Length": "10",
                                          "Upload-Metadata": tus_metadata(filename="a.mp4")})
    assert r.status_code == 400
    r = client.post("/uploads/", headers={**TUS, "Upload-Length": "10", "Upload-Defer-Length": "1",
                                          "Upload-Metadata": tus_metadata(match_id=match.id)})
    assert r.status_code == 400
    r = client.post("/uploads/", headers={**TUS, "Upload-Length": "10", "Upload-Metadata": "match_id !!!"})
    assert r.status_code == 400
    r = tus_create(client, match.id, 10, content="Q9")
    assert r.status_code == 400 and "Q9" in r.json()["detail"]
    assert tus_create(client, 9999, 10).status_code == 400


def test_tus_version_header_is_required(client, db):
    match = make_match(db)
    r = client.post("/uploads/", headers={"Upload-Length": "10",
                                          "Upload-Metadata": tus_metadata(match_id=match.id)})
    assert r.status_code == 412 and r.headers["Tus-Version"] == "1.0.0"


def test_delete_cancels_and_removes_file(client, db):
    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:5000])
    upload_id = url.rsplit("/", 1)[1]
    assert storage.exists(uploads.part_key(upload_id))
    assert client.delete(url, headers=TUS).status_code == 204
    assert not storage.exists(uploads.part_key(upload_id))
    assert db.get(UploadSession, upload_id) is None
    assert client.head(url, headers=TUS).status_code == 404
    assert db.scalar(select(Video)) is None


def test_part_file_is_streamed_to_disk_while_uploading(client, db):
    url = tus_create(client, make_match(db).id, 6 * 1024 * 1024).headers["Location"]
    tus_patch(client, url, 0, b"y" * (5 * 1024 * 1024))
    assert storage.size(uploads.part_key(url.rsplit("/", 1)[1])) == 5 * 1024 * 1024


# --- uprawnienia ---------------------------------------------------------------------
def test_other_users_upload_is_not_accessible(make_client, db):
    owner, _ = make_client("coach")
    intruder, _ = make_client("admin")  # nawet administrator nie dotyka cudzego uploadu
    url = tus_create(owner, make_match(db).id, len(DATA)).headers["Location"]
    tus_patch(owner, url, 0, DATA[:1000])
    assert intruder.head(url, headers=TUS).status_code == 404
    assert tus_patch(intruder, url, 1000, DATA[1000:]).status_code == 404
    assert intruder.delete(url, headers=TUS).status_code == 404
    assert owner.head(url, headers=TUS).headers["Upload-Offset"] == "1000"


def test_csrf_token_required_for_post_patch_delete(client, db):
    good = client.headers.pop("X-CSRF-Token")
    match = make_match(db)
    meta = {"Upload-Length": "100", "Upload-Metadata": tus_metadata(filename="a.mp4", match_id=match.id)}
    assert client.post("/uploads/", headers={**TUS, **meta}).status_code == 403
    assert client.post("/uploads/", headers={**TUS, **meta, "X-CSRF-Token": "zly"}).status_code == 403
    r = client.post("/uploads/", headers={**TUS, **meta, "X-CSRF-Token": good})
    assert r.status_code == 201
    url = r.headers["Location"]
    patch = {**TUS, "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"}
    assert client.patch(url, content=b"x" * 10, headers=patch).status_code == 403
    assert client.delete(url, headers=TUS).status_code == 403
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == "0"
    assert client.patch(url, content=b"x" * 10, headers={**patch, "X-CSRF-Token": good}).status_code == 204
    assert client.delete(url, headers={**TUS, "X-CSRF-Token": good}).status_code == 204


def test_referee_outside_the_crew_cannot_upload(make_client, db):
    outsider, _ = make_client("referee")
    r = tus_create(outsider, make_match(db).id, 100)
    assert r.status_code == 403
    assert db.scalar(select(UploadSession)) is None


def test_referee_in_the_crew_can_upload_and_loses_access_when_removed(make_client, db):
    ref_client, ref = make_client("referee")
    match = make_match(db, officials=(("CC", ref), ("U1", "Kasia Żółć")))
    url = tus_create(ref_client, match.id, len(DATA)).headers["Location"]
    assert tus_patch(ref_client, url, 0, DATA[:100]).status_code == 204
    services.set_officials(db, match, [("CC", None, "Ktoś Inny"), ("U1", None, "Kasia Żółć")])
    db.commit()
    assert tus_patch(ref_client, url, 100, DATA[100:]).status_code == 403
    assert ref_client.delete(url, headers=TUS).status_code == 204  # sprzątanie własnego uploadu zawsze możliwe


def test_every_tus_route_requires_login(anon_client):
    for method, url in (("post", "/uploads/"), ("options", "/uploads/"), ("head", "/uploads/abc"),
                        ("patch", "/uploads/abc"), ("delete", "/uploads/abc")):
        assert getattr(anon_client, method)(url).status_code == 401, method


# --- limity i rezerwacja miejsca --------------------------------------------------------
def test_one_active_upload_per_user(client, db):
    match = make_match(db)
    first = tus_create(client, match.id, 1000, filename="q1.mp4")
    assert first.status_code == 201
    r = tus_create(client, match.id, 2000, filename="q2.mp4")
    assert r.status_code == 409
    assert "q1.mp4" in r.json()["detail"] and r.headers["X-Active-Upload"] == first.headers["Location"]
    # przerwanie poprzedniego odblokowuje kolejny
    assert client.delete(r.headers["X-Active-Upload"], headers=TUS).status_code == 204
    assert tus_create(client, match.id, 2000, filename="q2.mp4").status_code == 201


def test_second_upload_allowed_after_first_completes(client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA, filename="q1.mp4", content="Q1")
    tus_upload(client, match.id, DATA, filename="q2.mp4", content="Q2")
    assert len(db.scalars(select(Video)).all()) == 2


def test_same_file_restarts_instead_of_blocking(client, db):
    """Klient, który zgubił adres uploadu, zaczyna ten sam plik od nowa (bez błędu limitu)."""
    match = make_match(db)
    first = tus_create(client, match.id, 1000).headers["Location"]
    tus_patch(client, first, 0, b"a" * 500)
    second = tus_create(client, match.id, 1000)
    assert second.status_code == 201 and second.headers["Location"] != first
    assert client.head(first, headers=TUS).status_code == 404
    assert len(db.scalars(select(UploadSession)).all()) == 1


def test_limit_is_per_user(make_client, db):
    a, _ = make_client("admin")
    b, _ = make_client("coach")
    match = make_match(db)
    assert tus_create(a, match.id, 1000).status_code == 201
    assert tus_create(b, match.id, 1000).status_code == 201


@pytest.fixture()
def fixed_space(monkeypatch):
    """Ustawia wolne miejsce na dysku i małe rezerwy (1 000 B wersji roboczej, 500 B zapasu)."""
    monkeypatch.setattr(config, "DRAFT_RESERVE_BYTES", 1000)
    monkeypatch.setattr(config, "DISK_SAFETY_BYTES", 500)

    def set_free(value):
        monkeypatch.setattr(storage, "free_bytes", lambda: value)
    return set_free


def test_space_reservation_rejects_with_507(client, db, fixed_space):
    match = make_match(db)
    fixed_space(5000 + 1000 + 500 - 1)  # o bajt za mało na plik + wersję roboczą + zapas
    r = tus_create(client, match.id, 5000)
    assert r.status_code == 507 and "brak miejsca" in r.json()["detail"].lower()
    assert db.scalar(select(UploadSession)) is None
    fixed_space(5000 + 1000 + 500)
    assert tus_create(client, match.id, 5000).status_code == 201


def test_space_reservation_counts_other_active_uploads(make_client, db, fixed_space):
    a, _ = make_client("admin")
    b, _ = make_client("coach")
    match = make_match(db)
    fixed_space(10_000)
    assert tus_create(a, match.id, 4000).status_code == 201   # rezerwuje 4000 + 1000
    # drugi: 3000 + 1000 + 500 + cudza rezerwacja 5000 = 9500 <= 10000
    assert tus_create(b, match.id, 3000).status_code == 201
    c, _ = make_client("admin")
    assert tus_create(c, match.id, 500).status_code == 507     # 500 + 1500 + 5000 + 4000 > 10000


def test_reservation_shrinks_as_bytes_arrive_and_counts_pending_conversions(client, db, fixed_space):
    match = make_match(db)
    url = tus_create(client, match.id, 4000).headers["Location"]
    tus_patch(client, url, 0, b"x" * 1500)
    assert uploads.reserved_bytes(db) == (4000 + 1000) - 1500  # zapisane bajty zajmują już dysk
    tus_patch(client, url, 1500, b"x" * 2500)                   # koniec: powstaje nagranie czekające na konwersję
    db.expire_all()
    assert uploads.reserved_bytes(db) == 1000                   # miejsce na jego wersję roboczą
    video = latest_video(db)
    video.status, video.original_path = "ready", None            # po konwersji rezerwacja znika
    db.commit()
    assert uploads.reserved_bytes(db) == 0


def test_space_error_does_not_leave_files(client, db, fixed_space):
    fixed_space(10)
    tus_create(client, make_match(db).id, 5000)
    assert list((config.DATA_DIR / "uploads").glob("tus-*")) == []


# --- sprzątanie -------------------------------------------------------------------------
def test_stale_uploads_are_removed_after_24h(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:1000])
    upload_id = url.rsplit("/", 1)[1]
    up = db.get(UploadSession, upload_id)

    up.updated_at = utcnow() - timedelta(hours=23)
    db.commit()
    assert uploads.cleanup_stale(db) == 0 and storage.exists(uploads.part_key(upload_id))

    up.updated_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert uploads.cleanup_stale(db) == 1
    assert not storage.exists(uploads.part_key(upload_id)) and db.get(UploadSession, upload_id) is None


def test_expired_upload_returns_410(client, db):
    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    up = db.get(UploadSession, upload_id)
    up.updated_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert client.head(url, headers=TUS).status_code == 410
    db.expire_all()
    assert db.get(UploadSession, upload_id) is None


def test_cleanup_removes_orphaned_part_files(db):
    old = config.DATA_DIR / "uploads" / "tus-orphan.part"
    fresh = config.DATA_DIR / "uploads" / "tus-fresh.part"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    import os
    past = (utcnow() - timedelta(hours=30)).timestamp() - 7200  # zapas na strefę czasową
    os.utime(old, (past, past))
    uploads.cleanup_stale(db)
    assert not old.exists() and fresh.exists()
    fresh.unlink()


def test_worker_maintenance_runs_cleanup(client, db):
    from app import worker
    url = tus_create(client, make_match(db).id, 100).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    up = db.get(UploadSession, upload_id)
    up.updated_at = utcnow() - timedelta(hours=48)
    db.commit()
    worker.run_maintenance()
    db.expire_all()
    assert db.get(UploadSession, upload_id) is None


# --- deklaracja zawartości pliku -------------------------------------------------------------
def test_normalize_content():
    assert services.normalize_content(None) == "full" and services.normalize_content("") == "full"
    assert services.normalize_content("FULL") == "full"
    assert services.normalize_content("q2") == "Q2"
    assert services.normalize_content("Q3, q1") == "Q1,Q3"
    with pytest.raises(services.MatchFormError):
        services.normalize_content("Q5")
    assert services.content_label("full") == "cały mecz" and services.content_label("Q2") == "kwarta Q2"
    assert services.content_label("Q1,Q2") == "kwarty Q1, Q2"


def test_full_match_declaration_requires_marks(client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA, content="full")
    video = latest_video(db)
    video.status = "ready"
    db.commit()
    assert video.content == "full" and video.marks == []
    assert services.match_state(match.videos).code == "no_marks"


def test_single_quarter_gets_default_start_mark_and_needs_no_marks(client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA, content="Q3")
    video = latest_video(db)
    video.status = "ready"
    db.commit()
    assert video.content == "Q3"
    assert [(m.period, m.time_sec) for m in video.marks] == [("Q3", 0.0)]
    assert services.match_state(match.videos).code == "ready"
    # klip z takiego pliku ma kwartę bez ręcznego znacznika
    clip = services.create_clip(db, video, None, time_sec=125, cut=False)
    assert services.period_position(video.marks, clip.time_sec) == ("Q3", 125)
    assert services.period_short(video.marks, 125) == "Q3 · 2:05"


def test_several_quarters_declaration_requires_all_marks(client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA, content="Q1,Q2")
    video = latest_video(db)
    video.status = "ready"
    db.commit()
    assert video.content == "Q1,Q2" and video.marks == []   # znaczniki ustawia użytkownik (segment 4)
    assert services.match_state(match.videos).code == "no_marks"
    assert services.period_position(video.marks, 100) is None  # „brak znaczników kwart”
    video.marks.append(PeriodMark(period="Q1", time_sec=10))
    db.commit()
    assert services.match_state(match.videos).code == "no_marks"
    video.marks.append(PeriodMark(period="Q2", time_sec=900))
    db.commit()
    assert services.match_state(match.videos).code == "ready"


def edit(client, video, **form):
    return client.post(f"/videos/{video.id}/update", data=form, follow_redirects=False)


def test_content_declaration_can_be_corrected_after_upload(client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA, content="full")
    video = latest_video(db)
    video.status = "ready"
    db.commit()
    assert services.match_state(match.videos).code == "no_marks"

    assert edit(client, video, content_kind="Q2", label="Druga kwarta").status_code == 303
    db.refresh(video)
    assert video.content == "Q2" and video.label == "Druga kwarta"
    assert [(m.period, m.time_sec) for m in video.marks] == [("Q2", 0.0)]
    assert services.match_state(match.videos).code == "ready"

    # zmiana na inną kwartę: znacznik 0:00 przechodzi na nową; przesunięty znacznik zachowuje czas
    edit(client, video, content_kind="Q4")
    db.refresh(video)
    assert [(m.period, m.time_sec) for m in video.marks] == [("Q4", 0.0)]
    video.marks[0].time_sec = 42
    db.commit()
    edit(client, video, content_kind="Q1")
    db.refresh(video)
    assert [(m.period, m.time_sec) for m in video.marks] == [("Q1", 42.0)]

    # na kilka kwart / cały mecz: samotny 0:00 niepasujący do nowej deklaracji znika
    video.marks[0].time_sec = 0
    db.commit()
    edit(client, video, content_kind="multi", periods=["Q3", "Q4"])
    db.refresh(video)
    assert video.content == "Q3,Q4" and video.marks == []
    assert services.match_state(match.videos).code == "no_marks"
    edit(client, video, content_kind="full")
    db.refresh(video)
    assert video.content == "full"


def test_content_edit_validation_and_permissions(make_client, client, db):
    match = make_match(db)
    tus_upload(client, match.id, DATA)
    video = latest_video(db)
    r = edit(client, video, content_kind="multi", periods=["Q1"])
    assert r.status_code == 422 and "co najmniej dwie" in r.text
    r = edit(client, video, content_kind="Q7")
    assert r.status_code == 422
    db.refresh(video)
    assert video.content == "full"
    outsider, _ = make_client("referee")
    assert edit(outsider, video, content_kind="Q1").status_code == 403
    assert outsider.get(f"/videos/{video.id}/edit").status_code == 403
    page = client.get(f"/videos/{video.id}/edit")
    assert page.status_code == 200 and "Co zawiera plik" in page.text


def test_match_page_has_tus_client_and_content_picker(client, db):
    match = make_match(db)
    page = client.get(f"/matches/{match.id}").text
    assert "/static/vendor/tus-js-client-4.3.1.min.js" in page and "content-template" in page
    assert client.get("/static/vendor/tus-js-client-4.3.1.min.js").status_code == 200


def test_connection_dropped_mid_patch_keeps_received_bytes(client, db):
    """Klient znika w połowie PATCH: to, co dotarło, zostaje zapisane, a HEAD podaje nowy offset."""
    import asyncio

    from app.main import app

    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:1000])
    first = DATA[1000:21000]
    messages = [{"type": "http.request", "body": first, "more_body": True},
                {"type": "http.disconnect"}]

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    sent = []

    async def send(message):
        sent.append(message)

    headers = {**TUS, "upload-offset": "1000", "content-type": "application/offset+octet-stream",
               "cookie": f"{config.SESSION_COOKIE}={client.cookies[config.SESSION_COOKIE]}",
               "x-csrf-token": client.headers["X-CSRF-Token"], "host": "testserver"}
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PATCH",
             "path": url, "raw_path": url.encode(), "query_string": b"", "scheme": "http",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
             "client": ("127.0.0.1", 1234), "server": ("testserver", 80)}
    asyncio.run(app(scope, receive, send))

    assert client.head(url, headers=TUS).headers["Upload-Offset"] == str(21000)
    r = tus_patch(client, url, 21000, DATA[21000:])   # wznowienie od zapisanego offsetu
    assert r.status_code == 204
    assert storage.local_path(latest_video(db).original_path).read_bytes() == DATA


def test_delete_during_patch_does_not_crash(client, db, monkeypatch):
    """Anulowanie (DELETE) w trakcie dopisywania: PATCH kończy się 404, a nie błędem serwera."""
    from app.db import SessionLocal
    from app.routers import uploads as router

    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    real = router._append

    def cancelled_midway(session, up, fh, data):
        with SessionLocal() as other:
            other.delete(other.get(UploadSession, upload_id))
            other.commit()
        real(session, up, fh, data)

    monkeypatch.setattr(router, "_append", cancelled_midway)
    assert tus_patch(client, url, 0, DATA[:1000]).status_code == 404
    monkeypatch.undo()
    assert client.head(url, headers=TUS).status_code == 404


# --- poprawki po review ---------------------------------------------------------------------
def test_offset_is_rechecked_after_acquiring_the_lock(client, db, monkeypatch):
    """Równoległy PATCH kończy się tuż przed blokadą: nieaktualny offset daje 409, nic się nie dopisuje."""
    from app.db import SessionLocal
    from app.routers import uploads as router

    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    real = router.storage.open_update

    def after_other_patch(key):
        fh = real(key)
        fh.write(DATA[:1000])   # „drugie żądanie” zdążyło dopisać 1000 B i zapisać offset
        fh.flush()
        with SessionLocal() as other:
            other.get(UploadSession, upload_id).offset_bytes = 1000
            other.commit()
        return fh

    monkeypatch.setattr(router.storage, "open_update", after_other_patch)
    r = tus_patch(client, url, 0, DATA[:500])
    assert r.status_code == 409 and r.headers["Upload-Offset"] == "1000"
    monkeypatch.undo()
    assert client.head(url, headers=TUS).headers["Upload-Offset"] == "1000"
    assert storage.size(uploads.part_key(upload_id)) == 1000
    assert tus_patch(client, url, 1000, DATA[1000:]).status_code == 204


def test_two_patches_at_the_same_offset(client, db):
    url = tus_create(client, make_match(db).id, len(DATA)).headers["Location"]
    assert tus_patch(client, url, 0, DATA[:1000]).status_code == 204
    r = tus_patch(client, url, 0, DATA[:1000])
    assert r.status_code == 409 and r.headers["Upload-Offset"] == "1000"
    assert storage.size(uploads.part_key(url.rsplit("/", 1)[1])) == 1000


def test_patch_after_completion_is_409_and_leaves_no_part_file(client, db):
    url = tus_upload(client, make_match(db).id, DATA)
    r = tus_patch(client, url, len(DATA), b"")
    assert r.status_code == 409
    assert not storage.exists(uploads.part_key(url.rsplit("/", 1)[1]))


def test_head_of_finished_upload_for_deleted_match_is_410(client, db):
    """Mecz zniknął (np. brak kaskady): HEAD kończący upload nie wybucha, tylko sprząta i zwraca 410."""
    match = make_match(db)
    url = tus_create(client, match.id, 100).headers["Location"]
    upload_id = url.rsplit("/", 1)[1]
    tus_patch(client, url, 0, b"x" * 99)
    up = db.get(UploadSession, upload_id)
    up.offset_bytes, up.match_id = up.size_bytes, None   # upload kompletny, ale bez meczu
    db.commit()
    storage.local_path(uploads.part_key(upload_id)).write_bytes(b"x" * 100)
    with pytest.raises(uploads.UploadError, match="Mecz został usunięty") as exc:
        uploads.finish(db, db.get(UploadSession, upload_id))
    assert exc.value.status_code == 410
    assert db.get(UploadSession, upload_id) is None and not storage.exists(uploads.part_key(upload_id))
    assert db.scalar(select(Video)) is None
    # to samo przez HTTP (HEAD nie ma treści): 410, bez błędu serwera
    url2 = tus_create(client, make_match(db).id, 100).headers["Location"]
    id2 = url2.rsplit("/", 1)[1]
    up2 = db.get(UploadSession, id2)
    up2.offset_bytes, up2.match_id = up2.size_bytes, None
    db.commit()
    storage.local_path(uploads.part_key(id2)).write_bytes(b"x" * 100)
    assert client.head(url2, headers=TUS).status_code == 410


def test_deleting_a_match_removes_its_unfinished_uploads(client, db):
    match = make_match(db)
    url = tus_create(client, match.id, len(DATA)).headers["Location"]
    tus_patch(client, url, 0, DATA[:1000])
    upload_id = url.rsplit("/", 1)[1]
    assert client.post(f"/matches/{match.id}/delete", follow_redirects=False).status_code == 303
    assert client.head(url, headers=TUS).status_code == 404
    assert not storage.exists(uploads.part_key(upload_id))
