"""Serve the compiled Vue shell on browser routes and keep FastAPI as the same-origin API."""
import re
from pathlib import Path
from urllib.parse import parse_qs

from fastapi.responses import FileResponse


ROUTES = re.compile(
    r"(?:/|/auth/(?:login|reset)|/connection-error"
    r"|/matches(?:/new|/\d+(?:/edit|/describe)?)?"
    r"|/clips(?:/\d+)?|/recordings/\d+(?:/edit)?|/notifications(?:/settings)?"
    r"|/groups(?:/\d+(?:/review)?)?|/training-sets(?:/\d+(?:/clips/\d+)?)?"
    r"|/admin(?:/[a-z-]+)?|/sheets/\d+(?:/edit)?"
    r"|/self-assessments(?:/\d+(?:/edit)?)?|/referees/\d+"
    r"|/(?:s|set-password|unsubscribe)/[A-Za-z0-9_-]+"
    # Vue Router redirects the former Polish paths, preserving their query and fragment.
    r"|/mecze(?:/nowy|/\d+(?:/edycja|/opisywanie)?)?"
    r"|/klipy(?:/\d+)?|/nagrania/\d+(?:/edycja)?|/powiadomienia(?:/ustawienia)?"
    r"|/grupy(?:/\d+(?:/do-oceny)?)?|/zestawy(?:/\d+(?:/klipy/\d+)?)?"
    r"|/administracja(?:/[a-z-]+)?|/arkusze/\d+(?:/edycja)?"
    r"|/samooceny(?:/\d+(?:/edycja)?)?|/sedziowie/\d+)"
)
SHELL_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


class VueShell:
    def __init__(self, app, *, directory: Path):
        self.app = app
        self.index = directory / "index.html"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        headers = dict(scope["headers"])
        if b"hx-request" not in headers and (path.startswith("/auth/") or b"text/html" in headers.get(b"accept", b"")):
            query = parse_qs(scope["query_string"].decode("latin-1"), keep_blank_values=True)
            if query.get("view", [None])[0] != "classic" and ROUTES.fullmatch(path.rstrip("/") or "/"):
                response = FileResponse(self.index, media_type="text/html", headers=SHELL_HEADERS)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
