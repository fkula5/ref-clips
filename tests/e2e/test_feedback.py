"""Scenariusz m): oceny szkoleniowców i komentarze (klip, mecz) w przeglądarce, odświeżanie strony meczu
a wpisywany komentarz oraz widoki mobilne (375×740)."""
import re

from playwright.sync_api import Page, expect

from tests.e2e.support import wait_until

PHONE = {"width": 375, "height": 740}


def rated_setup(ui):
    """Mecz CC=Roman (konto), nagranie i opisany klip (bez pliku klipu: to nie jest tu potrzebne)."""
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="full")
    clip_id = ui.server.insert_clip(video_id, 30.0, official="CC", category="kroki", described=True,
                                    description="Przekroczenie linii")
    return match_id, video_id, clip_id


def verdict(page: Page, label: str) -> None:
    page.locator("#oceny").get_by_label(label, exact=True).check()


def no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth")


# --- oceny ------------------------------------------------------------------------------
def test_szkoleniowiec_ocenia_i_zmienia_ocene(ui):
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

    # zmiana oceny: ta sama para (klip, szkoleniowiec) — nadal jedna ocena, z adnotacją o zmianie
    expect(card.get_by_label("nieprawidłowa", exact=True)).to_be_checked()
    verdict(page, "dyskusyjna")
    card.get_by_role("button", name="Zapisz zmianę").click()
    expect(page.locator("#oceny .rating")).to_have_count(1)
    expect(page.locator("#oceny .rating")).to_contain_text("dyskusyjna")
    expect(page.locator("#oceny .rating")).to_contain_text("zmieniona")
    expect(page.locator("#oceny .rating .verdict")).to_have_text("dyskusyjna")
    assert page.evaluate("window.__bez_przeladowania === true")
    # po odświeżeniu to samo
    page.reload()
    expect(page.locator("#oceny .rating")).to_have_count(1)
    expect(page.locator("#oceny .rating")).to_contain_text("zmieniona")


def test_sedzia_widzi_ocene_bez_formularza_a_admin_zmienia_i_usuwa_cudza(ui):
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

    # administrator (bez roli szkoleniowca): bez własnego formularza, ale zmienia i usuwa cudzą ocenę
    admin = ui.page("admin")
    admin.goto(f"/clips/{clip_id}")
    expect(admin.locator("#rating-form")).to_have_count(0)
    admin.locator("#oceny summary", has_text="Zmień").click()
    admin.locator("#oceny .rating-edit").get_by_label("nieprawidłowa", exact=True).check()
    admin.locator("#oceny .rating-edit").get_by_label("Komentarz (opcjonalnie)").fill("Korekta administratora")
    admin.get_by_role("button", name="Zapisz zmianę").click()
    expect(admin.locator("#oceny .rating")).to_contain_text("Cezary Trener")       # autor się nie zmienia
    expect(admin.locator("#oceny .rating")).to_contain_text("nieprawidłowa")
    expect(admin.locator("#oceny .rating")).to_contain_text("Korekta administratora")
    expect(admin.locator("#oceny .rating")).not_to_contain_text("Adam Admin")

    admin.on("dialog", lambda d: d.accept())
    admin.locator("#oceny").get_by_role("button", name="Usuń").click()
    expect(admin.locator("#oceny")).to_contain_text("Klip nie ma jeszcze ocen.")
    referee.reload()
    expect(referee.locator("#oceny")).to_contain_text("Klip nie ma jeszcze ocen.")


def test_inny_szkoleniowiec_nie_ma_przyciskow_przy_cudzej_ocenie(ui):
    _, _, clip_id = rated_setup(ui)
    coach = ui.page("coach")
    coach.goto(f"/clips/{clip_id}")
    verdict(coach, "prawidłowa")
    coach.locator("#oceny").get_by_role("button", name="Zapisz ocenę").click()
    expect(coach.locator("#oceny .rating")).to_have_count(1)
    expect(coach.locator("#oceny").get_by_role("button", name="Usuń")).to_have_count(1)   # własna
    # drugi szkoleniowiec: z rolą admin+coach nie ma konta testowego, więc sprawdzamy sędziego-outsidera
    outsider = ui.page("outsider")
    outsider.goto(f"/clips/{clip_id}")
    expect(outsider.locator("#oceny .rating")).to_have_count(1)
    expect(outsider.locator("#oceny").get_by_role("button")).to_have_count(0)


def test_podsumowanie_ocen_i_filtr_w_tabeli_klipow(ui):
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

    # globalna lista /clips: te same filtry w adresie
    page.goto(f"/clips?match_id={match_id}&rating=incorrect")
    expect(page.locator("#clips-list")).to_contain_text("Brak klipów dla wybranych filtrów.")
    page.goto(f"/clips?match_id={match_id}&rating=any")
    expect(page.locator("#clips-list tbody tr")).to_have_count(1)
    assert plain  # klip bez ocen nie pasuje do filtra „z oceną”


def test_blad_walidacji_oceny_i_komentarza_pokazuje_komunikat_i_zachowuje_tekst(ui):
    ui.allow(r"status of 422")      # serwer odpowiada 422 na błędną treść; przeglądarka loguje to w konsoli
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
    # poprawienie i ponowne wysłanie działa
    page.get_by_label("Nowy komentarz").fill("Krótki")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comments .comment")).to_have_count(1)
    expect(page.locator("#comment-form [role=alert]")).to_have_count(0)


# --- komentarze -------------------------------------------------------------------------
def comment_cycle(ui, page: Page, scope_name: str) -> None:
    """Dodaj, edytuj, anuluj edycję i usuń komentarz bez przeładowania strony."""
    ui.allow(r"status of 422")      # pusta edycja: serwer odpowiada 422 (sprawdzamy komunikat)
    page.evaluate("window.__bez_przeladowania = true")
    page.on("dialog", lambda d: d.accept())   # potwierdzenie usunięcia
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

    # edycja inline: formularz zamiast treści; Anuluj zostawia treść
    comment.get_by_role("link", name="Edytuj").click()
    editor = page.locator("#comments .comment textarea")
    expect(editor).to_have_value("Pierwsza linia\nDruga linia <b>nie jest HTML</b>")
    editor.fill("zmieniona w trakcie edycji")
    page.locator("#comments .comment").get_by_role("link", name="Anuluj").click()
    expect(page.locator("#comments .comment textarea")).to_have_count(0)
    expect(page.locator("#comments .comment .body")).to_contain_text("Pierwsza linia")

    # edycja i zapis: "edytowano" widoczne
    page.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    page.locator("#comments .comment textarea").fill("Poprawiony komentarz")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page.locator("#comments .comment .body")).to_have_text("Poprawiony komentarz")
    expect(page.locator("#comments .comment")).to_contain_text("edytowano")
    expect(page.locator("#comments .comment textarea")).to_have_count(0)

    # pusta edycja: komunikat błędu, treść zostaje w bazie
    page.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    page.locator("#comments .comment textarea").fill("   ")
    # `required` blokuje wysłanie pustego pola, więc zwalniamy walidację przeglądarki
    page.evaluate("document.querySelector('#comments .comment textarea').removeAttribute('required')")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page.locator("#comments .comment [role=alert]")).to_contain_text("wpisz treść")
    page.locator("#comments .comment").get_by_role("link", name="Anuluj").click()
    expect(page.locator("#comments .comment .body")).to_have_text("Poprawiony komentarz")

    # usunięcie z potwierdzeniem
    page.locator("#comments .comment").get_by_role("button", name="Usuń").click()
    expect(page.locator("#comments .comment")).to_have_count(0)
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")
    assert page.evaluate("window.__bez_przeladowania === true"), scope_name
    page.reload()
    expect(page.locator("#no-comments")).to_have_text("Brak komentarzy.")


def test_komentarz_do_klipu_dodaj_edytuj_anuluj_usun(ui):
    _, _, clip_id = rated_setup(ui)
    page = ui.page("admin")
    page.goto(f"/clips/{clip_id}")
    comment_cycle(ui, page, "klip")


def test_komentarz_do_meczu_dodaj_edytuj_anuluj_usun(ui):
    match_id, _, _ = rated_setup(ui)
    page = ui.page("admin")
    page.goto(f"/matches/{match_id}")
    comment_cycle(ui, page, "mecz")


def test_komentarze_uprawnienia_w_interfejsie(ui):
    ui.allow(r"status of 404|Error Code 404")      # edycja komentarza usuniętego w międzyczasie: 404 i komunikat
    match_id, _, _ = rated_setup(ui)
    author = ui.page("referee")
    author.goto(f"/matches/{match_id}")
    author.get_by_label("Nowy komentarz").fill("Komentarz sędziego")
    author.get_by_role("button", name="Dodaj komentarz").click()
    expect(author.locator("#comments .comment")).to_have_count(1)

    # administrator usuwa cudzy, ale nie edytuje
    admin = ui.page("admin")
    admin.goto(f"/matches/{match_id}")
    mine = admin.locator("#comments .comment")
    expect(mine).to_contain_text("Komentarz sędziego")
    expect(mine.get_by_role("link", name="Edytuj")).to_have_count(0)
    expect(mine.get_by_role("button", name="Usuń")).to_have_count(1)
    # inny sędzia nie widzi żadnych akcji
    other = ui.page("outsider")
    other.goto(f"/matches/{match_id}")
    expect(other.locator("#comments .comment")).to_have_count(1)
    expect(other.locator("#comments .comment .actions")).to_have_count(0)
    admin.on("dialog", lambda d: d.accept())
    mine.get_by_role("button", name="Usuń").click()
    expect(admin.locator("#comments .comment")).to_have_count(0)
    # autor próbuje edytować komentarz, który ktoś już usunął: komunikat zamiast cichej bezczynności
    author.locator("#comments .comment").get_by_role("link", name="Edytuj").click()
    expect(author.locator(".toast.error")).to_contain_text("Nie ma takiego komentarza")


def test_komentarze_bez_javascriptu_formularze_post_z_przekierowaniem(ui):
    ui.allow(r"status of 422")      # błąd walidacji w zwykłym formularzu: strona z kodem 422
    match_id, _, clip_id = rated_setup(ui)
    page = ui.page("admin", java_script_enabled=False)
    page.goto(f"/clips/{clip_id}")
    page.get_by_label("Nowy komentarz").fill("Bez JS")
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page).to_have_url(re.compile(rf"/clips/{clip_id}#comment-\d+$"))
    expect(page.locator("#comments .comment")).to_have_count(1)
    page.get_by_role("link", name="Edytuj").click()                  # osobna strona edycji
    expect(page.get_by_role("heading", name="Edycja komentarza")).to_be_visible()
    page.locator("textarea[name=body]").fill("Bez JS, poprawiony")
    page.get_by_role("button", name="Zapisz", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/clips/{clip_id}#comment-\d+$"))
    expect(page.locator("#comments .comment .body")).to_have_text("Bez JS, poprawiony")
    expect(page.locator("#comments .comment")).to_contain_text("edytowano")
    # błąd: cały widok z komunikatem i zachowaną treścią
    page.get_by_label("Nowy komentarz").fill("y" * 5001)
    page.get_by_role("button", name="Dodaj komentarz").click()
    expect(page.locator("#comment-form [role=alert]")).to_contain_text("najwyżej 5000 znaków")
    expect(page.get_by_label("Nowy komentarz")).to_have_value("y" * 5001)
    page.locator("#comments").get_by_role("button", name="Usuń").click()   # bez JS: bez potwierdzenia
    expect(page.locator("#comments .comment")).to_have_count(0)

    # ocena bez JS
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


# --- odświeżanie strony meczu --------------------------------------------------------------
def test_odswiezanie_strony_meczu_nie_kasuje_wpisywanego_komentarza_ani_edycji(ui):
    match_id, video_id, _ = rated_setup(ui)
    # nagranie w trakcie wgrywania => strona meczu odpytuje serwer co 3 s (hx-trigger every 3s)
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
    # znaczniki: te elementy nie mogą zostać podmienione; panel nagrań ma zostać odświeżony
    page.evaluate("""() => {
        document.querySelector('#komentarze').__zostaje = true;
        document.querySelector('#comment-form').__zostaje = true;
        document.querySelector('#comments .comment').__zostaje = true;
        document.querySelector('#videos-panel').__stary = true;
    }""")

    wait_until(page, lambda: len(polls) >= 2, timeout=20, message="strona meczu nie odświeżyła się dwa razy")
    page.wait_for_function("!document.querySelector('#videos-panel').__stary")        # panel faktycznie podmieniony
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


# --- widoki mobilne (375×740) ---------------------------------------------------------------
def populate_feedback(ui, match_id, clip_id):
    """Oceny i komentarze o długich słowach i wielu liniach: najgorszy przypadek dla układu."""
    from app.models import Comment, Rating
    long_word = "Superdługie" + "słowo" * 30
    with ui.server.db() as db:
        for key in ("admin", "referee", "coach"):
            user_id = ui.server.users[key]
            db.add(Comment(clip_id=clip_id, author_id=user_id, body=f"{long_word}\nDruga linia komentarza " * 3))
            db.add(Comment(match_id=match_id, author_id=user_id, body=f"{long_word}\nDruga linia komentarza " * 3))
        db.add(Rating(clip_id=clip_id, coach_id=ui.server.users["coach"], verdict="debatable", comment=long_word))
        db.commit()


def test_widoki_mobilne_bez_poziomego_przewijania(ui):
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
    # strona klipu: opis, oceny i komentarze widoczne w obrębie ekranu
    page.goto(f"/clips/{clip_id}")
    for selector in ("#clip-info", "#oceny", "#komentarze", "#comment-form textarea"):
        box = page.locator(selector).first.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"] + 1, (selector, box)
    # edycja komentarza i formularz oceny też mieszczą się w ekranie
    page.locator("#comments .comment").last.get_by_role("link", name="Edytuj").tap()
    assert no_horizontal_scroll(page)
    box = page.locator("#comments .comment textarea").bounding_box()
    assert box["x"] + box["width"] <= PHONE["width"] + 1
    # tabela klipów to karty z podsumowaniem ocen
    page.goto(f"/clips?match_id={match_id}")
    expect(page.locator("#clips-list td[data-label='Oceny']").first).to_contain_text("1× dyskusyjna")
    assert page.evaluate("getComputedStyle(document.querySelector('#clips-list thead')).position") == "absolute"
