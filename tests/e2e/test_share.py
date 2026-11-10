import io
import re
import time
import zipfile

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import select

from app.models import Category, Clip

SECRETS = ("Roman", "Sędzia", "Legia", "Wisła", "SEKRET-OPIS", "28.10.2026")


@pytest.fixture(scope="module")
def shared(server):
    match_id = server.make_match(level="III liga")
    video_id = server.make_ready_video(match_id)
    ids = [server.create_clip(video_id, t) for t in (30.0, 34.0, 38.0)]
    with server.db() as db:
        cats = {c.name: c.id for c in db.scalars(select(Category))}
        for clip_id, name in zip(ids, ("kroki", "kroki", "aut")):
            clip = db.get(Clip, clip_id)
            clip.category_id, clip.description = cats[name], "SEKRET-OPIS"
            clip.official_id = next(o.id for o in clip.match.officials if o.function == "CC")
        db.commit()
    deadline = time.monotonic() + 90
    while any(server.clip(i).status != "cut" for i in ids):
        assert time.monotonic() < deadline, "worker nie wyciął klipów"
        time.sleep(0.5)
    return {"match_id": match_id, "a": ids[0], "b": ids[1], "c": ids[2]}


def created_url(page: Page) -> str:
    expect(page).to_have_url(re.compile(r"/share-links/created$"))
    expect(page.locator("#share-created")).to_be_visible()
    return page.locator("#share-url").input_value()


def assert_code_not_in_server_log(server, url: str) -> None:
    code = url.rsplit("/", 1)[-1]
    log = server.log_tail("server", lines=100000)
    assert "/s/[ukryty]" in log and code not in log


def assert_no_scroll(page: Page, what: str) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"{what}: przewija się w bok"


def test_link_do_jednego_klipu_od_utworzenia_do_uniewaznienia(ui, server, shared):
    ui.allow(r"status of 404")
    coach = ui.page("coach")
    coach.goto(f"/clips/{shared['a']}")
    expect(coach.locator("#clip-share")).to_contain_text("Unieważnienie linku nie cofnie już pobranych plików")
    expect(coach.locator("#clip-share select[name=days]")).to_have_value("7")
    coach.get_by_role("button", name="Utwórz link").click()
    url = created_url(coach)
    assert url.startswith(server.base_url + "/s/")
    expect(coach.locator(".share-warning")).to_be_visible()
    coach.locator("#share-copy").click()
    expect(coach.locator("#share-copy")).to_contain_text(re.compile("Skopiowano|skopiuj ręcznie"))

    guest = ui.page()
    guest.goto(url)
    expect(guest.locator("h1")).to_have_text("Udostępniony klip")
    body = guest.locator("body").inner_text()
    assert "III liga" in body and "kroki" in body
    assert not any(secret in body for secret in SECRETS), body
    expect(guest.locator("a[href]:not(#share-download)")).to_have_count(0)
    guest.wait_for_function("document.querySelector('video').readyState >= 1 && document.querySelector('video').duration > 0")
    assert abs(guest.evaluate("document.querySelector('video').duration") - 30.0) < 0.6
    guest.evaluate("document.querySelector('video').play()")
    guest.wait_for_function("document.querySelector('video').currentTime > 0.5")
    guest.evaluate("document.querySelector('video').currentTime = 20")
    guest.wait_for_function("Math.abs(document.querySelector('video').currentTime - 20) < 1.5 && document.querySelector('video').readyState >= 2")
    with guest.expect_download() as download:
        guest.locator("#share-download").click()
    assert download.value.suggested_filename == "III-liga_kroki.mp4"
    assert download.value.path().stat().st_size > 10_000
    assert guest.context.cookies() == []

    coach.goto(f"/clips/{shared['a']}")
    expect(coach.locator("#clip-share .share-list li")).to_have_count(1)
    expect(coach.locator("#clip-share .share-list li")).to_contain_text("wejść: 1")
    coach.on("dialog", lambda d: d.accept())
    coach.get_by_role("button", name="Unieważnij").click()
    expect(coach.locator("#clip-share")).to_contain_text("Brak aktywnych linków")
    guest.reload()
    expect(guest.locator("h1")).to_have_text("Link jest nieaktywny")
    assert guest.locator("video").count() == 0
    assert_code_not_in_server_log(server, url)


def test_kilka_klipow_z_listy_zaznaczenie_przezywa_filtry_i_jeden_zip(ui, server, shared):
    coach = ui.page("coach")
    coach.goto(f"/clips?match_id={shared['match_id']}")
    checks = coach.locator("input.share-check")
    expect(checks).to_have_count(3)
    expect(coach.locator("#share-submit")).to_be_disabled()
    coach.evaluate("window.__bez_przeladowania = true")
    checks.nth(0).check()
    coach.locator("select[name=category_id]").select_option(label="aut")
    expect(checks).to_have_count(1)
    expect(coach.locator("#share-count")).to_have_text("Zaznaczono: 1")
    checks.nth(0).check()
    coach.locator("select[name=category_id]").select_option("")
    expect(checks).to_have_count(3)
    checks.nth(1).check()
    expect(coach.locator("#share-count")).to_have_text("Zaznaczono: 3")
    expect(coach.locator("input.share-check:checked")).to_have_count(3)
    assert coach.evaluate("window.__bez_przeladowania === true")
    coach.locator("#share-form select[name=days]").select_option("30")
    coach.get_by_role("button", name="Udostępnij zaznaczone").click()
    url = created_url(coach)
    expect(coach.locator(".share-contents li")).to_have_count(3)

    guest = ui.page()
    guest.goto(url)
    expect(guest.locator("h1")).to_have_text("Udostępnione klipy")
    expect(guest.locator("video")).to_have_count(3)
    expect(guest.locator("#share-download")).to_have_text("Pobierz wszystkie (3) jako ZIP")
    body = guest.locator("body").inner_text()
    assert not any(secret in body for secret in SECRETS), body
    with guest.expect_download() as download:
        guest.locator("#share-download").click()
    assert download.value.suggested_filename == "klipy.zip"
    archive = zipfile.ZipFile(io.BytesIO(download.value.path().read_bytes()))
    assert archive.namelist() == ["III-liga_kroki.mp4", "III-liga_kroki_2.mp4", "III-liga_aut.mp4"]
    assert archive.testzip() is None and all(i.file_size > 10_000 for i in archive.infolist())
    assert guest.context.cookies() == []
    assert_code_not_in_server_log(server, url)


def test_widok_telefonu_390_px_bez_przewijania_poziomego(ui, server, shared):
    ui.allow(r"status of 404")
    coach = ui.page("coach", mobile=True)
    coach.goto(f"/clips?match_id={shared['match_id']}")
    assert_no_scroll(coach, "lista klipów")
    expect(coach.locator("input.share-check")).to_have_count(3)
    for n in (0, 2):
        coach.locator("input.share-check").nth(n).check()
    expect(coach.locator("#share-count")).to_have_text("Zaznaczono: 2")
    assert_no_scroll(coach, "lista klipów z paskiem udostępniania")
    coach.get_by_role("button", name="Udostępnij zaznaczone").click()
    url = created_url(coach)
    assert_no_scroll(coach, "strona z nowym linkiem")
    coach.goto(f"/clips/{shared['a']}")
    expect(coach.locator("#clip-share")).to_be_visible()
    assert_no_scroll(coach, "strona klipu")

    guest = ui.page(mobile=True)
    guest.goto(url)
    expect(guest.locator("video")).to_have_count(2)
    expect(guest.locator("#share-download")).to_be_visible()
    assert_no_scroll(guest, "strona publiczna")
    guest.goto(f"{server.base_url}/s/{'A' * 43}")
    expect(guest.locator("h1")).to_have_text("Link jest nieaktywny")
    assert_no_scroll(guest, "strona nieaktywnego linku")
