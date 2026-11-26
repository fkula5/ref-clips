import zipfile

from playwright.sync_api import expect

from tests.e2e.conftest import MOBILE


def test_referee_fills_in_a_self_assessment_and_a_coach_reads_it(ui):
    server = ui.server
    match_id = server.make_match()  # CC = Roman Sędzia (account), U1 = Kasia Żółć (typed)
    video_id = server.make_ready_video(match_id)
    server.set_mark(video_id, "Q1", 0.0)
    for at, category, text in ((5, "aut", "Piłka ostatnio dotknięta przez obrońcę"), (12, "kroki", ""),
                               (20, "aut", "Druga sytuacja"), (30, "kroki", "Czwarta")):
        server.insert_clip(video_id, float(at), official="CC", category=category, description=text,
                           described=bool(text), file=True)

    referee = ui.page("referee")
    referee.goto(f"/matches/{match_id}")
    referee.get_by_role("button", name="Wypełnij samoocenę").click()
    expect(referee.locator("#page-notice")).to_contain_text("Założono samoocenę jako szkic")
    expect(referee.locator("#sa-head")).to_contain_text("Roman Sędzia")

    # the form is not complete: three clips are needed
    ui.allow(r"status of 42[2]")
    ui.allow(r"status of 404")
    referee.on("dialog", lambda d: d.accept())
    referee.get_by_role("button", name="Wyślij").click()
    expect(referee.locator("#sa-errors")).to_contain_text("Dodaj co najmniej 3 klipy")

    for _ in range(3):
        referee.locator("#sa-picker button", has_text="Dodaj").first.click()
        expect(referee.locator("#page-notice")).to_contain_text("Zapisano szkic")
    rows = referee.locator(".sa-row")
    expect(rows).to_have_count(3)
    expect(rows.nth(0).locator("textarea")).to_have_value("Piłka ostatnio dotknięta przez obrońcę")
    expect(rows.nth(1).locator("textarea")).to_have_value("")  # the clip has no description of its own

    rows.nth(1).locator("textarea").fill("Kroki po zbiórce")
    rows.nth(0).get_by_role("button", name="Przesuń klip 1 w dół").click()
    expect(referee.locator(".sa-row").nth(1).locator("textarea")).to_have_value("Piłka ostatnio dotknięta przez obrońcę")
    expect(referee.locator(".sa-row").nth(0).locator("textarea")).to_have_value("Kroki po zbiórce")

    referee.locator("textarea[name=opinion]").fill("Spokojny mecz, kilka spóźnionych decyzji.")
    referee.locator("textarea[name=good]").fill("Współpraca z U1.")
    referee.locator("textarea[name=bad]").fill("Ustawienie w kontrataku.")
    referee.get_by_role("button", name="Zapisz szkic").click()
    expect(referee.locator("#page-notice")).to_contain_text("Zapisano szkic")

    coach = ui.page("coach")
    assert coach.goto(f"/self-assessments/{referee.url.split('/')[-2]}").status == 404  # a draft stays private

    sa_url = referee.url.removesuffix("/edit")
    referee.goto(sa_url)
    expect(referee.locator("#sa-draft-mark")).to_be_visible()
    expect(referee.get_by_role("link", name="Pobierz PDF")).to_be_visible()
    expect(referee.get_by_role("link", name="Pobierz ZIP (PDF + klipy)")).to_have_count(0)  # drafts have no ZIP
    referee.goto(f"{sa_url}/edit")

    referee.get_by_role("button", name="Wyślij").click()
    expect(referee.locator("#page-notice")).to_contain_text("Wysłano samoocenę")
    expect(referee.locator("#sa-report")).to_contain_text("ARKUSZ SAMOOCENY RC 2026/27")
    expect(referee.get_by_role("link", name="Edytuj")).to_have_count(0)
    expect(referee.get_by_role("link", name="Pobierz PDF")).to_be_visible()

    coach.goto(f"/matches/{match_id}")
    expect(coach.locator("#sa-card")).to_contain_text("Roman Sędzia")
    coach.get_by_role("link", name="Otwórz").first.click()
    report = coach.locator("#sa-report")
    expect(report).to_contain_text("Ustawienie w kontrataku.")
    expect(report).to_contain_text("Kroki po zbiórce")
    expect(report.locator(".sa-block")).to_have_count(6)

    with coach.expect_download() as download:
        coach.get_by_role("link", name="Pobierz PDF").click()
    assert download.value.suggested_filename == "samoocena_2026-10-28_Legia-Wisla_CC.pdf"
    with coach.expect_download() as download:
        coach.get_by_role("link", name="Pobierz ZIP (PDF + klipy)").click()
    assert download.value.suggested_filename == "samoocena_2026-10-28_Legia-Wisla_CC.zip"
    with zipfile.ZipFile(download.value.path()) as archive:
        assert archive.namelist()[0] == "samoocena_2026-10-28_Legia-Wisla_CC.pdf"
        assert [n for n in archive.namelist() if n.startswith("klipy/")] == [
            "klipy/01_kroki.mp4", "klipy/02_aut.mp4", "klipy/03_aut.mp4"]

    outsider = ui.page("outsider")
    assert outsider.goto(f"/self-assessments/{coach.url.split('/')[-1]}").status == 404


def test_the_form_and_the_report_fit_a_phone(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id)
    ui.server.insert_clip(video_id, 5.0, category="aut", description="x", described=True, file=True)
    page = ui.page("referee", mobile=True)
    page.goto(f"/matches/{match_id}")
    page.get_by_role("button", name="Wypełnij samoocenę").click()
    expect(page.locator("#sa-picker")).to_be_visible()
    assert page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")
    page.get_by_role("link", name="Podgląd arkusza").click()
    expect(page.locator("#sa-draft-mark")).to_be_visible()
    assert page.viewport_size["width"] == MOBILE["width"]
    assert page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def test_referee_fills_in_a_self_assessment_of_a_match_outside_the_system(ui):
    referee = ui.page("referee")
    referee.goto("/self-assessments")
    referee.get_by_role("button", name="Nowa samoocena — mecz spoza systemu").click()
    expect(referee.locator("#page-notice")).to_contain_text("Założono samoocenę jako szkic")
    expect(referee.locator("#sa-picker")).to_have_count(0)

    referee.locator("input[name=league]").fill("Liga Amatorska")
    referee.locator("input[name=match_date]").fill("2026-11-07")
    referee.locator("input[name=home_team]").fill("Śląsk")
    referee.locator("input[name=away_team]").fill("Zagłębie")
    referee.locator("input[name=main_referee]").fill("Jan Kowalski")

    ui.allow(r"status of 42[2]")
    referee.on("dialog", lambda d: d.accept())
    for number in range(1, 4):
        referee.get_by_role("button", name="Dodaj wiersz ręcznie").click()
        expect(referee.locator(".sa-row")).to_have_count(number)
    rows = referee.locator(".sa-row")
    expect(rows.locator("input[name^=time_]")).to_have_count(0)  # the report leaves the time column empty
    for i in range(3):
        rows.nth(i).locator("input[name^=name_]").fill(f"Faul {i + 1}")
        if i < 2:
            rows.nth(i).locator("textarea").fill(f"Opis {i + 1}")
    referee.locator("textarea[name=opinion]").fill("Spokojny mecz.")
    referee.locator("textarea[name=good]").fill("Współpraca.")
    referee.locator("textarea[name=bad]").fill("Ustawienie.")

    referee.get_by_role("button", name="Wyślij").click()
    expect(referee.locator("#sa-errors")).to_contain_text("Klip 3: wpisz opis.")
    expect(referee.locator("input[name=home_team]")).to_have_value("Śląsk")  # the draft was saved
    referee.locator(".sa-row").nth(2).locator("textarea").fill("Opis 3")
    referee.get_by_role("button", name="Wyślij").click()
    expect(referee.locator("#page-notice")).to_contain_text("Wysłano samoocenę")
    report = referee.locator("#sa-report")
    expect(report).to_contain_text("Liga Amatorska")
    expect(report).to_contain_text("07.11.2026")
    expect(report).to_contain_text("Zagłębie")
    expect(report.locator(".sa-block")).to_have_count(6)

    coach = ui.page("coach")
    coach.goto("/self-assessments")
    expect(coach.locator("#sa-submitted")).to_contain_text("Śląsk – Zagłębie")
    expect(coach.locator("#sa-submitted")).to_contain_text("spoza systemu")
    coach.get_by_role("link", name="Otwórz").first.click()
    with coach.expect_download() as download:
        coach.get_by_role("link", name="Pobierz PDF").click()
    assert download.value.suggested_filename == "samoocena_2026-11-07_Slask-Zaglebie.pdf"
