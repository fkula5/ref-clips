"""Jednorazowe komunikaty po przekierowaniu POST -> 303 -> GET (panel admina).

Zwykły komunikat („Dodano kategorię…”) leci w krótkotrwałym ciasteczku `FLASH_COOKIE` (tylko
tekst, kodowany procentowo; do strony trafia przez autoescape, więc nie da się wstrzyknąć HTML).
Ciasteczko jest ograniczone do `/admin`, czytane raz i kasowane przy pierwszym wyświetleniu strony.

Link zaproszenia ma osobne ciasteczko `INVITE_COOKIE` ze ścieżką `/admin/users`: token NIE trafia do
adresu przekierowania (query string = dzienniki, historia, Referer). Ciasteczko jest HttpOnly,
SameSite=Strict, żyje `INVITE_MAX_AGE` sekund, jest widziane tylko przez stronę kont i kasowane przy
jej pierwszym wyświetleniu. Dziennik Caddy nie zapisuje nagłówków Cookie/Set-Cookie (domyślnie
zastępuje je napisem REDACTED), a filtr `app/logfilter.py` i tak dotyczy tylko `/set-password/`."""
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

INVITE_COOKIE = "refclips_invite"
INVITE_PATH = "/admin/users"
INVITE_MAX_AGE = 60
INVITE_VALUE = re.compile(r"^(\d{1,12})\.([A-Za-z0-9_-]{16,128})$")   # <id konta>.<token>


def redirect_with_notice(url: str, notice: str | None = None) -> RedirectResponse:
    """303 na stronę listy z komunikatem do jednorazowego wyświetlenia."""
    response = RedirectResponse(url, status_code=303)
    if notice:
        response.set_cookie(FLASH_COOKIE, quote(notice[:FLASH_MAX_CHARS], safe=""), max_age=FLASH_MAX_AGE,
                            path=FLASH_PATH, httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return response


def redirect_with_invite(url: str, user_id: int, token: str) -> RedirectResponse:
    """303 na listę kont; link zaproszenia (id konta i token) czeka w ciasteczku, nie w adresie."""
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(INVITE_COOKIE, f"{user_id}.{token}", max_age=INVITE_MAX_AGE, path=INVITE_PATH,
                        httponly=True, secure=config.COOKIE_SECURE, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


def read_notice(request: Request) -> str | None:
    """Komunikat z ciasteczka (nie kasuje go — robi to `clear` na odpowiedzi)."""
    raw = request.cookies.get(FLASH_COOKIE)
    text = unquote(raw)[:FLASH_MAX_CHARS].strip() if raw else ""
    return text or None


def read_invite(request: Request) -> tuple[int, str] | None:
    """(id konta, token) z ciasteczka zaproszenia albo None, gdy go nie ma lub ma zły kształt."""
    found = INVITE_VALUE.match(request.cookies.get(INVITE_COOKIE, ""))
    return (int(found[1]), found[2]) if found else None


def clear_notice(request: Request, response: Response) -> None:
    """Kasuje przeczytany komunikat (tylko gdy przyszedł z żądaniem)."""
    if FLASH_COOKIE in request.cookies:
        response.delete_cookie(FLASH_COOKIE, path=FLASH_PATH, httponly=True,
                               secure=config.COOKIE_SECURE, samesite="lax")


def clear_invite(request: Request, response: Response) -> None:
    """Kasuje ciasteczko zaproszenia (tylko gdy przyszło z żądaniem)."""
    if INVITE_COOKIE in request.cookies:
        response.delete_cookie(INVITE_COOKIE, path=INVITE_PATH, httponly=True,
                               secure=config.COOKIE_SECURE, samesite="strict")
