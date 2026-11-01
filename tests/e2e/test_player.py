"""Scenariusze f) i g): odtwarzacz, skróty klawiszowe, znaczniki i uprawnienia w interfejsie."""
import re

from playwright.sync_api import Page, expect

VIDEO = "document.getElementById('player')"
ROWS = "#decisions li:has(a.t)"  # wiersze znaczników (bez wiersza „Brak znaczników”)


def open_player(ui, role="admin", *, content="Q1,Q2", mobile=False):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content=content)
    page = ui.page(role, mobile=mobile)
    page.goto(f"/videos/{video_id}")
    wait_metadata(page)
    return page, match_id, video_id


def wait_metadata(page: Page) -> None:
    page.wait_for_function(f"{VIDEO}.readyState >= 1 && {VIDEO}.duration > 0")


def now(page: Page) -> float:
    return page.evaluate(f"{VIDEO}.currentTime")


def seek_to(page: Page, seconds: float) -> None:
    """Ustawia czas i czeka na zakończenie przewijania (zdarzenie seeked)."""
    page.evaluate(f"""new Promise(resolve => {{
        const v = {VIDEO};
        v.addEventListener('seeked', () => resolve(), {{once: true}});
        v.currentTime = {seconds};
    }})""")


def wait_time(page: Page, seconds: float, tolerance: float = 0.2) -> None:
    page.wait_for_function(f"Math.abs({VIDEO}.currentTime - {seconds}) <= {tolerance}")


def test_klawisz_q_ustawia_poczatki_kwart_i_baner_znika(ui):
    ui.allow(r"status of 422")  # serwer odrzuca kwartę w złej kolejności — test sprawdza komunikat
    page, _, video_id = open_player(ui)
    banner = page.locator("#marks-banner")
    expect(banner).to_be_visible()
    expect(page.locator("#missing-list")).to_have_text("Q1, Q2")
    expect(page.locator("#periods .period-row")).to_have_count(2)
    expect(page.locator("#next-period")).to_have_text("Q1")

    seek_to(page, 10)
    page.keyboard.press("q")
    q1 = page.locator("#periods .period-row", has_text="Q1")
    expect(q1.locator("a")).to_have_text("0:10")
    expect(q1.get_by_role("button", name="Ustaw ponownie tutaj")).to_be_visible()
    expect(page.locator("#next-period")).to_have_text("Q2")
    expect(banner).to_be_visible()  # Q2 nadal brakuje
    expect(page.locator("#missing-list")).to_have_text("Q2")

    seek_to(page, 30)
    page.keyboard.press("q")
    expect(page.locator("#periods .period-row", has_text="Q2").locator("a")).to_have_text("0:30")
    expect(banner).to_be_hidden()
    expect(page.locator("#next-period")).to_have_text("wszystkie ustawione")
    assert ui.server.marks_of(video_id) == {"Q1": 10.0, "Q2": 30.0} or all(
        abs(ui.server.marks_of(video_id)[p] - t) < 0.6 for p, t in (("Q1", 10), ("Q2", 30)))

    # kliknięcie czasu początku kwarty przewija wideo
    page.locator("#periods .period-row", has_text="Q1").locator("a").click()
    wait_time(page, 10)
    # przycisk „Ustaw ponownie tutaj” przesuwa znacznik, a kolejność pilnuje serwer
    seek_to(page, 12)
    q1.get_by_role("button", name="Ustaw ponownie tutaj").click()
    expect(q1.locator("a")).to_have_text("0:12")
    seek_to(page, 40)
    q1.get_by_role("button", name="Ustaw ponownie tutaj").click()
    expect(page.locator("#toast")).to_contain_text("Q1 nie może zaczynać się po Q2")
    expect(q1.locator("a")).to_have_text("0:12")


def test_zaznacz_podczas_odtwarzania_nie_zatrzymuje_wideo(ui):
    page, _, video_id = open_player(ui)
    seek_to(page, 12)
    page.evaluate(f"{VIDEO}.play()")
    page.wait_for_function(f"!{VIDEO}.paused && {VIDEO}.currentTime > 12.5")

    page.keyboard.press("z")
    # błysk na obrazie i licznik znaczników
    expect(page.locator("#flash")).to_contain_text("Znacznik")
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    expect(page.locator(ROWS)).to_have_count(1)
    expect(page.locator("#dec-count")).to_have_text("(1)")
    # wideo nadal gra
    assert page.evaluate(f"{VIDEO}.paused") is False
    t1 = now(page)
    page.wait_for_function(f"{VIDEO}.currentTime > {t1 + 0.4}")
    assert page.evaluate(f"{VIDEO}.paused") is False

    clips = ui.server.clips_of(video_id)
    assert len(clips) == 1 and 12.4 < clips[0].time_sec < 14.5 and clips[0].described_at is None
    item = page.locator(ROWS).first
    expect(item.locator("a.t")).to_have_text(re.compile(r"0:1[2-4]"))
    expect(item).to_contain_text("kwarta nieustalona")
    expect(item).to_contain_text("nieopisany")
    # stan cięcia aktualizuje się sam aż do „wycięty”
    expect(item.locator(".badge")).to_have_text("wycięty", timeout=60_000)
    # po wycięciu wideo nadal gra, a klip jest dostępny
    assert page.evaluate(f"{VIDEO}.paused") is False
    expect(item.get_by_role("link", name="klip")).to_have_attribute("href", re.compile(r"/clips/\d+"))


def test_podwojne_z_to_jeden_znacznik_a_backspace_cofa(ui):
    page, _, video_id = open_player(ui)
    seek_to(page, 20)
    page.keyboard.press("z")
    page.keyboard.press("z")
    expect(page.locator(ROWS)).to_have_count(1)
    page.wait_for_timeout(1300)  # okno ochrony przed podwójnym kliknięciem trwa 1 s (po stronie klienta i serwera)
    assert len(ui.server.clips_of(video_id)) == 1
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")

    seek_to(page, 35)
    page.keyboard.press("z")
    expect(page.locator(ROWS)).to_have_count(2)
    page.wait_for_timeout(1100)
    # Backspace cofa ostatni (35 s) i zostawia pierwszy
    page.keyboard.press("Backspace")
    expect(page.locator(ROWS)).to_have_count(1)
    expect(page.locator("#flash")).to_contain_text("Cofnięto znacznik")
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    clips = ui.server.clips_of(video_id)
    assert [round(c.time_sec) for c in clips] == [20]
    # cofnięcie przy braku własnych nieopisanych znaczników daje komunikat, nie błąd JS
    ui.allow(r"status of 404")
    page.keyboard.press("Backspace")
    expect(page.locator(ROWS)).to_have_count(0)
    page.keyboard.press("Backspace")
    expect(page.locator("#toast")).to_contain_text("Nie masz nieopisanego znacznika")


def test_przewijanie_klatki_tempo_i_pomoc(ui):
    page, _, _ = open_player(ui)
    page.evaluate(f"{VIDEO}.pause()")
    seek_to(page, 20)
    page.keyboard.press("ArrowRight")
    wait_time(page, 21)
    page.keyboard.press("Shift+ArrowRight")
    wait_time(page, 26)
    page.keyboard.press("ArrowLeft")
    wait_time(page, 25)
    page.keyboard.press("Shift+ArrowLeft")
    wait_time(page, 20)
    # krok o klatkę (25 kl./s = 0,04 s)
    page.keyboard.press(".")
    wait_time(page, 20.04, 0.02)
    page.keyboard.press(".")
    wait_time(page, 20.08, 0.02)
    page.keyboard.press(",")
    wait_time(page, 20.04, 0.02)
    assert page.evaluate(f"{VIDEO}.paused") is True

    # tempo: [ wolniej, ] szybciej, zsynchronizowane z listą wyboru
    speed = page.locator("#speed")
    expect(speed).to_have_value("1")
    page.keyboard.press("[")
    expect(speed).to_have_value("0.75")
    assert page.evaluate(f"{VIDEO}.playbackRate") == 0.75
    page.keyboard.press("]")
    page.keyboard.press("]")
    expect(speed).to_have_value("1.25")
    assert page.evaluate(f"{VIDEO}.playbackRate") == 1.25
    for _ in range(6):
        page.keyboard.press("]")
    expect(speed).to_have_value("2")  # górna granica
    for _ in range(8):
        page.keyboard.press("[")
    expect(speed).to_have_value("0.25")

    # spacja: start / pauza
    page.keyboard.press(" ")
    page.wait_for_function(f"!{VIDEO}.paused")
    page.keyboard.press(" ")
    page.wait_for_function(f"{VIDEO}.paused")

    # pomoc pod „?”
    help_box = page.locator("#help")
    expect(help_box).to_be_hidden()
    page.keyboard.press("?")
    expect(help_box).to_be_visible()
    expect(help_box).to_contain_text("Skróty klawiszowe")
    page.keyboard.press("Escape")
    expect(help_box).to_be_hidden()
    page.get_by_role("button", name="? Skróty").click()
    expect(help_box).to_be_visible()
    page.get_by_role("button", name="Zamknij (Esc)").click()
    expect(help_box).to_be_hidden()


def test_skroty_nie_dzialaja_przy_pisaniu_a_m_tworzy_znacznik_z_notatka(ui):
    page, _, video_id = open_player(ui)
    seek_to(page, 25)
    page.evaluate(f"{VIDEO}.play()")
    page.keyboard.press("m")
    quick = page.locator("#quick-form")
    expect(quick).to_be_visible()
    expect(page.locator("#quick-text")).to_be_focused()
    page.wait_for_function(f"{VIDEO}.paused")  # M zatrzymuje wideo na czas pisania
    expect(page.locator("#quick-time")).to_have_text(re.compile(r"0:2[5-6]"))

    # litery skrótów wpisane w pole to zwykły tekst: nie powstaje znacznik ani nie zmienia się tempo
    page.keyboard.type("zqm[]?., f")
    expect(page.locator("#quick-text")).to_have_value("zqm[]?., f")
    page.wait_for_timeout(300)
    assert ui.server.clips_of(video_id) == []
    assert ui.server.marks_of(video_id) == {}
    expect(page.locator("#help")).to_be_hidden()
    expect(page.locator("#speed")).to_have_value("1")

    page.locator("#quick-text").fill("Roman kroki")
    page.keyboard.press("Enter")
    expect(quick).to_be_hidden()
    item = page.locator(ROWS).first
    expect(item).to_contain_text("CC · Roman Sędzia")
    expect(item).to_contain_text("kroki")
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    clip = ui.server.clips_of(video_id)[0]
    assert clip.official_id and clip.category_id and 24.5 < clip.time_sec < 27

    # Esc zamyka pole bez zapisu
    page.keyboard.press("m")
    expect(quick).to_be_visible()
    page.keyboard.type("jakaś notatka")
    page.keyboard.press("Escape")
    expect(quick).to_be_hidden()
    assert len(ui.server.clips_of(video_id)) == 1

    # po zamknięciu pola skróty znów działają
    page.keyboard.press("?")
    expect(page.locator("#help")).to_be_visible()


def test_klikniecie_czasu_na_liscie_i_osi_przewija(ui):
    page, _, video_id = open_player(ui)
    ui.server.create_clip(video_id, 33.0)
    ui.server.set_mark(video_id, "Q1", 5.0)
    page.reload()
    wait_metadata(page)
    seek_to(page, 1)
    page.locator("#decisions a.t").first.click()
    wait_time(page, 33)
    expect(page.locator(ROWS).first).to_contain_text("Q1 · 0:28")  # 33 s - 5 s
    expect(page.locator("#timeline i.tl-dec")).to_have_count(1)
    expect(page.locator("#timeline i.tl-mark")).to_have_count(1)
    # oś czasu: kliknięcie w połowie przewija mniej więcej do połowy nagrania
    box = page.locator("#timeline").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    duration = page.evaluate(f"{VIDEO}.duration")
    wait_time(page, duration / 2, 1.0)


def test_pelny_ekran_klawiszem_f(ui):
    page, _, _ = open_player(ui)
    page.keyboard.press("f")
    # kontener z wideo (a nie sam <video>) wchodzi w pełny ekran, więc znaczniki i błysk są widoczne
    page.wait_for_function("document.fullscreenElement && document.fullscreenElement.id === 'video-wrap'")
    expect(page.locator("#btn-mark-fs")).to_be_visible()  # przycisk „Zaznacz” widoczny w pełnym ekranie
    page.keyboard.press("z")
    expect(page.locator("#flash")).to_be_visible()
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    page.keyboard.press("f")
    page.wait_for_function("!document.fullscreenElement")


# --- g) uprawnienia w interfejsie -----------------------------------------------------
def test_sedzia_spoza_obsady_widzi_nagranie_ale_nie_zaznacza(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    page = ui.page("outsider")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)

    # strona meczu: nagranie widoczne, ale bez wgrywania i notatek
    page.goto(f"/matches/{match_id}")
    expect(page.locator("#videos-panel")).to_contain_text("Całość")
    expect(page.get_by_role("link", name="Odtwarzacz", exact=True)).to_be_visible()
    expect(page.locator("#upload-form")).to_have_count(0)
    expect(page.get_by_role("link", name="Wklej notatki")).to_have_count(0)
    expect(page.get_by_role("link", name="Edytuj")).to_have_count(0)  # ani edycji nagrania, ani meczu

    page.get_by_role("link", name="Odtwarzacz", exact=True).click()
    wait_metadata(page)
    # wideo się odtwarza
    page.evaluate(f"{VIDEO}.play()")
    page.wait_for_function(f"{VIDEO}.currentTime > 0.3")
    # brak przycisków znaczników i kwart
    for button in ("#btn-z", "#btn-undo", "#btn-m", "#btn-q", "#btn-mark-fs", "#quick-form"):
        expect(page.locator(button)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile("Ustaw (ponownie )?tutaj"))).to_have_count(0)
    expect(page.locator("#periods .period-row")).to_have_count(2)  # panel kwart jest tylko do odczytu
    expect(page.get_by_role("link", name="Wklej notatki")).to_have_count(0)
    # skróty przeglądania działają
    page.keyboard.press("?")
    expect(page.locator("#help")).to_be_visible()
    page.keyboard.press("Escape")

    # Z, M, Q, Backspace nic nie tworzą (ani nie wysyłają żądań)
    for key in ("z", "m", "q", "Backspace"):
        page.keyboard.press(key)
    page.wait_for_timeout(500)
    assert not [u for u in posts if "/api/" in u], posts
    assert ui.server.clips_of(video_id) == [] and ui.server.marks_of(video_id) == {}
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 0")
    expect(page.locator("#decisions")).to_contain_text("Brak znaczników.")
    expect(page.locator("#decisions")).not_to_contain_text("naciśnij Z")


def test_sedzia_z_obsady_i_trener_maja_przyciski(ui):
    for role in ("referee", "coach"):
        page, _, _ = open_player(ui, role)
        expect(page.locator("#btn-z")).to_be_visible()
        expect(page.locator("#btn-m")).to_be_visible()
        expect(page.locator("#btn-q")).to_be_visible()
    # sędzia w obsadzie klika „Zaznacz”
    page, _, video_id = open_player(ui, "referee")
    page.get_by_role("button", name="Zaznacz (Z)").first.click()
    expect(page.locator(ROWS)).to_have_count(1)
    assert len(ui.server.clips_of(video_id)) == 1


def test_odtwarzacz_na_telefonie_miesci_sie_w_ekranie(ui):
    page, _, _ = open_player(ui, mobile=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#btn-z")).to_be_visible()
    box = page.locator("#player").bounding_box()
    assert box["width"] <= 390
    page.locator("#btn-z").tap()
    expect(page.locator(ROWS)).to_have_count(1)
