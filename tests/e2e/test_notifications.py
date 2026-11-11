import pytest
from playwright.sync_api import expect

from app import notify


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


def mark_everything_read(page):
    page.goto("/notifications")  # the server is shared: start from a clean bell
    button = page.get_by_role("button", name="Oznacz wszystkie jako przeczytane")
    if button.count():
        button.click()
    expect(page.locator(".notif.unread")).to_have_count(0)


def clip_with_comments(ui, comments):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="full")
    ui.server.set_mark(video_id, "Q1", 0.0)
    clip_id = ui.server.insert_clip(video_id, 18.0, official="CC", category="kroki", described=True)
    referee = ui.page("referee")
    mark_everything_read(referee)
    for _ in range(comments):
        ui.server.add_comment(clip_id, "coach")
    return referee, clip_id


@pytest.mark.parametrize("comments, leave", [(1, "back"), (2, "back"), (2, "reload")],
                         ids=["single-back", "two-on-one-clip-back", "two-on-one-clip-reload"])
def test_opened_notification_is_read_when_the_list_is_seen_again(ui, comments, leave):
    referee, clip_id = clip_with_comments(ui, comments)
    referee.goto("/notifications")
    expect(referee.locator(".notif.unread")).to_have_count(comments)
    expect(referee.locator("#bell .bell-count")).to_have_text(str(comments))

    referee.locator(".notif.unread").first.get_by_role("button").first.click()
    referee.wait_for_url(f"**/clips/{clip_id}#komentarze")
    if leave == "back":
        referee.go_back()
    else:
        referee.goto("/notifications")
    referee.wait_for_url("**/notifications")
    expect(referee.locator(".notif.unread")).to_have_count(0)
    expect(referee.locator("#bell .bell-count")).to_have_count(0)


def test_bell_refreshes_when_restored_from_the_back_forward_cache(ui):
    referee, clip_id = clip_with_comments(ui, 1)
    referee.goto("/")
    expect(referee.locator("#bell .bell-count")).to_have_text("1")
    with ui.server.db() as db:
        notify.mark_all_read(db, ui.server.users["referee"])
        db.commit()
    referee.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    expect(referee.locator("#bell .bell-count")).to_have_count(0)
