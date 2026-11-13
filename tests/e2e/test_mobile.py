"""Phone layout: the header menu and the absence of sideways scrolling on the main screens."""
import shutil

import pytest
from playwright.sync_api import expect

from app import groups, notify, training_sets
from app.models import TrainingGroup, TrainingSet, TrainingSetClip, User
from tests.e2e.conftest import login
from tests.e2e.support import HEIC_TINY, PDF_TINY, PNG_1X1, USERS

WIDTHS = [375, 390]
LONG_WORD = "Superdlugie" + "slowo" * 8

# `html, body { overflow-x: clip }` hides overflowing content instead of scrolling it, so scrollWidth alone
# proves nothing: the elements themselves are measured. Content inside a clipping/scrolling container that
# fits the viewport (an intentionally scrollable table, say) is fine, and so is anything parked off to the left.
OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth, bad = [];
  const clips = (el) => { const o = getComputedStyle(el).overflowX; return o !== "visible"; };
  for (const el of document.body.querySelectorAll("*")) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.right <= 0 || (r.right <= vw + 1 && r.left >= -1)) continue;
    let contained = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const pr = p.getBoundingClientRect();
      if (clips(p) && pr.right <= vw + 1 && pr.left >= -1) { contained = true; break; }
    }
    if (!contained) bad.push(el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + "." + el.className
      + " [" + Math.round(r.left) + ".." + Math.round(r.right) + "]");
  }
  return {scroll: document.documentElement.scrollWidth, client: vw, bad: bad.slice(0, 8)};
}"""


def overflow(page):
    return page.evaluate(OVERFLOW_JS)


@pytest.fixture(scope="module")
def data(server):
    match_id = server.make_match(
        team_a="Bardzo Długa Nazwa Klubu Koszykarskiego " + LONG_WORD, team_b="Goście z Przedmieść",
        level="Ekstraklasa Seniorów Mężczyzn Grupa Południowa",
        officials=(("CC", "referee"), ("U1", "Katarzyna Żółć-Wiśniewska-Kowalczyk"), ("U2", "second")))
    video_id = server.make_ready_video(match_id, content="Q1,Q2", label="Kamera główna, całość meczu, wersja długa")
    for name, content, content_type in ((f"Protokół-{LONG_WORD}.pdf", PDF_TINY, "application/pdf"),
                                        (f"IMG_{LONG_WORD}.png", PNG_1X1, "image/png"),
                                        ("IMG_0042.HEIC", HEIC_TINY, "image/heic")):
        server.add_scoresheet(match_id, name, content, content_type)
    server.set_mark(video_id, "Q1", 5.0)
    server.set_mark(video_id, "Q2", 35.0)
    clips = [
        server.insert_clip(video_id, 10, official="CC", category="kroki", described=True, file=True,
                           description="Długi opis klipu " * 8 + LONG_WORD),
        server.insert_clip(video_id, 40, whole_team=True, category="własna", custom=LONG_WORD, described=True,
                           file=True),
        server.insert_clip(video_id, 48, official="U1", category="aut"),
    ]
    for clip_id in clips[:2]:
        shutil.copy(server.sample, server.data_dir / server.clip(clip_id).clip_path)
        server.add_comment(clip_id, "coach", LONG_WORD)
    server.add_comment(clips[0], "referee", "Zwykły komentarz")
    with server.db() as db:
        coach = db.get(User, server.users["coach"])
        training_set = training_sets.create_set(db, coach, "Zestaw o bardzo długiej nazwie " + LONG_WORD,
                                                "Opis zestawu " * 10)
        for position, clip_id in enumerate(clips[:2], start=1):  # add_clip checks the file in this process's data dir
            db.add(TrainingSetClip(set_id=training_set.id, clip_id=clip_id, position=position))
        group = groups.create_group(db, coach, "Grupa o bardzo długiej nazwie " + LONG_WORD, "Opis grupy " * 10)
        groups.add_member(db, group, server.users["referee"], "referee", coach)
        db.add(TrainingSet(name="Drugi zestaw", created_by=coach.id))
        db.commit()
        set_id, group_id = training_set.id, group.id
        notify.group_added(db, db.get(TrainingGroup, group_id), server.users["admin"], server.users["coach"])
        db.commit()
    return {"match": match_id, "video": video_id, "clips": clips, "set": set_id, "group": group_id}


def key_pages(data):
    match_id, clip_id, set_id = data["match"], data["clips"][0], data["set"]
    return ["/", "/?date_from=2026-01-01&date_to=2026-12-31&mine=1", "/clips", f"/clips?match_id={match_id}",
            "/sets", "/groups", "/notifications", "/admin/users", "/admin/categories", "/admin/retention",
            "/admin/sheet-elements", f"/matches/{match_id}", f"/matches/{match_id}/describe",
            f"/clips/{clip_id}", f"/sets/{set_id}", f"/sets/{set_id}/clips/{clip_id}", f"/groups/{data['group']}",
            f"/groups/{data['group']}/review", f"/videos/{data['video']}", "/matches/new", f"/matches/{match_id}/edit",
            "/sets/new", f"/sets/{set_id}/edit", "/groups/new"]


@pytest.mark.parametrize("width", WIDTHS)
def test_no_page_scrolls_sideways_on_a_phone(ui, data, width):
    ui.allow(r"status of 40[34]")
    page = ui.page("admin", mobile=True, viewport={"width": width, "height": 800})
    failures = []
    for path in key_pages(data):
        response = page.goto(path)
        page.wait_for_load_state("networkidle")
        if response.status >= 400:
            failures.append(f"{path}: HTTP {response.status}")
            continue
        result = overflow(page)
        if result["scroll"] > result["client"] or result["bad"]:
            failures.append(f"{path}: {result}")
    assert not failures, "\n".join(failures)


def test_match_filters_stay_inside_the_card_on_a_phone(ui):
    page = ui.page("admin", mobile=True)
    page.goto("/")
    form = page.locator("form.match-filters").bounding_box()
    checkbox = page.locator("input[name=mine]")
    for control in (*page.locator(".match-filters label").all(), page.locator("input[name=date_from]"),
                    page.locator("input[name=date_to]"), checkbox, page.get_by_text("tylko moje")):
        box = control.bounding_box()
        assert box["x"] >= form["x"] - 1 and box["x"] + box["width"] <= form["x"] + form["width"] + 1, box
    assert checkbox.bounding_box()["width"] <= 24
    assert page.get_by_text("tylko moje").bounding_box()["x"] < 390


def test_sheet_pages_fit_a_phone(ui, data):
    coach = ui.page("coach", mobile=True)
    coach.goto(f"/matches/{data['match']}")
    coach.get_by_role("button", name="Wypełnij arkusz").click()
    expect(coach.get_by_role("heading", name="Arkusz oceny sędziów")).to_be_visible()
    result = overflow(coach)
    assert result["scroll"] <= result["client"] and not result["bad"], result
    coach.goto(f"/matches/{data['match']}")
    coach.get_by_role("link", name="Wypełnij arkusz").or_(coach.get_by_role("link", name="Otwórz")).first.click()
    result = overflow(coach)
    assert result["scroll"] <= result["client"] and not result["bad"], result


def toggle(page):
    return page.get_by_role("button", name="Menu")


def test_phone_header_collapses_into_a_menu(ui):
    page = ui.page("admin", mobile=True)
    page.goto("/")
    button = toggle(page)
    expect(button).to_be_visible()
    expect(button).to_have_attribute("aria-expanded", "false")
    expect(button).to_have_attribute("aria-controls", "site-nav site-account")
    expect(page.locator("#bell")).to_be_visible()
    expect(page.locator(".brand")).to_be_visible()
    expect(page.locator("#site-nav")).to_be_hidden()
    expect(page.get_by_role("button", name="Wyloguj")).to_be_hidden()
    assert page.locator("header.top").bounding_box()["height"] < 70

    button.tap()
    expect(button).to_have_attribute("aria-expanded", "true")
    for name in ("Mecze", "Klipy", "Zestawy", "Grupy", "Administracja"):
        expect(page.locator("#site-nav").get_by_role("link", name=name)).to_be_visible()
    expect(page.locator("#site-account")).to_contain_text("Adam Admin")
    expect(page.get_by_role("button", name="Wyloguj")).to_be_visible()
    result = overflow(page)
    assert result["scroll"] <= result["client"] and not result["bad"], result

    button.tap()
    expect(button).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#site-nav")).to_be_hidden()


def test_coach_reaches_the_admin_dictionaries_from_the_phone_menu(ui):
    page = ui.page("coach", mobile=True, viewport={"width": 375, "height": 800})
    page.goto("/")
    toggle(page).tap()
    page.locator("#site-nav").get_by_role("link", name="Administracja").tap()
    page.wait_for_url("**/admin/categories")
    for path in ("/admin/categories", "/admin/sheet-elements"):
        page.goto(path)
        page.wait_for_load_state("networkidle")
        result = overflow(page)
        assert result["scroll"] <= result["client"] and not result["bad"], (path, result)


def test_phone_menu_works_from_the_keyboard_and_closes_on_escape_and_navigation(ui):
    page = ui.page("admin", mobile=True)
    page.goto("/")
    button = toggle(page)
    button.focus()
    page.keyboard.press("Enter")
    expect(button).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Tab")
    expect(page.locator("#site-nav a").first).to_be_focused()
    page.keyboard.press("Escape")
    expect(button).to_have_attribute("aria-expanded", "false")
    expect(button).to_be_focused()
    expect(page.locator("#site-nav")).to_be_hidden()

    button.press("Space")
    expect(button).to_have_attribute("aria-expanded", "true")
    page.locator("#site-nav").get_by_role("link", name="Klipy").click()
    page.wait_for_url("**/clips")
    expect(toggle(page)).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#site-nav")).to_be_hidden()

    # A session of its own: logging out ends it on the server, and the shared role states must survive.
    own = ui.page(mobile=True)
    login(own, USERS["admin"][0])
    own.wait_for_url("**/")
    toggle(own).tap()
    own.get_by_role("button", name="Wyloguj").tap()
    own.wait_for_url("**/login")


def test_desktop_header_keeps_the_full_navigation(ui):
    page = ui.page("admin")
    page.goto("/")
    expect(toggle(page)).to_be_hidden()
    expect(page.locator("#site-nav").get_by_role("link", name="Administracja")).to_be_visible()
    expect(page.get_by_role("button", name="Wyloguj")).to_be_visible()
    expect(page.locator("#bell")).to_be_visible()
    assert page.locator("header.top").bounding_box()["height"] < 70


def test_menu_links_stay_reachable_without_javascript(ui):
    page = ui.page("admin", mobile=True, java_script_enabled=False)
    page.goto("/")
    expect(toggle(page)).to_be_hidden()
    expect(page.locator("#site-nav").get_by_role("link", name="Zestawy")).to_be_visible()
    expect(page.get_by_role("button", name="Wyloguj")).to_be_visible()
    result = overflow(page)
    assert result["scroll"] <= result["client"] and not result["bad"], result
