from playwright.sync_api import expect

from tests.e2e.test_player import ROWS, VIDEO, open_player, seek_to, wait_metadata

INSTALL_SOCKET_LOG = """
window.__sockets = [];
window.WebSocket = class extends WebSocket {
  constructor(...args) { super(...args); window.__sockets.push(this); }
};
"""


def position(page) -> float:
    return page.evaluate(f"{VIDEO}.currentTime")


def test_two_viewers_follow_the_leader_mark_together_and_hand_over_control(ui):
    leader, _, video_id = open_player(ui, "admin")
    leader.get_by_role("button", name="Oglądaj razem").click()
    expect(leader.locator("#watch-leader")).to_have_text("Ty sterujesz")
    link = leader.locator("#watch-link").input_value()
    assert "/watch/" in link

    follower = ui.page("coach")
    follower.add_init_script(INSTALL_SOCKET_LOG)
    follower.goto(link)
    wait_metadata(follower)
    expect(follower.locator("#watch-leader")).to_have_text("Steruje: Adam Admin")
    expect(follower.locator("#speed")).to_be_disabled()
    expect(leader.locator("#watch-people li")).to_have_count(2)

    seek_to(leader, 20)
    leader.evaluate(f"{VIDEO}.play()")
    follower.wait_for_function(f"{VIDEO}.currentTime > 20.3 && !{VIDEO}.paused")
    assert abs(position(follower) - position(leader)) < 1.0
    leader.select_option("#speed", "0.5")
    follower.wait_for_function(f"{VIDEO}.playbackRate === 0.5")
    leader.evaluate(f"{VIDEO}.pause()")
    follower.wait_for_function(f"{VIDEO}.paused && Math.abs({VIDEO}.currentTime - {position(leader)}) < 0.05")

    follower.keyboard.press(" ")  # a follower cannot start playback
    expect(follower.locator("#toast")).to_contain_text("Steruje: Adam Admin")
    assert follower.evaluate(f"{VIDEO}.paused")
    leader.keyboard.press(".")  # frame step arrives as a paused seek
    follower.wait_for_function(f"Math.abs({VIDEO}.currentTime - {position(leader)}) < 0.02")

    follower.keyboard.press("z")  # Z works for a follower and shows up for the leader
    expect(leader.locator(ROWS)).to_have_count(1)
    expect(follower.locator(ROWS)).to_have_count(1)
    [clip] = ui.server.clips_of(video_id)
    assert clip.author_id == ui.server.users["coach"]

    follower.evaluate("window.__sockets[0].close()")  # dropped connection: reconnects, leader keeps the lead
    expect(follower.locator("#watch-status")).to_have_text("połączenie przerwane, łączę ponownie…")
    expect(follower.locator("#watch-status")).to_have_text("połączono")
    expect(follower.locator("#watch-leader")).to_have_text("Steruje: Adam Admin")

    leader.get_by_role("button", name="Przekaż sterowanie").click()
    expect(follower.locator("#watch-leader")).to_have_text("Ty sterujesz")
    expect(follower.locator("#speed")).to_be_enabled()
    expect(leader.locator("#watch-leader")).to_have_text("Steruje: Cezary Trener")
    seek_to(follower, 10)
    leader.wait_for_function(f"Math.abs({VIDEO}.currentTime - 10) < 0.2")

    leader.get_by_role("button", name="Odłącz").click()  # watching alone again
    seek_to(leader, 35)
    follower.wait_for_timeout(600)
    assert abs(position(follower) - 10) < 0.5
