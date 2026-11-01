"""Scenariusz a) Logowanie: zły login, poprawny, wylogowanie, przekierowanie `next`."""
from playwright.sync_api import expect

from tests.e2e.conftest import login
from tests.e2e.support import USERS


def test_zly_login_pokazuje_komunikat_i_zachowuje_email(ui):
    ui.allow(r"status of 401")  # strona logowania odpowiada 401 — przeglądarka loguje to w konsoli
    page = ui.page()
    login(page, "admin@example.com", "zle-haslo-12345")
    expect(page.locator(".banner.error")).to_have_text("Nieprawidłowy e-mail lub hasło.")
    expect(page).to_have_url(ui.server.base_url + "/login")
    expect(page.get_by_label("E-mail")).to_have_value("admin@example.com")
    expect(page.get_by_label("Hasło")).to_have_value("")


def test_poprawne_logowanie_i_wylogowanie(ui):
    page = ui.page()
    login(page, USERS["coach"][0])
    expect(page).to_have_url(ui.server.base_url + "/")
    expect(page.locator(".who")).to_contain_text("Cezary Trener")
    # szkoleniowiec nie zarządza kontami
    expect(page.get_by_role("link", name="Użytkownicy")).to_have_count(0)

    page.get_by_role("button", name="Wyloguj").click()
    expect(page).to_have_url(ui.server.base_url + "/login")
    page.goto("/")  # po wylogowaniu strona przekierowuje na logowanie
    expect(page).to_have_url(ui.server.base_url + "/login?next=/")


def test_przekierowanie_next_po_zalogowaniu(ui):
    page = ui.page()
    # wejście na chronioną stronę bez sesji przenosi na logowanie z parametrem next
    page.goto("/clips")
    expect(page).to_have_url(ui.server.base_url + "/login?next=/clips")
    page.get_by_label("E-mail").fill(USERS["referee"][0])
    page.get_by_label("Hasło").fill("E2e-haslo-12345")
    page.get_by_role("button", name="Zaloguj").click()
    expect(page).to_have_url(ui.server.base_url + "/clips")
    expect(page.get_by_role("heading", name="Klipy")).to_be_visible()


def test_next_nie_przekierowuje_na_obca_domene(ui):
    page = ui.page()
    login(page, USERS["referee"][0], next_path="//evil.example.com/")
    expect(page).to_have_url(ui.server.base_url + "/")
