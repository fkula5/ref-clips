"""One-time messages after POST -> 303 -> GET.
FLASH_COOKIE: short-lived, scoped to /admin, text only (percent-encoded, rendered through autoescape,
so no HTML injection), read once and cleared.
INVITE_COOKIE (path /admin/users): the token must not go into the redirect URL (query string = logs,
history, Referer). HttpOnly, SameSite=Strict, cleared on first display. Caddy does not log
Cookie/Set-Cookie (REDACTED) and app/logfilter.py covers /set-password/ and /s/.
SHARE_COOKIE (path /share-links) works the same: POST /share-links -> 303 -> GET
/share-links/created, code only in the cookie.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from app import config

FLASH_COOKIE = "refclips_flash"
FLASH_PATH = "/admin"
FLASH_MAX_AGE = 60
FLASH_MAX_CHARS = 600

# Like FLASH_COOKIE but valid site-wide (pages outside /admin, e.g. sheets).
PAGE_COOKIE = "refclips_notice"

INVITE_COOKIE = "refclips_invite"
INVITE_PATH = "/admin/users"
INVITE_MAX_AGE = 60
INVITE_VALUE = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{16,128})$")

SHARE_COOKIE = "refclips_share"
SHARE_PATH = "/share-links"
SHARE_MAX_AGE = 60
SHARE_VALUE = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{43})$")


def redirect_with_notice(url: str, notice: str | None = None) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if notice:
        response.set_cookie(FLASH_COOKIE, quote(notice[:FLASH_MAX_CHARS], safe=""), max_age=FLASH_MAX_AGE,
                            path=FLASH_PATH, httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return response


def redirect_with_page_notice(url: str, notice: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(PAGE_COOKIE, quote(notice[:FLASH_MAX_CHARS], safe=""), max_age=FLASH_MAX_AGE,
                        path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return response


def read_page_notice(request: Request) -> str | None:
    raw = request.cookies.get(PAGE_COOKIE)
    text = unquote(raw)[:FLASH_MAX_CHARS].strip() if raw else ""
    return text or None


def clear_page_notice(request: Request, response: Response) -> None:
    if PAGE_COOKIE in request.cookies:
        response.delete_cookie(PAGE_COOKIE, path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


def redirect_with_invite(url: str, user_id: int, token: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(INVITE_COOKIE, f"{user_id}.{token}", max_age=INVITE_MAX_AGE, path=INVITE_PATH,
                        httponly=True, secure=config.COOKIE_SECURE, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


def read_notice(request: Request) -> str | None:
    """Does not clear the cookie; `clear` does that on the response."""
    raw = request.cookies.get(FLASH_COOKIE)
    text = unquote(raw)[:FLASH_MAX_CHARS].strip() if raw else ""
    return text or None


def read_invite(request: Request) -> tuple[int, str] | None:
    found = INVITE_VALUE.match(request.cookies.get(INVITE_COOKIE, ""))
    return (int(found[1]), found[2]) if found else None


def clear_notice(request: Request, response: Response) -> None:
    if FLASH_COOKIE in request.cookies:
        response.delete_cookie(FLASH_COOKIE, path=FLASH_PATH, httponly=True,
                               secure=config.COOKIE_SECURE, samesite="lax")


def clear_invite(request: Request, response: Response) -> None:
    if INVITE_COOKIE in request.cookies:
        response.delete_cookie(INVITE_COOKIE, path=INVITE_PATH, httponly=True,
                               secure=config.COOKIE_SECURE, samesite="strict")


def redirect_with_share(url: str, link_id: int, code: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(SHARE_COOKIE, f"{link_id}.{code}", max_age=SHARE_MAX_AGE, path=SHARE_PATH,
                        httponly=True, secure=config.COOKIE_SECURE, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


def read_share(request: Request) -> tuple[int, str] | None:
    found = SHARE_VALUE.match(request.cookies.get(SHARE_COOKIE, ""))
    return (int(found[1]), found[2]) if found else None


def clear_share(request: Request, response: Response) -> None:
    if SHARE_COOKIE in request.cookies:
        response.delete_cookie(SHARE_COOKIE, path=SHARE_PATH, httponly=True,
                               secure=config.COOKIE_SECURE, samesite="strict")
