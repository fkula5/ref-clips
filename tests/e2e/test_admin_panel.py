import re
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


def test_coach_opens_administration_and_edits_a_category(ui):
    coach = ui.page("coach")
    coach.goto("/")
    coach.locator("#site-nav").get_by_role("link", name="Administracja").click()
    expect(coach).to_have_url(ui.server.base_url + "/admin/categories")
    expect(coach.get_by_role("heading", name="Kategorie klipów")).to_be_visible()
    tabs = coach.locator(".admin-tabs")
    expect(tabs.get_by_role("link", name="Kategorie")).to_be_visible()
    expect(tabs.get_by_role("link", name="Arkusz oceny")).to_be_visible()
    expect(tabs.get_by_role("link", name="Użytkownicy")).to_have_count(0)
    expect(tabs.get_by_role("link", name="Retencja i dysk")).to_have_count(0)

    form = coach.locator("#new-category")
    form.get_by_label("Nazwa").fill("Faul trenera")
    form.get_by_role("button", name="Dodaj kategorię").click()
    expect(coach.locator("#admin-notice")).to_contain_text("Dodano kategorię „Faul trenera”")
    row = category_row(coach, "Faul trenera")
    row.locator('input[name="name"]').fill("Faul trenera 2")
    row.get_by_role("button", name="Zapisz").click()
    expect(coach.locator("#admin-notice")).to_contain_text("Zapisano kategorię „Faul trenera 2”")
    expect(category_row(coach, "Faul trenera 2")).to_have_count(1)

    tabs.get_by_role("link", name="Arkusz oceny").click()
    expect(coach).to_have_url(ui.server.base_url + "/admin/sheet-elements")

    ui.allow(r"status of 403")
    assert coach.goto("/admin/users").status == 403


def league_row(page, name):
    return page.locator("tr[data-league]").filter(has=page.locator(f'input[name="name"][value="{name}"]'))


def test_admin_adds_a_league_and_a_coach_renames_it_and_the_match_form_offers_it(ui):
    admin = ui.page("admin")
    admin.goto("/admin/users")
    admin.get_by_role("link", name="Ligi").click()
    expect(admin.get_by_role("heading", name="Ligi", exact=True)).to_be_visible()
    form = admin.locator("#new-league")
    form.get_by_label("Nazwa").fill("Liga Panelowa")
    form.get_by_role("button", name="Dodaj ligę").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Dodano ligę „Liga Panelowa”")
    expect(league_row(admin, "Liga Panelowa")).to_contain_text("aktywna")
    ui.allow(r"status of 409")
    form.get_by_label("Nazwa").fill("liga panelowa")
    form.get_by_role("button", name="Dodaj ligę").click()
    expect(admin.locator("#admin-error")).to_contain_text("już istnieje")

    coach = ui.page("coach")
    coach.goto("/admin/leagues")
    expect(coach.locator(".admin-tabs").get_by_role("link", name="Ligi")).to_be_visible()
    row = league_row(coach, "Liga Panelowa")
    row.locator('input[name="name"]').fill("Liga Przemianowana")
    row.get_by_role("button", name="Zapisz").click()
    expect(coach.locator("#admin-notice")).to_contain_text("Zapisano ligę „Liga Przemianowana”")
    expect(league_row(coach, "Liga Panelowa")).to_have_count(0)

    page = ui.page("referee")
    page.goto("/matches/new")
    options = page.locator("select[name=level] option").all_inner_texts()
    assert "Liga Przemianowana" in options and "Liga Panelowa" not in options
    page.locator("input[name=date]").fill("2026-10-31")
    page.locator("select[name=level]").select_option("Liga Przemianowana")
    page.locator("input[name=team_a_name]").fill("Panelowi")
    page.locator("input[name=u1_name]").fill("Piotr Partner")
    page.get_by_role("button", name="Zapisz").click()
    expect(page).to_have_url(re.compile(r"/matches/\d+$"))
    expect(page.locator("dd", has_text="Liga Przemianowana")).to_be_visible()

    coach.reload()  # the match uses it now: only deactivating is offered
    used = league_row(coach, "Liga Przemianowana")
    expect(used.get_by_role("button", name="Usuń")).to_have_count(0)
    expect(used.locator('td[data-label="Mecze"]')).to_have_text("1")


def test_renaming_a_league_to_another_one_asks_and_merges_their_matches(ui):
    ui.server.add_league("Liga Scalana A")
    ui.server.add_league("Liga Scalana B")
    in_a = ui.server.make_match(level="Liga Scalana A")
    in_b = ui.server.make_match(level="Liga Scalana B")
    admin = ui.page("admin")
    messages, accept = [], {"now": False}
    admin.on("dialog", lambda dialog: (messages.append(dialog.message),
                                       dialog.accept() if accept["now"] else dialog.dismiss()))
    admin.goto("/admin/leagues")
    row = league_row(admin, "Liga Scalana A")
    row.locator('input[name="name"]').fill("liga scalana b")
    row.get_by_role("button", name="Zapisz").click()
    admin.wait_for_timeout(300)
    assert len(messages) == 1 and "Liga „Liga Scalana B” już istnieje" in messages[0]
    assert ui.server.match_level(in_a) == "Liga Scalana A"
    expect(league_row(admin, "Liga Scalana A")).to_have_count(1)

    accept["now"] = True
    row.get_by_role("button", name="Zapisz").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Połączono z ligą „Liga Scalana B” — przeniesiono mecze: 1")
    expect(league_row(admin, "Liga Scalana A")).to_have_count(0)
    expect(league_row(admin, "Liga Scalana B").locator('td[data-label="Mecze"]')).to_have_text("2")
    assert ui.server.match_level(in_a) == ui.server.match_level(in_b) == "Liga Scalana B"

    row = league_row(admin, "Liga Scalana B")  # an ordinary rename does not ask
    count = len(messages)
    row.locator('input[name="name"]').fill("Liga Scalona")
    row.get_by_role("button", name="Zapisz").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Zapisano ligę „Liga Scalona” (zmieniono mecze: 2)")
    assert len(messages) == count and ui.server.match_level(in_a) == "Liga Scalona"


def test_league_can_be_reordered_deactivated_and_deleted(ui):
    ui.server.add_league("Liga Kolejna 1")
    ui.server.add_league("Liga Kolejna 2")
    admin = ui.page("admin")
    accept_dialogs(admin)
    admin.goto("/admin/leagues")
    names = lambda: [r.get_attribute("data-league") for r in admin.locator("tr[data-league]").all()]
    assert names().index("Liga Kolejna 1") < names().index("Liga Kolejna 2")
    league_row(admin, "Liga Kolejna 2").get_by_role("button", name="Wyżej: Liga Kolejna 2").click()
    def moved_up():
        try:
            return names().index("Liga Kolejna 2") < names().index("Liga Kolejna 1")
        except Exception:  # the page is reloading
            return False

    wait_until(admin, moved_up, message="liga nie przesunęła się wyżej")
    league_row(admin, "Liga Kolejna 1").get_by_role("button", name="Dezaktywuj").click()
    expect(admin.locator("#admin-notice")).to_contain_text("„Liga Kolejna 1” jest teraz nieaktywna")
    page = ui.page("admin")
    page.goto("/matches/new")
    options = page.locator("select[name=level] option").all_inner_texts()
    assert "Liga Kolejna 2" in options and "Liga Kolejna 1" not in options
    league_row(admin, "Liga Kolejna 2").get_by_role("button", name="Usuń").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Usunięto ligę „Liga Kolejna 2”")


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


def test_referee_does_not_see_the_panel_and_coach_not_the_admin_only_tabs(ui):
    page = ui.page("referee")
    page.goto("/")
    expect(page.get_by_role("link", name="Administracja")).to_have_count(0)
    ui.allow(r"status of 403")
    for role, paths in (("referee", ("/admin/users", "/admin/categories", "/admin/sheet-elements", "/admin/retention")),
                        ("coach", ("/admin/users", "/admin/retention"))):
        page = ui.page(role)
        for path in paths:
            response = page.goto(path)
            assert response.status == 403, (role, path)
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
