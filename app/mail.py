"""Sending e-mail with the standard library only. `get_sender()` picks the backend from the environment
(app/config.py): SMTP, a directory of .eml files (development) or an in-memory outbox (tests); with nothing
configured it returns None and callers skip sending, which is the normal state of a fresh install.
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app import config
from app.timeutil import utcnow

log = logging.getLogger("mail")

OUTBOX: list[EmailMessage] = []
_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
_logged: set[str] = set()


class Sender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SmtpSender:
    def send(self, message: EmailMessage) -> None:
        security = config.SMTP_SECURITY
        context = ssl.create_default_context()
        if security == "ssl":
            smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS,
                                    context=context)
        else:
            smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_SECONDS)
        with smtp:
            if security == "starttls":
                smtp.starttls(context=context)
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(message, from_addr=config.MAIL_FROM, to_addrs=[message["To"].addresses[0].addr_spec])


class FileSender:
    """The file name carries no recipient, so nothing user-controlled reaches the path."""

    def __init__(self, directory: Path):
        self.directory = directory

    def send(self, message: EmailMessage) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%S")
        (self.directory / f"{stamp}-{uuid4().hex[:8]}.eml").write_bytes(bytes(message))


class MemorySender:
    def send(self, message: EmailMessage) -> None:
        OUTBOX.append(message)


def log_once(key: str, text: str) -> None:
    if key not in _logged:
        _logged.add(key)
        log.warning(text)


def smtp_problem() -> str | None:
    if not config.SMTP_HOST:
        return "REFCLIPS_SMTP_HOST is not set"
    if not _ADDRESS.match(config.MAIL_FROM):
        return "REFCLIPS_MAIL_FROM (or REFCLIPS_SMTP_USER) is not a valid address"
    if config.SMTP_SECURITY not in ("starttls", "ssl", "none"):
        return "REFCLIPS_SMTP_SECURITY must be starttls, ssl or none"
    return None


def get_sender() -> Sender | None:
    if config.MAIL_MODE == "memory":
        return MemorySender()
    if config.MAIL_MODE == "file":
        return FileSender(config.DATA_DIR / "outbox")
    problem = smtp_problem()
    if problem is None:
        return SmtpSender()
    log_once("disabled", f"E-mail digest is disabled: {problem}")
    return None


def is_dry_run() -> bool:
    """File and memory modes need no public address: the links in them are only looked at."""
    return config.MAIL_MODE in ("file", "memory")
