import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app import config, watch
from app.models import Video
from app.routers.watch import origin_allowed
from tests.helpers import make_match, make_ready_video

ORIGIN = "http://testserver"


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(watch, "registry", watch.Registry(clock=fake))
    return fake


@pytest.fixture()
def video(db):
    return make_ready_video(db, make_match(db), duration=600)


@pytest.fixture()
def loop():
    event_loop = asyncio.new_event_loop()
    yield event_loop
    event_loop.close()


def new_room(client, video):
    res = client.post(f"/api/videos/{video.id}/watch")
    assert res.status_code == 200, res.text
    return res.json()["room"]


def connect(client, room, origin=ORIGIN):
    headers = {"origin": origin} if origin else {}
    return client.websocket_connect(f"/ws/watch/{room}", headers=headers)


@contextmanager
def joined(*clients_and_rooms):
    """Opens sockets in order; each one's `welcome` is consumed, and so is the others' `roster`."""
    with ExitStack() as stack:
        sockets = []
        for client, room in clients_and_rooms:
            sock = stack.enter_context(connect(client, room))
            assert sock.receive_json()["type"] == "welcome"
            for earlier in sockets:
                assert earlier.receive_json()["type"] == "roster"
            sockets.append(sock)
        yield sockets


def state(playing=True, t=10.0, rate=1.0):
    return {"type": "state", "playing": playing, "t": t, "rate": rate}


def closed_with(sock) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        for _ in range(100):
            sock.receive_json()
    return info.value.code


# --- handshake -----------------------------------------------------------------------------------

@pytest.mark.parametrize("cookie,origin", [
    ("none", ORIGIN), ("forged", ORIGIN), ("valid", "https://evil.example"), ("valid", "null"), ("valid", None)])
def test_handshake_rejects_missing_session_and_foreign_origin(make_client, video, cookie, origin):
    client, _ = make_client("referee")
    room = new_room(client, video)
    if cookie != "valid":
        client.cookies.clear()
        if cookie == "forged":
            client.cookies.set(config.SESSION_COOKIE, "x" * 43)
    with pytest.raises(WebSocketDisconnect):
        with connect(client, room, origin):
            pass


@pytest.mark.parametrize("public_url,origin,ok", [
    ("", "http://testserver", True), ("", "https://testserver", True),
    ("https://klipy.example.pl", "https://klipy.example.pl", True),
    ("https://klipy.example.pl", "https://evil.example.pl", False), ("", "http://testserver:9999", False)])
def test_origin_check(monkeypatch, public_url, origin, ok):
    monkeypatch.setattr(config, "PUBLIC_URL", public_url)
    assert origin_allowed("testserver", origin) is ok


def test_inactive_account_and_unknown_room_are_refused(make_client, db, video):
    client, user = make_client("referee")
    room = new_room(client, video)
    with connect(client, "no-such-room") as sock:
        assert closed_with(sock) == watch.CLOSE_GONE
    user.is_active = False
    db.commit()
    with pytest.raises(WebSocketDisconnect):
        with connect(client, room):
            pass


def test_viewer_cannot_join_when_the_recording_is_no_longer_playable(make_client, db, video):
    leader, _ = make_client("coach")
    guest, _ = make_client("referee")
    room = new_room(leader, video)
    video.purged_at = datetime(2026, 1, 1)
    db.commit()
    with connect(guest, room) as sock:
        assert closed_with(sock) == watch.CLOSE_FORBIDDEN


def test_room_creation_needs_login_and_a_ready_recording(anon_client, make_client, db, video):
    assert anon_client.post(f"/api/videos/{video.id}/watch").status_code == 401
    client, _ = make_client("referee")
    draft = Video(match_id=video.match_id, label="x", status="processing")
    db.add(draft)
    db.commit()
    assert client.post(f"/api/videos/{draft.id}/watch").status_code == 409


def test_share_link_redirects_into_the_player_with_the_token_in_the_fragment(make_client, anon_client, video):
    client, _ = make_client("referee")
    room = new_room(client, video)
    res = client.get(f"/watch/{room}", follow_redirects=False)
    assert (res.status_code, res.headers["location"]) == (303, f"/videos/{video.id}#room={room}")
    assert client.get("/watch/nope").status_code == 404
    login = anon_client.get(f"/watch/{room}", follow_redirects=False)
    assert login.status_code == 303 and login.headers["location"].startswith("/login")


# --- protocol ------------------------------------------------------------------------------------

def test_leader_state_reaches_followers_and_roster_is_shared(make_client, video):
    (lead, lead_user), (guest, _) = make_client("coach", name="Ala"), make_client("referee", name="Bartek")
    room = new_room(lead, video)
    with connect(lead, room) as a:
        welcome = a.receive_json()
        assert welcome["you"] == lead_user.id and welcome["leader"]["id"] == lead_user.id
        assert welcome["state"] == {"playing": False, "t": 0.0, "rate": 1.0}
        with connect(guest, room) as b:
            joined_msg = b.receive_json()
            assert joined_msg["leader"]["name"] == "Ala"
            assert [p["name"] for p in joined_msg["people"]] == ["Ala", "Bartek"]
            assert [p["name"] for p in a.receive_json()["people"]] == ["Ala", "Bartek"]
            a.send_json({**state(t=42.5, rate=0.5), "evil": "<img src=x>"})
            assert b.receive_json() == {"type": "state", "playing": True, "t": 42.5, "rate": 0.5}


def test_only_the_leaders_control_messages_are_applied(make_client, video):
    clients = [make_client("coach")[0], make_client("referee")[0], make_client("referee")[0]]
    room = new_room(clients[0], video)
    with joined(*[(c, room) for c in clients]) as (lead, b, c):
        b.send_json(state(t=99))
        b.send_json({"type": "handover", "to": 1})
        lead.send_json(state(t=5))
        assert c.receive_json()["t"] == 5  # b's messages were dropped, not forwarded
        b.send_json({"type": "handover", "to": 12345})  # not a participant: ignored too
        lead.send_json(state(t=6))
        assert c.receive_json()["t"] == 6


def test_handover_moves_control_to_the_chosen_participant(make_client, video):
    (lead, _), (guest, guest_user), (other, _) = make_client("coach"), make_client("referee"), make_client("referee")
    room = new_room(lead, video)
    with joined((lead, room), (guest, room), (other, room)) as (a, b, c):
        a.send_json({"type": "handover", "to": guest_user.id})
        for sock in (a, b, c):
            assert sock.receive_json()["leader"]["id"] == guest_user.id
        a.send_json(state(t=7))  # the old leader is a follower now
        b.send_json(state(t=8))
        assert c.receive_json()["t"] == 8


def test_same_user_in_a_second_window_replaces_the_first(make_client, video):
    client, _ = make_client("coach")
    room = new_room(client, video)
    with connect(client, room) as first:
        first.receive_json()
        with connect(client, room) as second:
            welcome = second.receive_json()
            assert len(welcome["people"]) == 1 and welcome["leader"]["away"] is False
            assert closed_with(first) == watch.CLOSE_REPLACED


@pytest.mark.parametrize("send,code", [
    (lambda s: s.send_text("not json"), watch.CLOSE_PROTOCOL),
    (lambda s: s.send_bytes(b"\x00\x01"), watch.CLOSE_PROTOCOL),
    (lambda s: s.send_json({"type": "state", "playing": "yes", "t": 1, "rate": 1}), watch.CLOSE_PROTOCOL),
    (lambda s: s.send_text("x" * (watch.MAX_MESSAGE_CHARS + 1)), watch.CLOSE_TOO_BIG),
    (lambda s: [s.send_json(state()) for _ in range(watch.RATE_BURST + 5)], watch.CLOSE_RATE)])
def test_bad_traffic_closes_the_connection(make_client, clock, video, send, code):
    client, _ = make_client("coach")
    room = new_room(client, video)
    with connect(client, room) as sock:
        sock.receive_json()
        send(sock)
        assert closed_with(sock) == code


@pytest.mark.parametrize("raw", [
    "[]", "null", '{"type":"nope"}', '{"type":"state"}',
    '{"type":"state","playing":true,"t":NaN,"rate":1}', '{"type":"state","playing":true,"t":1e999,"rate":1}',
    '{"type":"state","playing":true,"t":-1,"rate":1}', '{"type":"state","playing":true,"t":611,"rate":1}',
    '{"type":"state","playing":true,"t":true,"rate":1}', '{"type":"state","playing":true,"t":1,"rate":0}',
    '{"type":"state","playing":true,"t":1,"rate":8}', '{"type":"state","playing":1,"t":1,"rate":1}',
    '{"type":"state","playing":true,"t":1' + "0" * 400 + ',"rate":1}',
    '{"type":"handover","to":"7"}', '{"type":"handover","to":true}', '{"type":"handover","to":1.5}'])
def test_invalid_messages_are_rejected(raw):
    with pytest.raises(watch.ProtocolError):
        watch.parse_message(raw, 600)


def test_valid_messages_keep_only_known_fields():
    assert watch.parse_message('{"type":"state","playing":false,"t":3,"rate":2,"x":1}', 600) == state(False, 3.0, 2.0)
    assert watch.parse_message('{"type":"handover","to":4,"x":1}', 600) == {"type": "handover", "to": 4}
    assert watch.parse_message('{"type":"leave"}', None) == {"type": "leave"}


def test_room_and_participant_limits(make_client, monkeypatch, clock, db, video):
    monkeypatch.setattr(watch, "MAX_ROOMS", 2)
    monkeypatch.setattr(watch, "MAX_ROOMS_PER_USER", 1)
    monkeypatch.setattr(watch, "MAX_PARTICIPANTS", 1)
    (a, _), (b, _), (c, _) = make_client("coach"), make_client("coach"), make_client("coach")
    room = new_room(a, video)
    assert new_room(a, video) == room  # the same recording: the same room
    assert a.post(f"/api/videos/{make_ready_video(db, make_match(db)).id}/watch").status_code == 429  # per user
    new_room(b, video)
    assert c.post(f"/api/videos/{video.id}/watch").status_code == 429  # whole server
    with joined((a, room)):
        with connect(b, room) as sock:
            assert closed_with(sock) == watch.CLOSE_FULL


def test_adding_a_marker_notifies_everyone_in_the_room(make_client, video):
    lead, guest = make_client("referee")[0], make_client("coach")[0]
    room = new_room(lead, video)
    with joined((lead, room), (guest, room)) as (a, b):
        res = guest.post(f"/api/videos/{video.id}/markers", json={"time_sec": 30})
        assert res.json()["created"] is True and res.json()["clips"][0]["mine"] is True
        assert a.receive_json() == b.receive_json() == {"type": "markers"}


# --- time-dependent behaviour (injected clock) ----------------------------------------------------

def make_room(loop, *names):
    room = watch.registry.create(1, 600.0, 1, names[0])
    for index, name in enumerate(names, start=1):
        room.join(index, name, loop)
    return room


def test_leaving_leader_hands_over_to_the_longest_present(clock, loop):
    room = make_room(loop, "A", "B", "C")
    room.leave(room.participants[1], explicit=True)
    assert room.leader_id == 2
    room.join(1, "A", loop)  # A is back, last in line
    room.leave(room.participants[2], explicit=True)
    assert room.leader_id == 3


def test_dropped_leader_keeps_the_lead_for_a_grace_period(clock, loop):
    room = make_room(loop, "A", "B", "C")
    room.leave(room.participants[1])
    assert room.leader_id == 1 and room.roster()["leader"]["away"] is True
    clock.now += watch.LEADER_GRACE_SECONDS - 1
    watch.registry.tick()
    room.join(1, "A", loop)  # reconnected in time
    assert room.leader_id == 1 and room.roster()["leader"]["away"] is False
    room.leave(room.participants[1])
    clock.now += watch.LEADER_GRACE_SECONDS
    watch.registry.tick()
    assert room.leader_id == 2


def test_empty_room_closes_after_ten_minutes_and_a_rejoin_keeps_it(clock, loop):
    room = make_room(loop, "A")
    room.leave(room.participants[1])
    clock.now += watch.ROOM_TTL_SECONDS - 1
    assert watch.registry.get(room.id) is room
    room.join(1, "A", loop)
    clock.now += watch.ROOM_TTL_SECONDS * 2
    assert watch.registry.get(room.id) is room  # someone is present
    room.leave(room.participants[1], explicit=True)
    clock.now += watch.ROOM_TTL_SECONDS
    assert watch.registry.get(room.id) is None
    assert room.leader_id is None and not watch.registry.rooms


def test_state_extrapolates_while_playing(clock, loop):
    room = make_room(loop, "A")
    room.apply_state(room.participants[1], state(True, 10.0, 2.0))
    clock.now += 5
    assert room.current_state()["t"] == 20.0
    assert make_room(loop, "B").current_state() == {"playing": False, "t": 0.0, "rate": 1.0}
