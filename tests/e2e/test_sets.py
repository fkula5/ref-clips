import shutil

from playwright.sync_api import expect


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def test_coach_builds_a_set_from_the_clip_page_and_a_referee_views_it_with_names_hidden(ui):
    server = ui.server
    match_id = server.make_match(officials=(("CC", "Jan Tajemniczy"), ("U1", "Kasia Żółć")),
                                 team_a="Zestawowi", team_b="Goście")
    video_id = server.make_ready_video(match_id)
    first = server.insert_clip(video_id, 18.0, official="CC", category="kroki", description="Opis z meczu",
                               described=True, file=True)
    second = server.insert_clip(video_id, 30.0, official="U1", category="aut", described=True, file=True)
    for clip_id in (first, second):  # a real playable file, without cutting it with ffmpeg
        shutil.copy(server.sample, server.data_dir / server.clip(clip_id).clip_path)

    coach = ui.page("coach")
    coach.goto(f"/clips/{first}")
    coach.locator("#clip-sets").get_by_label("albo nowy zestaw").fill("Akcja rzutowa E2E")
    coach.locator("#clip-sets").get_by_role("button", name="Dodaj klip").click()
    expect(coach.locator("#page-notice")).to_contain_text("Dodano klip do zestawu „Akcja rzutowa E2E”")
    expect(coach.locator("#clip-sets")).to_contain_text("W zestawach: Akcja rzutowa E2E")

    coach.goto(f"/clips/{second}")
    coach.locator("#clip-sets").get_by_label("Istniejący zestaw").select_option(label="Akcja rzutowa E2E")
    coach.locator("#clip-sets").get_by_role("button", name="Dodaj klip").click()
    expect(coach.locator("#page-notice")).to_contain_text("Dodano klip do zestawu")

    coach.goto("/sets")
    coach.get_by_role("link", name="Akcja rzutowa E2E").click()
    coach.get_by_role("link", name="Obejrzyj od pierwszego klipu").click()
    coach.get_by_label("Twoja notatka do tego klipu").fill("Zwróć uwagę na kroki rozbiegowe")
    coach.get_by_role("button", name="Zapisz notatkę").click()
    expect(coach.locator("#note-text")).to_have_text("Zwróć uwagę na kroki rozbiegowe")
    viewer_url = coach.url

    referee = ui.page("referee")
    referee.goto(viewer_url)
    expect(referee.locator("#set-position")).to_have_text("1 / 2")
    main = referee.locator("main")
    for text in ("CC", "Zwróć uwagę na kroki rozbiegowe", "Opis z meczu", "Zestawowi", "kroki"):
        expect(main).to_contain_text(text)
    expect(main).not_to_contain_text("Tajemniczy")
    expect(main).not_to_contain_text("Jan")
    expect(referee.get_by_role("button", name="Zapisz notatkę")).to_have_count(0)
    referee.wait_for_function("document.getElementById('clip-video').readyState >= 1")
    assert no_horizontal_scroll(referee)

    referee.get_by_role("link", name="następny").click()
    expect(referee.locator("#set-position")).to_have_text("2 / 2")
    expect(referee.locator("#clip-info")).to_contain_text("U1")
    expect(referee.locator("main")).not_to_contain_text("Żółć")
    with referee.expect_download() as download:
        referee.get_by_role("link", name="Pobierz MP4").click()
    assert download.value.suggested_filename == "II-liga_U1_aut.mp4"
    referee.get_by_role("link", name="przejdź do klipu").click()
    expect(referee.locator("#clip-info")).to_contain_text("U1 · Kasia Żółć")

    phone = ui.page("referee", mobile=True)
    phone.goto(viewer_url)
    expect(phone.locator("#set-position")).to_be_visible()
    assert no_horizontal_scroll(phone)
