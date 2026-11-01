"""Scenariusz c) Nowy mecz: obsada CC/U1/U2 (konto i wpisane nazwisko), lista lig, błędy walidacji."""
import re

from playwright.sync_api import expect


def fill_basics(page, level="Liga Formularzowa"):
    page.locator("input[name=date]").fill("2026-10-30")
    page.locator("input[name=level]").fill(level)
    page.locator("input[name=team_a_name]").fill("Arka")
    page.locator("input[name=team_a_color]").fill("czerwone")
    page.locator("input[name=team_b_name]").fill("Bałtyk")
    page.locator("input[name=team_b_color]").fill("niebieskie")


def test_nowy_mecz_z_obsada_z_konta_i_wpisana(ui):
    ui.server.make_match(level="Liga Podpowiedziana")  # ta liga ma pojawić się w datalist
    page = ui.page("admin")
    page.goto("/matches/new")
    expect(page.get_by_role("heading", name="Nowy mecz")).to_be_visible()
    options = page.locator("datalist#levels option")
    assert "Liga Podpowiedziana" in [o.get_attribute("value") for o in options.all()]
    # lista kont sędziów zawiera tylko konta z rolą sędziego
    names = page.locator("select[name=cc_user] option").all_inner_texts()
    assert "Roman Sędzia" in names and "Ula Druga" in names
    assert "Adam Admin" not in names

    fill_basics(page)
    page.locator("select[name=cc_user]").select_option(label="Roman Sędzia")
    page.locator("input[name=u1_name]").fill("Jan Wpisany")
    page.locator("select[name=u2_user]").select_option(label="Ula Druga")
    page.get_by_role("button", name="Zapisz").click()

    expect(page).to_have_url(re.compile(r"/matches/\d+$"))
    expect(page.get_by_role("heading", name="2026-10-30 · Arka – Bałtyk")).to_be_visible()
    officials = page.locator(".chip.official")
    expect(officials).to_have_count(3)
    expect(officials.nth(0)).to_contain_text("CC Roman Sędzia")
    expect(officials.nth(0)).to_contain_text("konto")
    expect(officials.nth(1)).to_contain_text("U1 Jan Wpisany")
    expect(officials.nth(1)).to_contain_text("bez konta")
    expect(officials.nth(2)).to_contain_text("U2 Ula Druga")


def test_duplikat_osoby_blad_w_formularzu_z_zachowanymi_wartosciami(ui):
    ui.allow(r"status of 422")
    page = ui.page("admin")
    page.goto("/matches/new")
    fill_basics(page, level="Liga Zachowana")
    page.locator("select[name=cc_user]").select_option(label="Roman Sędzia")
    page.locator("select[name=u1_user]").select_option(label="Roman Sędzia")
    page.locator("input[name=u2_name]").fill("Ktoś Trzeci")
    page.get_by_role("button", name="Zapisz").click()

    expect(page.locator(".banner.error")).to_have_text("To samo konto nie może zajmować dwóch pozycji w obsadzie.")
    expect(page.get_by_role("heading", name="Nowy mecz")).to_be_visible()
    assert page.locator("input[name=date]").input_value() == "2026-10-30"
    assert page.locator("input[name=level]").input_value() == "Liga Zachowana"
    assert page.locator("input[name=team_a_name]").input_value() == "Arka"
    assert page.locator("input[name=team_b_color]").input_value() == "niebieskie"
    assert page.locator("select[name=cc_user] option:checked").inner_text() == "Roman Sędzia"
    assert page.locator("select[name=u1_user] option:checked").inner_text() == "Roman Sędzia"
    assert page.locator("input[name=u2_name]").input_value() == "Ktoś Trzeci"

    # po poprawce formularz da się zapisać
    page.locator("select[name=u1_user]").select_option(label="Ula Druga")
    page.get_by_role("button", name="Zapisz").click()
    expect(page).to_have_url(re.compile(r"/matches/\d+$"))


def test_duplikat_wpisanego_nazwiska_z_kontem_tej_samej_osoby(ui):
    ui.allow(r"status of 422")
    page = ui.page("admin")
    page.goto("/matches/new")
    fill_basics(page)
    page.locator("select[name=cc_user]").select_option(label="Roman Sędzia")
    page.locator("input[name=u1_name]").fill("roman sedzia")  # to samo, bez polskich znaków i wielkości liter
    page.get_by_role("button", name="Zapisz").click()
    expect(page.locator(".banner.error")).to_contain_text("to ta sama osoba")
    assert page.locator("input[name=u1_name]").input_value() == "roman sedzia"


def test_sedzia_zakladajacy_mecz_jest_w_obsadzie(ui):
    page = ui.page("referee")
    page.goto("/matches/new")
    # formularz wstawia sędziego na pozycję CC
    assert page.locator("select[name=cc_user] option:checked").inner_text() == "Roman Sędzia"
    fill_basics(page)
    page.locator("input[name=u1_name]").fill("Piotr Partner")
    page.get_by_role("button", name="Zapisz").click()
    expect(page).to_have_url(re.compile(r"/matches/\d+$"))
    me = page.locator(".chip.official", has_text="Roman Sędzia")
    expect(me).to_contain_text("to Ty")
    # jako członek obsady może wgrywać nagrania
    expect(page.locator("#upload-form")).to_be_visible()


def test_sedzia_nie_zapisze_meczu_bez_siebie_w_obsadzie(ui):
    ui.allow(r"status of 403")
    page = ui.page("referee")
    page.goto("/matches/new")
    fill_basics(page)
    page.locator("select[name=cc_user]").select_option(label="Ula Druga")
    page.locator("input[name=u1_name]").fill("Piotr Partner")
    page.get_by_role("button", name="Zapisz").click()
    expect(page.locator(".banner.error")).to_be_visible()
    expect(page.get_by_role("heading", name="Nowy mecz")).to_be_visible()
    assert page.locator("input[name=team_a_name]").input_value() == "Arka"
