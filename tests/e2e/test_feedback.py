import re

from playwright.sync_api import Page, expect

from tests.e2e.support import wait_until

PHONE = {"width": 375, "height": 740}


def rated_setup(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="full")
    clip_id = ui.server.insert_clip(video_id, 30.0, official="CC", category="kroki", described=True,
                                    description="Przekroczenie linii")
    return match_id, video_id, clip_id


def verdict(page: Page, label: str) -> None:
    page.locator("#oceny").get_by_label(label, exact=True).check()


def no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


def test_coach_rates_and_changes_the_rating(ui):
    _, _, clip_id = rated_setup(ui)
    page = ui.page("coach")
    page.goto(f"/clips/{clip_id}")
    card = page.locator("#oceny")
    expect(card).to_contain_text("Klip nie ma jeszcze ocen.")
    page.evaluate("window.__bez_przeladowania = true")

    verdict(page, "nieprawidłowa")
    card.get_by_label("Komentarz (opcjonalnie)").fill("Gracz nie przekroczył linii.")
    card.get_by_role("button", name="Zapisz ocenę").click()
    rating = page.locator("#oceny .rating")
    expect(rating).to_have_count(1)
    expect(rating).to_contain_text("nieprawidłowa")
    expect(rating).to_contain_text("Cezary Trener")
    expect(rating).to_contain_text("Gracz nie przekroczył linii.")
    expect(rating).not_to_contain_text("zmieniona")
    expect(card.get_by_role("button", name="Zapisz zmianę")).to_be_visible()
    assert page.evaluate("window.__bez_przeladowania === true")

    expect(card.get_by_label("nieprawidłowa", exact=True)).to_be_checked()
    verdict(page, "dyskusyjna")
    card.get_by_role("button", name="Zapisz zmianę").click()
    expect(page.locator("#oceny .rating")).to_have_count(1)
    expect(page.locator("#oceny .rating")).to_contain_text("dyskusyjna")
    expect(page.locator("#oceny .rating")).to_contain_text("zmieniona")
    expect(page.locator("#oceny .rating .verdict")).to_have_text("dyskusyjna")
    assert page.evaluate("window.__bez_przeladowania === true")
    page.reload()
    expect(page.locator("#oceny .rating")).to_have_count(1)
    expect(page.locator("#oceny .rating")).to_contain_text("zmieniona")


def test_referee_sees_a_rating_without_the_form_and_admin_changes_and_deletes_someone_elses(ui):
    _, _, clip_id = rated_setup(ui)
    coach = ui.page("coach")
    coach.goto(f"/clips/{clip_id}")
    verdict(coach, "prawidłowa")
    coach.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(coach.locator("#oceny .rating")).to_have_count(1)

    referee = ui.page("referee")
    referee.goto(f"/clips/{clip_id}")
    expect(referee.locator("#oceny .rating")).to_contain_text("Cezary Trener")
    expect(referee.locator("#oceny .rating")).to_contain_text("prawidłowa")
    expect(referee.locator("#oceny form")).to_have_count(0)
    expect(referee.locator("#oceny").get_by_role("button")).to_have_count(0)

    admin = ui.page("admin")
    admin.goto(f"/clips/{clip_id}")
    expect(admin.locator("#rating-form")).to_have_count(0)
    admin.locator("#oceny summary", has_text="Zmień").click()
    admin.locator("#oceny .rating-edit").get_by_label("nieprawidłowa", exact=True).check()
    admin.locator("#oceny .rating-edit").get_by_label("Komentarz (opcjonalnie)").fill("Korekta administratora")
    admin.get_by_role("button", name="Zapisz zmianę").click()
    expect(admin.locator("#oceny .rating")).to_contain_text("Cezary Trener")
    expect(admin.locator("#oceny .rating")).to_contain_text("nieprawidłowa")
    expect(admin.locator("#oceny .rating")).to_contain_text("Korekta administratora")
    expect(admin.locator("#oceny .rating")).not_to_contain_text("Adam Admin")

    admin.on("dialog", lambda d: d.accept())
    admin.locator("#oceny").get_by_role("button", name="Usuń").click()
    expect(admin.locator("#oceny")).to_contain_text("Klip nie ma jeszcze ocen.")
    referee.reload()
    expect(referee.locator("#oceny")).to_contain_text("Klip nie ma jeszcze ocen.")


def test_another_coach_has_no_buttons_on_someone_elses_rating(ui):
    _, _, clip_id = rated_setup(ui)
    coach = ui.page("coach")
    coach.goto(f"/clips/{clip_id}")
    verdict(coach, "prawidłowa")
    coach.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(coach.locator("#oceny .rating")).to_have_count(1)
    expect(coach.locator("#oceny").get_by_role("button", name="Usuń")).to_have_count(1)
    # a second coach: the admin+coach role has no test account, so the outsider referee is checked
    outsider = ui.page("outsider")
    outsider.goto(f"/clips/{clip_id}")
    expect(outsider.locator("#oceny .rating")).to_have_count(1)
    expect(outsider.locator("#oceny").get_by_role("button")).to_have_count(0)


def test_rating_summary_and_filter_in_the_clips_table(ui):
    match_id, video_id, rated = rated_setup(ui)
    plain = ui.server.insert_clip(video_id, 60.0, official="U1", category="aut", described=True)
    coach = ui.page("coach")
    coach.goto(f"/clips/{rated}")
    verdict(coach, "dyskusyjna")
    coach.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(coach.locator("#oceny .rating")).to_have_count(1)

    page = ui.page("referee")
    page.goto(f"/matches/{match_id}")
    expect(page.locator("#clips-list tbody tr")).to_have_count(2)
    expect(page.locator("#clips-list td[data-label='Oceny']").first).to_contain_text("1× dyskusyjna")
    expect(page.locator("#clips-list td[data-label='Oceny']").nth(1)).to_have_text("—")
    page.evaluate("window.__bez_przeladowania = true")

    page.locator("select[name=rating]").select_option(label="bez ocen")
    expect(page).to_have_url(re.compile(r"rating=none"))
    expect(page.locator("#clips-list tbody tr")).to_have_count(1)
    expect(page.locator("#clips-list tbody tr")).to_contain_text("U1 · Kasia Żółć")
    assert "person" not in page.url and "period" not in page.url, page.url
    page.locator("select[name=rating]").select_option(label="ma ocenę: dyskusyjna")
    expect(page.locator("#clips-list tbody tr")).to_have_count(1)
    expect(page.locator("#clips-list tbody tr")).to_contain_text("Przekroczenie linii")
    assert page.evaluate("window.__bez_przeladowania === true")

    page.goto(f"/clips?match_id={match_id}&rating=incorrect")
    expect(page.locator("#clips-list")).to_contain_text("Brak klipów dla wybranych filtrów.")
    page.goto(f"/clips?match_id={match_id}&rating=any")
    expect(page.locator("#clips-list tbody tr")).to_have_count(1)
    assert plain


def test_rating_and_comment_validation_error_shows_a_message_and_keeps_the_text(ui):
    ui.allow(r"status of 422")
    _, _, clip_id = rated_setup(ui)
    page = ui.page("coach")
    page.goto(f"/clips/{clip_id}")
    long_text = "x" * 5001
    verdict(page, "prawidłowa")
    page.locator("#oceny").get_by_label("Komentarz (opcjonalnie)").fill(long_text)
    page.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(page.locator("#oceny [role=alert]")).to_contain_text("najwyżej 5000 znaków")
    expect(page.locator("#oceny").get_by_label("Komentarz (opcjonalnie)")).to_have_value(long_text)
    expect(page.locator("#oceny .rating")).to_have_count(0)

    page.get_by_label("Nowy komentarz").fill(long_text)
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comment-form [role=alert]")).to_contain_text("najwyżej 5000 znaków")
    expect(page.get_by_label("Nowy komentarz")).to_have_value(long_text)
    expect(page.locator("#comments .comment")).to_have_count(0)
    page.get_by_label("Nowy komentarz").fill("Krótki")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comments .comment")).to_have_count(1)
    expect(page.locator("#comment-form [role=alert]")).to_have_count(0)


def comment_cycle(ui, page: Page, scope_name: str) -> None:
    ui.allow(r"status of 422")
    page.evaluate("window.__bez_przeladowania = true")
    page.on("dialog", lambda d: d.accept())
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")

    box = page.get_by_label("Nowy komentarz")
    box.fill("Pierwsza linia\nDruga linia <b>nie jest HTML</b>")
    page.get_by_role("button", name="Dodaj komentarz").click()
    comment = page.locator("#comments .comment")
    expect(comment).to_have_count(1)
    expect(comment).to_contain_text("Adam Admin")
    expect(box).to_have_value("")
    expect(page.locator("#no-comments")).to_have_text("")
    body = comment.locator(".body")
    expect(body).to_have_text("Pierwsza linia\nDruga linia <b>nie jest HTML</b>", use_inner_text=True)
    assert page.evaluate("getComputedStyle(document.querySelector('#comments .body')).whiteSpace") == "pre-wrap"
    assert page.locator("#comments .comment b").count() == 0
    expect(comment).not_to_contain_text("edytowano")

    comment.get_by_role("link", name="Edytuj").click()
    editor = page.locator("#comments .comment textarea")
    expect(editor).to_have_value("Pierwsza linia\nDruga linia <b>nie jest HTML</b>")
    editor.fill("zmieniona w trakcie edycji")
    page.locator("#comments .comment").get_by_role("link", name="Anuluj").click()
    expect(page.locator("#comments .comment textarea")).to_have_count(0)
    expect(page.locator("#comments .comment .body")).to_contain_text("Pierwsza linia")

    page.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    page.locator("#comments .comment textarea").fill("Poprawiony komentarz")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page.locator("#comments .comment .body")).to_have_text("Poprawiony komentarz")
    expect(page.locator("#comments .comment")).to_contain_text("edytowano")
    expect(page.locator("#comments .comment textarea")).to_have_count(0)

    page.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    page.locator("#comments .comment textarea").fill("   ")
    # `required` blocks sending an empty field, so browser validation is released
    page.evaluate("document.querySelector('#comments .comment textarea').removeAttribute('required')")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page.locator("#comments .comment [role=alert]")).to_contain_text("wpisz treść")
    page.locator("#comments .comment").get_by_role("link", name="Anuluj").click()
    expect(page.locator("#comments .comment .body")).to_have_text("Poprawiony komentarz")

    page.locator("#comments .comment").get_by_role("button", name="Usuń").click()
    expect(page.locator("#comments .comment")).to_have_count(0)
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")
    assert page.evaluate("window.__bez_przeladowania === true"), scope_name
    page.reload()
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")


def test_clip_comment_add_edit_cancel_delete(ui):
    _, _, clip_id = rated_setup(ui)
    page = ui.page("admin")
    page.goto(f"/clips/{clip_id}")
    comment_cycle(ui, page, "klip")


def test_match_comment_add_edit_cancel_delete(ui):
    match_id, _, _ = rated_setup(ui)
    page = ui.page("admin")
    page.goto(f"/matches/{match_id}")
    comment_cycle(ui, page, "mecz")


def test_comments_permissions_in_the_interface(ui):
    ui.allow(r"status of 404|Error Code 404")
    match_id, _, _ = rated_setup(ui)
    author = ui.page("referee")
    author.goto(f"/matches/{match_id}")
    author.get_by_label("Nowy komentarz").fill("Komentarz sędziego")
    author.get_by_role("button", name="Dodaj komentarz").click()
    expect(author.locator("#comments .comment")).to_have_count(1)

    admin = ui.page("admin")
    admin.goto(f"/matches/{match_id}")
    mine = admin.locator("#comments .comment")
    expect(mine).to_contain_text("Komentarz sędziego")
    expect(mine.get_by_role("link", name="Edytuj")).to_have_count(0)
    expect(mine.get_by_role("button", name="Usuń")).to_have_count(1)
    other = ui.page("outsider")
    other.goto(f"/matches/{match_id}")
    expect(other.locator("#comments .comment")).to_have_count(1)
    expect(other.locator("#comments .comment .actions")).to_have_count(0)
    admin.on("dialog", lambda d: d.accept())
    mine.get_by_role("button", name="Usuń").click()
    expect(admin.locator("#comments .comment")).to_have_count(0)
    author.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    expect(author.locator(".toast.error")).to_contain_text("Nie ma takiego komentarza")


def test_comments_without_javascript_post_forms_with_redirect(ui):
    ui.allow(r"status of 422")
    match_id, _, clip_id = rated_setup(ui)
    page = ui.page("admin", java_script_enabled=False)
    page.goto(f"/clips/{clip_id}")
    page.get_by_label("Nowy komentarz").fill("Bez JS")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page).to_have_url(re.compile(rf"/clips/{clip_id}#comment-\d+$"))
    expect(page.locator("#comments .comment")).to_have_count(1)
    page.get_by_role("link", name="Edytuj").click()
    expect(page.get_by_role("heading", name="Edycja komentarza")).to_be_visible()
    page.locator("textarea[name=body]").fill("Bez JS, poprawiony")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/clips/{clip_id}#comment-\d+$"))
    expect(page.locator("#comments .comment .body")).to_have_text("Bez JS, poprawiony")
    expect(page.locator("#comments .comment")).to_contain_text("edytowano")
    page.get_by_label("Nowy komentarz").fill("y" * 5001)
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comment-form [role=alert]")).to_contain_text("najwyżej 5000 znaków")
    expect(page.get_by_label("Nowy komentarz")).to_have_value("y" * 5001)
    page.locator("#comments").get_by_role("button", name="Usuń").click()
    expect(page.locator("#comments .comment")).to_have_count(0)

    coach = ui.page("coach", java_script_enabled=False)
    coach.goto(f"/clips/{clip_id}")
    coach.get_by_label("dyskusyjna", exact=True).check()
    coach.get_by_role("button", name="Zapisz ocenę").click()
    expect(coach).to_have_url(re.compile(rf"/clips/{clip_id}#oceny$"))
    expect(coach.locator("#oceny .rating")).to_contain_text("dyskusyjna")
    page2 = ui.page("admin", java_script_enabled=False)
    page2.goto(f"/matches/{match_id}")
    page2.get_by_label("Nowy komentarz").fill("Do meczu bez JS")
    page2.get_by_role("button", name="Dodaj komentarz").click()
    expect(page2.locator("#comments .comment")).to_have_count(1)


def test_match_page_refresh_does_not_wipe_a_comment_being_typed_or_an_edit(ui):
    match_id, video_id, _ = rated_setup(ui)
    from app.models import Video
    with ui.server.db() as db:
        db.get(Video, video_id).status = "processing"
        db.commit()
    own = ui.server.user_by_email("admin@example.com")
    from app.models import Comment
    with ui.server.db() as db:
        db.add(Comment(match_id=match_id, author_id=own.id, body="Istniejący komentarz"))
        db.commit()

    page = ui.page("admin")
    polls = []
    page.on("request", lambda r: polls.append(r) if r.method == "GET" and r.headers.get("hx-request")
            and r.url.split("?")[0].endswith(f"/matches/{match_id}") else None)
    page.goto(f"/matches/{match_id}")
    expect(page.locator("#videos-panel")).to_be_visible()

    page.get_by_label("Nowy komentarz").fill("Rozpoczęty, niewysłany komentarz")
    page.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    editor = page.locator("#comments .comment textarea")
    editor.fill("Edycja w toku")
    editor.focus()
    # markers: these elements must not be swapped; the recordings panel must be refreshed
    page.evaluate("""() => {
        document.querySelector('#komentarze').__zostaje = true;
        document.querySelector('#comment-form').__zostaje = true;
        document.querySelector('#comments .comment').__zostaje = true;
        document.querySelector('#videos-panel').__stary = true;
    }""")

    wait_until(page, lambda: len(polls) >= 2, timeout=20, message="strona meczu nie odświeżyła się dwa razy")
    page.wait_for_function("!document.querySelector('#videos-panel').__stary")
    page.wait_for_timeout(300)
    assert page.evaluate("""() => ({
        sekcja: !!document.querySelector('#komentarze').__zostaje,
        formularz: !!document.querySelector('#comment-form').__zostaje,
        komentarz: !!document.querySelector('#comments .comment').__zostaje,
        szkic: document.querySelector('#comment-form textarea').value,
        edycja: document.querySelector('#comments .comment textarea').value,
        fokus: document.activeElement === document.querySelector('#comments .comment textarea'),
    })""") == {"sekcja": True, "formularz": True, "komentarz": True,
              "szkic": "Rozpoczęty, niewysłany komentarz", "edycja": "Edycja w toku", "fokus": True}


def populate_feedback(ui, match_id, clip_id):
    """Long words and many lines: the worst case for the layout."""
    from app.models import Comment, Rating
    long_word = "Superdługie" + "słowo" * 30
    with ui.server.db() as db:
        for key in ("admin", "referee", "coach"):
            user_id = ui.server.users[key]
            db.add(Comment(clip_id=clip_id, author_id=user_id, body=f"{long_word}\nDruga linia komentarza " * 3))
            db.add(Comment(match_id=match_id, author_id=user_id, body=f"{long_word}\nDruga linia komentarza " * 3))
        db.add(Rating(clip_id=clip_id, coach_id=ui.server.users["coach"], verdict="debatable", comment=long_word))
        db.commit()


def test_mobile_views_without_horizontal_scrolling(ui):
    match_id, video_id, clip_id = rated_setup(ui)
    for t in (60.0, 90.0, 120.0):
        ui.server.insert_clip(video_id, t, official="U1", category="aut", described=True,
                              description="Długi opis klipu " * 8)
    populate_feedback(ui, match_id, clip_id)

    page = ui.page("coach", mobile=True, viewport=PHONE)
    for path in (f"/clips/{clip_id}", f"/matches/{match_id}", f"/clips?match_id={match_id}"):
        page.goto(path)
        page.wait_for_load_state("networkidle")
        assert no_horizontal_scroll(page), (path, page.evaluate(
            "[document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth]"))
    page.goto(f"/clips/{clip_id}")
    for selector in ("#clip-info", "#oceny", "#komentarze", "#comment-form textarea"):
        box = page.locator(selector).first.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"] + 1, (selector, box)
    page.locator("#comments .comment").last.get_by_role("link", name="Edytuj").tap()
    assert no_horizontal_scroll(page)
    box = page.locator("#comments .comment textarea").bounding_box()
    assert box["x"] + box["width"] <= PHONE["width"] + 1
    page.goto(f"/clips?match_id={match_id}")
    expect(page.locator("#clips-list td[data-label='Oceny']").first).to_contain_text("1× dyskusyjna")
    assert page.evaluate("getComputedStyle(document.querySelector('#clips-list thead')).position") == "absolute"
