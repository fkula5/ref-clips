"""Filtr logów: tokeny z linków zaproszeń (`/set-password/<token>`) nie trafiają do dziennika dostępu.

Token w adresie pozwala ustawić hasło do cudzego konta, więc nie powinien zostawać w logach
(uvicorn zapisuje pełny adres każdego żądania). Odpowiednik dla Caddy jest w `deploy/Caddyfile`.
"""
from __future__ import annotations

import logging
import re

TOKEN_PATH = re.compile(r"(/set-password/)[^/?#\s\"]+")
REPLACEMENT = r"\1[ukryty]"


def redact(text: str) -> str:
    return TOKEN_PATH.sub(REPLACEMENT, text)


class RedactTokens(logging.Filter):
    """Podmienia token w komunikacie i jego argumentach (uvicorn.access podaje adres jako argument)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install() -> None:
    """Dołącza filtr do dziennika dostępu uvicorna (idempotentne)."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokens) for f in access.filters):
        access.addFilter(RedactTokens())
