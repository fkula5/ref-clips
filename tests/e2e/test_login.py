from playwright.sync_api import expect

from tests.e2e.conftest import login
from tests.e2e.support import USERS


def test_wrong_login_shows_a_message_and_keeps_the_email(ui):
    ui.allow(r"status of 401")
    page = ui.page()
    login(page, "admin@example.com", "zle-haslo-12345")
    expect(page.locator(".banner.error")).to_have_text("Nieprawidłowy e-mail lub hasło.")
    expect(page).to_have_url(ui.server.base_url + "/login")
    expect(page.get_by_label("E-mail")).to_have_value("admin@example.com")
    expect(page.get_by_label("Hasło")).to_have_value("")


def test_successful_login_and_logout(ui):
    page = ui.page()
    login(page, USERS["coach"][0])
    expect(page).to_have_url(ui.server.base_url + "/")
    expect(page.locator(".who")).to_contain_text("Cezary Trener")
    expect(page.get_by_role("link", name="Użytkownicy")).to_have_count(0)

    page.get_by_role("button", name="Wyloguj").click()
    expect(page).to_have_url(ui.server.base_url + "/login")
    page.goto("/")
    expect(page).to_have_url(ui.server.base_url + "/login?next=/")


def test_next_redirect_after_login(ui):
    page = ui.page()
    page.goto("/clips")
    expect(page).to_have_url(ui.server.base_url + "/login?next=/clips")
    page.get_by_label("E-mail").fill(USERS["referee"][0])
    page.get_by_label("Hasło").fill("E2e-haslo-12345")
    page.get_by_role("button", name="Zaloguj").click()
    expect(page).to_have_url(ui.server.base_url + "/clips")
    expect(page.get_by_role("heading", name="Klipy")).to_be_visible()


def test_next_does_not_redirect_to_a_foreign_domain(ui):
    page = ui.page()
    login(page, USERS["referee"][0], next_path="//evil.example.com/")
    expect(page).to_have_url(ui.server.base_url + "/")


def test_a_mistyped_address_keeps_the_logged_in_header_and_the_way_back(ui):
    ui.allow(r"status of 404")
    page = ui.page("coach")
    page.goto("/groups/1/coachs")
    expect(page.get_by_role("heading", name="Nie znaleziono")).to_be_visible()
    expect(page.locator(".who")).to_contain_text("Cezary Trener")
    page.get_by_role("link", name="Lista meczów").click()
    expect(page).to_have_url(ui.server.base_url + "/")
