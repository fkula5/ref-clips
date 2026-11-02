"""Scenariusz l): zakładka „Klipy” meczu (filtry HTMX i bez JS, widok mobilny), nawigacja poprzedni/następny
na stronie klipu oraz stany błędów klipu."""
import re

from playwright.sync_api import expect


def setup_tab(ui, mobile=False):
    """Mecz CC=Roman (konto), U1=Kasia, U2=Ula (konto); kwarty w 5 s i 35 s; sześć klipów."""
    match_id = ui.server.make_match(officials=(("CC", "referee"), ("U1", "Kasia Żółć"), ("U2", "second")))
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    ui.server.set_mark(video_id, "Q1", 5.0)
    ui.server.set_mark(video_id, "Q2", 35.0)
    ins = ui.server.insert_clip
    ids = {
        "k1": ins(video_id, 10, official="CC", category="kroki", described=True, description="Przekroczenie linii"),
        "n1": ins(video_id, 15, status="new"),
        "a1": ins(video_id, 20, official="U1", category="aut", described=True),
        "k2": ins(video_id, 40, official="CC", category="kroki", described=True, description="Drugi raz kroki"),
        "t2": ins(video_id, 45, whole_team=True, category="własna", custom="Kontakt z ławką", described=True),
        "a2": ins(video_id, 48, official="U2", category="aut"),
    }
    page = ui.page("admin", mobile=mobile)
    page.goto(f"/matches/{match_id}")
    return page, match_id, video_id, ids


def rows(page):
    return page.locator("#clips-list tbody tr")


def clip_times(page):
    return page.locator("#clips-list tbody tr td[data-label='Czas w nagraniu']").all_inner_texts()


def test_filtry_zakladki_klipow_przez_htmx(ui):
    page, match_id, _, ids = setup_tab(ui)
    expect(page.locator("#clips-head h2")).to_have_text("Klipy (6, nieopisane: 2)")
    expect(rows(page)).to_have_count(6)
    expect(rows(page).first).to_contain_text("CC · Roman Sędzia")
    expect(rows(page).first).to_contain_text("Q1 · 0:05")                  # czas od początku kwarty (nagranie)
    expect(rows(page).first).to_contain_text("Przekroczenie linii")
    expect(page.locator("#clips-list td[data-label='Oceny']").first).to_have_text("—")
    page.evaluate("window.__bez_przeladowania = true")

    page.locator("select[name=person]").select_option(label="CC · Roman Sędzia")
    expect(page).to_have_url(re.compile(r"person=u\d+"))
    expect(rows(page)).to_have_count(2)
    assert clip_times(page) == ["0:10", "0:40"]
    assert "category_id" not in page.url and "period" not in page.url, page.url      # adres bez pustych parametrów

    page.locator("select[name=category_id]").select_option(label="kroki")
    expect(page).to_have_url(re.compile(r"category_id=\d+"))
    expect(rows(page)).to_have_count(2)
    page.locator("select[name=period]").select_option("Q2")                # kombinacja: CC + kroki + Q2
    expect(page).to_have_url(re.compile(r"period=Q2"))
    expect(rows(page)).to_have_count(1)
    assert clip_times(page) == ["0:40"]
    expect(page.locator("#clips-list")).to_contain_text("Pokazano 1 z 6")

    page.locator("select[name=person]").select_option("")                  # luzujemy sędziego: kroki + Q2
    page.locator("select[name=category_id]").select_option("")
    expect(rows(page)).to_have_count(3)                                     # 40, 45, 48 s
    page.locator("select[name=described]").select_option(label="nieopisane")
    expect(page).to_have_url(re.compile(r"described=0"))
    expect(rows(page)).to_have_count(1)
    assert clip_times(page) == ["0:48"]
    page.locator("select[name=period]").select_option("")
    page.locator("select[name=person]").select_option(label="cały zespół")
    expect(page.locator("#clips-list")).to_contain_text("Brak klipów dla wybranych filtrów.")
    page.locator("select[name=described]").select_option("")
    expect(rows(page)).to_have_count(1)
    expect(rows(page).first).to_contain_text("Kontakt z ławką")
    assert page.evaluate("window.__bez_przeladowania === true"), "filtrowanie przeładowało stronę"
    expect(page.locator("#clips-head h2")).to_have_text("Klipy (6, nieopisane: 2)")   # nagłówek liczy cały mecz

    # adres z filtrami po odświeżeniu daje ten sam widok; „Wyczyść” wraca do pełnej listy
    page.reload()
    expect(rows(page)).to_have_count(1)
    expect(page.locator("select[name=person] option:checked")).to_have_text("cały zespół")
    page.get_by_role("link", name="Wyczyść").first.click()
    expect(rows(page)).to_have_count(6)
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}#klipy$"))


def test_przycisk_wstecz_przywraca_poprzedni_filtr(ui):
    page, match_id, _, _ = setup_tab(ui)
    page.locator("select[name=period]").select_option("Q2")
    expect(rows(page)).to_have_count(3)
    page.locator("select[name=described]").select_option(label="nieopisane")
    expect(rows(page)).to_have_count(1)
    page.go_back()
    expect(page).to_have_url(re.compile(r"\?period=Q2#klipy$"))
    expect(rows(page)).to_have_count(3)


def test_filtry_dzialaja_bez_javascriptu(ui):
    _, match_id, _, _ = setup_tab(ui)
    page = ui.page("admin", java_script_enabled=False)
    page.goto(f"/matches/{match_id}")
    expect(rows(page)).to_have_count(6)
    page.locator("select[name=category_id]").select_option(label="aut")
    page.locator("select[name=described]").select_option(label="opisane")
    page.locator("#clip-filters").get_by_role("button", name="Filtruj").click()
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}\?.*category_id=\d+.*described=1"))
    expect(rows(page)).to_have_count(1)
    assert clip_times(page) == ["0:20"]
    expect(page.locator("select[name=described] option:checked")).to_have_text("opisane")


def test_zakladka_klipow_na_telefonie_to_karty_z_dzialajacymi_filtrami(ui):
    page, match_id, _, _ = setup_tab(ui, mobile=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    first = rows(page).first
    assert page.evaluate("getComputedStyle(document.querySelector('#clips-list tbody tr')).display") == "block"
    assert page.evaluate("getComputedStyle(document.querySelector('#clips-list thead')).position") == "absolute"
    expect(first.locator("td[data-label='Sędzia']")).to_contain_text("CC · Roman Sędzia")
    box = first.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 390 + 1
    page.locator("select[name=period]").select_option("Q2")
    expect(rows(page)).to_have_count(3)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    rows(page).first.get_by_role("link", name="Otwórz klip").tap()
    expect(page).to_have_url(re.compile(r"/clips/\d+\?period=Q2$"))
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_nawigacja_poprzedni_nastepny_wg_filtrow_z_ktorych_przyszedl_uzytkownik(ui):
    page, match_id, _, ids = setup_tab(ui)
    page.locator("select[name=described]").select_option(label="opisane")
    expect(rows(page)).to_have_count(4)                                       # 10, 20, 40, 45 s
    rows(page).nth(1).get_by_role("link", name="Otwórz klip").click()         # 0:20, U1
    expect(page).to_have_url(re.compile(rf"/clips/{ids['a1']}\?described=1$"))
    expect(page.locator("h1")).to_contain_text("0:20")
    expect(page.locator("#prev-clip")).to_contain_text("0:10")                # pomija nieopisany 0:15
    expect(page.locator("#next-clip")).to_contain_text("0:40")
    page.locator("#next-clip").click()
    expect(page).to_have_url(re.compile(rf"/clips/{ids['k2']}\?described=1$"))
    expect(page.locator("#clip-info")).to_contain_text("Drugi raz kroki")
    expect(page.locator("#clip-info")).to_contain_text("Q2 · 0:05 od początku kwarty (czas nagrania)")
    expect(page.locator("#clip-info")).to_contain_text("czas nagrania – nie zegar meczowy")
    page.locator("#next-clip").click()
    expect(page.locator("h1")).to_contain_text("0:45")
    expect(page.locator("#next-clip")).to_have_count(0)                         # ostatni opisany
    expect(page.locator("[aria-disabled=true]")).to_have_text("Następny klip ›")
    page.locator("#prev-clip").click()
    page.locator("#prev-clip").click()
    expect(page.locator("h1")).to_contain_text("0:20")
    # powrót do listy zachowuje filtr
    page.get_by_role("link", name="wszystkie klipy meczu").click()
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}\?described=1#klipy$"))
    expect(rows(page)).to_have_count(4)

    # bez filtrów nawigacja idzie po wszystkich klipach meczu wg czasu
    page.goto(f"/clips/{ids['n1']}")
    expect(page.locator("#prev-clip")).to_contain_text("0:10")
    expect(page.locator("#next-clip")).to_contain_text("0:20")


def test_strona_klipu_pokazuje_pelny_opis_oceny_i_link_do_nagrania(ui):
    page, match_id, video_id, ids = setup_tab(ui)
    page.goto(f"/clips/{ids['t2']}")
    info = page.locator("#clip-info")
    for text in ("cały zespół", "Kontakt z ławką", "Q2 · 0:10 od początku kwarty (czas nagrania)", "Adam Admin", "Opisano"):
        expect(info).to_contain_text(text)
    expect(page.locator("#oceny")).to_contain_text("Klip nie ma jeszcze ocen.")
    page.get_by_role("link", name="pokaż w pełnym nagraniu").click()
    expect(page).to_have_url(re.compile(rf"/videos/{video_id}\?t=45"))


def test_klip_w_bledzie_ciecia_ma_wytnij_ponownie_i_usun(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    ui.server.set_mark(video_id, "Q1", 5.0)
    ui.server.set_mark(video_id, "Q2", 35.0)
    failed = ui.server.insert_clip(video_id, 20.0, status="error", error="ffmpeg: nieoczekiwany błąd")
    outside = ui.server.insert_clip(video_id, 30.0, status="error", error="Moment poza nagraniem: 99:00 (nagranie trwa 0:50)")
    page = ui.page("admin")

    page.goto(f"/clips/{outside}")
    expect(page.locator("#cut-problem")).to_contain_text("Moment poza nagraniem")
    expect(page.get_by_role("button", name="Wytnij ponownie")).to_have_count(0)
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Usuń klip").click()
    expect(page).to_have_url(re.compile(rf"/matches/{match_id}#klipy$"))
    assert ui.server.clip(outside) is None

    page.goto(f"/clips/{failed}")
    expect(page.locator("#cut-problem")).to_contain_text("Nie udało się wyciąć klipu: ffmpeg: nieoczekiwany błąd")
    page.get_by_role("button", name="Wytnij ponownie").click()
    expect(page.locator("#clip-video")).to_be_visible(timeout=60_000)               # worker naprawdę wycina
    assert ui.server.clip(failed).status == "cut"
    expect(page.get_by_role("link", name="Pobierz MP4")).to_be_visible()
    page.wait_for_function("document.getElementById('clip-video').readyState >= 1")
    # nazwa pliku: data_kwarta_czas_sędzia_kategoria
    with page.expect_download() as download:
        page.get_by_role("link", name="Pobierz MP4").click()
    assert download.value.suggested_filename == "2026-10-28_Q1_00m20s.mp4"


def test_nazwa_pobieranego_pliku_po_opisie_i_zmianie_kategorii(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    ui.server.set_mark(video_id, "Q1", 5.0)
    ui.server.set_mark(video_id, "Q2", 35.0)
    clip_id = ui.server.create_clip(video_id, 40.0)
    page = ui.page("admin")
    page.goto(f"/clips/{clip_id}")
    expect(page.locator("#clip-video")).to_be_visible(timeout=60_000)
    page.get_by_label("CC · Roman Sędzia").check()
    page.locator("#category-select").select_option(label="blok / szarża")
    page.get_by_role("button", name="Zapisz opis").click()
    expect(page.locator("#clip-info")).to_contain_text("blok / szarża")
    expect(page.locator("#clip-info")).not_to_contain_text("nieopisany")
    with page.expect_download() as download:
        page.get_by_role("link", name="Pobierz MP4").click()
    assert download.value.suggested_filename == "2026-10-28_Q2_00m40s_CC_blok-szarza.mp4"
    page.locator("#category-select").select_option(label="własna")
    page.locator("input[name=custom_category]").fill("Zażółć gęślą jaźń")
    page.get_by_label("cały zespół").check()
    page.get_by_role("button", name="Zapisz opis").click()
    expect(page.locator("#clip-info")).to_contain_text("Zażółć gęślą jaźń")
    with page.expect_download() as download:
        page.get_by_role("link", name="Pobierz MP4").click()
    assert download.value.suggested_filename == "2026-10-28_Q2_00m40s_zespol_Zazolc-gesla-jazn.mp4"
