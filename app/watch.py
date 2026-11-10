"""Rooms for watching a recording together. State lives in memory of the single uvicorn process, so a
restart drops every room (clients reconnect and get 4404). All mutation happens on the event loop;
only `Participant.send` may be called from other threads.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from app import security

MAX_ROOMS = 30
MAX_ROOMS_PER_USER = 3
MAX_PARTICIPANTS = 10
MAX_MESSAGE_CHARS = 1024
RATE_BURST = 40
RATE_PER_SECOND = 20.0
ROOM_TTL_SECONDS = 600.0  # an empty room closes after this long
SESSION_RECHECK_SECONDS = 60.0
LEADER_GRACE_SECONDS = 10.0  # a dropped connection keeps the lead this long (reload, network blip)
OUTBOX_SIZE = 64
MIN_RATE, MAX_RATE = 0.25, 2.0
MAX_TIME = 86_400.0
TIME_SLACK = 10.0  # the stored duration may differ a little from the real one

CLOSE_PROTOCOL = 4400
CLOSE_SESSION = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_GONE = 4404
CLOSE_RATE = 4408
CLOSE_REPLACED = 4409
CLOSE_FULL = 4410
CLOSE_SLOW = 4411
CLOSE_TOO_BIG = 1009


class ProtocolError(Exception):
    def __init__(self, code: int = CLOSE_PROTOCOL):
        super().__init__(code)
        self.code = code


class LimitError(Exception):
    pass


def _reject_constant(name: str):
    raise ValueError(name)


def _number(value, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError
    try:
        number = float(value)
    except OverflowError:
        raise ProtocolError from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ProtocolError
    return number


def parse_message(raw: str, duration: float | None) -> dict:
    """Only known types; every field is validated and copied, so unknown keys never travel on."""
    if len(raw) > MAX_MESSAGE_CHARS:
        raise ProtocolError(CLOSE_TOO_BIG)
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except ValueError:
        raise ProtocolError from None
    if not isinstance(data, dict):
        raise ProtocolError
    kind = data.get("type")
    if kind == "state":
        if not isinstance(data.get("playing"), bool):
            raise ProtocolError
        return {"type": "state", "playing": data["playing"],
                "t": _number(data.get("t"), 0.0, (duration or MAX_TIME) + TIME_SLACK),
                "rate": _number(data.get("rate"), MIN_RATE, MAX_RATE)}
    if kind == "handover":
        target = data.get("to")
        if isinstance(target, bool) or not isinstance(target, int):
            raise ProtocolError
        return {"type": "handover", "to": target}
    if kind == "leave":
        return {"type": "leave"}
    raise ProtocolError


@dataclass
class LeadState:
    playing: bool = False
    t: float = 0.0
    rate: float = 1.0
    at: float = 0.0


class Participant:
    def __init__(self, user_id: int, name: str, loop: asyncio.AbstractEventLoop, joined_at: float):
        self.user_id = user_id
        self.name = name
        self.loop = loop
        self.joined_at = joined_at
        self.outbox: asyncio.Queue = asyncio.Queue(OUTBOX_SIZE)
        self.close_code: int | None = None
        self._tokens = float(RATE_BURST)
        self._refilled = joined_at

    def allow(self, now: float) -> bool:
        self._tokens = min(float(RATE_BURST), self._tokens + (now - self._refilled) * RATE_PER_SECOND)
        self._refilled = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True

    def send(self, message: dict) -> None:
        """Thread-safe: the marker endpoints run in the thread pool."""
        try:
            self.loop.call_soon_threadsafe(self._put, message)
        except RuntimeError:  # the loop is closed
            pass

    def close(self, code: int) -> None:
        try:
            self.loop.call_soon_threadsafe(self._close, code)
        except RuntimeError:
            pass

    def _put(self, message: dict | None) -> None:
        if self.close_code is not None:
            return
        try:
            self.outbox.put_nowait(message)
        except asyncio.QueueFull:
            self._close(CLOSE_SLOW)

    def _close(self, code: int) -> None:
        if self.close_code is not None:
            return
        self.close_code = code
        while True:
            try:
                self.outbox.put_nowait(None)
                return
            except asyncio.QueueFull:
                self.outbox.get_nowait()


class Room:
    def __init__(self, registry: Registry, video_id: int, duration: float | None, creator_id: int,
                 creator_name: str):
        self.registry = registry
        self.id = security.new_token()
        self.video_id = video_id
        self.duration = duration
        self.creator_id = creator_id
        self.leader_id: int | None = creator_id
        self.leader_name = creator_name
        self.leader_away_since: float | None = None
        self.participants: dict[int, Participant] = {}  # insertion order = time of joining
        self.state = LeadState(at=registry.clock())
        self.empty_since: float | None = registry.clock()

    def expired(self, now: float) -> bool:
        return self.empty_since is not None and now - self.empty_since >= ROOM_TTL_SECONDS

    def join(self, user_id: int, name: str, loop: asyncio.AbstractEventLoop) -> Participant:
        now = self.registry.clock()
        old = self.participants.get(user_id)
        if old is None and len(self.participants) >= MAX_PARTICIPANTS:
            raise LimitError
        person = Participant(user_id, name, loop, now)
        if old is not None:
            old.close(CLOSE_REPLACED)
        self.participants[user_id] = person  # a replaced connection keeps its place in the order
        self.empty_since = None
        if self.leader_id is None:
            self.leader_id = user_id
        if self.leader_id == user_id:
            self.leader_away_since = None
            self.leader_name = name
        self.broadcast(self.roster(), exclude=person)
        person.send(self.welcome(person))
        return person

    def leave(self, person: Participant, *, explicit: bool = False) -> None:
        if self.participants.get(person.user_id) is not person:
            return
        del self.participants[person.user_id]
        if not self.participants:
            self.empty_since = self.registry.clock()
        if self.leader_id == person.user_id:
            if explicit:
                self._pass_lead()
            else:
                self.leader_away_since = self.registry.clock()
        self.broadcast(self.roster())

    def apply_state(self, person: Participant, message: dict) -> None:
        if person.user_id != self.leader_id:
            return
        self.state = LeadState(message["playing"], message["t"], message["rate"], self.registry.clock())
        self.broadcast({"type": "state", **self.current_state()}, exclude=person)

    def handover(self, person: Participant, to: int) -> None:
        target = self.participants.get(to)
        if person.user_id != self.leader_id or target is None or target is person:
            return
        self._set_leader(target)
        self.broadcast(self.roster())

    def tick(self, now: float) -> None:
        if self.leader_away_since is not None and now - self.leader_away_since >= LEADER_GRACE_SECONDS:
            self._pass_lead()
            self.broadcast(self.roster())

    def _pass_lead(self) -> None:
        successor = next(iter(self.participants.values()), None)
        if successor is None:
            self.leader_id, self.leader_name, self.leader_away_since = None, "", None
        else:
            self._set_leader(successor)

    def _set_leader(self, person: Participant) -> None:
        self.leader_id, self.leader_name, self.leader_away_since = person.user_id, person.name, None

    def current_state(self) -> dict:
        state = self.state
        t = state.t
        if state.playing:
            t += (self.registry.clock() - state.at) * state.rate
        if self.duration:
            t = min(t, self.duration)
        return {"playing": state.playing, "t": round(t, 3), "rate": state.rate}

    def roster(self) -> dict:
        leader = None
        if self.leader_id is not None:
            leader = {"id": self.leader_id, "name": self.leader_name,
                      "away": self.leader_id not in self.participants}
        return {"type": "roster", "leader": leader,
                "people": [{"id": p.user_id, "name": p.name} for p in self.participants.values()]}

    def welcome(self, person: Participant) -> dict:
        return {**self.roster(), "type": "welcome", "you": person.user_id, "state": self.current_state()}

    def broadcast(self, message: dict, exclude: Participant | None = None) -> None:
        for person in list(self.participants.values()):
            if person is not exclude:
                person.send(message)


class Registry:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.rooms: dict[str, Room] = {}

    def create(self, video_id: int, duration: float | None, creator_id: int, creator_name: str) -> Room:
        self.tick()
        rooms = list(self.rooms.values())
        if len(rooms) >= MAX_ROOMS or sum(r.creator_id == creator_id for r in rooms) >= MAX_ROOMS_PER_USER:
            raise LimitError
        room = Room(self, video_id, duration, creator_id, creator_name)
        self.rooms[room.id] = room
        return room

    def find_own(self, creator_id: int, video_id: int) -> Room | None:
        now = self.clock()
        return next((r for r in self.rooms.values()
                     if r.creator_id == creator_id and r.video_id == video_id and not r.expired(now)), None)

    def get(self, room_id: str) -> Room | None:
        room = self.rooms.get(room_id)
        if room is not None and room.expired(self.clock()):
            del self.rooms[room_id]
            return None
        return room

    def tick(self) -> None:
        now = self.clock()
        for room_id, room in list(self.rooms.items()):
            if room.expired(now):
                del self.rooms[room_id]
            else:
                room.tick(now)

    def notify_markers_changed(self, video_id: int) -> None:
        """Called from the marker endpoints (thread pool): snapshots are copied before iterating."""
        for room in list(self.rooms.values()):
            if room.video_id == video_id:
                room.broadcast({"type": "markers"})


registry = Registry()


def notify_markers_changed(video_id: int) -> None:
    registry.notify_markers_changed(video_id)


async def sweep_forever() -> None:
    while True:
        await asyncio.sleep(1)
        registry.tick()
