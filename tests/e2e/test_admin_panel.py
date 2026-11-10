from datetime import timedelta

from playwright.sync_api import expect

from app.models import UploadRejection, User, Video
from app.timeutil import utcnow
from tests.e2e.support import wait_until


def accept_dialogs(page):
    page.on("dialog", lambda dialog: dialog.accept())


def category_row(page, name):
    return page.locator("tr[data-category]").filter(has=page.locator(f'input[name="name"][value="{name}"]'))


def test_admin_adds_and_deactivates_a_category_and_the_describe_form_loses_it(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1")
    ui.server.set_mark(video_id, "Q1", 0.0)
    fresh_clip = ui.server.insert_clip(video_id, 20.0, status="new")

    admin = ui.page("admin")
    accept_dialogs(admin)
    admin.goto("/admin/users")
    admin.get_by_role("link", name="Kategorie").click()
    expect(admin.get_by_role("heading", name="Kategorie klipów")).to_be_visible()

    ui.allow(r"status of 422")
    form = admin.locator("#new-category")
    form.get_by_label("Nazwa").fill("Faul w ataku")
    form.get_by_label("Aliasy (po przecinku, opcjonalnie)").fill("krok")
    form.get_by_role("button", name="Dodaj kategorię").click()
    expect(admin.locator("#admin-error")).to_contain_text("„krok” jest już używany przez kategorię „kroki”")
    expect(admin.locator('#new-category input[name="name"]')).to_have_value("Faul w ataku")

    form.get_by_label("Aliasy (po przecinku, opcjonalnie)").fill("faul atakujacego")
    form.get_by_role("button", name="Dodaj kategorię").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Dodano kategorię „Faul w ataku”")
    expect(category_row(admin, "Faul w ataku")).to_contain_text("aktywna")

    page = ui.page("admin")
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(1)

    described = ui.server.insert_clip(video_id, 30.0, official="CC", category="Faul w ataku", described=True)
    category_row(admin, "Faul w ataku").get_by_role("button", name="Dezaktywuj").click()
    expect(admin.locator("#admin-notice")).to_contain_text("„Faul w ataku” jest teraz nieaktywna")
    expect(category_row(admin, "Faul w ataku")).to_contain_text("nieaktywna")
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(0)
    page.goto(f"/clips/{described}")
    expect(page.locator("#category-select option:checked")).to_have_text("Faul w ataku (nieaktywna)")
    page.get_by_role("button", name="Zapisz opis").click()
    expect(page).to_have_url(ui.server.base_url + f"/clips/{described}")
    assert ui.server.clip(described).category_id is not None
    expect(page.locator("#clip-info")).to_contain_text("Faul w ataku")
    expect(category_row(admin, "Faul w ataku").get_by_role("button", name="Usuń")).to_have_count(0)

    own = category_row(admin, "własna")
    expect(own.get_by_role("button", name="Dezaktywuj")).to_have_count(0)
    expect(own.get_by_role("button", name="Usuń")).to_have_count(0)

    form.get_by_label("Nazwa").fill("Tymczasowa")
    form.get_by_role("button", name="Dodaj kategorię").click()
    category_row(admin, "Tymczasowa").get_by_role("button", name="Usuń").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Usunięto kategorię „Tymczasowa”")
    expect(category_row(admin, "Tymczasowa")).to_have_count(0)
    category_row(admin, "Faul w ataku").get_by_role("button", name="Aktywuj").click()
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(1)


def test_admin_changes_retention_days_with_validation_and_the_recalculate_option(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id)
    with ui.server.db() as db:
        video = db.get(Video, video_id)
        video.expires_at = video.created_at + timedelta(days=30)
        db.commit()
        before = video.expires_at

    admin = ui.page("admin")
    accept_dialogs(admin)
    admin.goto("/admin/retention")
    ui.allow(r"status of 422")
    days = admin.locator('#retention-form input[name="days"]')
    days.evaluate("el => { el.removeAttribute('min'); el.removeAttribute('max'); }")  # bypass HTML5 validation
    days.fill("0")
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-error")).to_contain_text("Liczba dni retencji musi mieścić się w zakresie 1–365")
    expect(admin.locator('#retention-form input[name="days"]')).to_have_value("0")

    admin.locator('#retention-form input[name="days"]').fill("14")
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-notice")).to_contain_text("14 dni")
    expect(admin.locator('#retention-form input[name="days"]')).to_have_value("14")
    with ui.server.db() as db:
        assert db.get(Video, video_id).expires_at == before

    admin.get_by_label("przelicz termin dla istniejących nagrań").check()
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-notice")).to_contain_text("Przeliczono termin")
    with ui.server.db() as db:
        video = db.get(Video, video_id)
        assert video.expires_at == video.created_at + timedelta(days=14)


def test_admin_sees_the_disk_and_removes_the_full_recording_early_while_clips_still_play(ui):
    match_id = ui.server.make_match(team_a="Zniknie", team_b="Nagranie")
    video_id = ui.server.make_ready_video(match_id, content="Q1")
    ui.server.set_mark(video_id, "Q1", 0.0)
    clip_id = ui.server.create_clip(video_id, 25.0)
    page = ui.page("admin")
    accept_dialogs(page)
    page.goto("/admin/retention")

    wait_until(page, lambda: ui.server.clip(clip_id).status == "cut", timeout=60, message="klip nie został wycięty")
    page.goto("/admin/retention")
    for ident in ("u-drafts", "u-clips", "u-free", "u-reserved"):
        expect(page.locator(f"#{ident}")).to_be_visible()
    expect(page.locator("#u-clips")).not_to_have_text("0 B")
    row = page.locator("tr[data-video]").filter(has_text="Zniknie – Nagranie")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("MB")
    page.goto(f"/clips/{clip_id}")
    page.wait_for_function("document.getElementById('clip-video').readyState >= 1")

    page.goto("/admin/retention")
    row = page.locator("tr[data-video]").filter(has_text="Zniknie – Nagranie")
    row.get_by_role("button", name="Usuń pełne nagranie teraz").click()
    expect(page.locator("#admin-notice")).to_contain_text("Usunięto pełne nagranie")
    expect(page.locator("tr[data-video]").filter(has_text="Zniknie – Nagranie")).to_have_count(0)

    viewer = ui.page("admin")
    viewer.goto(f"/matches/{match_id}")
    expect(viewer.locator("#match-state")).to_contain_text("pełne nagranie usunięte")
    expect(viewer.get_by_role("link", name="Odtwarzacz")).to_have_count(0)
    viewer.goto(f"/videos/{video_id}")
    expect(viewer.locator("#purged-banner")).to_be_visible()
    expect(viewer.locator("video")).to_have_count(0)
    expect(viewer.locator("#btn-z")).to_have_count(0)
    for key in ("z", "m", "q", "Backspace", "?"):
        viewer.keyboard.press(key)
    viewer.wait_for_timeout(500)
    assert len(ui.server.clips_of(video_id)) == 1
    assert ui.server.marks_of(video_id) == {"Q1": 0.0}

    clip_page = ui.page("admin")
    clip_page.goto(f"/clips/{clip_id}")
    clip_page.wait_for_function("document.getElementById('clip-video').readyState >= 1 "
                                "&& document.getElementById('clip-video').duration > 0")
    clip_page.evaluate("document.getElementById('clip-video').play()")
    clip_page.wait_for_function("document.getElementById('clip-video').currentTime > 0.5")
    expect(clip_page.get_by_role("link", name="pokaż w pełnym nagraniu")).to_have_count(0)


def test_available_for_x_more_days_note_on_the_list_and_the_match_page(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id)
    with ui.server.db() as db:
        db.get(Video, video_id).expires_at = utcnow() + timedelta(days=2, hours=3)
        db.commit()
    page = ui.page("coach")
    page.goto(f"/matches/{match_id}")
    expect(page.locator("#expiry-note")).to_have_text("pełne nagranie dostępne jeszcze 3 dni")
    page.goto("/")
    expect(page.locator("tr", has_text="Legia – Wisła").first.locator(".expiry-note")).to_have_text(
        "pełne nagranie dostępne jeszcze 3 dni")


def test_banner_about_uploads_rejected_for_lack_of_space(ui):
    with ui.server.db() as db:
        db.add(UploadRejection(created_at=utcnow(), user_id=ui.server.users["coach"], filename="ogromny-mecz.mp4",
                               size_bytes=6 * 1024 ** 3, free_bytes=2 * 1024 ** 3))
        db.commit()
    admin = ui.page("admin")
    admin.goto("/admin/users")
    expect(admin.locator("#rejected-banner")).to_contain_text("Brak miejsca na dysku")
    admin.get_by_role("link", name="Zobacz szczegóły").click()
    expect(admin).to_have_url(ui.server.base_url + "/admin/retention#odrzucone")
    expect(admin.locator("#odrzucone")).to_contain_text("ogromny-mecz.mp4")
    expect(admin.locator("#odrzucone")).to_contain_text("6,0 GB")
    expect(admin.locator("#odrzucone")).to_contain_text(ui.server.user_name("coach"))


def test_non_admin_does_not_see_the_panel(ui):
    for role in ("coach", "referee"):
        page = ui.page(role)
        page.goto("/")
        expect(page.get_by_role("link", name="Administracja")).to_have_count(0)
    ui.allow(r"status of 403")
    page = ui.page("coach")
    for path in ("/admin/users", "/admin/categories", "/admin/retention"):
        response = page.goto(path)
        assert response.status == 403, path
        expect(page.get_by_role("heading", name="Brak dostępu")).to_be_visible()
        expect(page.locator(".admin-tabs")).to_have_count(0)


def test_admin_table_row_cells_have_one_height(ui):
    """A cell with action buttons must not be a flex container (it broke the table row)."""
    admin = ui.page("admin")
    for path in ("/admin/categories", "/admin/users"):
        admin.goto(path)
        bad = admin.evaluate("""() => [...document.querySelectorAll('tbody tr')].filter(tr => {
            const cells = [...tr.children];
            const rects = cells.map(c => c.getBoundingClientRect());
            return cells.some(c => getComputedStyle(c).display !== 'table-cell')
                || Math.max(...rects.map(r => r.top)) - Math.min(...rects.map(r => r.top)) > 0.5
                || Math.max(...rects.map(r => r.bottom)) - Math.min(...rects.map(r => r.bottom)) > 0.5;
        }).length""")
        assert bad == 0, f"{path}: {bad} wierszy z nierównymi komórkami"


def test_users_table_on_a_phone_is_cards_without_sideways_scrolling(ui):
    with ui.server.db() as db:
        user = User(email="ktos.z.bardzo.dlugim.adresem.pocztowym@subdomena-firmowa.example.com",
                    name="Aleksandra Wiśniewska-Kowalczyk", is_active=True)
        user.set_roles(["referee"])
        db.add(user)
        db.commit()
        user_id = user.id

    scrolls = "document.documentElement.scrollWidth <= window.innerWidth"
    phone = ui.page("admin", mobile=True)
    phone.goto("/admin/users")
    expect(phone.locator("table.users-table.responsive")).to_have_count(1)
    assert phone.evaluate(scrolls), "strona kont przewija się w bok na telefonie"
    card = phone.locator("tr").filter(has_text="Aleksandra Wiśniewska-Kowalczyk")
    expect(card).to_have_count(1)
    assert phone.evaluate("() => getComputedStyle(document.querySelector('table.users-table tbody tr')).display") == "block"
    labels = card.locator("td").evaluate_all("cells => cells.map(c => c.dataset.label || '')")
    assert labels[:4] == ["Imię i nazwisko", "E-mail", "Role", "Stan"]
    box = card.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390
    card.get_by_label("szkoleniowiec").check()
    card.get_by_role("button", name="Zapisz role").click()
    expect(phone.locator("#admin-notice")).to_contain_text("Zapisano role: Aleksandra Wiśniewska-Kowalczyk")
    with ui.server.db() as db:
        assert db.get(User, user_id).roles == {"referee", "coach"}
    assert phone.evaluate(scrolls)
    for path in ("/admin/categories", "/admin/retention"):
        phone.goto(path)
        assert phone.evaluate(scrolls), f"{path}: przewijanie w bok na telefonie"

    desktop = ui.page("admin")
    desktop.goto("/admin/users")
    assert desktop.evaluate("() => getComputedStyle(document.querySelector('table.users-table')).display") == "table"
    expect(desktop.locator("table.users-table thead")).to_be_visible()
    assert desktop.evaluate(scrolls)
