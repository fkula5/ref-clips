"""Scenariusz h): strona klipu — odtwarzanie pliku klipu, kwarta i czas, komentarze przez HTMX."""
import re

from playwright.sync_api import Page, expect

CLIP_VIDEO = "document.getElementById('clip-video')"


def cut_clip(ui, time_sec, *, marks=(("Q1", 10.0), ("Q2", 40.0)), role="admin", mobile=False):
    """Mecz, nagranie ze znacznikami kwart i klip, który wycina prawdziwy worker."""
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    for period, at in marks:
        ui.server.set_mark(video_id, period, at)
    clip_id = ui.server.create_clip(video_id, time_sec)
    page = ui.page(role, mobile=mobile)
    page.goto(f"/clips/{clip_id}")
    return page, clip_id


def wait_clip_ready(page: Page) -> None:
    # strona sama podmienia sekcję, gdy worker skończy cięcie (hx-trigger every 3s)
    expect(page.locator("#clip-video")).to_be_visible(timeout=60_000)
    page.wait_for_function(f"{CLIP_VIDEO}.readyState >= 1 && {CLIP_VIDEO}.duration > 0")


def test_klip_odtwarza_plik_30_s_z_kwarta_i_czasem_od_poczatku_kwarty(ui):
    page, clip_id = cut_clip(ui, 30.0)  # klip 15–45 s; Q1 zaczyna się w 10 s
    page.evaluate("window.__bez_przeladowania = true")
    wait_clip_ready(page)
    assert page.evaluate("window.__bez_przeladowania === true"), "oczekiwanie na klip przeładowało stronę"
    duration = page.evaluate(f"{CLIP_VIDEO}.duration")
    assert abs(duration - 30.0) < 0.6, duration
    assert page.evaluate(f"{CLIP_VIDEO}.videoWidth") > 0

    expect(page.locator("aside .card").first).to_contain_text("Q1 · 0:20 od początku kwarty (czas nagrania)")
    expect(page.locator("h1")).to_contain_text("0:30")
    expect(page.locator(".badge.cut").first).to_have_text("wycięty")
    expect(page.get_by_role("link", name="Pobierz MP4")).to_have_attribute("href", f"/clips/{clip_id}/download")

    # odtwarzanie rzeczywiście idzie
    page.evaluate(f"{CLIP_VIDEO}.play()")
    page.wait_for_function(f"{CLIP_VIDEO}.currentTime > 0.5")
    # link do pełnego nagrania wraca w to samo miejsce
    page.get_by_role("link", name="pokaż w pełnym nagraniu").click()
    page.wait_for_function("document.getElementById('player').readyState >= 1")
    page.wait_for_function("Math.abs(document.getElementById('player').currentTime - 30) < 0.5")


def test_klip_przy_poczatku_nagrania_jest_krotszy(ui):
    page, _ = cut_clip(ui, 5.0, marks=())  # 0–20 s: margines przed obcięty do początku nagrania
    wait_clip_ready(page)
    duration = page.evaluate(f"{CLIP_VIDEO}.duration")
    assert abs(duration - 20.0) < 0.6, duration
    expect(page.locator("aside .card").first).to_contain_text("kwarta nieustalona")


def test_komentarz_dodany_i_usuniety_przez_htmx_bez_przeladowania(ui):
    page, _ = cut_clip(ui, 30.0)
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")
    page.evaluate("window.__bez_przeladowania = true")
    page.on("dialog", lambda d: d.accept())  # hx-confirm przy usuwaniu

    box = page.get_by_label("Nowy komentarz")
    box.fill("Moim zdaniem prawidłowa decyzja.")
    page.get_by_role("button", name="Dodaj komentarz").click()
    comment = page.locator("#comments .comment")
    expect(comment).to_have_count(1)
    expect(comment).to_contain_text("Adam Admin")
    expect(comment).to_contain_text("Moim zdaniem prawidłowa decyzja.")
    expect(box).to_have_value("")  # formularz wyczyszczony (hx-on::after-request)
    expect(page.locator("#no-comments")).to_have_text("")
    assert page.evaluate("window.__bez_przeladowania === true")

    # drugi komentarz; treść jest tekstem, nie HTML
    box.fill("<b>pogrubione</b> & drugi")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comments .comment")).to_have_count(2)
    expect(page.locator("#comments .comment").nth(1).locator(".body")).to_have_text("<b>pogrubione</b> & drugi")

    # usunięcie pierwszego
    page.locator("#comments .comment").first.get_by_role("button", name="Usuń").click()
    expect(page.locator("#comments .comment")).to_have_count(1)
    expect(page.locator("#comments")).not_to_contain_text("Moim zdaniem")
    page.locator("#comments .comment").first.get_by_role("button", name="Usuń").click()
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")
    assert page.evaluate("window.__bez_przeladowania === true")


def test_cudzego_komentarza_nie_mozna_usunac(ui):
    page, clip_id = cut_clip(ui, 30.0)
    page.get_by_label("Nowy komentarz").fill("Komentarz admina")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comments .comment")).to_have_count(1)

    other = ui.page("outsider")
    other.goto(f"/clips/{clip_id}")
    expect(other.locator("#comments .comment")).to_contain_text("Komentarz admina")
    expect(other.locator("#comments .comment").get_by_role("button", name="Usuń")).to_have_count(0)
    # każdy zalogowany może komentować
    other.get_by_label("Nowy komentarz").fill("Komentarz sędziego")
    other.get_by_role("button", name="Dodaj komentarz").click()
    expect(other.locator("#comments .comment")).to_have_count(2)
    # sędzia spoza obsady nie opisuje klipu
    expect(other.get_by_role("button", name="Zapisz opis")).to_have_count(0)


def test_opis_klipu_pole_wlasnej_kategorii(ui):
    page, _ = cut_clip(ui, 30.0)
    custom = page.locator("#custom-label")
    expect(custom).to_be_hidden()
    page.locator("#category-select").select_option(label="własna")
    expect(custom).to_be_visible()
    page.locator("#category-select").select_option(label="kroki")
    expect(custom).to_be_hidden()
    page.locator("#category-select").select_option(label="własna")
    page.locator("input[name=custom_category]").fill("ustawienie przy autach")
    page.get_by_label("CC · Roman Sędzia").check()
    page.locator("textarea[name=description]").fill("Sytuacja przy linii bocznej")
    page.get_by_role("button", name="Zapisz opis").click()
    expect(page.locator("#clip-info")).not_to_contain_text("nieopisany")
    expect(page.locator("#clip-info")).to_contain_text("ustawienie przy autach")
    expect(page.locator("input[name=custom_category]")).to_have_value("ustawienie przy autach")


def test_strona_klipu_na_telefonie(ui):
    page, _ = cut_clip(ui, 30.0, mobile=True)
    wait_clip_ready(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("#clip-video").bounding_box()["width"] <= 390
    assert abs(page.evaluate(f"{CLIP_VIDEO}.duration") - 30.0) < 0.6
    page.get_by_label("Nowy komentarz").fill("Z telefonu")
    page.get_by_role("button", name="Dodaj komentarz").tap()
    expect(page.locator("#comments .comment")).to_have_count(1)
