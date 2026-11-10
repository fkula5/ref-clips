from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app import accounts, config, permissions, watch
from app.auth import require
from app.db import SessionLocal
from app.loaders import get_video
from app.models import User, Video
from app.routers.videos import _playable

router = APIRouter()  # session + CSRF dependencies are added where it is included
ws_router = APIRouter()  # a WebSocket authenticates itself: the CSRF dependency expects an HTTP request


@router.post("/api/videos/{video_id}/watch")
async def create_room(video: Video = Depends(get_video), user: User = require(permissions.can_view)):
    """Opening a second room for the same recording returns the first one."""
    if not _playable(video):
        raise HTTPException(409, "Nagranie nie jest gotowe do odtwarzania")
    room = watch.registry.find_own(user.id, video.id)
    if room is None:
        try:
            room = watch.registry.create(video.id, video.duration, user.id, user.name)
        except watch.LimitError:
            raise HTTPException(429, "Za dużo otwartych pokoi — zamknij nieużywane albo spróbuj za chwilę") from None
    return {"room": room.id}


@router.get("/watch/{room_id}")
async def open_room(room_id: str, user: User = require(permissions.can_view)):
    """The shared link. The token goes in the fragment of the redirect, so it never reaches logs."""
    room = watch.registry.get(room_id)
    if room is None:
        raise HTTPException(404, "Pokój nie istnieje lub został zamknięty")
    return RedirectResponse(f"/videos/{room.video_id}#room={room.id}", status_code=303)


def origin_allowed(host: str, origin: str | None) -> bool:
    """Browsers always send Origin on a WebSocket handshake; a page of another site must not ride on
    the session cookie. The scheme is ignored because the proxy terminates TLS.
    """
    if not origin:
        return False
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    allowed = {host.lower()}
    if config.PUBLIC_URL:
        allowed.add(urlsplit(config.PUBLIC_URL).netloc.lower())
    return parts.netloc.lower() in allowed


def _identity(token: str | None) -> tuple[int, str] | None:
    with SessionLocal() as db:
        session = accounts.get_session(db, token)
        return (session.user.id, session.user.name) if session else None


def _may_watch(user_id: int, video_id: int) -> bool:
    with SessionLocal() as db:
        user, video = db.get(User, user_id), db.get(Video, video_id)
        return bool(user and video and _playable(video) and permissions.can_view(user))


@ws_router.websocket("/ws/watch/{room_id}")
async def watch_socket(ws: WebSocket, room_id: str):
    if not origin_allowed(ws.headers.get("host", ""), ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    token = ws.cookies.get(config.SESSION_COOKIE)
    identity = await run_in_threadpool(_identity, token)
    if identity is None:
        await ws.close(code=1008)
        return

    # From here on the caller is a logged-in user, so refusals carry an application close code.
    await ws.accept()
    room = watch.registry.get(room_id)
    if room is None:
        await ws.close(code=watch.CLOSE_GONE)
        return
    if not await run_in_threadpool(_may_watch, identity[0], room.video_id):
        await ws.close(code=watch.CLOSE_FORBIDDEN)
        return
    try:
        person = room.join(identity[0], identity[1], asyncio.get_running_loop())
    except watch.LimitError:
        await ws.close(code=watch.CLOSE_FULL)
        return

    try:
        async with anyio.create_task_group() as group:
            group.start_soon(_writer, ws, person, group.cancel_scope)
            group.start_soon(_watchdog, person, token)
            await _reader(ws, room, person)
            group.cancel_scope.cancel()
    finally:
        room.leave(person)
        if ws.application_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except (WebSocketDisconnect, RuntimeError):
                pass


async def _reader(ws: WebSocket, room: watch.Room, person: watch.Participant) -> None:
    while True:
        event = await ws.receive()
        if event["type"] == "websocket.disconnect":
            return
        raw = event.get("text")
        if raw is None:
            person.close(watch.CLOSE_PROTOCOL)
            continue
        if not person.allow(room.registry.clock()):
            person.close(watch.CLOSE_RATE)
            continue
        try:
            message = watch.parse_message(raw, room.duration)
        except watch.ProtocolError as exc:
            person.close(exc.code)
            continue
        if message["type"] == "state":
            room.apply_state(person, message)
        elif message["type"] == "handover":
            room.handover(person, message["to"])
        else:
            room.leave(person, explicit=True)
            return


async def _writer(ws: WebSocket, person: watch.Participant, scope: anyio.CancelScope) -> None:
    try:
        while True:
            message = await person.outbox.get()
            if message is None:
                await ws.close(code=person.close_code)
                break
            await ws.send_text(json.dumps(message, separators=(",", ":")))
    except (WebSocketDisconnect, RuntimeError, OSError):  # the peer is gone
        pass
    scope.cancel()


async def _watchdog(person: watch.Participant, token: str | None) -> None:
    """A logout or a deactivated account ends the live connection too."""
    while True:
        await anyio.sleep(watch.SESSION_RECHECK_SECONDS)
        if await run_in_threadpool(_identity, token) is None:
            person.close(watch.CLOSE_SESSION)
