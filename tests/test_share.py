import io
import os
import re
import time
import zipfile
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import config, retention, share
from app.models import Clip, Comment, Rating, ShareLink
from app.security import hash_token
from app.storage import storage
from app.timeutil import utcnow
from tests.helpers import category_named, make_match, make_ready_video, mark_periods

SECRETS = ["Kowalski", "Żółć", "Legia", "Wisła", "SEKRET-OPIS", "SEKRET-KOMENTARZ", "SEKRET-OCENA",
           "Trener Jan", "Sędzia Autor", "2026-10-28", "28.10.2026"]
CODE_URLS = ["", "/clips/1/file", "/clips/1/download", "/zip"]  # page, file, single download, ZIP


@pytest.fixture()
def world(db, make_client):
    coach_client, coach = make_client("coach", name="Trener Jan")
    ref_client, ref = make_client("referee", name="Sędzia Autor")
    other_client, other = make_client("coach", name="Inny Trener")
    admin_client, admin = make_client("admin", name="Admin Główny")
    match = make_match(db, created_by=coach)  # II liga, Legia – Wisła, CC Filip Kowalski, U1 Kasia Żółć
    video = mark_periods(db, make_ready_video(db, match))
    for sub in ("tmp",):
        for path in (config.DATA_DIR / sub).glob("*"):
            path.unlink()
    w = SimpleNamespace(db=db, match=match, video=video, coach=coach_client, coach_user=coach, ref=ref_client,
                        ref_user=ref, other=other_client, admin=admin_client, admin_user=admin)

    def clip(*, author=None, category="kroki", status="cut", file=True, custom=None, t=100.0):
        c = Clip(match_id=match.id, video_id=video.id, author_id=(author or coach).id, time_sec=t,
                 official_id=match.official("CC").id, category_id=category_named(db, category),
                 custom_category=custom, description="SEKRET-OPIS", status=status)
        db.add(c)
        db.commit()
        if file:
            c.clip_path, c.clip_version = f"clips/{c.id}_v1.mp4", 1
            with storage.open_write(c.clip_path) as fh:
                fh.write(bytes([c.id % 256]) * 4096)
            db.commit()
        return c

    w.clip = clip
    return w


def link_to(w, *clips, user=None, days="7"):
    return share.create_link(w.db, user or w.coach_user, [str(c.id) for c in clips], days)


def snapshot(r):
    return (r.status_code, r.text, r.headers["content-type"], r.headers.get("cache-control"))


def test_page_file_range_download_and_zip_work_without_login(world, anon_client):
    one, two = world.clip(t=10), world.clip(t=20)
    _, single = link_to(world, one)
    _, multi = link_to(world, one, two)
    for client in (anon_client, world.admin):
        page = client.get(f"/s/{single}")
        assert page.status_code == 200 and "<video" in page.text and f"/s/{single}/clips/1/file" in page.text
        assert "set-cookie" not in page.headers and world.admin_user.name not in page.text
        full = client.get(f"/s/{single}/clips/1/file")
        assert full.status_code == 200 and full.content == storage.local_path(one.clip_path).read_bytes()
        part = client.get(f"/s/{single}/clips/1/file", headers={"Range": "bytes=10-19"})
        assert part.status_code == 206 and part.content == full.content[10:20]
        assert part.headers["content-range"] == f"bytes 10-19/{len(full.content)}"
        download = client.get(f"/s/{single}/clips/1/download")
        assert download.status_code == 200
        assert download.headers["content-disposition"] == 'attachment; filename="II-liga_kroki.mp4"'
        assert client.get(f"/s/{single}/zip").status_code == 404
        assert client.get(f"/s/{multi}/clips/1/download").status_code == 404
        archive = zipfile.ZipFile(io.BytesIO(client.get(f"/s/{multi}/zip").content))
        assert archive.namelist() == ["II-liga_kroki.mp4", "II-liga_kroki_2.mp4"]
        assert archive.read("II-liga_kroki_2.mp4") == storage.local_path(two.clip_path).read_bytes()
    assert anon_client.head(f"/s/{single}").status_code == 200


@pytest.mark.parametrize("state", ["expired", "revoked", "no_clips", "bad_format"])
def test_dead_links_are_indistinguishable_from_unknown(world, anon_client, state):
    clip = world.clip()
    link, code = link_to(world, clip)
    if state == "expired":
        link.expires_at = utcnow() - timedelta(seconds=1)
    elif state == "revoked":
        link.revoked_at = utcnow()
    elif state == "no_clips":
        world.db.delete(clip)
    elif state == "bad_format":
        code = "krótki"
    world.db.commit()
    for suffix in CODE_URLS:
        got, base = anon_client.get(f"/s/{code}{suffix}"), anon_client.get(f"/s/{'A' * 43}{suffix}")
        assert got.status_code == 404 and snapshot(got) == snapshot(base), (state, suffix)
        assert code not in got.text and "set-cookie" not in got.headers


@pytest.mark.parametrize("request_", [("post", "/s/{c}"), ("get", "/s/{c}/inne/ścieżki/tu"), ("get", "/s/{c}/clips/x/file"),
                                      ("get", "/s/"), ("head", "/s/{c}/zip")])
def test_other_requests_under_s_get_the_same_plain_404_without_cookies(world, anon_client, request_):
    method, url = request_
    _, code = link_to(world, world.clip())
    r = getattr(anon_client, method)(url.format(c=code))
    assert r.status_code == 404 and "set-cookie" not in r.headers
    assert snapshot(r)[1:] == snapshot(anon_client.get("/s/" + "A" * 43))[1:] or method == "head"


def test_public_html_and_filenames_hide_names_teams_description_comments(world, anon_client):
    clip = world.clip(author=world.ref_user, t=10)
    world.db.add_all([Comment(clip_id=clip.id, author_id=world.coach_user.id, body="SEKRET-KOMENTARZ"),
                      Rating(clip_id=clip.id, coach_id=world.coach_user.id, verdict="correct", comment="SEKRET-OCENA")])
    world.db.commit()
    second = world.clip(t=20)
    _, one = link_to(world, clip)
    _, two = link_to(world, clip, second)
    seen = []
    for code in (one, two):
        page = anon_client.get(f"/s/{code}")
        seen += [page.text, str(page.headers)]
        assert "II liga" in page.text and "kroki" in page.text
        assert not re.search(r'<a [^>]*href="(?!/s/)', page.text) and "<nav" not in page.text and "csrf" not in page.text.lower()
        assert 'name="robots" content="noindex, nofollow"' in page.text and "/login" not in page.text
    seen.append(str(anon_client.get(f"/s/{one}/clips/1/download").headers))
    archive = zipfile.ZipFile(io.BytesIO(anon_client.get(f"/s/{two}/zip").content))
    seen += archive.namelist() + [str(i.date_time) for i in archive.infolist()]
    assert archive.namelist() == ["II-liga_kroki.mp4", "II-liga_kroki_2.mp4"] and archive.testzip() is None
    joined = "\n".join(seen)
    for secret in SECRETS:
        assert secret not in joined, secret


def test_custom_category_text_is_public_and_in_the_filename(world, anon_client):
    """Known risk: text typed as a "custom" category is visible on the page and in the file name."""
    _, code = link_to(world, world.clip(category="własna", custom="Sytuacja przy ławce"))
    assert "Sytuacja przy ławce" in anon_client.get(f"/s/{code}").text
    assert 'filename="II-liga_Sytuacja-przy-lawce.mp4"' in anon_client.get(f"/s/{code}/clips/1/download").headers["content-disposition"]


def test_database_stores_only_a_hash_of_the_code(world):
    link, code = link_to(world, world.clip())
    assert len(code) == 43 and link.token_hash == hash_token(code) and code not in link.token_hash
    world.db.commit()
    for suffix in ("", "-wal"):  # neither the DB file nor the WAL journal contains the plain code
        path = config.DATA_DIR / f"ref-clips.db{suffix}"
        assert not path.exists() or code.encode() not in path.read_bytes()


def test_positions_are_stable_and_missing_files_are_skipped(world, anon_client):
    a, b, c = world.clip(t=1), world.clip(t=2), world.clip(t=3)
    _, code = link_to(world, a, b, c)
    assert [anon_client.get(f"/s/{code}/clips/{n}/file").status_code for n in (1, 2, 3)] == [200] * 3
    world.db.delete(b)  # clip deleted
    a.status = "queued"  # clip being re-cut
    world.db.commit()
    page = anon_client.get(f"/s/{code}")
    assert page.status_code == 200 and page.text.count("<video") == 1 and f"/s/{code}/clips/3/file" in page.text
    assert anon_client.get(f"/s/{code}/clips/3/file").status_code == 200
    assert [anon_client.get(f"/s/{code}/clips/{n}/file").status_code for n in (1, 2, 9)] == [404, 404, 404]
    assert snapshot(anon_client.get(f"/s/{code}/clips/9/file")) == snapshot(anon_client.get(f"/s/{'A' * 43}/clips/9/file"))
    c.status = "queued"
    world.db.commit()
    assert anon_client.get(f"/s/{code}").status_code == 404


@pytest.mark.parametrize("dead", [False, True])
@pytest.mark.parametrize("suffix", CODE_URLS)
def test_privacy_headers_on_every_public_response(world, anon_client, suffix, dead):
    one, two = world.clip(t=1), world.clip(t=2)
    _, code = link_to(world, one, two)
    r = anon_client.get(f"/s/{'A' * 43 if dead else code}{suffix}")
    assert r.status_code == (404 if dead or suffix == "/clips/1/download" else 200)
    assert r.headers["x-robots-tag"] == "noindex, nofollow" and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == ("private, no-store" if suffix.endswith("/file") and not dead else "no-store")
    assert "set-cookie" not in r.headers


def test_view_count_grows_only_on_page_get(world, anon_client):
    one, two = world.clip(t=1), world.clip(t=2)
    single, code = link_to(world, one)
    multi, multi_code = link_to(world, one, two)

    def views(link):
        world.db.refresh(link)
        return link.view_count

    anon_client.get(f"/s/{code}")
    anon_client.get(f"/s/{code}")
    assert views(single) == 2
    anon_client.head(f"/s/{code}")
    anon_client.get(f"/s/{code}/clips/1/file")
    anon_client.get(f"/s/{code}/clips/1/file", headers={"Range": "bytes=0-9"})
    anon_client.get(f"/s/{code}/clips/1/download")
    anon_client.get(f"/s/{multi_code}/zip")
    anon_client.get(f"/s/{'A' * 43}")
    assert views(single) == 2 and views(multi) == 0
    anon_client.get(f"/s/{multi_code}")
    assert views(multi) == 1


def post_share(client, ids, days="7", **kw):
    return client.post("/share-links", data={"clip_ids": ids, "days": days}, follow_redirects=False, **kw)


@pytest.mark.parametrize("case,status,fragment", [
    ("cudzy klip", 403, "Nie możesz udostępnić"),
    ("niewycięty", 409, "nie są wycięte"),
    ("nieistniejący", 404, "już nie istnieje"),
    ("za dużo", 422, "najwyżej 2 klipów"),
    ("zła ważność", 422, "Wybierz ważność linku: 1, 7 albo 30 dni"),
    ("brak ważności", 422, "Wybierz ważność linku"),
    ("pusty wybór", 422, "co najmniej jeden klip"),
    ("zły id", 422, "Niepoprawna lista klipów"),
])
def test_creation_is_refused_as_a_whole_with_a_readable_message(world, monkeypatch, case, status, fragment):
    monkeypatch.setattr(config, "SHARE_MAX_CLIPS", 2)
    own, foreign = world.clip(author=world.ref_user, t=1), world.clip(author=world.coach_user, t=2)
    uncut = world.clip(author=world.ref_user, status="queued", file=False, t=3)
    ids, days, client = {
        "cudzy klip": ([own.id, foreign.id], "7", world.ref),
        "niewycięty": ([own.id, uncut.id], "7", world.ref),
        "nieistniejący": ([own.id, 99999], "7", world.ref),
        "za dużo": ([own.id, foreign.id, uncut.id], "7", world.coach),
        "zła ważność": ([own.id], "5", world.ref),
        "brak ważności": ([own.id], "", world.ref),
        "pusty wybór": ([], "7", world.ref),
        "zły id": (["abc"], "7", world.ref),
    }[case]
    r = post_share(client, ids, days)
    assert r.status_code == status and fragment in r.json()["detail"], r.text
    assert "set-cookie" not in r.headers and world.db.scalar(select(ShareLink)) is None


def test_creation_validates_expiry_and_who_may_share(world):
    own, foreign = world.clip(author=world.ref_user, t=1), world.clip(author=world.coach_user, t=2)
    for days in (1, 7, 30):
        link, _ = link_to(world, own, days=str(days))
        assert abs((link.expires_at - utcnow()) - timedelta(days=days)) < timedelta(minutes=1)
    assert post_share(world.ref, [own.id]).status_code == 303
    assert post_share(world.ref, [own.id, foreign.id]).status_code == 403
    assert post_share(world.admin, [own.id, foreign.id, own.id]).status_code == 303
    newest = world.db.scalars(select(ShareLink).order_by(ShareLink.id.desc())).first()
    assert [i.clip_id for i in newest.items] == [own.id, foreign.id] and [i.position for i in newest.items] == [1, 2]


def test_code_is_shown_once_and_never_in_the_redirect_url(world, anon_client):
    clip = world.clip()
    r = post_share(world.coach, [clip.id], "30")
    assert r.status_code == 303 and r.headers["location"] == "/share-links/created"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/share-links" in cookie
    assert r.headers["cache-control"] == "no-store"
    page = world.coach.get("/share-links/created")
    code = re.search(r'value="http://testserver/s/([A-Za-z0-9_-]{43})"', page.text).group(1)
    assert page.headers["cache-control"] == "no-store" and "pobranych plików" in page.text
    assert "Max-Age=0" in page.headers["set-cookie"] and anon_client.get(f"/s/{code}").status_code == 200
    again = world.coach.get("/share-links/created")
    assert code not in again.text and "tylko raz" in again.text
    world.other.cookies.set("refclips_share", f"{world.db.scalar(select(ShareLink.id))}.{code}", path="/share-links")
    assert code not in world.other.get("/share-links/created").text


def test_public_url_uses_configured_address(world, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_URL", "https://klipy.example.pl")
    post_share(world.coach, [world.clip().id])
    assert re.search(r'value="https://klipy\.example\.pl/s/[A-Za-z0-9_-]{43}"', world.coach.get("/share-links/created").text)


def test_revoke_rules_and_clip_page_lists_active_links(world, anon_client):
    clip = world.clip(author=world.ref_user)
    mine, code = link_to(world, clip, user=world.coach_user)
    by_ref, ref_code = link_to(world, clip, user=world.ref_user)
    expired, _ = link_to(world, clip)
    expired.expires_at = utcnow() - timedelta(days=1)
    anon_client.get(f"/s/{code}")
    world.db.commit()
    page = world.coach.get(f"/clips/{clip.id}").text
    assert page.count("Unieważnij") == 1 and "Aktywne linki (2)" in page and "wejść: <strong>1</strong>" in page
    assert f"/share-links/{mine.id}/revoke" in page and f"/share-links/{by_ref.id}/revoke" not in page
    assert f"/share-links/{by_ref.id}/revoke" in world.admin.get(f"/clips/{clip.id}").text
    assert code not in page and "Utwórz link" in page
    assert world.other.post(f"/share-links/{mine.id}/revoke").status_code == 403
    assert world.ref.post(f"/share-links/{mine.id}/revoke").status_code == 403
    assert anon_client.post(f"/share-links/{mine.id}/revoke").status_code == 401
    assert anon_client.get(f"/s/{code}").status_code == 200
    r = world.coach.post(f"/share-links/{mine.id}/revoke", data={"clip_id": str(clip.id)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/clips/{clip.id}"
    assert world.admin.post(f"/share-links/{by_ref.id}/revoke", follow_redirects=False).headers["location"] == "/clips"
    assert [anon_client.get(f"/s/{c}").status_code for c in (code, ref_code)] == [404, 404]
    assert "Brak aktywnych linków" in world.coach.get(f"/clips/{clip.id}").text
    assert world.coach.post(f"/share-links/{mine.id}/revoke", follow_redirects=False).status_code == 303


def test_share_controls_appear_only_where_the_user_may_share(world):
    own, foreign = world.clip(author=world.ref_user, t=1), world.clip(author=world.coach_user, t=2)
    pending = world.clip(author=world.ref_user, status="queued", file=False, t=3)
    assert 'id="clip-share"' in world.ref.get(f"/clips/{own.id}").text
    assert 'id="clip-share"' not in world.ref.get(f"/clips/{foreign.id}").text
    assert "Link można utworzyć po wycięciu" in world.ref.get(f"/clips/{pending.id}").text
    for url in ("/clips", f"/matches/{world.match.id}"):
        ref_page, coach_page = world.ref.get(url).text, world.coach.get(url).text
        assert ref_page.count('class="share-check"') == 1 and f'value="{own.id}"' in ref_page
        assert coach_page.count('class="share-check"') == 2 and "Udostępnij zaznaczone" in coach_page
    assert 'id="share-form"' in world.ref.get("/clips").text


def tmp_files():
    return list((config.DATA_DIR / "tmp").glob("*"))


@pytest.mark.parametrize("case,status", [("ok", 200), ("zajęte", 503), ("brak miejsca", 503), ("awaria", None)])
def test_zip_leaves_no_temp_file_and_releases_its_slot(world, anon_client, monkeypatch, case, status):
    _, code = link_to(world, world.clip(t=1), world.clip(t=2))
    if case == "zajęte":
        monkeypatch.setattr(config, "SHARE_ZIP_MAX_PARALLEL", 0)
    elif case == "brak miejsca":
        monkeypatch.setattr(storage, "free_bytes", lambda: 0)
    elif case == "awaria":
        monkeypatch.setattr(share.shutil, "copyfileobj", lambda *a, **k: (_ for _ in ()).throw(OSError("dysk")))
        with pytest.raises(OSError):
            anon_client.get(f"/s/{code}/zip")
    if status:
        r = anon_client.get(f"/s/{code}/zip")
        assert r.status_code == status
        assert (status == 200) == (r.headers["content-type"] == "application/zip")
        assert status == 200 or ("retry-after" in r.headers and "Nie można" not in r.text and code not in r.text)
    assert tmp_files() == [] and share._zips_running == 0


def test_cleanup_removes_only_old_zip_leftovers_from_tmp(world):
    tmp = config.DATA_DIR / "tmp"
    old, fresh, other = tmp / "share-stare.zip", tmp / "share-nowe.zip", tmp / "inny.txt"
    for path in (old, fresh, other):
        path.write_bytes(b"x")
    stale = time.time() - config.ORPHAN_MIN_AGE_SECONDS - 60
    os.utime(old, (stale, stale))
    os.utime(other, (stale, stale))
    assert retention.cleanup_tmp(world.db) == 1
    assert not old.exists() and fresh.exists() and other.exists()


def test_public_filenames_hide_the_referee_and_zip_names_are_numbered(world):
    from app import services
    clip = world.clip()
    assert services.clip_filename(clip) == "II-liga_Kowalski_kroki.mp4"
    assert services.clip_filename(clip, with_referee=False) == "II-liga_kroki.mp4"
    world.match.level = ""
    assert services.clip_filename(clip, with_referee=False) == "kroki.mp4"
    clip.category = None
    assert services.clip_filename(clip, with_referee=False) == "klip.mp4"
    assert services.unique_filenames(["a.mp4", "a.mp4", "b.mp4", "a.mp4"]) == ["a.mp4", "a_2.mp4", "b.mp4", "a_3.mp4"]
