import json
import re

from playwright.sync_api import expect
from sqlalchemy import select

from app.models import Clip, UploadSession, Video
from tests.e2e.support import CHUNK_KB, RECORD_UPLOAD_PROGRESS, wait_until

NOTES = "0:20 Roman kroki\n0:35 U1 dlaczego nie blok?\nnie wiem kiedy to było"


def open_match(ui, role="admin", **kwargs):
    match_id = ui.server.make_match(**kwargs)
    page = ui.page(role)
    page.add_init_script(RECORD_UPLOAD_PROGRESS)
    page.goto(f"/matches/{match_id}")
    return page, match_id


def choose_file(page, ui, kind="full", periods=()):
    page.set_input_files("#upload-files", str(ui.server.sample))
    row = page.locator("#upload-files-list .file-row")
    expect(row).to_have_count(1)
    expect(row).to_contain_text(ui.server.sample.name)
    if kind != "full":
        row.locator(".content-kind").select_option(kind)
    for period in periods:
        row.locator(f".content-periods input[value={period}]").check()
    return row


def progress_states(page) -> list[str]:
    return json.loads(page.evaluate("sessionStorage.getItem('__upload_states') || '[]'"))


def server_video(ui, match_id) -> Video | None:
    with ui.server.db() as db:
        return db.scalar(select(Video).where(Video.match_id == match_id))


def test_upload_with_declaration_notes_and_conversion(ui):
    page, match_id = open_match(ui)
    expect(page.locator("#videos-panel")).to_contain_text("Brak nagrań")

    row = choose_file(page, ui, "multi")
    periods = row.locator(".content-periods")
    expect(periods).to_be_visible()
    row.locator(".content-periods input[value=Q1]").check()
    row.locator(".content-periods input[value=Q2]").check()

    row.locator("details.notes-block summary").click()
    row.locator(".notes-text").fill(NOTES)
    row.get_by_role("button", name="Podgląd").click()
    table = row.locator("table.preview")
    expect(table).to_be_visible()
    rows = table.locator("tbody tr")
    expect(rows).to_have_count(3)
    expect(rows.nth(0).locator("td").nth(1)).to_have_text("0:20")
    expect(rows.nth(0).locator("td").nth(2)).to_contain_text("Roman Sędzia")
    expect(rows.nth(0).locator("td").nth(3)).to_have_text("kroki")
    expect(rows.nth(1).locator("td").nth(2)).to_contain_text("Kasia Żółć")
    expect(rows.nth(1).locator("td").nth(3)).to_have_text("blok / szarża")
    expect(rows.nth(2)).to_have_class("bad")
    expect(rows.nth(2).locator("td").nth(5)).not_to_be_empty()
    expect(row.locator(".notes-preview .small-note")).to_contain_text("2 z 3 linii zamieni się w klipy")

    page.get_by_role("button", name="Wgraj").click()
    expect(page.locator("#upload-progress .upload-row")).to_be_visible()
    video_row = page.locator("#videos-panel .video-row")
    expect(video_row).to_have_count(1, timeout=30_000)
    expect(video_row).to_contain_text(ui.server.sample.name)
    expect(video_row).to_contain_text("zawiera: kwarty Q1, Q2")

    states = progress_states(page)
    assert any(s.startswith("100|100%") for s in states), states
    assert any("gotowe — konwersja w tle" in s for s in states), states
    values = [int(s.split("|")[0]) for s in states]
    assert values == sorted(values), "postęp nie powinien się cofać"

    page.evaluate("window.__bez_przeladowania = true")
    expect(video_row.locator(".badge")).to_have_text("gotowe", timeout=90_000)
    assert page.evaluate("window.__bez_przeladowania === true"), "panel nagrań przeładował całą stronę"
    expect(page.locator("#marks-banner")).to_contain_text("Ustaw początki kwart")
    expect(page.locator("#marks-banner")).to_contain_text("brakuje: Q1, Q2")
    expect(page.get_by_role("link", name="ustaw w odtwarzaczu")).to_be_visible()
    expect(page.locator(".match-head .badge")).to_have_text("brak znaczników kwart")

    clips_table = page.locator("#clips-section table tbody tr")
    expect(clips_table).to_have_count(2)
    expect(clips_table.locator(".badge.cut")).to_have_count(2, timeout=60_000)
    assert page.evaluate("window.__bez_przeladowania === true")

    video = server_video(ui, match_id)
    assert video.status == "ready" and video.content == "Q1,Q2" and video.original_path is None
    with ui.server.db() as db:
        clips = list(db.scalars(select(Clip).where(Clip.match_id == match_id).order_by(Clip.time_sec)))
    assert [c.time_sec for c in clips] == [20.0, 35.0]
    assert all(c.official_id and c.category_id and c.described_at is None for c in clips)


def test_connection_dropped_midway_and_automatic_resume(ui):
    ui.allow(r"ERR_CONNECTION_RESET")  # we drop the connection ourselves
    page, match_id = open_match(ui)
    state = {"patches": 0, "aborted": 0, "block": False}

    def handler(route):
        request = route.request
        if request.method != "PATCH":
            return route.continue_()
        state["patches"] += 1
        if state["block"] or state["patches"] > 3:
            state["block"] = True
            state["aborted"] += 1
            return route.abort("connectionreset")
        return route.continue_()

    page.route(re.compile(r"/uploads/[0-9a-f]+$"), handler)
    choose_file(page, ui)
    page.get_by_role("button", name="Wgraj").click()

    wait_until(page, lambda: state["aborted"] >= 2, message="klient nie ponowił próby po zerwaniu połączenia")
    pct = page.locator("#upload-progress .pct")
    expect(pct).not_to_contain_text("gotowe")
    assert "error-text" not in (pct.get_attribute("class") or ""), pct.inner_text()
    with ui.server.db() as db:
        up = db.scalar(select(UploadSession).where(UploadSession.match_id == match_id))
        assert 0 < up.offset_bytes < up.size_bytes

    state["block"] = False
    state["patches"] = -10_000  # from now on everything goes through
    video_row = page.locator("#videos-panel .video-row")
    expect(video_row).to_have_count(1, timeout=60_000)
    states = progress_states(page)
    assert any("gotowe — konwersja w tle" in s for s in states), states
    video = server_video(ui, match_id)
    assert video.size_bytes == ui.server.sample.stat().st_size
    expect(video_row.locator(".badge")).to_have_text("gotowe", timeout=90_000)
    assert ui.server.sample.stat().st_size == video.size_bytes


def test_page_refresh_midway_and_resume_from_where_it_stopped(ui):
    ui.allow(r"ERR_CONNECTION_RESET")
    page, match_id = open_match(ui)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.type), d.accept()))
    state = {"patches": 0, "block": False}

    def handler(route):
        if route.request.method != "PATCH":
            return route.continue_()
        state["patches"] += 1
        if state["block"] or state["patches"] > 4:
            state["block"] = True
            return route.abort("connectionreset")
        return route.continue_()

    page.route(re.compile(r"/uploads/[0-9a-f]+$"), handler)
    choose_file(page, ui, "Q1")
    page.get_by_role("button", name="Wgraj").click()
    wait_until(page, lambda: state["block"], message="upload nie doszedł do miejsca przerwania")
    with ui.server.db() as db:
        up = db.scalar(select(UploadSession).where(UploadSession.match_id == match_id))
        offset_before, size = up.offset_bytes, up.size_bytes
    assert 0 < offset_before < size

    page.reload()  # the PATCH lock is held, so retries from the old page cannot append anything
    assert "beforeunload" in dialogs
    expect(page.locator("#upload-progress .upload-row")).to_have_count(0)
    with ui.server.db() as db:
        assert db.scalar(select(UploadSession.offset_bytes).where(UploadSession.match_id == match_id)) == offset_before

    state["block"], state["patches"] = False, -10_000
    requests = []
    page.on("request", lambda r: requests.append(
        (r.method, r.url, r.headers.get("upload-offset")))
        if "/uploads/" in r.url else None)
    choose_file(page, ui, "Q1")
    page.get_by_role("button", name="Wgraj").click()
    video_row = page.locator("#videos-panel .video-row")
    expect(video_row).to_have_count(1, timeout=60_000)

    creates = [r for r in requests if r[0] == "POST" and r[1].endswith("/uploads/")]
    patches = [r for r in requests if r[0] == "PATCH"]
    assert not creates, f"wznowienie nie powinno tworzyć nowego uploadu: {creates}"
    assert int(patches[0][2]) == offset_before, f"pierwszy PATCH po odświeżeniu: {patches[0]}"
    chunk = CHUNK_KB * 1024
    expected = list(range(offset_before, size, chunk))
    assert [int(p[2]) for p in patches] == expected, f"PATCH-e po odświeżeniu: {patches}"
    assert len(expected) < size / chunk
    assert server_video(ui, match_id).size_bytes == size
    expect(video_row.locator(".badge")).to_have_text("gotowe", timeout=90_000)


def test_cancel_button_removes_the_upload(ui):
    ui.allow(r"ERR_CONNECTION_RESET")
    page, match_id = open_match(ui)
    state = {"patches": 0}

    def handler(route):
        if route.request.method != "PATCH":
            return route.continue_()
        state["patches"] += 1
        return route.abort("connectionreset") if state["patches"] > 2 else route.continue_()

    page.route(re.compile(r"/uploads/[0-9a-f]+$"), handler)
    choose_file(page, ui)
    page.get_by_role("button", name="Wgraj").click()
    wait_until(page, lambda: state["patches"] > 3, message="upload nie doszedł do zerwania")
    page.get_by_role("button", name="Przerwij").click()
    expect(page.locator("#upload-progress .pct")).to_have_text("przerwano")
    wait_until(page, lambda: not _uploads_left(ui, match_id), message="sesja uploadu nie została usunięta")
    expect(page.get_by_role("button", name="Wgraj")).to_be_enabled()
    assert server_video(ui, match_id) is None
    assert not list((ui.server.data_dir / "uploads").glob("tus-*.part"))


def _uploads_left(ui, match_id):
    with ui.server.db() as db:
        return list(db.scalars(select(UploadSession).where(UploadSession.match_id == match_id)))


def test_second_upload_by_the_same_user_gives_a_message_and_cancels_the_previous_one(ui, tmp_path):
    ui.allow(r"ERR_CONNECTION_RESET|status of 409")
    first, match_id = open_match(ui)
    state = {"patches": 0}

    def handler(route):
        if route.request.method != "PATCH":
            return route.continue_()
        state["patches"] += 1
        return route.abort("connectionreset") if state["patches"] > 2 else route.continue_()

    first.route(re.compile(r"/uploads/[0-9a-f]+$"), handler)
    choose_file(first, ui)
    first.get_by_role("button", name="Wgraj").click()
    wait_until(first, lambda: state["patches"] > 3, message="upload nie doszedł do zerwania")

    other_file = tmp_path / "inny-plik.mp4"
    other_file.write_bytes(ui.server.sample.read_bytes()[:700_000])
    second = ui.page("admin")
    second.goto(f"/matches/{match_id}")
    second.set_input_files("#upload-files", str(other_file))
    second.get_by_role("button", name="Wgraj").click()
    pct = second.locator("#upload-progress .pct")
    expect(pct).to_contain_text("Masz niedokończone wgrywanie pliku")
    cancel = second.get_by_role("button", name="Przerwij poprzednie wgrywanie")
    cancel.click()
    expect(second.locator("#upload-progress")).to_contain_text("Poprzednie wgrywanie przerwane")
    assert not _uploads_left(ui, match_id)


def test_two_files_at_once_with_separate_declarations(ui, tmp_path):
    page, match_id = open_match(ui)
    second_file = tmp_path / "druga-kwarta.mp4"
    second_file.write_bytes(ui.server.sample.read_bytes())
    page.set_input_files("#upload-files", [str(ui.server.sample), str(second_file)])
    rows = page.locator("#upload-files-list .file-row")
    expect(rows).to_have_count(2)
    rows.nth(0).locator(".content-kind").select_option("Q1")
    rows.nth(1).locator(".content-kind").select_option("Q2")
    page.locator("#upload-label").fill("Mecz")
    page.get_by_role("button", name="Wgraj").click()
    panel_rows = page.locator("#videos-panel .video-row")
    expect(panel_rows).to_have_count(2, timeout=60_000)
    expect(panel_rows.nth(0)).to_contain_text("Mecz (mecz-probka.mp4)")
    expect(panel_rows.nth(0)).to_contain_text("zawiera: kwarta Q1")
    expect(panel_rows.nth(1)).to_contain_text("Mecz (druga-kwarta.mp4)")
    expect(panel_rows.nth(1)).to_contain_text("zawiera: kwarta Q2")
    expect(panel_rows.locator(".badge")).to_have_text(["gotowe", "gotowe"], timeout=120_000)
    # every one-quarter file gets a start marker (0:00) at once, so the banner does not appear
    expect(page.locator("#marks-banner")).to_have_count(0)
    expect(page.locator(".match-head .badge")).to_have_text("gotowy")
