"""The shared playback strip (player_controls.js): full screen and the keyboard-only features, by click and touch."""
import re
import shutil

from playwright.sync_api import Page, expect

from tests.e2e.test_player import ROWS, VIDEO, now, open_player, seek_to, wait_metadata, wait_time

LAPTOP = {"width": 1366, "height": 768}
FS_WRAP = "document.fullscreenElement && document.fullscreenElement.id === 'video-wrap'"


def strip_button(page: Page, name: str):
    return page.locator(".pc-strip").get_by_role("button", name=name, exact=True)


def clip_with_file(ui, *, at=30.0, **kwargs):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id)
    clip_id = ui.server.insert_clip(video_id, at, described=True, file=True, category="kroki", **kwargs)
    shutil.copy(ui.server.sample, ui.server.data_dir / ui.server.clip(clip_id).clip_path)
    return match_id, video_id, clip_id


def wait_clip_video(page: Page, selector="video") -> None:
    page.wait_for_function(f"document.querySelector('{selector}').readyState >= 1")


def test_fullscreen_button_is_on_screen_and_works_by_click(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    button = strip_button(page, "Pełny ekran")
    expect(button).to_be_visible()
    box = button.bounding_box()
    assert box["y"] + box["height"] <= LAPTOP["height"], "the button is below the fold"
    assert page.evaluate("document.documentElement.scrollHeight") >= LAPTOP["height"]
    assert strip_button(page, "Zaznacz (Z)").bounding_box()["y"] + 40 <= LAPTOP["height"]

    button.click()
    page.wait_for_function(FS_WRAP)
    expect(page.locator(".pc-strip")).to_be_visible()
    strip_button(page, "Zaznacz (Z)").click()
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    expect(page.locator("#flash")).to_be_visible()
    strip_button(page, "Zamknij pełny ekran").click()
    page.wait_for_function("!document.fullscreenElement")
    expect(strip_button(page, "Pełny ekran")).to_have_attribute("aria-pressed", "false")


def test_controls_stay_usable_in_fullscreen_and_hide_when_idle_playing_or_paused(ui):
    page, _, video_id = open_player(ui, viewport=LAPTOP)
    page.get_by_role("button", name="Pełny ekran").click()
    page.wait_for_function(FS_WRAP)
    page.evaluate(f"{VIDEO}.pause()")
    seek_to(page, 20)
    strip_button(page, "Klatka naprzód").click()
    wait_time(page, 20.04, 0.02)
    page.locator("#speed").select_option("0.5")
    assert page.evaluate(f"{VIDEO}.playbackRate") == 0.5
    # paused and idle: the top of the frame is free
    expect(page.locator(".pc-wrap")).to_have_class(re.compile(r"pc-idle"), timeout=10_000)
    expect(page.locator(".pc-strip")).to_be_hidden()
    page.mouse.move(400, 300)
    page.mouse.move(420, 320)
    expect(page.locator(".pc-strip")).to_be_visible()
    strip_button(page, "Odtwórz").click()
    page.wait_for_function(f"!{VIDEO}.paused")
    expect(page.locator(".pc-wrap")).to_have_class(re.compile(r"pc-idle"), timeout=10_000)
    page.keyboard.press("Shift")
    expect(page.locator(".pc-strip")).to_be_visible()
    strip_button(page, "Pauza").click()
    page.wait_for_function(f"{VIDEO}.paused")


def test_fullscreen_strip_stays_while_a_control_has_focus(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    page.get_by_role("button", name="Pełny ekran").click()
    page.wait_for_function(FS_WRAP)
    page.locator("#speed").focus()
    page.wait_for_timeout(4500)
    expect(page.locator(".pc-strip")).to_be_visible()
    page.locator("#speed").blur()
    expect(page.locator(".pc-wrap")).to_have_class(re.compile(r"pc-idle"), timeout=10_000)


def test_touch_tap_brings_the_idle_strip_back(ui):
    page, _, _ = open_player(ui, mobile=True)
    strip_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_WRAP)
    expect(page.locator(".pc-wrap")).to_have_class(re.compile(r"pc-idle"), timeout=10_000)
    expect(page.locator(".pc-strip")).to_be_hidden()
    page.touchscreen.tap(200, 500)
    expect(page.locator(".pc-strip")).to_be_visible()


def test_touch_only_user_can_step_a_frame_seek_slow_down_and_play(ui):
    page, _, _ = open_player(ui, mobile=True)
    page.evaluate(f"{VIDEO}.pause()")
    seek_to(page, 20)
    strip_button(page, "Klatka naprzód").tap()
    wait_time(page, 20.04, 0.02)
    strip_button(page, "Klatka wstecz").tap()
    wait_time(page, 20.0, 0.02)
    strip_button(page, "Naprzód o 5 sekund").tap()
    wait_time(page, 25, 0.1)
    strip_button(page, "Wstecz o sekundę").tap()
    wait_time(page, 24, 0.1)
    page.locator("#speed").select_option("0.25")
    assert page.evaluate(f"{VIDEO}.playbackRate") == 0.25
    strip_button(page, "Odtwórz").tap()
    page.wait_for_function(f"!{VIDEO}.paused && {VIDEO}.currentTime > 24.1")
    strip_button(page, "Pauza").tap()
    page.wait_for_function(f"{VIDEO}.paused")
    assert now(page) < 26, "slow motion: 0.25x advances far less than real time"


def test_touch_targets_and_layout_on_a_phone(ui):
    page, _, _ = open_player(ui, mobile=True)
    boxes = page.evaluate("""() => [...document.querySelectorAll('.pc-strip button, .pc-strip select, .controls .btn')]
        .map(el => { const r = el.getBoundingClientRect(); return [el.id || el.getAttribute('aria-label') || el.textContent, r.width, r.height]; })""")
    assert len(boxes) >= 12
    small = [b for b in boxes if b[1] < 40 or b[2] < 40]
    assert not small, small
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert page.evaluate(f"{VIDEO}.playsInline") is True
    for el in page.locator(".pc-strip button, .pc-strip select").all():
        assert el.get_attribute("aria-label") or el.evaluate("e => e.labels && e.labels.length") or el.text_content().strip()


def test_fullscreen_by_touch_keeps_mark_and_undo_reachable(ui):
    page, _, video_id = open_player(ui, mobile=True)
    strip_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_WRAP)
    seek_to(page, 12)
    strip_button(page, "Zaznacz (Z)").tap()
    expect(page.locator(ROWS)).to_have_count(1)
    assert len(ui.server.clips_of(video_id)) == 1
    strip_button(page, "Cofnij").tap()
    expect(page.locator(ROWS)).to_have_count(0)
    strip_button(page, "Zamknij pełny ekran").tap()
    page.wait_for_function("!document.fullscreenElement")


def test_fixed_position_fallback_where_element_fullscreen_is_missing(ui):
    page, _, _ = open_player(ui, mobile=True)
    page.add_init_script("Element.prototype.requestFullscreen = undefined; Element.prototype.webkitRequestFullscreen = undefined;")
    page.reload()
    wait_metadata(page)
    strip_button(page, "Pełny ekran").tap()
    expect(page.locator("#video-wrap")).to_have_class(re.compile(r"pc-pseudo-fs"))
    assert page.evaluate("!document.fullscreenElement")
    box = page.locator("#video-wrap").bounding_box()
    assert box["width"] == 390 and box["height"] >= 800
    expect(strip_button(page, "Zaznacz (Z)")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#video-wrap")).not_to_have_class(re.compile(r"pc-pseudo-fs"))
    strip_button(page, "Pełny ekran").tap()
    strip_button(page, "Zamknij pełny ekran").tap()
    assert page.evaluate("!document.documentElement.classList.contains('pc-lock')")


def test_clip_page_has_the_strip_and_the_new_keys(ui):
    _, _, clip_id = clip_with_file(ui)
    page = ui.page("admin")
    page.goto(f"/clips/{clip_id}")
    wait_clip_video(page, "#clip-video")
    expect(page.locator("#clip-video")).to_have_attribute("controlslist", "nofullscreen")
    page.evaluate("document.getElementById('clip-video').pause()")
    strip_button(page, "Klatka naprzód").click()
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 0.04) < 0.02")
    page.keyboard.press("]")
    assert page.evaluate("document.getElementById('clip-video').playbackRate") == 1.25
    page.keyboard.press("[")
    page.keyboard.press("[")
    assert page.evaluate("document.getElementById('clip-video').playbackRate") == 0.75
    page.keyboard.press(".")
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 0.08) < 0.02")
    page.keyboard.press("f")
    page.wait_for_function("document.fullscreenElement && document.fullscreenElement.classList.contains('pc-wrap')")
    strip_button(page, "Zamknij pełny ekran").click()
    page.wait_for_function("!document.fullscreenElement")


def test_typing_in_the_description_does_not_trigger_player_keys(ui):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id, content="Q1,Q2")
    ui.server.set_mark(video_id, "Q1", 5.0)
    ui.server.set_mark(video_id, "Q2", 35.0)
    ui.server.insert_clip(video_id, 20.0, status="new", margin=1.0)
    page = ui.page("admin")
    page.goto(f"/matches/{match_id}/describe")
    page.wait_for_function("document.getElementById('preview').readyState >= 1")
    page.locator("#description").click()
    page.keyboard.type("f,.[] ok")
    expect(page.locator("#description")).to_have_value("f,.[] ok")
    assert page.evaluate("!document.fullscreenElement && document.getElementById('preview').playbackRate === 1")
    expect(strip_button(page, "Pełny ekran")).to_be_visible()
    page.locator("body").click(position={"x": 5, "y": 300})
    page.keyboard.press("]")
    assert page.evaluate("document.getElementById('preview').playbackRate") == 1.25


def test_public_share_page_strip_works_per_clip(ui):
    match_id, video_id, first = clip_with_file(ui, at=30.0)
    second = ui.server.insert_clip(video_id, 60.0, described=True, file=True, category="aut")
    shutil.copy(ui.server.sample, ui.server.data_dir / ui.server.clip(second).clip_path)
    coach = ui.page("coach")
    coach.goto(f"/clips?match_id={match_id}")
    for box in coach.locator("input.share-check").all():
        box.check()
    coach.locator("#share-submit").click()
    expect(coach.locator("#share-created")).to_be_visible()
    url = coach.locator("#share-url").input_value()

    page = ui.page(None, mobile=True)
    page.goto(url)
    expect(page.locator(".pc-strip")).to_have_count(2)
    page.wait_for_function("[...document.querySelectorAll('video')].every(v => v.readyState >= 1)")
    page.evaluate("document.querySelectorAll('video')[1].pause()")
    page.locator(".pc-strip").nth(1).get_by_role("button", name="Klatka naprzód").tap()
    page.wait_for_function("Math.abs(document.querySelectorAll('video')[1].currentTime - 0.04) < 0.02")
    assert page.evaluate("document.querySelectorAll('video')[0].currentTime") < 0.01
    page.locator(".pc-strip").nth(1).get_by_role("button", name="Pełny ekran").tap()
    page.wait_for_function("document.fullscreenElement === document.querySelectorAll('.pc-wrap')[1]")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_set_clip_view_has_the_strip(ui):
    _, _, clip_id = clip_with_file(ui)
    coach = ui.page("coach")
    coach.goto(f"/clips/{clip_id}")
    coach.locator("#clip-sets").get_by_label("albo nowy zestaw").fill("Zestaw E2E")
    coach.locator("#clip-sets").get_by_role("button", name="Dodaj klip").click()
    expect(coach.locator("#page-notice")).to_contain_text("Dodano klip do zestawu")
    coach.goto("/sets")
    coach.get_by_role("link", name="Zestaw E2E").click()
    coach.get_by_role("link", name="Obejrzyj od pierwszego klipu").click()
    set_url = coach.url

    page = ui.page("referee", mobile=True)
    page.goto(set_url)
    wait_clip_video(page, "#clip-video")
    page.evaluate("document.getElementById('clip-video').pause()")
    strip_button(page, "Naprzód o 5 sekund").tap()
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 5) < 0.2")
    strip_button(page, "Pełny ekran").tap()
    page.wait_for_function("document.fullscreenElement && document.fullscreenElement.classList.contains('pc-wrap')")


def test_watch_together_follower_controls_are_locked_but_full_screen_works(ui):
    leader, _, _ = open_player(ui, "admin")
    leader.get_by_role("button", name="Oglądaj razem").click()
    expect(leader.locator("#watch-leader")).to_have_text("Ty sterujesz")
    link = leader.locator("#watch-link").input_value()
    follower = ui.page("coach", mobile=True)
    follower.goto(link)
    wait_metadata(follower)
    expect(follower.locator("#watch-leader")).to_have_text("Steruje: Adam Admin")

    locked = follower.locator(".pc-strip button[data-needs-control]")
    expect(locked.first).to_have_attribute("aria-disabled", "true")
    follower.locator("#speed").scroll_into_view_if_needed()
    expect(follower.locator("#speed")).to_be_disabled()
    strip_button(follower, "Odtwórz").tap(force=True)
    expect(follower.locator("#toast")).to_contain_text("Steruje: Adam Admin")
    assert follower.evaluate(f"{VIDEO}.paused")
    seek_to(leader, 15)
    leader.evaluate(f"{VIDEO}.pause()")
    follower.wait_for_function(f"Math.abs({VIDEO}.currentTime - 15) < 0.1")
    strip_button(follower, "Naprzód o 5 sekund").tap(force=True)
    assert abs(now(follower) - 15) < 0.2

    strip_button(follower, "Pełny ekran").tap()
    follower.wait_for_function(FS_WRAP)
    expect(follower.locator("#watch-badge")).to_be_visible()
    strip_button(follower, "Zaznacz (Z)").tap()
    expect(follower.locator(ROWS)).to_have_count(1)
    expect(leader.locator(ROWS)).to_have_count(1)
    strip_button(follower, "Zamknij pełny ekran").tap()
    follower.wait_for_function("!document.fullscreenElement")

    leader.get_by_role("button", name="Pełny ekran").click()
    leader.wait_for_function(FS_WRAP)
    strip_button(leader, "Klatka naprzód").click()
    follower.wait_for_function(f"Math.abs({VIDEO}.currentTime - {now(leader)}) < 0.05")
    expect(leader.locator(".pc-strip button[data-needs-control]").first).to_have_attribute("aria-disabled", "false")

    follower.get_by_role("button", name="Odłącz").click()
    expect(follower.locator(".pc-strip button[data-needs-control]").first).to_have_attribute("aria-disabled", "false")
