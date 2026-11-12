import re

from playwright.sync_api import expect


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def test_coach_builds_a_group_and_the_referee_sees_it_and_the_notification(ui):
    in_group = ui.server.make_match(team_a="Grupowi", team_b="Goście")
    outside = ui.server.make_match(team_a="Obcy", team_b="Goście", officials=(("CC", "outsider"), ("U1", "Jan Obcy")))
    clip_in = ui.server.insert_clip(ui.server.make_ready_video(in_group), 18.0, author="referee", described=True)
    clip_out = ui.server.insert_clip(ui.server.make_ready_video(outside), 18.0, described=True)

    referee = ui.page("referee")
    referee.goto("/notifications")  # the server is shared: start from a clean bell
    if referee.get_by_role("button", name="Oznacz wszystkie jako przeczytane").count():
        referee.get_by_role("button", name="Oznacz wszystkie jako przeczytane").click()
    referee.goto("/groups")
    expect(referee.get_by_role("link", name="+ Nowa grupa")).to_have_count(0)

    coach = ui.page("coach")
    coach.goto("/groups")
    coach.get_by_role("link", name="+ Nowa grupa").click()
    coach.get_by_label("Nazwa").fill("Grupa E2E")
    coach.get_by_label("Opis (opcjonalnie)").fill("Sędziowie na sezon")
    coach.get_by_role("button", name="Utwórz grupę").click()
    expect(coach.get_by_role("heading", name="Grupa E2E")).to_be_visible()
    expect(coach.locator("#page-notice")).to_contain_text("Utworzono grupę")

    coach.locator("form.member-add").first.locator("select").select_option(label="Roman Sędzia")
    coach.locator("form.member-add").first.get_by_role("button", name="Dodaj").click()
    row = coach.locator("#activity tbody tr", has_text="Roman Sędzia")
    expect(row).to_have_count(1)
    expect(row.locator("td[data-label=Znaczniki]")).to_have_text("1")
    expect(row).not_to_contain_text("brak aktywności")

    coach.evaluate("window.__bez_przeladowania = true")
    coach.locator("select[name=days]").select_option("7")
    expect(coach).to_have_url(re.compile(r"days=7"))
    expect(coach.locator("#activity")).to_contain_text("ostatnich 7 dni")
    assert coach.evaluate("window.__bez_przeladowania === true"), "zmiana okresu przeładowała stronę"

    coach.goto("/clips")
    coach.locator("select[name=group]").select_option(label="Grupa E2E")
    expect(coach).to_have_url(re.compile(r"group=\d+"))
    expect(coach.locator(f"#clips-list a[href^='/clips/{clip_in}']").first).to_be_visible()
    expect(coach.locator(f"#clips-list a[href^='/clips/{clip_out}']")).to_have_count(0)

    referee.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(referee.locator("#bell")).to_have_attribute("aria-label", "Powiadomienia: 1 nowe")
    referee.goto("/notifications")
    item = referee.locator(".notif.unread")
    expect(item).to_have_count(1)
    expect(item).to_contain_text("Cezary Trener")
    expect(item).to_contain_text("dodano Cię do grupy „Grupa E2E”")
    item.get_by_role("button").first.click()
    referee.wait_for_url("**/groups")
    group_row = referee.locator("table.responsive tbody tr", has_text="Grupa E2E")
    expect(group_row).to_contain_text("Cezary Trener")
    expect(group_row.get_by_role("link")).to_have_count(0)  # a referee only sees the group, not its page
    expect(referee.locator("#bell")).to_have_attribute("aria-label", "Powiadomienia")

    phone = ui.page("referee", mobile=True)
    phone.goto("/groups")
    expect(phone.locator("table.responsive tbody tr", has_text="Grupa E2E")).to_be_visible()
    assert no_horizontal_scroll(phone)
    group_id = int(re.search(r"group=(\d+)", coach.url)[1])
    phone_coach = ui.page("coach", mobile=True)
    phone_coach.goto(f"/groups/{group_id}")
    expect(phone_coach.locator("#activity tbody tr", has_text="Roman Sędzia")).to_be_visible()
    assert no_horizontal_scroll(phone_coach)


def test_coach_adds_another_coach_through_the_real_form(ui):
    coach = ui.page("coach")
    coach.goto("/groups/new")
    coach.get_by_label("Nazwa").fill("Grupa dwóch trenerów")
    coach.get_by_role("button", name="Utwórz grupę").click()
    expect(coach.get_by_role("heading", name="Grupa dwóch trenerów")).to_be_visible()

    coach.get_by_label("Dodaj szkoleniowca").select_option(label="Daria Trenerka")
    coach.get_by_role("button", name="Dodaj").last.click()
    expect(coach.locator("#page-notice")).to_contain_text("Dodano szkoleniowca: Daria Trenerka")
    expect(coach.locator(".coach-list .chip", has_text="Daria Trenerka")).to_have_count(1)

    second = ui.page("coach2")
    second.goto(coach.url)
    expect(second.get_by_role("heading", name="Grupa dwóch trenerów")).to_be_visible()

    coach.on("dialog", lambda dialog: dialog.accept())
    coach.get_by_role("button", name="Usuń z grupy: Daria Trenerka").click()
    expect(coach.locator("#page-notice")).to_contain_text("Usunięto z grupy: Daria Trenerka")
    expect(coach.locator(".coach-list")).not_to_contain_text("Daria Trenerka")

    ui.allow(r"status of 422")
    coach.get_by_role("button", name="Usuń z grupy: Cezary Trener").click()
    expect(coach.locator("#group-error")).to_contain_text("musi zostać co najmniej jeden szkoleniowiec")
    expect(coach.locator(".coach-list")).to_contain_text("Cezary Trener")
