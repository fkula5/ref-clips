import os
import re
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, scoresheets, share, training_sets, uploads
from app.main import app
from app.models import Clip, Match, MatchScoresheet, TrainingSetClip
from app.storage import storage
from tests.helpers import category_named, make_match, make_ready_video, mark_periods

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 16
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"
HEIF = b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML = b"<!doctype html><html><script>alert(1)</script></html>"
GIF = b"GIF89a" + b"\x00" * 16
AVIF = b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00mif1avif"


@pytest.fixture()
def world(db, make_client):
    crew_client, crew = make_client("referee", name="Sędzia Z Obsady")
    out_client, _ = make_client("referee", name="Sędzia Spoza Obsady")
    coach_client, coach = make_client("coach", name="Trener Jan")
    admin_client, _ = make_client("admin", name="Szef")
    match = make_match(db, officials=(("CC", crew), ("U1", "Kasia Żółć")), created_by=coach)
    return SimpleNamespace(db=db, match=match, crew=crew_client, outsider=out_client, coach=coach_client,
                           admin=admin_client, make_client=make_client)


def post_files(client, match, *files, **kwargs):
    """files: (name, bytes) pairs; the browser's Content-Type is deliberately a fixed lie."""
    return client.post(f"/matches/{match.id}/scoresheets", follow_redirects=False,
                       files=[("files", (name, data, "image/png")) for name, data in files], **kwargs)


def rows(db, match=None):
    db.expire_all()
    stmt = select(MatchScoresheet).order_by(MatchScoresheet.id)
    return list(db.scalars(stmt.where(MatchScoresheet.match_id == match.id) if match else stmt))


def stored_files():
    return sorted(key for key, _size, _mtime in storage.iter_files("scoresheets"))


def add(w, name="protokol.pdf", data=PDF, client=None):
    r = post_files(client or w.coach, w.match, (name, data))
    assert r.status_code == 303, r.text
    return rows(w.db, w.match)[-1]


@pytest.mark.parametrize("who,status", [("crew", 303), ("coach", 303), ("admin", 303), ("outsider", 403)])
def test_who_may_upload(world, who, status):
    r = post_files(getattr(world, who), world.match, ("a.pdf", PDF))
    assert r.status_code == status
    assert len(rows(world.db)) == (1 if status == 303 else 0)
    assert len(stored_files()) == (1 if status == 303 else 0)


def test_referee_in_the_crew_of_another_match_is_refused(world, make_client):
    other_match = make_match(world.db, officials=(("CC", "Ktoś"),))
    assert post_files(world.crew, other_match, ("a.pdf", PDF)).status_code == 403


def test_anonymous_and_csrf(world, anon_client):
    assert anon_client.post(f"/matches/{world.match.id}/scoresheets", files=[("files", ("a.pdf", PDF))]).status_code in (401, 403)
    assert post_files(world.coach, world.match, ("a.pdf", PDF), headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert not rows(world.db)


def test_who_may_delete(world):
    sheet = add(world)
    url = f"/matches/{world.match.id}/scoresheets/{sheet.id}/delete"
    assert world.outsider.post(url, follow_redirects=False).status_code == 403
    assert world.coach.get(f"/matches/{world.match.id}/scoresheets/{sheet.id}/file").status_code == 200
    assert world.outsider.post(url, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert rows(world.db) and stored_files()
    assert world.crew.post(url, follow_redirects=False).status_code == 303
    assert not rows(world.db) and not stored_files()


@pytest.mark.parametrize("who", ["coach", "admin"])
def test_coach_and_admin_delete(world, who):
    sheet = add(world)
    assert getattr(world, who).post(f"/matches/{world.match.id}/scoresheets/{sheet.id}/delete",
                                    follow_redirects=False).status_code == 303
    assert not rows(world.db) and not stored_files()


def test_deleting_through_another_match_url_is_404(world):
    sheet = add(world)
    other = make_match(world.db)
    assert world.admin.post(f"/matches/{other.id}/scoresheets/{sheet.id}/delete").status_code == 404
    assert world.admin.get(f"/matches/{other.id}/scoresheets/{sheet.id}/file").status_code == 404
    assert rows(world.db)


@pytest.mark.parametrize("data,content_type,extension", [
    (PDF, "application/pdf", "pdf"), (JPEG, "image/jpeg", "jpg"), (PNG, "image/png", "png"),
    (WEBP, "image/webp", "webp"), (HEIC, "image/heic", "heic"), (HEIF, "image/heif", "heif"),
])
def test_allowed_types_are_detected_from_the_content(world, data, content_type, extension):
    sheet = add(world, "IMG_0001.xyz", data)  # a wrong extension and a wrong browser type change nothing
    assert sheet.content_type == content_type
    assert re.fullmatch(rf"scoresheets/[0-9a-f]{{32}}\.{extension}", sheet.path)
    assert sheet.original_filename == f"IMG_0001.xyz.{extension}"
    assert sheet.size_bytes == len(data) and sheet.uploaded_by is not None


@pytest.mark.parametrize("name,data", [
    ("protokol.pdf", HTML), ("protokol.png", SVG), ("logo.svg", SVG), ("a.jpg", GIF), ("a.heic", AVIF),
    ("a.pdf", b"PK\x03\x04zip"), ("a.pdf", b"MZ\x90\x00"), ("a.pdf", b"x"), ("a.pdf", b"<html>%PDF-"), ("a.pdf", b"\n%PDF-1.4"),
])
def test_other_types_are_rejected_by_magic_bytes(world, name, data):
    r = post_files(world.coach, world.match, (name, data))
    assert r.status_code == 415
    assert "niedozwolony typ pliku" in r.text and "PDF, JPEG, PNG, WebP, HEIC/HEIF" in r.text
    assert not rows(world.db) and not stored_files()


def test_empty_file_and_empty_selection(world):
    assert post_files(world.coach, world.match, ("a.pdf", b"")).status_code == 422
    r = world.coach.post(f"/matches/{world.match.id}/scoresheets", files=[("files", ("", b"", "application/octet-stream"))],
                         follow_redirects=False)
    assert r.status_code == 422 and "Wybierz co najmniej jeden plik" in r.text
    assert not rows(world.db)


def test_size_limit_is_per_file(world, monkeypatch):
    monkeypatch.setattr(config, "SCORESHEET_MAX_BYTES", len(PDF) + 10)
    assert post_files(world.coach, world.match, ("ok.pdf", PDF)).status_code == 303
    r = post_files(world.coach, world.match, ("duzy.pdf", PDF + b"x" * 11))
    assert r.status_code == 413 and "za duży" in r.text and "duzy.pdf" in r.text
    assert len(rows(world.db)) == 1 and len(stored_files()) == 1


def test_count_limit_covers_the_whole_match(world, monkeypatch):
    monkeypatch.setattr(config, "SCORESHEET_MAX_FILES", 3)
    assert post_files(world.coach, world.match, ("a.pdf", PDF), ("b.pdf", PDF)).status_code == 303
    r = post_files(world.coach, world.match, ("c.pdf", PDF), ("d.pdf", PDF))
    assert r.status_code == 422 and "najwyżej 3 pliki" in r.text and "zostało miejsca na: 1" in r.text
    assert len(rows(world.db)) == 2
    assert post_files(world.coach, world.match, ("c.pdf", PDF)).status_code == 303
    page = world.coach.get(f"/matches/{world.match.id}").text
    assert 'id="scoresheet-form"' not in page and "Osiągnięto limit 3 plików" in page


def test_a_rejected_file_rejects_the_whole_batch(world):
    r = post_files(world.coach, world.match, ("a.pdf", PDF), ("b.png", PNG), ("zly.pdf", HTML))
    assert r.status_code == 415 and "zly.pdf" in r.text
    assert not rows(world.db) and not stored_files()


def test_several_files_in_one_request(world):
    r = post_files(world.coach, world.match, ("a.pdf", PDF), ("b.jpg", JPEG), ("c.heic", HEIC))
    assert r.status_code == 303
    assert [s.content_type for s in rows(world.db)] == ["application/pdf", "image/jpeg", "image/heic"]
    assert len(set(stored_files())) == 3
    page = world.coach.get(r.headers["location"]).text
    assert "Dodano do protokołu: 3 pliki." in page


def test_no_space_on_the_server(world, monkeypatch):
    monkeypatch.setattr(storage, "free_bytes", lambda: 0)
    r = post_files(world.coach, world.match, ("a.pdf", PDF))
    assert r.status_code == 507 and uploads.NO_SPACE_MESSAGE in r.text
    assert not rows(world.db) and not stored_files()


def test_a_failure_while_saving_leaves_no_files_or_rows(world, monkeypatch):
    calls = []
    real = scoresheets.shutil.copyfileobj

    def flaky(src, dst):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        real(src, dst)

    monkeypatch.setattr(scoresheets.shutil, "copyfileobj", flaky)
    with pytest.raises(OSError):
        post_files(world.coach, world.match, ("a.pdf", PDF), ("b.pdf", PDF))
    assert not rows(world.db) and not stored_files()


@pytest.mark.parametrize("sent,shown", [
    ("../../etc/passwd.pdf", "passwd.pdf"), ("C:\\Users\\x\\Protokół meczu.PDF", "Protokół meczu.PDF"),
("<img src=x onerror=1>.pdf", "<img src=x onerror=1>.pdf"),
    ("...", "protokol.pdf"), ("a" * 400 + ".pdf", "a" * (scoresheets.FILENAME_MAX - 4) + ".pdf"),
])
def test_user_filename_is_only_sanitized_display_text(world, sent, shown):
    sheet = add(world, sent)
    assert sheet.original_filename == shown
    assert "/" not in sheet.original_filename and "\\" not in sheet.original_filename
    assert re.fullmatch(r"scoresheets/[0-9a-f]{32}\.pdf", sheet.path)
    page = world.coach.get(f"/matches/{world.match.id}").text
    assert "<img src=x onerror=1>" not in page


def test_files_are_served_with_safe_headers(world):
    pdf, png, heic = add(world, "protokół.pdf", PDF), add(world, "foto.png", PNG), add(world, "IMG.HEIC", HEIC)
    base = f"/matches/{world.match.id}/scoresheets"
    for sheet, content_type in ((pdf, "application/pdf"), (png, "image/png"), (heic, "image/heic")):
        inline = world.outsider.get(f"{base}/{sheet.id}/file")  # everybody logged in may view
        assert inline.status_code == 200 and inline.headers["content-type"] == content_type
        assert inline.headers["x-content-type-options"] == "nosniff"
        assert inline.headers["content-disposition"].startswith("inline;")
        assert inline.headers["cache-control"] == "private, no-cache"
        download = world.outsider.get(f"{base}/{sheet.id}/download")
        assert download.status_code == 200 and download.headers["content-type"] == content_type
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.headers["x-content-type-options"] == "nosniff"
    assert "filename*=utf-8''protok%C3%B3%C5%82.pdf" in world.coach.get(f"{base}/{pdf.id}/download").headers["content-disposition"]
    assert world.coach.get(f"{base}/{pdf.id}/file").content == PDF


def test_a_stored_type_is_what_is_served_even_for_a_misleading_name(world):
    sheet = add(world, "page.html", PNG)
    r = world.coach.get(f"/matches/{world.match.id}/scoresheets/{sheet.id}/file")
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"] == 'inline; filename="page.html.png"'


def test_files_need_a_login(world, anon_client):
    sheet = add(world)
    for suffix in ("file", "download"):
        r = anon_client.get(f"/matches/{world.match.id}/scoresheets/{sheet.id}/{suffix}", follow_redirects=False)
        assert r.status_code in (401, 303) and not r.content.startswith(b"%PDF")


def test_file_missing_on_disk_is_a_404(world):
    sheet = add(world)
    storage.delete(sheet.path)
    assert world.coach.get(f"/matches/{world.match.id}/scoresheets/{sheet.id}/file").status_code == 404


def test_match_page_lists_files_with_previews_and_actions(world):
    pdf, png, heic = add(world, "a.pdf", PDF), add(world, "b.png", PNG), add(world, "c.heic", HEIC)
    for client, can_edit in ((world.crew, True), (world.outsider, False)):
        page = client.get(f"/matches/{world.match.id}").text
        section = page[page.index('id="protokol"'):page.index('id="nagrania"')]
        assert f"/scoresheets/{png.id}/file" in section and f'<img src="/matches/{world.match.id}/scoresheets/{png.id}/file"' in section
        assert section.count("<img") == 1  # PDF and HEIC are tiles, not inline previews
        for sheet in (pdf, png, heic):
            assert f"/scoresheets/{sheet.id}/download" in section
        assert f"/scoresheets/{heic.id}/file" not in section
        assert f"/scoresheets/{pdf.id}/file" in section
        assert (f"/scoresheets/{pdf.id}/delete" in section) is can_edit
        assert ('id="scoresheet-form"' in section) is can_edit
        assert 'accept="' in section or not can_edit
    assert "multiple" in world.crew.get(f"/matches/{world.match.id}").text


def test_upload_form_accepts_the_types_a_phone_offers(world):
    page = world.crew.get(f"/matches/{world.match.id}").text
    accept = re.search(r'name="files" id="scoresheet-files" accept="([^"]+)"', page)[1]
    for item in ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", ".heic", ".pdf"):
        assert item in accept.split(",")
    assert "svg" not in accept


def test_rejection_shows_a_polish_message_on_the_match_page(world):
    r = post_files(world.coach, world.match, ("logo.svg", SVG))
    assert r.status_code == 415 and 'id="scoresheet-error"' in r.text and "Protokół" in r.text


def test_delete_match_removes_its_scoresheet_files(world):
    other = make_match(world.db)
    add(world)
    add(world, "b.png", PNG)
    kept = post_files(world.admin, other, ("c.pdf", PDF))
    assert kept.status_code == 303 and len(stored_files()) == 3
    match_id = world.match.id
    r = world.admin.post(f"/matches/{match_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert len(stored_files()) == 1
    assert [s.match_id for s in rows(world.db)] == [other.id]
    assert world.db.get(Match, match_id) is None


def test_delete_confirmation_mentions_scoresheet_files(world):
    assert "pliki protokołu" not in world.admin.get(f"/matches/{world.match.id}/delete").text
    add(world)
    assert "pliki protokołu: <strong>1</strong>" in world.admin.get(f"/matches/{world.match.id}/delete").text


def test_match_list_marks_matches_with_a_scoresheet(world):
    make_match(world.db)
    assert 'aria-label="Protokół"' not in world.coach.get("/").text
    add(world)
    page = world.coach.get("/").text
    assert page.count('aria-label="Protokół"') == 1
    row = page[page.index("scoresheet-mark") - 400:page.index("scoresheet-mark")]
    assert f"/matches/{world.match.id}" in row


def cut_clip(w):
    video = mark_periods(w.db, make_ready_video(w.db, w.match))
    clip = Clip(match_id=w.match.id, video_id=video.id, author_id=w.match.created_by, time_sec=100.0,
                official_id=w.match.official("CC").id, category_id=category_named(w.db, "kroki"),
                description="opis", described_at=datetime(2026, 10, 29), status="cut",
                clip_path="clips/1_v1.mp4", clip_version=1)
    w.db.add(clip)
    w.db.commit()
    with storage.open_write(clip.clip_path) as fh:
        fh.write(b"x" * 10)
    return clip


def test_scoresheets_are_not_reachable_through_share_links(world):
    sheet = add(world)
    clip = cut_clip(world)
    _, code = share.create_link(world.db, world.match.creator, [str(clip.id)], "7")
    anon = TestClient(app)
    page = anon.get(f"/s/{code}")
    assert page.status_code == 200 and "<video" in page.text
    assert "scoresheet" not in page.text.lower() and "protok" not in page.text.lower()
    for tail in (f"/scoresheets/{sheet.id}/file", "/scoresheets", f"/matches/{world.match.id}/scoresheets/{sheet.id}/file"):
        r = anon.get(f"/s/{code}{tail}")
        assert r.status_code == 404 and not r.content.startswith(b"%PDF")


def test_training_set_pages_do_not_show_scoresheets(world):
    add(world)
    clip = cut_clip(world)
    training_set = training_sets.create_set(world.db, world.match.creator, "Zestaw", "")
    world.db.add(TrainingSetClip(set_id=training_set.id, clip_id=clip.id, position=1))
    world.db.commit()
    for path in (f"/sets/{training_set.id}", f"/sets/{training_set.id}/clips/{clip.id}"):
        response = world.crew.get(path)
        assert response.status_code == 200
        assert "scoresheet" not in response.text.lower() and "Protokół" not in response.text


def test_orphan_files_are_cleaned_only_when_old_and_unused(world):
    used = add(world)
    for name, age in (("old.pdf", 7200), ("fresh.pdf", 60)):
        with storage.open_write(f"scoresheets/{name}") as fh:
            fh.write(PDF)
        os.utime(storage.local_path(f"scoresheets/{name}"), (time.time() - age,) * 2)
    os.utime(storage.local_path(used.path), (time.time() - 7200,) * 2)
    assert scoresheets.cleanup_orphans(world.db) == 1
    assert sorted(stored_files()) == sorted([used.path, "scoresheets/fresh.pdf"])


def test_clean_filename_drops_control_characters_and_directories():
    assert scoresheets.clean_filename("a/b\\c\r\nd\x00e\u202ef.pdf", "application/pdf") == "c d e f.pdf"
    assert scoresheets.clean_filename("\x00\x01", "image/png") == "protokol.png"


@pytest.mark.parametrize("n,text", [(1, "1 plik"), (2, "2 pliki"), (5, "5 plików"), (12, "12 plików"),
                                    (22, "22 pliki"), (10, "10 plików")])
def test_plural(n, text):
    assert scoresheets.plural_files(n) == text


@pytest.mark.parametrize("name,type_,expected", [
    ("scan.PDF", "application/pdf", "scan.PDF"), ("scan.jpeg", "image/jpeg", "scan.jpeg"),
    ("scan.pdf", "image/jpeg", "scan.pdf.jpg"), ("noext", "image/png", "noext.png"),
    ("IMG_1.HEIC", "image/heif", "IMG_1.HEIC"), (".pdf", "application/pdf", "pdf.pdf"),
])
def test_clean_filename_matches_the_extension_to_the_real_type(name, type_, expected):
    assert scoresheets.clean_filename(name, type_) == expected
