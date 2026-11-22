import re
from datetime import date

from playwright.sync_api import expect

from app import feedback, groups
from app.models import Clip, GroupMember, User


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def make_group_with_history(ui):
    """Ula Druga (referee) in a group led by Cezary Trener, with one match today and two clips: one rated
    incorrect by Cezary, one not rated.
    """
    server = ui.server
    match = server.make_match(team_a="Profilowi", team_b="Goście", day=date.today(),
                              officials=(("CC", "second"), ("U1", "Jan Obcy")))
    video = server.make_ready_video(match)
    rated = server.insert_clip(video, 20.0, official="CC", category="kroki", described=True)
    server.insert_clip(video, 40.0, official="CC", category="kroki", described=True)
    with server.db() as db:
        coach, referee = db.get(User, server.users["coach"]), db.get(User, server.users["second"])
        group = groups.create_group(db, coach, "Grupa profilowa", "")
        group.members.append(GroupMember(user_id=referee.id, role="referee"))
        db.commit()
        feedback.save_own_rating(db, db.get(Clip, rated), coach.id, "incorrect", "Za późno gwizdnięty")
        db.commit()
        return group.id


def test_profile_opens_from_the_group_table_and_works_on_a_phone(ui):
    group_id = make_group_with_history(ui)

    coach = ui.page("coach")
    coach.goto(f"/groups/{group_id}")
    coach.locator("#activity tbody tr", has_text="Ula Druga").get_by_role("link", name="Ula Druga").click()
    expect(coach).to_have_url(re.compile(r"/referees/\d+$"))
    expect(coach.get_by_role("heading", name="Ula Druga", level=1)).to_be_visible()
    expect(coach.locator("#profile-groups")).to_contain_text("Grupa profilowa")
    row = coach.locator("table.profile-matches tbody tr", has_text="Profilowi")
    expect(row.locator("td[data-label=Klipy]")).to_have_text("2")
    expect(row.locator("td[data-label=Ocenione]")).to_have_text("1")
    expect(row.locator("td[data-label=nieprawidłowa]")).to_have_text("1")
    expect(coach.locator("#profile-ratings")).to_contain_text("Za późno gwizdnięty")

    coach.evaluate("window.__bez_przeladowania = true")
    coach.locator("select[name=range]").select_option("all")
    expect(coach).to_have_url(re.compile(r"range=all"))
    expect(coach.locator("#profile-summary")).to_contain_text("cały czas")
    assert coach.evaluate("window.__bez_przeladowania === true"), "zmiana okresu przeładowała stronę"

    coach.locator("table.profile-categories tbody tr", has_text="kroki").locator("td[data-label=nieprawidłowa] a").click()
    expect(coach).to_have_url(re.compile(r"/clips\?.*rating=incorrect"))
    expect(coach.locator("#clips-list a[href^='/clips/']").first).to_be_visible()

    phone = ui.page("second", mobile=True)
    phone.goto("/")
    phone.get_by_role("button", name="Menu").click()
    phone.get_by_role("link", name="Mój profil").click()
    expect(phone.get_by_role("heading", name="Ula Druga", level=1)).to_be_visible()
    expect(phone.locator("table.profile-matches tbody tr", has_text="Profilowi")).to_be_visible()
    assert no_horizontal_scroll(phone)
    phone.locator("select[name=range]").select_option("all")
    expect(phone).to_have_url(re.compile(r"range=all"))
    assert no_horizontal_scroll(phone)
