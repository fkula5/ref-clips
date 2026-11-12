from playwright.sync_api import expect

from tests.e2e.support import PDF_TINY, PNG_1X1


def files(page, *items):
    page.set_input_files("#scoresheet-files", [{"name": n, "mimeType": t, "buffer": b} for n, t, b in items])


def test_crew_referee_uploads_a_pdf_and_a_photo_then_deletes_one(ui):
    match_id = ui.server.make_match()  # CC = Roman Sędzia (account)
    page = ui.page("referee")
    page.goto(f"/matches/{match_id}")
    card = page.locator("#scoresheet-card")
    expect(card).to_contain_text("Brak plików protokołu")
    expect(card.locator("#scoresheet-files")).to_have_attribute("multiple", "")
    assert "image/heic" in card.locator("#scoresheet-files").get_attribute("accept")

    files(page, ("protokol.pdf", "application/pdf", PDF_TINY), ("zdjecie.png", "image/png", PNG_1X1))
    card.get_by_role("button", name="Dodaj do protokołu").click()
    expect(page.locator("#page-notice")).to_contain_text("Dodano do protokołu: 2 pliki.")
    items = card.locator(".scoresheet-item")
    expect(items).to_have_count(2)
    expect(items.nth(0)).to_contain_text("protokol.pdf")
    expect(items.nth(1)).to_contain_text("zdjecie.png")
    thumb = items.nth(1).locator("img")
    expect(thumb).to_be_visible()
    assert thumb.evaluate("img => img.complete && img.naturalWidth > 0")

    pdf_link = items.nth(0).get_by_role("link", name="Otwórz")
    response = page.request.get(pdf_link.get_attribute("href"))
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    with page.expect_download() as download:
        items.nth(1).get_by_role("link", name="Pobierz").click()
    assert download.value.suggested_filename == "zdjecie.png"

    page.once("dialog", lambda d: d.dismiss())
    items.nth(0).get_by_role("button", name="Usuń").click()
    expect(items).to_have_count(2)
    page.once("dialog", lambda d: d.accept())
    items.nth(0).get_by_role("button", name="Usuń").click()
    expect(items).to_have_count(1)
    expect(page.locator("#page-notice")).to_contain_text("Usunięto plik protokołu")
    expect(items.first).to_contain_text("zdjecie.png")
    assert [s.original_filename for s in ui.server.scoresheets_of(match_id)] == ["zdjecie.png"]


def test_a_wrong_file_is_refused_with_a_message_and_an_outsider_cannot_upload(ui):
    match_id = ui.server.make_match()
    ui.allow(r"status of 415")
    page = ui.page("coach")
    page.goto(f"/matches/{match_id}")
    files(page, ("protokol.pdf", "application/pdf", b"<html><script>1</script></html>"))
    page.locator("#scoresheet-form").get_by_role("button", name="Dodaj do protokołu").click()
    expect(page.locator("#scoresheet-error")).to_contain_text("niedozwolony typ pliku")
    assert not ui.server.scoresheets_of(match_id)

    outsider = ui.page("outsider")
    outsider.goto(f"/matches/{match_id}")
    expect(outsider.locator("#scoresheet-card")).to_contain_text("Brak plików protokołu")
    expect(outsider.locator("#scoresheet-form")).to_have_count(0)


def test_the_browser_checks_the_count_before_sending(ui):
    match_id = ui.server.make_match()
    page = ui.page("admin")
    page.goto(f"/matches/{match_id}")
    files(page, *[(f"s{i}.png", "image/png", PNG_1X1) for i in range(11)])
    expect(page.locator("#scoresheet-client-error")).to_contain_text("najwyżej 10 plików")
    page.locator("#scoresheet-form").get_by_role("button", name="Dodaj do protokołu").click()
    assert page.url.endswith(f"/matches/{match_id}") and not ui.server.scoresheets_of(match_id)


def test_matches_list_marks_a_match_with_a_scoresheet(ui):
    match_id = ui.server.make_match(team_a="Znacznik", team_b="Protokołowy")
    ui.server.add_scoresheet(match_id, "p.pdf", PDF_TINY, "application/pdf")
    page = ui.page("referee")
    page.goto("/")
    row = page.locator("tr", has_text="Znacznik")
    expect(row.get_by_role("img", name="Protokół")).to_be_visible()
