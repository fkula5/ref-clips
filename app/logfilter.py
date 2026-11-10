"""A token in the URL lets someone set another account's password and a share code opens clips without
login, so neither may stay in logs (uvicorn logs the full URL). The rest of the path stays:
/s/[ukryty]/clips/1/file. The Caddy counterpart is in deploy/Caddyfile.
"""
from __future__ import annotations

import logging
import re

TOKEN_PATH = re.compile(r"(/(?:set-password|s)/)[^/?#\s\"]+")
REPLACEMENT = r"\1[ukryty]"


def redact(text: str) -> str:
    return TOKEN_PATH.sub(REPLACEMENT, text)


class RedactTokens(logging.Filter):
    """uvicorn.access passes the URL as a log argument, so the arguments are rewritten too."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokens) for f in access.filters):
        access.addFilter(RedactTokens())
