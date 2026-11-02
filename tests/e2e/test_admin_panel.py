"""Scenariusz l) Panel administratora (segment 7): kategorie, retencja, zajętość dysku i ręczne usunięcie
pełnego nagrania, odrzucone uploady, brak panelu dla nie-administratora."""
from datetime import timedelta

from playwright.sync_api import expect

from app.models import UploadRejection, Video
from app.timeutil import utcnow
from tests.e2e.support import wait_until


def accept_dialogs(page):
    """Potwierdza okna confirm() (usunięcie, dezaktywacja, przeliczenie)."""
    page.on("dialog", lambda dialog: dialog.accept())


def category_row(page, name):
    return page.locator("tr[data-category]").filter(has=page.locator(f'input[name="name"][value="{name}"]'))


def test_admin_dodaje_i_dezaktywuje_kategorie_a_formularz_opisu_ja_traci(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1")
    ui.server.set_mark(video_id, "Q1", 0.0)
    fresh_clip = ui.server.insert_clip(video_id, 20.0, status="new")

    admin = ui.page("admin")
    accept_dialogs(admin)
    admin.goto("/admin/users")
    admin.get_by_role("link", name="Kategorie").click()
    expect(admin.get_by_role("heading", name="Kategorie klipów")).to_be_visible()

    # walidacja: alias już używany przez inną kategorię
    ui.allow(r"status of 422")
    form = admin.locator("#new-category")
    form.get_by_label("Nazwa").fill("Faul w ataku")
    form.get_by_label("Aliasy (po przecinku, opcjonalnie)").fill("krok")
    form.get_by_role("button", name="Dodaj kategorię").click()
    expect(admin.locator("#admin-error")).to_contain_text("„krok” jest już używany przez kategorię „kroki”")
    expect(admin.locator('#new-category input[name="name"]')).to_have_value("Faul w ataku")   # wartości zostają

    form.get_by_label("Aliasy (po przecinku, opcjonalnie)").fill("faul atakujacego")
    form.get_by_role("button", name="Dodaj kategorię").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Dodano kategorię „Faul w ataku”")
    expect(category_row(admin, "Faul w ataku")).to_contain_text("aktywna")

    # nowa kategoria jest w formularzu opisu klipu
    page = ui.page("admin")
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(1)

    # klip opisany nową kategorią; potem jej dezaktywacja: znika z wyboru, a ten klip ją zachowuje
    described = ui.server.insert_clip(video_id, 30.0, official="CC", category="Faul w ataku", described=True)
    category_row(admin, "Faul w ataku").get_by_role("button", name="Dezaktywuj").click()
    expect(admin.locator("#admin-notice")).to_contain_text("„Faul w ataku” jest teraz nieaktywna")
    expect(category_row(admin, "Faul w ataku")).to_contain_text("nieaktywna")
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(0)
    page.goto(f"/clips/{described}")
    expect(page.locator("#category-select option:checked")).to_have_text("Faul w ataku (nieaktywna)")
    page.get_by_role("button", name="Zapisz opis").click()           # zapis bez zmian zachowuje kategorię
    expect(page).to_have_url(ui.server.base_url + f"/clips/{described}")
    assert ui.server.clip(described).category_id is not None
    expect(page.locator("#clip-info")).to_contain_text("Faul w ataku")
    # kategoria używana w klipach: bez przycisku „Usuń”
    expect(category_row(admin, "Faul w ataku").get_by_role("button", name="Usuń")).to_have_count(0)

    # „własna” nie ma przycisków dezaktywacji ani usuwania
    own = category_row(admin, "własna")
    expect(own.get_by_role("button", name="Dezaktywuj")).to_have_count(0)
    expect(own.get_by_role("button", name="Usuń")).to_have_count(0)

    # nieużywaną kategorię można usunąć
    form.get_by_label("Nazwa").fill("Tymczasowa")
    form.get_by_role("button", name="Dodaj kategorię").click()
    category_row(admin, "Tymczasowa").get_by_role("button", name="Usuń").click()
    expect(admin.locator("#admin-notice")).to_contain_text("Usunięto kategorię „Tymczasowa”")
    expect(category_row(admin, "Tymczasowa")).to_have_count(0)
    # ponowna aktywacja przywraca wybór
    category_row(admin, "Faul w ataku").get_by_role("button", name="Aktywuj").click()
    page.goto(f"/clips/{fresh_clip}")
    expect(page.locator("#category-select option", has_text="Faul w ataku")).to_have_count(1)


def test_admin_zmienia_retention_days_z_walidacja_i_opcja_przeliczenia(ui):
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
    days.evaluate("el => { el.removeAttribute('min'); el.removeAttribute('max'); }")   # pomijamy walidację HTML5
    days.fill("0")
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-error")).to_contain_text("Liczba dni retencji musi mieścić się w zakresie 1–365")
    expect(admin.locator('#retention-form input[name="days"]')).to_have_value("0")

    admin.locator('#retention-form input[name="days"]').fill("14")
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-notice")).to_contain_text("14 dni")
    expect(admin.locator('#retention-form input[name="days"]')).to_have_value("14")
    with ui.server.db() as db:
        assert db.get(Video, video_id).expires_at == before        # domyślnie istniejące nagrania bez zmian

    admin.get_by_label("przelicz termin dla istniejących nagrań").check()
    admin.get_by_role("button", name="Zapisz", exact=True).click()
    expect(admin.locator("#admin-notice")).to_contain_text("Przeliczono termin")
    with ui.server.db() as db:
        video = db.get(Video, video_id)
        assert video.expires_at == video.created_at + timedelta(days=14)


def test_admin_widzi_dysk_i_usuwa_pelne_nagranie_wczesniej_a_klipy_graja(ui):
    match_id = ui.server.make_match(team_a="Zniknie", team_b="Nagranie")
    video_id = ui.server.make_ready_video(match_id, content="Q1")
    ui.server.set_mark(video_id, "Q1", 0.0)
    clip_id = ui.server.create_clip(video_id, 25.0)                    # prawdziwe cięcie przez workera
    page = ui.page("admin")
    accept_dialogs(page)
    page.goto("/admin/retention")

    # dopóki klip czeka na cięcie, usunięcie jest odrzucone (przycisku nie ma); po wycięciu — jest
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

    # strona meczu i odtwarzacz: brak odtwarzacza, skróty znaczników nic nie robią i nie psują strony
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
    assert len(ui.server.clips_of(video_id)) == 1                    # nic nie powstało
    assert ui.server.marks_of(video_id) == {"Q1": 0.0}

    # klip dalej gra
    clip_page = ui.page("admin")
    clip_page.goto(f"/clips/{clip_id}")
    clip_page.wait_for_function("document.getElementById('clip-video').readyState >= 1 "
                                "&& document.getElementById('clip-video').duration > 0")
    clip_page.evaluate("document.getElementById('clip-video').play()")
    clip_page.wait_for_function("document.getElementById('clip-video').currentTime > 0.5")
    expect(clip_page.get_by_role("link", name="pokaż w pełnym nagraniu")).to_have_count(0)


def test_oznaczenie_dostepne_jeszcze_x_dni_na_liscie_i_stronie_meczu(ui):
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


def test_baner_o_odrzuconych_uploadach_z_braku_miejsca(ui):
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


def test_nie_administrator_nie_widzi_panelu(ui):
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
