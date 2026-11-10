from playwright.sync_api import expect


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def test_rating_reaches_the_crew_referee_who_clicks_through(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="full")
    ui.server.set_mark(video_id, "Q1", 0.0)
    clip_id = ui.server.insert_clip(video_id, 18.0, official="CC", category="kroki", described=True)

    referee = ui.page("referee")
    referee.goto("/notifications")  # the server is shared: start from a clean bell
    if referee.get_by_role("button", name="Oznacz wszystkie jako przeczytane").count():
        referee.get_by_role("button", name="Oznacz wszystkie jako przeczytane").click()
    referee.goto(f"/matches/{match_id}")
    bell = referee.locator("#bell")
    expect(bell).to_have_attribute("aria-label", "Powiadomienia")
    expect(bell.locator(".bell-count")).to_have_count(0)

    coach = ui.page("coach")
    coach.goto(f"/clips/{clip_id}")
    coach.locator("#oceny").get_by_label("nieprawidłowa", exact=True).check()
    coach.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(coach.locator("#oceny .rating")).to_have_count(1)

    referee.evaluate("document.dispatchEvent(new Event('visibilitychange'))")  # the tab comes back to the front
    expect(bell).to_have_attribute("aria-label", "Powiadomienia: 1 nowe")
    expect(bell.locator(".bell-count")).to_have_text("1")

    bell.click()
    referee.wait_for_url("**/notifications")
    item = referee.locator(".notif.unread")
    expect(item).to_have_count(1)
    expect(item).to_contain_text("Cezary Trener")
    expect(item).to_contain_text("nowa ocena klipu Q1 · 0:18 w meczu Legia – Wisła")
    expect(item).to_contain_text("nieprawidłowa")

    phone = ui.page("referee", mobile=True)
    phone.goto("/notifications")
    expect(phone.locator("#bell")).to_be_visible()
    expect(phone.locator(".notif").first).to_be_visible()
    assert no_horizontal_scroll(phone)

    item.get_by_role("button").first.click()
    referee.wait_for_url(f"**/clips/{clip_id}#oceny")
    expect(referee.locator("#oceny .rating")).to_contain_text("nieprawidłowa")
    expect(referee.locator("#bell")).to_have_attribute("aria-label", "Powiadomienia")
    referee.goto("/notifications")
    expect(referee.locator(".notif.unread")).to_have_count(0)
