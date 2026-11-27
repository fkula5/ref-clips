"""Self-service password reset by e-mail.

The public endpoint must not reveal which accounts exist, so every request that passes the per-IP limit is
handled the same way and answered identically: one transaction that records the request and, only for an
active account within the limits, also creates the reset link. The mail goes out afterwards (`deliver`, run
as a background task), so the response time does not depend on it. Limits are counted in the database
(config.RESET_*); the lock only serialises the check-and-record step of this process.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import accounts, config, digest, mail, security
from app.models import PasswordResetRequest, User
from app.timeutil import utcnow

log = logging.getLogger("password_reset")

_lock = threading.Lock()
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates" / "email"),
                   autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


class ResetThrottled(Exception):
    """The caller's IP address is over its request limit."""


@dataclass
class PendingMail:
    sender: mail.Sender
    name: str
    email: str
    link: str


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def email_key(email: str) -> str:
    """Hash of the normalised address: the table never holds addresses."""
    return security.hash_token(email)


def _count(db: Session, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(PasswordResetRequest).where(*conditions)) or 0


def _prune(db: Session, now) -> None:
    db.execute(delete(PasswordResetRequest).where(
        PasswordResetRequest.requested_at < now - timedelta(hours=config.RESET_KEEP_HOURS)))


def request_reset(db: Session, email: str, ip: str) -> PendingMail | None:
    """`email` is normalised and valid. Raises ResetThrottled when `ip` is over its limit; otherwise
    returns the mail to send, or None when nothing is to be sent (unknown or inactive account, a limit
    reached, mail not configured). The caller must answer the same in every case.
    """
    now = utcnow()
    key = email_key(email)
    reset = PasswordResetRequest.kind == "reset"
    with _lock:
        _prune(db, now)
        if _count(db, reset, PasswordResetRequest.ip == ip, PasswordResetRequest.requested_at
                  >= now - timedelta(minutes=config.RESET_IP_WINDOW_MINUTES)) >= config.RESET_IP_MAX_REQUESTS:
            db.commit()  # keeps the pruning only
            raise ResetThrottled
        user = db.scalar(select(User).where(User.email == email))
        mailed = (reset, PasswordResetRequest.mailed.is_(True))
        hour_ago = now - timedelta(hours=1)
        recent = _count(db, *mailed, PasswordResetRequest.email_key == key, PasswordResetRequest.requested_at
                        >= now - timedelta(minutes=config.RESET_EMAIL_COOLDOWN_MINUTES))
        hourly = _count(db, *mailed, PasswordResetRequest.email_key == key,
                        PasswordResetRequest.requested_at >= hour_ago)
        total = _count(db, *mailed, PasswordResetRequest.requested_at >= hour_ago)
        if total >= config.RESET_GLOBAL_MAX_PER_HOUR:
            mail.log_once(f"reset-global-{int(now.replace(tzinfo=UTC).timestamp() // 3600)}",
                          f"Password reset: {config.RESET_GLOBAL_MAX_PER_HOUR} mails in the last hour, "
                          "the limit is reached and further requests get no mail until it passes")
        sender, base = mail.get_sender(), digest.base_url()
        if sender is None or not base:
            mail.log_once("reset-disabled", "Password reset mails are not sent: "
                          + (mail.smtp_problem() or "REFCLIPS_PUBLIC_URL is not set (links need it)"))
        allowed = (user is not None and user.is_active and sender is not None and bool(base)
                   and recent == 0 and hourly < config.RESET_EMAIL_MAX_PER_HOUR
                   and total < config.RESET_GLOBAL_MAX_PER_HOUR)
        db.add(PasswordResetRequest(kind="reset", email_key=key, ip=ip, mailed=allowed, requested_at=now))
        token = (accounts.create_invite(db, user, "reset", None, commit=False,
                                        ttl=timedelta(minutes=config.PASSWORD_RESET_MINUTES))
                 if allowed else None)
        db.commit()
    if token is None:
        return None
    log.info("Password reset link created for %s", mask_email(email))
    return PendingMail(sender, user.name, user.email, f"{base}/set-password/{token}")


def build_message(pending: PendingMail) -> EmailMessage:
    context = {"name": pending.name, "link": pending.link, "minutes": config.PASSWORD_RESET_MINUTES}
    message = EmailMessage()
    sender_domain = config.MAIL_FROM.rsplit("@", 1)[-1] if "@" in config.MAIL_FROM else "localhost"
    message["From"] = Address(config.MAIL_FROM_NAME, addr_spec=config.MAIL_FROM or f"ref-clips@{sender_domain}")
    message["To"] = Address(pending.name, addr_spec=pending.email)
    message["Subject"] = "ref-clips — ustawienie nowego hasła"
    message["Date"] = format_datetime(utcnow().replace(tzinfo=UTC))
    message["Message-ID"] = make_msgid(domain=sender_domain)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(_env.get_template("reset.txt").render(**context), cte="quoted-printable")
    message.add_alternative(_env.get_template("reset.html").render(**context), subtype="html",
                            cte="quoted-printable")
    return message


def deliver(pending: PendingMail) -> None:
    """Background task. Logs the class of a failure only: SMTP errors quote the recipient."""
    try:
        pending.sender.send(build_message(pending))
    except Exception as exc:  # noqa: BLE001 - nobody is waiting for the result
        log.warning("Password reset mail to %s failed: %s", mask_email(pending.email), type(exc).__name__)
    else:
        log.info("Password reset mail sent to %s", mask_email(pending.email))


def token_throttled(db: Session, ip: str) -> bool:
    """Too many unusable /set-password links from this address lately."""
    since = utcnow() - timedelta(minutes=config.TOKEN_MISS_WINDOW_MINUTES)
    return _count(db, PasswordResetRequest.kind == "token_miss", PasswordResetRequest.ip == ip,
                  PasswordResetRequest.requested_at >= since) >= config.TOKEN_MISS_MAX


def note_token_miss(db: Session, ip: str) -> None:
    now = utcnow()
    _prune(db, now)
    db.add(PasswordResetRequest(kind="token_miss", ip=ip, requested_at=now))
    db.commit()
