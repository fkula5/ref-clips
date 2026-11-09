"""Nagłówki prywatności dla publicznych stron linków (`/s/*`).

Dokładane do KAŻDEJ odpowiedzi pod `/s/` (strona, plik, ZIP, błędy), niezależnie od trasy:
- `X-Robots-Tag: noindex, nofollow` — wyszukiwarki nie indeksują linków,
- `Referrer-Policy: no-referrer` — kod linku nie trafia dalej w nagłówku Referer (Caddy nie nadpisuje go
  dla `/s/*`, patrz `deploy/Caddyfile`),
- `Cache-Control: no-store` — domyślnie; trasa może ustawić własną wartość (plik wideo: `private, no-store`).
"""
from __future__ import annotations

PREFIX = "/s/"
FIXED = {b"x-robots-tag": b"noindex, nofollow", b"referrer-policy": b"no-referrer"}
DEFAULT = {b"cache-control": b"no-store"}


class SharePrivacyHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in FIXED]
                present = {k.lower() for k, _ in headers}
                headers += list(FIXED.items()) + [(k, v) for k, v in DEFAULT.items() if k not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
