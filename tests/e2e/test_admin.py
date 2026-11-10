from playwright.sync_api import expect

from tests.e2e.support import PASSWORD


def test_dodanie_konta_link_zaproszenia_i_logowanie_nowym_kontem(ui):
    admin = ui.page("admin")
    admin.goto("/admin/users")
    admin.get_by_label("Imię i nazwisko").first.fill("Nowy Sędzia")
    admin.get_by_label("E-mail (login)").fill("nowy.sedzia@example.com")
    admin.get_by_label("sędzia").first.check()
    admin.get_by_label("szkoleniowiec").first.check()
    admin.get_by_role("button", name="Utwórz konto i pokaż link").click()

    link_box = admin.locator("#invite-link")
    expect(link_box).to_be_visible()
    expect(admin.locator(".invite-box")).to_contain_text("Nowy Sędzia (nowy.sedzia@example.com)")
    invite_url = link_box.input_value()
    assert "/set-password/" in invite_url
    # PRG: the token is not in the URL, and a refresh neither resubmits the form nor shows the link
    # again.
    expect(admin).to_have_url(ui.server.base_url + "/admin/users")
    expect(admin.locator("tr", has_text="nowy.sedzia@example.com")).to_contain_text("czeka na ustawienie hasła")
    admin.reload()
    expect(admin.get_by_role("heading", name="Konta")).to_be_visible()
    expect(admin.locator("#invite-link")).to_have_count(0)
    assert ui.server.user_by_email("nowy.sedzia@example.com") is not None

    guest = ui.page()
    guest.goto(invite_url)
    expect(guest.get_by_role("heading", name="Ustaw hasło")).to_be_visible()
    expect(guest.locator("body")).to_contain_text("nowy.sedzia@example.com")
    guest.get_by_label("Nowe hasło (min. 10 znaków)").fill(PASSWORD)
    guest.get_by_label("Powtórz hasło").fill(PASSWORD)
    guest.get_by_role("button", name="Zapisz hasło").click()
    expect(guest).to_have_url(ui.server.base_url + "/login?ok=1")
    expect(guest.locator(".banner.ok")).to_contain_text("Hasło zostało ustawione")

    guest.get_by_label("E-mail").fill("nowy.sedzia@example.com")
    guest.get_by_label("Hasło").fill(PASSWORD)
    guest.get_by_role("button", name="Zaloguj").click()
    expect(guest.locator(".who")).to_contain_text("Nowy Sędzia")
    expect(guest.get_by_role("link", name="+ Nowy mecz")).to_be_visible()
    expect(guest.get_by_role("link", name="Użytkownicy")).to_have_count(0)

    token = invite_url.rsplit("/", 1)[-1]
    assert token not in (ui.server.logs / "server.log").read_text(errors="replace")

    ui.allow(r"status of 410")
    again = ui.page()
    again.goto(invite_url)
    expect(again.get_by_role("heading", name="Link nieważny")).to_be_visible()


def test_niezgodne_hasla_pokazuja_blad_w_formularzu(ui):
    ui.allow(r"status of 422")
    admin = ui.page("admin")
    admin.goto("/admin/users")
    admin.get_by_label("Imię i nazwisko").first.fill("Kolejny Trener")
    admin.get_by_label("E-mail (login)").fill("kolejny.trener@example.com")
    admin.get_by_label("szkoleniowiec").first.check()
    admin.get_by_role("button", name="Utwórz konto i pokaż link").click()
    invite_url = admin.locator("#invite-link").input_value()

    guest = ui.page()
    guest.goto(invite_url)
    guest.get_by_label("Nowe hasło (min. 10 znaków)").fill(PASSWORD)
    guest.get_by_label("Powtórz hasło").fill(PASSWORD + "x")
    guest.get_by_role("button", name="Zapisz hasło").click()
    expect(guest.locator(".banner.error")).to_have_text("Hasła nie są takie same.")
