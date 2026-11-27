"""The e2e server has one client address for the whole run, so these tests send only a few reset requests
(the per-IP limit is 5 per 15 minutes) and use their own account instead of the shared ones.
"""
import re
from email import message_from_bytes, policy

from playwright.sync_api import expect

from app import accounts
from tests.e2e.conftest import login
from tests.e2e.support import PASSWORD

NEUTRAL = "Jeśli konto o tym adresie istnieje, wysłaliśmy na nie link do ustawienia nowego hasła. Link jest ważny 60 minut."


def test_login_page_links_to_the_reset_form_and_back(ui):
    page = ui.page()
    page.goto("/login")
    page.get_by_role("link", name="Nie pamiętasz hasła?").click()
    expect(page).to_have_url(ui.server.base_url + "/forgot-password")
    expect(page.get_by_role("heading", name="Nie pamiętasz hasła?")).to_be_visible()
    expect(page.get_by_label("E-mail")).to_be_focused()
    assert page.get_by_label("Nie wypełniaj tego pola").bounding_box()["x"] < 0  # the honeypot is out of sight
    page.get_by_role("link", name="Wróć do logowania").click()
    expect(page).to_have_url(ui.server.base_url + "/login")


def test_an_unknown_address_gets_the_neutral_message_and_no_mail(ui):
    before = len(ui.server.outbox())
    page = ui.page()
    page.goto("/forgot-password")
    page.get_by_label("E-mail").fill("nikt-taki@example.com")
    page.get_by_role("button", name="Wyślij link").click()
    expect(page).to_have_url(ui.server.base_url + "/forgot-password?sent=1")
    expect(page.locator(".banner.ok")).to_have_text(NEUTRAL)
    expect(page.get_by_label("E-mail")).to_have_count(0)
    expect(page.get_by_role("link", name="Wróć do logowania")).to_be_visible()
    assert len(ui.server.outbox()) == before


def test_mailed_link_sets_a_new_password_and_it_works_once(ui):
    email = "zapomniane@example.com"
    with ui.server.db() as db:
        accounts.create_user(db, email=email, name="Zofia Zapominalska", roles=["referee"], password=PASSWORD)
    before = len(ui.server.outbox())
    page = ui.page()
    page.goto("/forgot-password")
    page.get_by_label("E-mail").fill(email)
    page.get_by_role("button", name="Wyślij link").click()
    expect(page.locator(".banner.ok")).to_have_text(NEUTRAL)

    files = ui.server.outbox()
    assert len(files) == before + 1
    message = message_from_bytes(files[-1].read_bytes(), policy=policy.default)
    assert message["Subject"] == "ref-clips — ustawienie nowego hasła" and message["To"].addresses[0].addr_spec == email
    link = re.search(r"https?://\S+/set-password/[\w-]+", message.get_body(("plain",)).get_content()).group(0)
    assert link.startswith(ui.server.base_url)

    page.goto(link)
    expect(page.get_by_role("heading", name="Ustaw hasło")).to_be_visible()
    expect(page.get_by_text("reset hasła")).to_be_visible()
    page.get_by_label("Nowe hasło (min. 10 znaków)").fill("Nowe-haslo-98765")
    page.get_by_label("Powtórz hasło").fill("Nowe-haslo-98765")
    page.get_by_role("button", name="Zapisz hasło").click()
    expect(page).to_have_url(ui.server.base_url + "/login?ok=1")
    expect(page.locator(".banner.ok")).to_have_text("Hasło zostało ustawione. Zaloguj się.")

    login(page, email, "Nowe-haslo-98765")
    expect(page).to_have_url(ui.server.base_url + "/")
    expect(page.locator(".who")).to_contain_text("Zofia Zapominalska")

    ui.allow(r"status of 410")
    again = ui.page()
    again.goto(link)
    expect(again.get_by_role("heading", name="Link nieważny")).to_be_visible()
    expect(again.get_by_role("link", name="poprosić o nowy")).to_be_visible()


def test_reset_pages_fit_a_phone(ui):
    from tests.e2e.test_mobile import overflow

    page = ui.page(mobile=True)
    for path in ("/login", "/forgot-password", "/forgot-password?sent=1", "/set-password/niema"):
        ui.allow(r"status of 410")
        page.goto(path)
        result = overflow(page)
        assert result["bad"] == [] and result["scroll"] <= result["client"], (path, result)
