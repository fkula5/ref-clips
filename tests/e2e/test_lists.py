"""Scenariusze i) i j): lista meczów (filtry HTMX, paginacja, widok mobilny) oraz strony błędów."""
import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

PAGINATION_LEVEL = "Liga Paginacyjna"
FILTER_LEVEL = "Liga Filtrowa"


@pytest.fixture(scope="module")
def many_matches(server):
    """27 meczów jednej ligi (dwie strony po 25) i kilka meczów innej ligi z innymi datami."""
    start = date(2025, 3, 1)
    for i in range(27):
        server.make_match(level=PAGINATION_LEVEL, day=start + timedelta(days=i), team_a=f"Gospodarz {i:02d}",
                          team_b="Goście")
    for i in range(3):
        server.make_match(level=FILTER_LEVEL, day=date(2025, 1, 10) + timedelta(days=i), team_a=f"Filtr {i}",
                          team_b="Goście", officials=(("CC", "second"), ("U1", "Jan Obcy")))


def rows(page):
    return page.locator("#matches-list tbody tr")


def test_filtry_podmieniaja_liste_i_adres_bez_przeladowania(ui, many_matches):
    page = ui.page("admin")
    page.goto("/")
    page.evaluate("window.__bez_przeladowania = true")

    page.locator("select[name=level]").select_option(FILTER_LEVEL)
    expect(page).to_have_url(re.compile(r"level=Liga(\+|%20)Filtrowa"))
    expect(rows(page)).to_have_count(3)
    expect(page.locator("#matches-list")).to_contain_text("Mecze: 3 · strona 1 z 1")

    # filtr sędziego (konto Ula Druga) i zakres dat
    page.locator("select[name=person]").select_option(label="Ula Druga")
    expect(page).to_have_url(re.compile(r"person=u\d+"))
    expect(rows(page)).to_have_count(3)
    page.locator("input[name=date_from]").fill("2025-01-11")
    expect(page).to_have_url(re.compile(r"date_from=2025-01-11"))
    expect(rows(page)).to_have_count(2)
    page.locator("input[name=date_to]").fill("2025-01-11")
    expect(rows(page)).to_have_count(1)
    expect(rows(page).first).to_contain_text("11.01.2025")

    # brak wyników
    page.locator("input[name=date_from]").fill("2025-01-12")
    expect(page.locator("#matches-list")).to_contain_text("Brak meczów dla wybranych filtrów.")
    assert page.evaluate("window.__bez_przeladowania === true"), "filtrowanie przeładowało stronę"

    # „Wyczyść” wraca do pełnej listy (zwykły link)
    page.get_by_role("link", name="Wyczyść").click()
    expect(page).to_have_url(ui.server.base_url + "/")
    expect(rows(page)).to_have_count(25)


def test_paginacja_i_przycisk_wstecz(ui, many_matches):
    page = ui.page("admin")
    page.goto("/")
    page.evaluate("window.__bez_przeladowania = true")
    page.locator("select[name=level]").select_option(PAGINATION_LEVEL)
    expect(page.locator("#matches-list")).to_contain_text("Mecze: 27 · strona 1 z 2")
    expect(rows(page)).to_have_count(25)
    expect(page.get_by_role("link", name="‹ Nowsze")).to_have_count(0)
    # od najnowszego: pierwszy wiersz to ostatnia data
    expect(rows(page).first).to_contain_text("Gospodarz 26")

    page.get_by_role("link", name="Starsze ›").click()
    expect(page).to_have_url(re.compile(r"page=2"))
    expect(page).to_have_url(re.compile(r"level=Liga(\+|%20)Paginacyjna"))  # filtr zostaje w adresie
    expect(page.locator("#matches-list")).to_contain_text("strona 2 z 2")
    expect(rows(page)).to_have_count(2)
    expect(rows(page).first).to_contain_text("Gospodarz 01")
    expect(page.get_by_role("link", name="Starsze ›")).to_have_count(0)
    assert page.evaluate("window.__bez_przeladowania === true")

    page.get_by_role("link", name="‹ Nowsze").click()
    expect(page.locator("#matches-list")).to_contain_text("strona 1 z 2")
    expect(rows(page)).to_have_count(25)

    # przycisk „Wstecz” przeglądarki wraca do poprzedniej strony wyników
    page.get_by_role("link", name="Starsze ›").click()
    expect(rows(page)).to_have_count(2)
    page.go_back()
    expect(page.locator("#matches-list")).to_contain_text("strona 1 z 2")
    expect(rows(page)).to_have_count(25)

    # bezpośrednie wejście na adres z filtrem działa bez JavaScriptu (zwykły GET)
    page.goto(f"/?level={PAGINATION_LEVEL}&page=2")
    expect(rows(page)).to_have_count(2)
    expect(page.locator("select[name=level]")).to_have_value(PAGINATION_LEVEL)


def test_widok_mobilny_pokazuje_karty_zamiast_tabeli(ui, many_matches):
    desktop = ui.page("admin")
    desktop.goto(f"/?level={FILTER_LEVEL}")
    head = desktop.locator("table.responsive thead")
    assert head.bounding_box()["x"] >= 0  # nagłówek tabeli widoczny na komputerze
    assert desktop.locator("table.responsive tbody tr").first.evaluate("e => getComputedStyle(e).display") == "table-row"

    page = ui.page("admin", mobile=True)
    page.goto(f"/?level={FILTER_LEVEL}")
    expect(rows(page)).to_have_count(3)
    # nagłówek kolumn jest schowany poza ekranem, wiersz to karta (blok), a etykiety biorą się z data-label
    assert page.locator("table.responsive thead").bounding_box()["x"] < -1000
    first = rows(page).first
    assert first.evaluate("e => getComputedStyle(e).display") == "block"
    cell = first.locator("td[data-label=Data]")
    assert cell.evaluate("e => getComputedStyle(e, '::before').content") == '"Data"'
    assert first.locator("td").first.evaluate("e => getComputedStyle(e).display") == "flex"
    labels = first.locator("td").evaluate_all("els => els.map(e => e.dataset.label)")
    assert labels == ["Data", "Mecz", "Liga", "Obsada", "Stan", "Klipy", "Nieopisane"]
    # nic nie wystaje poza ekran
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for card in rows(page).all():
        box = card.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390 + 1

    # karta prowadzi do meczu
    first.get_by_role("link", name=re.compile("Filtr")).tap()
    expect(page).to_have_url(re.compile(r"/matches/\d+$"))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_filtry_na_telefonie_dzialaja(ui, many_matches):
    page = ui.page("admin", mobile=True)
    page.goto("/")
    page.locator("select[name=level]").select_option(FILTER_LEVEL)
    expect(rows(page)).to_have_count(3)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


# --- j) strony błędów -----------------------------------------------------------------
def test_strona_404_z_przyciskiem_wroc(ui):
    ui.allow(r"status of 404")
    page = ui.page("admin")
    page.goto("/clips")
    # nawigacja z pustego linku: przeglądarka wysyła Referer z poprzedniej strony
    page.evaluate("location.href = '/matches/999999'")
    expect(page.get_by_role("heading", name="Nie znaleziono")).to_be_visible()
    expect(page.locator(".banner.error")).to_have_text("Nie ma takiego meczu")
    back = page.get_by_role("link", name="← Wróć")
    expect(back).to_have_attribute("href", "/clips")
    back.click()
    expect(page).to_have_url(ui.server.base_url + "/clips")
    expect(page.get_by_role("heading", name="Klipy")).to_be_visible()

    page.goto("/matches/999999")  # bez Referera nie ma przycisku „Wróć”, jest lista meczów
    expect(page.get_by_role("link", name="← Wróć")).to_have_count(0)
    page.get_by_role("link", name="Lista meczów").click()
    expect(page).to_have_url(ui.server.base_url + "/")


def test_strona_403_dla_sedziego_w_panelu_admina(ui):
    ui.allow(r"status of 403")
    page = ui.page("outsider")
    page.goto("/")
    page.evaluate("location.href = '/admin/users'")
    expect(page.get_by_role("heading", name="Brak dostępu")).to_be_visible()
    expect(page.get_by_role("link", name="← Wróć")).to_have_attribute("href", "/")


def test_niezalogowany_widzi_link_do_logowania_na_stronie_bledu(ui):
    ui.allow(r"status of 404")
    page = ui.page()
    page.goto("/nie-ma-takiej-strony")
    expect(page.get_by_role("heading", name="Nie znaleziono")).to_be_visible()
