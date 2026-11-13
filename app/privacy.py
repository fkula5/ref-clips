"""Added to EVERY response under `/s/` (shared clips) and `/unsubscribe/` (page, file, ZIP, errors), whatever the route:
- `X-Robots-Tag: noindex, nofollow`: search engines do not index links.
- `Referrer-Policy: no-referrer`: the link code must not leak in Referer (Caddy does not override it
for `/s/*` and `/unsubscribe/*`, see `deploy/Caddyfile`).
- `Cache-Control: no-store` by default; a route may set its own (video: `private, no-store`).
"""
from __future__ import annotations

PREFIXES = ("/s/", "/unsubscribe/")
FIXED = {b"x-robots-tag": b"noindex, nofollow", b"referrer-policy": b"no-referrer"}
DEFAULT = {b"cache-control": b"no-store"}


class SharePrivacyHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(PREFIXES):
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
