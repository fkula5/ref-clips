from playwright.sync_api import expect

from tests.e2e.support import USERS


def test_settings_toggles_persist_and_follow_the_role(ui):
    page = ui.page("referee")
    page.goto("/")
    page.get_by_role("link", name="Ustawienia powiadomień").click()
    page.wait_for_url("**/settings/notifications")
    form = page.locator("#notification-settings")
    expect(page.get_by_role("heading", name="Ustawienia powiadomień")).to_be_visible()
    expect(form.get_by_label("Wysyłaj maile")).to_be_checked()
    expect(form.get_by_label("Komentarze i oceny dotyczące mnie")).to_be_checked()
    expect(form.get_by_label("Opublikowane arkusze oceny moich meczów")).to_be_checked()
    expect(form.get_by_label("Nowe mecze sędziów z moich grup")).to_have_count(0)  # a referee does not coach groups
    expect(page.get_by_role("button", name="Wyślij mi testowe podsumowanie")).to_have_count(0)

    form.get_by_label("Dodanie mnie do grupy").uncheck()
    form.get_by_label("Opublikowane arkusze oceny moich meczów").uncheck()
    form.get_by_role("button", name="Zapisz").click()
    expect(page.locator("#page-notice")).to_have_text("Zapisano ustawienia powiadomień.")
    page.reload()
    expect(form.get_by_label("Dodanie mnie do grupy")).not_to_be_checked()
    expect(form.get_by_label("Opublikowane arkusze oceny moich meczów")).not_to_be_checked()
    expect(form.get_by_label("Komentarze i oceny dotyczące mnie")).to_be_checked()

    form.get_by_label("Wysyłaj maile").uncheck()
    form.get_by_label("Dodanie mnie do grupy").check()
    form.get_by_label("Opublikowane arkusze oceny moich meczów").check()
    form.get_by_role("button", name="Zapisz").click()
    page.goto("/settings/notifications")
    expect(form.get_by_label("Wysyłaj maile")).not_to_be_checked()
    expect(form.get_by_label("Dodanie mnie do grupy")).to_be_checked()
    form.get_by_label("Wysyłaj maile").check()  # leave the shared server as it was
    form.get_by_role("button", name="Zapisz").click()
    expect(page.locator("#page-notice")).to_be_visible()

    coach = ui.page("coach")
    coach.goto("/settings/notifications")
    expect(coach.locator("#notification-settings").get_by_label("Nowe mecze sędziów z moich grup")).to_be_checked()


def test_admin_test_button_sends_a_message_to_the_admin(ui):
    page = ui.page("admin")
    page.goto("/settings/notifications")
    before = len(ui.server.outbox())
    page.get_by_role("button", name="Wyślij mi testowe podsumowanie").click()
    expect(page.locator("#settings-notice")).to_contain_text(f"Wysłano wiadomość testową na adres {USERS['admin'][0]}")
    files = ui.server.outbox()
    assert len(files) == before + 1
    raw = files[-1].read_bytes()
    assert b"Subject: [TEST] ref-clips" in raw and b"List-Unsubscribe-Post: List-Unsubscribe=One-Click" in raw


def test_unsubscribe_page_needs_a_click_and_works_without_logging_in(ui):
    ui.allow(r"status of 404")  # the wrong token below
    token = ui.server.unsubscribe_token("second")
    page = ui.page()
    page.goto(f"/unsubscribe/{token}")
    expect(page.get_by_role("heading", name="Wyłączyć wszystkie maile?")).to_be_visible()
    assert ui.server.email_preference("second").digest_enabled is True  # opening the link changed nothing

    page.get_by_role("button", name="Wyłącz wszystkie maile").click()
    expect(page.get_by_role("heading", name="Maile wyłączone")).to_be_visible()
    assert ui.server.email_preference("second").digest_enabled is False
    page.goto(f"/unsubscribe/{token}")
    expect(page.get_by_role("heading", name="Maile wyłączone")).to_be_visible()

    page.goto("/unsubscribe/" + "A" * 43)
    expect(page.get_by_role("heading", name="Link jest nieprawidłowy")).to_be_visible()

    owner = ui.page("second")
    owner.goto("/settings/notifications")
    expect(owner.get_by_label("Wysyłaj maile")).not_to_be_checked()
    owner.get_by_label("Wysyłaj maile").check()
    owner.get_by_role("button", name="Zapisz").click()
    expect(owner.locator("#page-notice")).to_be_visible()
