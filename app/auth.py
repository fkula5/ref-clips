from __future__ import annotations

import ipaddress
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import accounts, config, security
from app.db import get_db
from app.models import User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def client_ip(request: Request) -> str:
    """Last X-Forwarded-For entry: the trusted proxy (Caddy) appends it, entries to the left may be
    forged by the client. Non-IP entries are ignored.
    """
    if config.TRUST_PROXY:
        last = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip()
        try:
            ipaddress.ip_address(last)
        except ValueError:
            pass
        else:
            return last
    return (request.client.host if request.client else "unknown")[:64]


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        config.SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400, path="/",
        httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE, path="/", httponly=True,
                           secure=config.COOKIE_SECURE, samesite="lax")


def set_anon_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(config.CSRF_COOKIE, token, path="/", httponly=True,
                        secure=config.COOKIE_SECURE, samesite="lax")


class SessionRefreshMiddleware:
    """A dependency cannot set headers on a response a route builds itself, hence this."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                token = scope.get("state", {}).get("refresh_session_cookie")
                if token:
                    carrier = Response()
                    set_session_cookie(carrier, token)
                    message = {**message, "headers": [*message.get("headers", []),
                                                      *carrier.raw_headers]}
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(config.SESSION_COOKIE)
    session = accounts.get_session(db, token)
    if session is None:
        raise HTTPException(401, "Wymagane logowanie")
    if accounts.refresh_session(db, session):
        request.state.refresh_session_cookie = token
    request.state.user = session.user
    request.state.session = session
    return session.user


def attach_user_if_missing(request: Request, db: Session) -> None:
    """For error pages raised before `current_user` ran (unknown route, bad path parameter). Read-only:
    unlike `current_user` it never extends the session.
    """
    if getattr(request.state, "user", None) is not None:
        return
    session = accounts.get_session(db, request.cookies.get(config.SESSION_COOKIE))
    if session is not None:
        request.state.user = session.user
        request.state.session = session


async def _supplied_csrf(request: Request) -> str | None:
    """The body is read only for forms, so raw file uploads must send the header."""
    supplied = request.headers.get("x-csrf-token")
    if supplied:
        return supplied
    if request.headers.get("content-type", "").startswith(FORM_TYPES):
        value = (await request.form()).get("csrf_token")
        return value if isinstance(value, str) else None
    return None


async def csrf_protect(request: Request, _user: User = Depends(current_user)) -> None:
    if request.method in SAFE_METHODS:
        return
    supplied = await _supplied_csrf(request)
    if not supplied or not security.tokens_equal(supplied, request.state.session.csrf_token):
        raise HTTPException(403, "Nieprawidłowy token CSRF — odśwież stronę i spróbuj ponownie")


async def csrf_anonymous(request: Request) -> None:
    """Double-submit cookie for forms without a session (login, set-password)."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(config.CSRF_COOKIE)
    supplied = await _supplied_csrf(request)
    if not cookie or not supplied or not security.tokens_equal(supplied, cookie):
        raise HTTPException(403, "Nieprawidłowy token CSRF — odśwież stronę i spróbuj ponownie")


PROTECTED = [Depends(csrf_protect)]
PUBLIC = [Depends(csrf_anonymous)]


def require(check: Callable[..., bool], loader: Callable | None = None):
    """`require(can_x)` calls `can_x(user)`; `require(can_x, get_match)` loads the object and calls
    `can_x(user, obj)`.
    Returns the user, so it can be a parameter default. Denied -> 403.
    """
    def _deny() -> None:
        raise HTTPException(403, "Brak uprawnień do tej operacji")

    if loader is None:
        def dependency(user: User = Depends(current_user)) -> User:
            if not check(user):
                _deny()
            return user
    else:
        def dependency(user: User = Depends(current_user), obj=Depends(loader)) -> User:
            if not check(user, obj):
                _deny()
            return user
    return Depends(dependency)


def via_match(check: Callable[..., bool]) -> Callable[..., bool]:
    return lambda user, obj: check(user, obj.match)
