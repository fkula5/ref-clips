"""Scenariusz k): ekran opisywania znaczników — kolejka, skróty klawiszowe, propozycje z notatek,
kwarta nieustalona, podgląd klipu, pomiń/usuń, wejście z meczu i z odtwarzacza."""
import re

from playwright.sync_api import Page, expect

from tests.e2e.support import wait_until

PREVIEW = "document.getElementById('preview')"


def setup_match(ui, times=(20.0, 30.0, 40.0), *, content="Q1,Q2", periods=(("Q1", 5.0), ("Q2", 35.0)),
                officials=(("CC", "referee"), ("U1", "Kasia Żółć"), ("U2", "second")), **clip_kwargs):
    """Mecz z obsadą CC/U1/U2, nagraniem (50 s) ze znacznikami kwart i klipami bez zadań cięcia."""
    match_id = ui.server.make_match(officials=officials)
    video_id = ui.server.make_ready_video(match_id, content=content)
    for period, at in periods:
        ui.server.set_mark(video_id, period, at)
    clip_ids = [ui.server.insert_clip(video_id, t, status="new", margin=1.0, **clip_kwargs) for t in times]
    return match_id, video_id, clip_ids


def open_describe(ui, match_id, role="admin", *, mobile=False, query=""):
    page = ui.page(role, mobile=mobile)
    page.goto(f"/matches/{match_id}/describe{query}")
    return page


def current_id(page: Page) -> int:
    return int(page.locator("#describe").get_attribute("data-clip"))


def test_opisanie_trzech_znacznikow_z_klawiatury(ui):
    match_id, video_id, (c1, c2, c3) = setup_match(ui)
    page = open_describe(ui, match_id)
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 3")
    expect(page.locator("#describe-list li")).to_have_count(3)
    assert current_id(page) == c1

    # znacznik 1: 1 = CC, K + wpisanie nazwy kategorii, Enter = zapisz i dalej
    page.keyboard.press("1")
    expect(page.get_by_label("CC · Roman Sędzia")).to_be_checked()
    page.keyboard.press("k")
    expect(page.locator("#category-select")).to_be_focused()
    page.keyboard.type("kroki")
    expect(page.locator("#category-select option:checked")).to_have_text("kroki")
    page.keyboard.press("Enter")
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 2")
    assert current_id(page) == c2
    first = ui.server.clip(c1)
    assert first.described_at is not None and first.official_id and first.category_id and not first.whole_team

    # znacznik 2: 2 = U1; kategoria listą (grupy), potem Enter na stronie
    page.keyboard.press("2")
    expect(page.get_by_label("U1 · Kasia Żółć")).to_be_checked()
    page.locator("#category-select").select_option(label="aut")
    page.locator("#category-select").evaluate("el => el.blur()")
    page.keyboard.press("Enter")
    expect(page.locator("#describe-list li")).to_have_count(1)
    assert current_id(page) == c3
    assert ui.server.clip(c2).described_at is not None

    # znacznik 3: 0 = cały zespół, D = opis; cyfry w opisie nie zmieniają sędziego; Ctrl+Enter zapisuje
    page.keyboard.press("0")
    expect(page.get_by_label("cały zespół")).to_be_checked()
    page.keyboard.press("d")
    expect(page.locator("#description")).to_be_focused()
    page.keyboard.type("Zdarzenie 123 w 0 minucie")
    expect(page.get_by_label("cały zespół")).to_be_checked()
    expect(page.locator("#description")).to_have_value("Zdarzenie 123 w 0 minucie")
    page.locator("#category-select").select_option(label="inne")
    page.locator("#description").press("Control+Enter")
    expect(page.locator("#all-described")).to_be_visible()
    last = ui.server.clip(c3)
    assert last.whole_team and last.official_id is None and last.description == "Zdarzenie 123 w 0 minucie"
    clips = {c.id: c for c in ui.server.clips_of(video_id)}
    assert all(c.described_at is not None for c in clips.values())
    # wejście na stronę klipu pokazuje zapisane wartości
    page.goto(f"/clips/{c1}")
    expect(page.locator("#clip-info")).to_contain_text("CC · Roman Sędzia")
    expect(page.locator("#clip-info")).to_contain_text("kroki")


def test_skroty_nie_dzialaja_w_polach_tekstowych(ui):
    match_id, _, _ = setup_match(ui)
    page = open_describe(ui, match_id)
    page.get_by_label("Opis (opcjonalnie)").click()
    page.keyboard.type("1230 k d r")
    expect(page.locator("#description")).to_have_value("1230 k d r")
    expect(page.locator("input[name=official]:checked")).to_have_count(0)
    # własna kategoria: pole nazwy jest widoczne i też przyjmuje cyfry
    page.locator("#category-select").select_option(label="własna")
    custom = page.locator("input[name=custom_category]")
    expect(custom).to_be_visible()
    custom.click()
    page.keyboard.type("T 3")
    expect(custom).to_have_value("T 3")
    expect(page.locator("input[name=official]:checked")).to_have_count(0)


def test_propozycje_z_notatek_sa_widoczne_i_zatwierdzane(ui):
    match_id, video_id, (c1, c2) = setup_match(ui, times=(20.0, 30.0), official="U1", category="kroki",
                                               description="0:20 Kasia kroki")
    page = open_describe(ui, match_id)
    expect(page.locator("#proposal-note")).to_contain_text("pochodzą z notatek")
    expect(page.get_by_label("U1 · Kasia Żółć")).to_be_checked()
    expect(page.locator("#category-select option:checked")).to_have_text("kroki")
    expect(page.locator("#description")).to_have_value("0:20 Kasia kroki")
    expect(page.locator("#describe-list li").first.locator(".chip", has_text="propozycja")).to_be_visible()
    assert ui.server.clip(c1).described_at is None            # propozycja nie jest jeszcze opisem
    page.keyboard.press("Enter")                                 # zatwierdzenie bez zmian
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 1")
    done = ui.server.clip(c1)
    assert done.described_at is not None and done.category_id and done.official_id
    # poprawka propozycji przed zatwierdzeniem
    page.keyboard.press("3")
    page.keyboard.press("Enter")
    expect(page.locator("#all-described")).to_be_visible()
    fixed = ui.server.clip(c2)
    assert fixed.described_at is not None
    with ui.server.db() as db:
        from app.models import Clip
        assert db.get(Clip, c2).official.function == "U2"


def test_kwarta_nieustalona_blokuje_opis_i_prowadzi_do_ustawienia_kwart(ui):
    match_id, video_id, (c1,) = setup_match(ui, times=(20.0,), content="full", periods=())
    page = open_describe(ui, match_id)
    block = page.locator("#describe-block")
    expect(block).to_contain_text("Kwarta tego klipu jest nieustalona")
    expect(block).to_contain_text("brakuje: Q1, Q2, Q3, Q4")
    expect(page.locator("#clip-form")).to_have_count(0)
    expect(page.locator("#describe-list li").first).to_contain_text("kwarta nieustalona")
    page.keyboard.press("Enter")                                   # skróty niczego nie zapisują
    page.keyboard.press("1")
    assert ui.server.clip(c1).described_at is None
    # strona klipu też nie pozwala opisać
    page.goto(f"/clips/{c1}")
    expect(page.locator("#clip-edit #describe-block")).to_be_visible()
    # link prowadzi do panelu „Początki kwart” w odtwarzaczu
    page.goto(f"/matches/{match_id}/describe")
    page.get_by_role("link", name="Ustaw początki kwart w odtwarzaczu").click()
    expect(page).to_have_url(re.compile(rf"/videos/{video_id}#poczatki-kwart$"))
    expect(page.locator("#poczatki-kwart")).to_be_visible()
    # po ustawieniu kwart opisywanie działa
    for period, at in (("Q1", 5.0), ("Q2", 15.0), ("Q3", 30.0), ("Q4", 40.0)):
        ui.server.set_mark(video_id, period, at)
    page.goto(f"/matches/{match_id}/describe")
    expect(page.locator("#clip-form")).to_be_visible()
    expect(page.locator("#describe-block")).to_have_count(0)


def test_walidacja_przegladarki_i_serwera_w_formularzu(ui):
    match_id, _, (c1, c2, c3) = setup_match(ui)
    page = open_describe(ui, match_id)
    # brak wyboru: formularz się nie wysyła (required), nic się nie zapisuje
    page.keyboard.press("Enter")
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 3")
    page.keyboard.press("2")
    page.keyboard.press("Enter")                                  # nadal bez kategorii
    assert ui.server.clip(c1).described_at is None
    page.locator("#category-select").select_option(label="własna")
    page.keyboard.press("Enter")                                  # kategoria własna bez nazwy
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 3")
    assert ui.server.clip(c1).described_at is None
    page.locator("input[name=custom_category]").fill("ustawienie przy linii")
    page.locator("input[name=custom_category]").press("Enter")    # Enter w polu nazwy zapisuje
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 2")
    saved = ui.server.clip(c1)
    assert saved.custom_category == "ustawienie przy linii" and saved.described_at is not None

    # serwer: kategoria nieaktywna odrzucona (formularz otwarty przed dezaktywacją)
    ui.allow(r"status of 422")
    page.keyboard.press("1")
    page.locator("#category-select").select_option(label="aut")
    with ui.server.db() as db:
        from sqlalchemy import update
        from app.models import Category
        db.execute(update(Category).where(Category.name == "aut").values(is_active=False))
        db.commit()
    try:
        page.keyboard.press("Enter")
        error = page.locator("#form-error")
        expect(error).to_contain_text("Ta kategoria jest nieaktywna")
        expect(page.get_by_label("CC · Roman Sędzia")).to_be_checked()      # wartości zachowane
        assert ui.server.clip(c2).described_at is None
    finally:
        with ui.server.db() as db:
            db.execute(update(Category).where(Category.name == "aut").values(is_active=True))
            db.commit()


def test_pomin_nie_zapisuje_a_usun_znacznik_pyta_o_potwierdzenie(ui):
    match_id, video_id, (c1, c2, c3) = setup_match(ui)
    page = open_describe(ui, match_id)
    page.get_by_role("link", name="Pomiń").click()
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 2 z 3")
    assert current_id(page) == c2 and ui.server.clip(c1).described_at is None
    page.get_by_role("link", name="Pomiń").click()
    assert current_id(page) == c3
    page.get_by_role("link", name="Pomiń").click()                  # po ostatnim wraca do pierwszego
    assert current_id(page) == c1

    # lista z boku też przełącza klipy
    page.locator("#describe-list li", has_text="0:40").get_by_role("link").click()
    assert current_id(page) == c3

    # usunięcie: najpierw odmowa w oknie potwierdzenia, potem zgoda
    dialogs = []
    page.once("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.get_by_role("button", name="Usuń znacznik").click()
    assert dialogs and "Usunąć ten znacznik" in dialogs[0]
    assert ui.server.clip(c3) is not None
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Usuń znacznik").click()
    expect(page.locator("#describe-list li")).to_have_count(2)
    assert ui.server.clip(c3) is None
    assert current_id(page) == c1                                   # następny po usuniętym 0:40 (wraca do początku)


def test_podglad_z_wersji_roboczej_zatrzymuje_sie_na_koncu_klipu(ui):
    match_id, video_id, (c1, c2) = setup_match(ui, times=(20.0, 45.0))
    page = open_describe(ui, match_id, query=f"?clip={c1}")
    expect(page.locator("#draft-note")).to_contain_text("czeka na wycięcie")
    page.wait_for_function(f"{PREVIEW}.readyState >= 1")
    page.wait_for_function(f"Math.abs({PREVIEW}.currentTime - 19) < 0.3")      # start klipu = znacznik − margines (1 s)
    assert page.evaluate(f"{PREVIEW}.paused")
    page.keyboard.press(" ")                                                    # spacja = odtwórz
    page.wait_for_function(f"!{PREVIEW}.paused")
    page.keyboard.press(" ")                                                    # i pauza
    page.wait_for_function(f"{PREVIEW}.paused")
    page.keyboard.press(" ")
    page.wait_for_function(f"{PREVIEW}.paused && {PREVIEW}.currentTime >= 20.9", timeout=15_000)   # zatrzymanie na końcu
    assert page.evaluate(f"{PREVIEW}.currentTime") < 21.6
    page.keyboard.press(" ")                                                    # ponowne odtwarzanie wraca na początek
    page.wait_for_function(f"!{PREVIEW}.paused && {PREVIEW}.currentTime < 20.5")
    page.keyboard.press("r")
    page.wait_for_function(f"{PREVIEW}.currentTime < 20.2")


def test_podglad_pliku_klipu_gdy_wyciety(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    ui.server.set_mark(video_id, "Q1", 5.0)
    ui.server.set_mark(video_id, "Q2", 40.0)
    clip_id = ui.server.create_clip(video_id, 25.0)                              # prawdziwe cięcie przez workera
    page = ui.page("admin")
    wait_until(page, lambda: ui.server.clip(clip_id).status == "cut", timeout=60, message="worker nie wyciął klipu")
    page.goto(f"/matches/{match_id}/describe?clip={clip_id}")
    expect(page.locator("#preview")).to_have_attribute("src", re.compile(rf"/clips/{clip_id}/file\?v=1"))
    page.wait_for_function(f"{PREVIEW}.readyState >= 1 && {PREVIEW}.duration > 20")


def test_blad_ciecia_na_ekranie_opisywania(ui):
    match_id, video_id, (c1, c2) = setup_match(ui, times=(20.0, 30.0))
    ui.server.insert_clip(video_id, 45.0, status="error", error="Moment poza nagraniem: 9:00 (nagranie trwa 0:50)")
    page = open_describe(ui, match_id, query=f"?video_id={video_id}")
    page.locator("#describe-list li", has_text="0:45").get_by_role("link").click()
    problem = page.locator("#cut-problem")
    expect(problem).to_contain_text("Moment poza nagraniem")
    expect(page.get_by_role("button", name="Wytnij ponownie")).to_have_count(0)
    expect(page.get_by_role("button", name="Usuń znacznik")).to_be_visible()
    expect(page.locator("#preview")).to_have_count(0)
    page.keyboard.press("Space")                                                 # bez podglądu skrót nic nie psuje


def test_wejscie_ze_strony_meczu(ui):
    match_id, video_id, _ = setup_match(ui)
    page = ui.page("admin")
    page.goto(f"/matches/{match_id}")
    button = page.get_by_role("link", name="Opisz znaczniki (3)")
    expect(button).to_be_visible()
    button.click()
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}/describe$"))
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 3")
    # sędzia spoza obsady nie ma przycisku, a bezpośredni adres daje 403
    ui.allow(r"status of 403")
    other = ui.page("outsider")
    other.goto(f"/matches/{match_id}")
    expect(other.get_by_role("link", name=re.compile("Opisz znaczniki"))).to_have_count(0)
    other.goto(f"/matches/{match_id}")
    other.evaluate(f"location.href = '/matches/{match_id}/describe'")
    expect(other.get_by_role("heading", name="Brak dostępu")).to_be_visible()


def test_wejscie_z_odtwarzacza_i_licznik_nieopisanych(ui):
    match_id, video_id, _ = setup_match(ui, times=(), content="Q1,Q2")
    page = ui.page("admin")
    page.goto(f"/videos/{video_id}")
    page.wait_for_function("document.getElementById('player').readyState >= 1")
    counter = page.locator("#undescribed-count")
    expect(counter).to_have_text("0")
    page.evaluate("document.getElementById('player').currentTime = 12")
    page.wait_for_function("document.getElementById('player').currentTime > 11.5")
    page.keyboard.press("z")
    expect(counter).to_have_text("1")
    page.wait_for_timeout(1200)
    page.keyboard.press("z")
    expect(counter).to_have_text("2")
    page.get_by_role("link", name=re.compile(r"Opisz znaczniki \(2\)")).click()
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}/describe\?video_id={video_id}$"))
    expect(page.locator("#describe-list li")).to_have_count(2)
    expect(page.locator("h1")).to_have_text("Opisywanie znaczników")
    # opisanie jednego zmniejsza licznik po powrocie do odtwarzacza
    page.keyboard.press("0")
    page.locator("#category-select").select_option(label="inne")
    page.keyboard.press("Enter")
    expect(page.locator("#describe-list li")).to_have_count(1)
    page.get_by_role("link", name="odtwarzacz").click()
    page.wait_for_function("document.getElementById('player').readyState >= 1")
    expect(page.locator("#undescribed-count")).to_have_text("1")


def test_ekran_opisywania_na_telefonie(ui):
    match_id, _, (c1, _c2, _c3) = setup_match(ui)
    page = open_describe(ui, match_id, mobile=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#preview")).to_be_visible()
    assert page.locator("#preview").bounding_box()["width"] <= 390
    page.get_by_label("U1 · Kasia Żółć").tap()
    page.locator("#category-select").select_option(label="aut")
    page.get_by_role("button", name="Zapisz i dalej").tap()
    expect(page.locator("#describe-position")).to_contain_text("Znacznik 1 z 2")
    assert ui.server.clip(c1).described_at is not None
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
