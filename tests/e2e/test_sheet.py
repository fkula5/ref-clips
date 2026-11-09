"""Scenario: the qualifier's assessment sheet in the browser: a coach fills it in and publishes, a crew referee
reads it, an outsider cannot, the phone layout (390 px) and the print stylesheet."""
from playwright.sync_api import expect

from tests.e2e.conftest import MOBILE


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def open_form(page, match_id):
    page.goto(f"/matches/{match_id}")
    page.get_by_role("button", name="Wypełnij arkusz").click()
    expect(page.get_by_role("heading", name="Arkusz oceny sędziów")).to_be_visible()


def test_trener_wypelnia_i_publikuje_a_sedzia_z_obsady_czyta(ui):
    match_id = ui.server.make_match()   # CC = Roman Sędzia (konto), U1 = Kasia Żółć (wpisana)
    coach = ui.page("coach")
    open_form(coach, match_id)
    expect(coach.locator("#page-notice")).to_contain_text("Założono arkusz jako szkic")
    coach.get_by_label("Mechanika, CC · Roman Sędzia").fill("Pewne ustawienie.\nDobra rotacja.")
    coach.get_by_label("Wynik").fill("78:65")

    # leaving with unsaved text asks first; saving does not (no false alarm on submit)
    dialogs = []
    watch = lambda d: (dialogs.append(d.type), d.dismiss())   # noqa: E731
    coach.on("dialog", watch)
    coach.get_by_role("link", name="Anuluj").click()
    assert dialogs == ["beforeunload"] and "/edit" in coach.url
    dialogs.clear()
    coach.get_by_role("button", name="Zapisz szkic").click()
    expect(coach.locator("#page-notice")).to_contain_text("Zapisano szkic")
    assert dialogs == []
    coach.remove_listener("dialog", watch)
    expect(coach.get_by_label("Mechanika, CC · Roman Sędzia")).to_have_value("Pewne ustawienie.\nDobra rotacja.")

    # a crew referee does not see the draft
    referee = ui.page("referee")
    referee.goto(f"/matches/{match_id}")
    expect(referee.locator("#sheet-card")).not_to_contain_text("Cezary Trener")

    # publishing needs a difficulty, then asks for confirmation that states the empty fields
    ui.allow(r"status of 42[2]")
    coach.get_by_role("button", name="Opublikuj").click()
    expect(coach.locator("#sheet-errors")).to_contain_text("stopień trudności")
    expect(coach.get_by_label("Mechanika, CC · Roman Sędzia")).to_have_value("Pewne ustawienie.\nDobra rotacja.")
    coach.locator("select[name=difficulty]").select_option("trudny")
    messages = []
    coach.once("dialog", lambda d: (messages.append(d.message), d.dismiss()))
    coach.get_by_role("button", name="Opublikuj").click()
    assert "Puste pola: 24 z 25" in messages[0] and "/edit" in coach.url   # dismissed: nothing happens
    coach.once("dialog", lambda d: d.accept())
    coach.get_by_role("button", name="Opublikuj").click()
    expect(coach.locator("#page-notice")).to_contain_text("Opublikowano arkusz. Puste pola: 24 z 25")
    expect(coach.locator("#sheet-elements")).to_contain_text("Pewne ustawienie.")

    # the crew referee now sees it on the match page and can read it; an outsider cannot
    referee.goto(f"/matches/{match_id}")
    expect(referee.locator("#sheet-card")).to_contain_text("Cezary Trener")
    referee.get_by_role("link", name="Otwórz").click()
    expect(referee.locator("#sheet-elements")).to_contain_text("Dobra rotacja.")
    expect(referee.get_by_role("link", name="Edytuj")).to_have_count(0)
    outsider = ui.page("outsider")
    outsider.goto(f"/matches/{match_id}")
    expect(outsider.locator("#sheet-card")).to_have_count(0)
    ui.allow(r"status of 404")
    outsider.goto(referee.url)
    expect(outsider.get_by_role("heading", name="Nie znaleziono")).to_be_visible()


def test_uklad_na_telefonie_bez_przewijania_w_bok(ui):
    match_id = ui.server.make_match()
    page = ui.page("coach", mobile=True)
    assert page.viewport_size["width"] == MOBILE["width"] == 390
    open_form(page, match_id)
    field = page.get_by_label("Mechanika, CC · Roman Sędzia")
    field.fill("Tekst na telefonie " * 20)
    expect(field).to_be_visible()
    assert field.bounding_box()["width"] > 250 and no_horizontal_scroll(page)
    page.once("dialog", lambda d: d.accept())   # leaving with unsaved text
    page.get_by_role("link", name="Podgląd").click()
    expect(page.locator("#sheet-elements")).to_be_visible()
    assert no_horizontal_scroll(page)


def test_arkusz_do_wydruku_bez_nawigacji_i_przyciskow(ui):
    match_id = ui.server.make_match()
    page = ui.page("coach")
    open_form(page, match_id)
    page.get_by_label("Wynik").fill("70:60")
    page.locator("select[name=difficulty]").select_option("normalny")
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Opublikuj").click()
    expect(page.get_by_role("button", name="Drukuj / zapisz jako PDF")).to_be_visible()
    expect(page.locator("header.top")).to_be_visible()
    page.emulate_media(media="print")
    for hidden in ("header.top", ".app-version", "#page-notice", "#sheet-print", ".no-print"):
        expect(page.locator(hidden).first).to_be_hidden()
    expect(page.get_by_role("heading", name="Arkusz oceny sędziów")).to_be_visible()
    expect(page.locator("#sheet-elements")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.querySelector('.sheet-table tr')).breakInside") == "avoid"
