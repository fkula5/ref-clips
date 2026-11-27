"""The shared Video.js player (player_controls.js): one control bar, full screen and the keyboard-only features, by click and touch."""
import re
import shutil

from playwright.sync_api import Page, expect

from tests.e2e.test_player import (FS_PLAYER, ROWS, VIDEO, choose_rate, now, open_player, rate_label, seek_to,
                                   wait_metadata, wait_time)

LAPTOP = {"width": 1366, "height": 768}
PHONE_LANDSCAPE = {"width": 844, "height": 390}
BAR = ".vjs-control-bar"


def bar_button(page: Page, name: str):
    return page.locator(BAR).get_by_role("button", name=name, exact=True)


def show_bar(page: Page, x=200, y=300) -> None:
    """A tap on the picture toggles the bar, so tap only when it is hidden."""
    if not page.locator(BAR).first.is_visible():
        page.touchscreen.tap(x, y)
    expect(page.locator(BAR).first).to_be_visible()


def wiggle(page: Page) -> None:
    """Video.js swallows the first mouse move after the bar went idle."""
    for x in (420, 440, 460):
        page.mouse.move(x, 320)


def clip_with_file(ui, *, at=30.0, **kwargs):
    match_id = ui.server.make_match()
    video_id = ui.server.make_ready_video(match_id)
    clip_id = ui.server.insert_clip(video_id, at, described=True, file=True, category="kroki", **kwargs)
    shutil.copy(ui.server.sample, ui.server.data_dir / ui.server.clip(clip_id).clip_path)
    return match_id, video_id, clip_id


def wait_clip_video(page: Page, selector="video") -> None:
    page.wait_for_function(f"document.querySelector('{selector}').readyState >= 1")


def layout(page: Page) -> dict:
    """Geometry of the first player: the bar must sit at its bottom and nothing may stick out of it."""
    return page.evaluate("""() => {
      const player = document.querySelector('.video-js').getBoundingClientRect();
      const bar = document.querySelector('.vjs-control-bar');
      const box = bar.getBoundingClientRect();
      const outside = [...bar.querySelectorAll('button, .vjs-progress-control, .vjs-time-control')]
        .filter(el => el.offsetParent && !el.closest('.vjs-menu'))
        .filter(el => { const r = el.getBoundingClientRect(); return r.right > box.right + 1 || r.left < box.left - 1; })
        .map(el => el.getAttribute('aria-label') || el.className);
      return {playerBottom: player.bottom, barBottom: box.bottom, barHeight: box.height, barRight: box.right,
              playerRight: player.right, outside, innerWidth, innerHeight,
              overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth};
    }""")


def test_one_set_of_controls_and_no_native_controls_attribute(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    assert page.evaluate(f"{VIDEO}.controls") is False
    assert page.evaluate(f"{VIDEO}.hasAttribute('controls')") is False
    expect(page.locator(".video-js")).to_have_count(1)
    expect(page.locator(BAR)).to_have_count(1)
    expect(page.locator("#player")).to_have_class("vjs-tech")
    assert page.evaluate(f"{VIDEO}.closest('.video-js') === document.querySelector('.video-js')")
    names = [el.get_attribute("aria-label") or el.inner_text() for el in page.locator(f"{BAR} button").all()]
    for name in ("Odtwórz", "Wstecz o 5 sekund", "Wstecz o sekundę", "Klatka wstecz", "Klatka naprzód",
                 "Naprzód o sekundę", "Naprzód o 5 sekund", "Pełny ekran"):
        assert name in names, (name, names)
    expect(page.locator("button.vjs-playback-rate")).to_be_visible()
    assert layout(page)["barBottom"] <= layout(page)["playerBottom"] + 1


def test_fullscreen_button_is_on_screen_and_works_by_click(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    button = bar_button(page, "Pełny ekran")
    expect(button).to_be_visible()
    assert page.get_by_role("button", name="Zaznacz (Z)").bounding_box()["y"] + 40 <= LAPTOP["height"], "below the fold"

    button.click()
    page.wait_for_function(FS_PLAYER)
    for overlay in ("#mark-count", "#timeline"):
        expect(page.locator(overlay)).to_be_visible()
        assert page.evaluate(f"document.fullscreenElement.contains(document.querySelector('{overlay}'))")
    page.get_by_role("button", name="Zaznacz (Z)").click()
    expect(page.locator("#mark-count")).to_have_text("Znaczniki: 1")
    expect(page.locator("#flash")).to_be_visible()
    assert page.evaluate("document.fullscreenElement.contains(document.getElementById('flash'))")
    bar_button(page, "Zamknij pełny ekran").click()
    page.wait_for_function("!document.fullscreenElement")
    # back in the page: the extra buttons and the marker bar are where they were
    expect(page.locator(".controls #btn-z")).to_have_count(1)
    expect(page.locator(".video-wrap + #timeline, #video-wrap #timeline")).to_have_count(1)
    assert page.evaluate("!document.querySelector('.video-js').contains(document.getElementById('timeline'))")


def test_fit_to_viewport_on_common_laptop_sizes(ui):
    for size in ({"width": 1366, "height": 768}, {"width": 1280, "height": 720}):
        page, _, _ = open_player(ui, viewport=size)
        for name in ("Pełny ekran", "Klatka naprzód"):
            box = bar_button(page, name).bounding_box()
            assert box["y"] + box["height"] <= size["height"], (name, size)
        box = page.get_by_role("button", name="Zaznacz (Z)").bounding_box()
        assert box["y"] + box["height"] <= size["height"], size
        assert layout(page)["overflowX"] is False


def test_controls_stay_usable_in_fullscreen_and_hide_when_idle_playing_or_paused(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    bar_button(page, "Pełny ekran").click()
    page.wait_for_function(FS_PLAYER)
    page.evaluate(f"{VIDEO}.pause()")
    seek_to(page, 20)
    bar_button(page, "Klatka naprzód").click()
    wait_time(page, 20.04, 0.02)
    choose_rate(page, "0.5")
    assert page.evaluate(f"{VIDEO}.playbackRate") == 0.5
    expect(rate_label(page)).to_have_text("0.5x")
    # paused and idle: the whole frame is free
    page.mouse.move(400, 300)
    expect(page.locator(BAR)).to_be_hidden(timeout=10_000)
    wiggle(page)
    expect(page.locator(BAR)).to_be_visible()
    bar_button(page, "Odtwórz").click()
    page.wait_for_function(f"!{VIDEO}.paused")
    page.mouse.move(700, 300)
    expect(page.locator(BAR)).to_be_hidden(timeout=10_000)
    page.keyboard.press("Shift")
    expect(page.locator(BAR)).to_be_visible()
    bar_button(page, "Pauza").click()
    page.wait_for_function(f"{VIDEO}.paused")


def test_controls_hide_when_idle_outside_full_screen_too(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    page.mouse.move(300, 300)
    expect(page.locator(BAR)).to_be_hidden(timeout=10_000)
    wiggle(page)
    expect(page.locator(BAR)).to_be_visible()
    page.mouse.move(300, 700)
    expect(page.locator(BAR)).to_be_hidden(timeout=10_000)


def test_bar_stays_while_a_control_has_keyboard_focus(ui):
    page, _, _ = open_player(ui, viewport=LAPTOP)
    bar_button(page, "Pełny ekran").click()
    page.wait_for_function(FS_PLAYER)
    page.mouse.move(400, 300)
    page.keyboard.press("Shift")
    bar_button(page, "Klatka wstecz").focus()
    page.wait_for_timeout(4500)
    expect(page.locator(BAR)).to_be_visible()
    page.locator("body").evaluate("() => document.activeElement.blur()")
    expect(page.locator(BAR)).to_be_hidden(timeout=12_000)


def test_touch_tap_brings_the_idle_bar_back(ui):
    page, _, _ = open_player(ui, mobile=True)
    bar_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_PLAYER)
    expect(page.locator(BAR)).to_be_hidden(timeout=10_000)
    page.touchscreen.tap(200, 400)
    expect(page.locator(BAR)).to_be_visible()
    page.touchscreen.tap(200, 400)
    expect(page.locator(BAR)).to_be_hidden()


def test_touch_only_user_can_step_a_frame_seek_slow_down_and_play(ui):
    page, _, _ = open_player(ui, mobile=True)
    page.evaluate(f"{VIDEO}.pause()")
    seek_to(page, 20)
    bar_button(page, "Klatka naprzód").tap()
    wait_time(page, 20.04, 0.02)
    bar_button(page, "Klatka wstecz").tap()
    wait_time(page, 20.0, 0.02)
    bar_button(page, "Naprzód o 5 sekund").tap()
    wait_time(page, 25, 0.1)
    page.locator("button.vjs-playback-rate").tap()
    page.get_by_role("menuitemradio", name="0.25x", exact=True).tap()
    assert page.evaluate(f"{VIDEO}.playbackRate") == 0.25
    bar_button(page, "Odtwórz").tap()
    page.wait_for_function(f"!{VIDEO}.paused && {VIDEO}.currentTime > 25.1")
    bar_button(page, "Pauza").tap()
    page.wait_for_function(f"{VIDEO}.paused")
    assert now(page) < 27, "slow motion: 0.25x advances far less than real time"


def test_touch_targets_and_layout_on_a_phone_in_portrait(ui):
    page, _, _ = open_player(ui, mobile=True)
    boxes = page.evaluate("""() => [...document.querySelectorAll('.vjs-control-bar button, .controls .btn')]
        .filter(el => el.offsetParent)
        .map(el => { const r = el.getBoundingClientRect(); return [el.id || el.getAttribute('aria-label') || el.textContent, r.width, r.height]; })""")
    assert len(boxes) >= 9
    small = [b for b in boxes if b[1] < 40 or b[2] < 40]
    assert not small, small
    geometry = layout(page)
    assert not geometry["overflowX"] and not geometry["outside"], geometry
    assert geometry["barBottom"] <= geometry["playerBottom"] + 1
    assert page.evaluate(f"{VIDEO}.playsInline") is True
    # the least important buttons give way, the keys still provide them
    expect(bar_button(page, "Naprzód o sekundę")).to_be_hidden()
    expect(page.locator(".vjs-volume-panel")).to_be_hidden()
    expect(bar_button(page, "Klatka naprzód")).to_be_visible()
    for el in page.locator(f"{BAR} button").all():
        assert el.get_attribute("aria-label") or el.get_attribute("title") or el.text_content().strip()


def test_fullscreen_by_touch_keeps_mark_and_undo_reachable_in_portrait(ui):
    page, _, video_id = open_player(ui, mobile=True)
    bar_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_PLAYER)
    seek_to(page, 12)
    show_bar(page)
    page.get_by_role("button", name="Zaznacz (Z)").tap()
    expect(page.locator(ROWS)).to_have_count(1)
    assert len(ui.server.clips_of(video_id)) == 1
    geometry = layout(page)
    assert not geometry["overflowX"] and not geometry["outside"], geometry
    page.get_by_role("button", name="Cofnij").tap()
    expect(page.locator(ROWS)).to_have_count(0)
    bar_button(page, "Zamknij pełny ekran").tap()
    page.wait_for_function("!document.fullscreenElement")


def test_phone_landscape_fullscreen_is_one_slim_row_at_the_bottom(ui):
    page, _, video_id = open_player(ui, mobile=True, viewport=PHONE_LANDSCAPE)
    bar_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_PLAYER)
    show_bar(page, 400, 150)
    geometry = layout(page)
    assert not geometry["overflowX"] and not geometry["outside"], geometry
    assert geometry["barHeight"] <= 60, "a single slim row"
    assert geometry["barBottom"] >= PHONE_LANDSCAPE["height"] - 14
    assert geometry["barBottom"] <= PHONE_LANDSCAPE["height"]
    # picture, overlays and the marking buttons all fit
    for name in ("Zaznacz (Z)", "Cofnij", "Klatka naprzód", "Zamknij pełny ekran"):
        box = page.get_by_role("button", name=name, exact=True).bounding_box()
        assert box["y"] > PHONE_LANDSCAPE["height"] - 70 and box["height"] >= 36, (name, box)
    seek_to(page, 12)
    page.get_by_role("button", name="Zaznacz (Z)").tap()
    expect(page.locator(ROWS)).to_have_count(1)


def test_phone_landscape_clip_page_bar_has_no_overflow(ui):
    _, _, clip_id = clip_with_file(ui)
    page = ui.page("admin", mobile=True, viewport=PHONE_LANDSCAPE)
    page.goto(f"/clips/{clip_id}")
    wait_clip_video(page, "#clip-video")
    bar_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_PLAYER)
    show_bar(page, 400, 150)
    geometry = layout(page)
    assert not geometry["overflowX"] and not geometry["outside"], geometry
    assert geometry["barHeight"] <= 60 and geometry["barBottom"] >= PHONE_LANDSCAPE["height"] - 2


def test_full_window_fallback_where_element_fullscreen_is_missing(ui):
    page, _, _ = open_player(ui, mobile=True)
    page.add_init_script("""
      for (const name of ['requestFullscreen', 'webkitRequestFullscreen', 'webkitRequestFullScreen']) delete Element.prototype[name];
      for (const name of ['exitFullscreen', 'webkitExitFullscreen', 'webkitCancelFullScreen']) delete Document.prototype[name];
    """)
    page.reload()
    wait_metadata(page)
    bar_button(page, "Pełny ekran").tap()
    expect(page.locator(".video-js")).to_have_class(re.compile(r"vjs-fullscreen"))
    assert page.evaluate("!document.fullscreenElement")
    box = page.locator(".video-js").bounding_box()
    assert box["width"] == 390 and box["height"] >= 800
    for overlay in ("#mark-count", "#timeline"):
        assert page.evaluate(f"document.querySelector('.video-js').contains(document.querySelector('{overlay}'))")
    show_bar(page)
    expect(page.get_by_role("button", name="Zaznacz (Z)")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".video-js")).not_to_have_class(re.compile(r"vjs-fullscreen"))
    # Room below the player so the page can scroll whatever its content, then the button at the top of the
    # viewport, so tap() has no reason to scroll the page first.
    page.evaluate("document.body.style.paddingBottom = '2000px'")
    bar_button(page, "Pełny ekran").evaluate("el => el.scrollIntoView({block: 'start'})")
    before = page.evaluate("window.scrollY")
    assert before > 0
    bar_button(page, "Pełny ekran").tap()
    bar_button(page, "Zamknij pełny ekran").tap()
    assert page.evaluate("document.documentElement.style.overflow !== 'hidden'")
    page.wait_for_function(f"Math.abs(window.scrollY - {before}) < 2")  # back where the page was


def test_phone_portrait_bar_sits_under_the_picture_and_stays(ui):
    page, _, _ = open_player(ui, mobile=True)
    geometry = page.evaluate("""() => {
      const video = document.querySelector('.video-js video').getBoundingClientRect();
      const bar = document.querySelector('.vjs-control-bar').getBoundingClientRect();
      return {videoBottom: video.bottom, barTop: bar.top, barVisible: getComputedStyle(document.querySelector('.vjs-control-bar')).visibility};
    }""")
    assert geometry["barTop"] >= geometry["videoBottom"] - 1, geometry
    page.wait_for_timeout(3500)  # past the idle timeout
    expect(bar_button(page, "Pełny ekran")).to_be_visible()


def test_clip_page_has_the_bar_and_the_keys(ui):
    _, _, clip_id = clip_with_file(ui)
    page = ui.page("admin")
    page.goto(f"/clips/{clip_id}")
    wait_clip_video(page, "#clip-video")
    assert page.evaluate("!document.getElementById('clip-video').controls")
    expect(page.locator(BAR)).to_have_count(1)
    page.evaluate("document.getElementById('clip-video').pause()")
    bar_button(page, "Klatka naprzód").click()
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 0.04) < 0.02")
    page.keyboard.press("]")
    assert page.evaluate("document.getElementById('clip-video').playbackRate") == 1.25
    page.keyboard.press("[")
    page.keyboard.press("[")
    assert page.evaluate("document.getElementById('clip-video').playbackRate") == 0.75
    expect(rate_label(page)).to_have_text("0.75x")
    page.keyboard.press(".")
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 0.08) < 0.02")
    page.keyboard.press("f")
    page.wait_for_function(FS_PLAYER)
    bar_button(page, "Zamknij pełny ekran").click()
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
    expect(bar_button(page, "Pełny ekran")).to_be_visible()
    page.locator("body").click(position={"x": 5, "y": 300})
    page.keyboard.press("]")
    assert page.evaluate("document.getElementById('preview').playbackRate") == 1.25


def test_public_share_page_bar_works_per_clip(ui):
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
    expect(page.locator(BAR)).to_have_count(2)
    page.wait_for_function("[...document.querySelectorAll('video')].every(v => v.readyState >= 1)")
    page.evaluate("document.querySelectorAll('video')[1].pause()")
    page.locator(BAR).nth(1).get_by_role("button", name="Klatka naprzód").tap()
    page.wait_for_function("Math.abs(document.querySelectorAll('video')[1].currentTime - 0.04) < 0.02")
    assert page.evaluate("document.querySelectorAll('video')[0].currentTime") < 0.01
    page.locator(BAR).nth(1).get_by_role("button", name="Pełny ekran").tap()
    page.wait_for_function("document.fullscreenElement === document.querySelectorAll('.video-js')[1]")
    show_bar(page)
    bar_button(page, "Zamknij pełny ekran").tap()
    page.wait_for_function("!document.fullscreenElement")
    assert not layout(page)["overflowX"]


def test_set_clip_view_has_the_bar(ui):
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
    bar_button(page, "Naprzód o 5 sekund").tap()
    page.wait_for_function("Math.abs(document.getElementById('clip-video').currentTime - 5) < 0.2")
    bar_button(page, "Pełny ekran").tap()
    page.wait_for_function(FS_PLAYER)


def test_watch_together_follower_controls_are_locked_but_full_screen_works(ui):
    leader, _, _ = open_player(ui, "admin")
    leader.get_by_role("button", name="Oglądaj razem").click()
    expect(leader.locator("#watch-leader")).to_have_text("Ty sterujesz")
    link = leader.locator("#watch-link").input_value()
    follower = ui.page("coach", mobile=True)
    follower.goto(link)
    wait_metadata(follower)
    expect(follower.locator("#watch-leader")).to_have_text("Steruje: Adam Admin")

    locked = follower.locator(f"{BAR} .pc-ctl, {BAR} .vjs-play-control, button.vjs-playback-rate, .vjs-progress-control")
    assert locked.count() >= 8
    for el in locked.all():
        expect(el).to_have_attribute("aria-disabled", "true")
    expect(follower.locator(".video-js")).to_have_class(re.compile(r"pc-locked"))
    bar_button(follower, "Odtwórz").tap(force=True)
    expect(follower.locator("#toast")).to_contain_text("Steruje: Adam Admin")
    assert follower.evaluate(f"{VIDEO}.paused")
    follower.locator("button.vjs-playback-rate").tap(force=True)
    assert follower.evaluate(f"{VIDEO}.playbackRate") == 1
    expect(follower.get_by_role("menuitemradio", name="0.5x", exact=True)).to_be_hidden()
    seek_to(leader, 15)
    leader.evaluate(f"{VIDEO}.pause()")
    follower.wait_for_function(f"Math.abs({VIDEO}.currentTime - 15) < 0.1")
    bar_button(follower, "Naprzód o 5 sekund").tap(force=True)
    assert abs(now(follower) - 15) < 0.2
    box = follower.locator(".vjs-progress-holder").bounding_box()
    follower.mouse.click(box["x"] + box["width"] * 0.8, box["y"] + box["height"] / 2)
    follower.wait_for_timeout(300)
    assert abs(now(follower) - 15) < 0.5, "the seek bar is locked as well"

    bar_button(follower, "Pełny ekran").tap()
    follower.wait_for_function(FS_PLAYER)
    expect(follower.locator("#watch-badge")).to_be_visible()
    show_bar(follower)
    follower.get_by_role("button", name="Zaznacz (Z)").tap()
    expect(follower.locator(ROWS)).to_have_count(1)
    expect(leader.locator(ROWS)).to_have_count(1)
    bar_button(follower, "Zamknij pełny ekran").tap()
    follower.wait_for_function("!document.fullscreenElement")

    bar_button(leader, "Pełny ekran").click()
    leader.wait_for_function(FS_PLAYER)
    bar_button(leader, "Klatka naprzód").click()
    follower.wait_for_function(f"Math.abs({VIDEO}.currentTime - {now(leader)}) < 0.05")
    expect(leader.locator(f"{BAR} .pc-ctl").first).to_have_attribute("aria-disabled", "false")
    expect(leader.locator(".video-js")).not_to_have_class(re.compile(r"pc-locked"))

    follower.get_by_role("button", name="Odłącz").click()
    expect(follower.locator(f"{BAR} .pc-ctl").first).to_have_attribute("aria-disabled", "false")
