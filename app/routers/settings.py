"""Account settings. Every account edits only its own; the admin-only test send goes to the admin's own
address.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app import digest, flash, mail, permissions
from app.auth import require
from app.db import get_db
from app.models import DIGEST_EVENTS, User
from app.web import render

router = APIRouter(prefix="/settings")
log = logging.getLogger("settings")


def _page(request: Request, db: Session, user: User, *, status_code: int = 200, notice: str | None = None,
          error: str | None = None):
    pref = digest.get_pref(db, user.id)
    shown = digest.configurable_events(user)
    enabled = digest.enabled_events(user, pref)
    return render(request, "settings_notifications.html", status_code=status_code, notice=notice, error=error,
                  digest_enabled=pref.digest_enabled, events=[(e, DIGEST_EVENTS[e], e in enabled) for e in shown],
                  mail_problem=digest.disabled_reason())


@router.get("/notifications")
def notification_settings(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    return _page(request, db, user)


@router.post("/notifications")
def save_notification_settings(
        db: Session = Depends(get_db), user: User = require(permissions.can_view),
        digest_enabled: str = Form(""), new_clips_in_groups: str = Form(""), new_match_in_groups: str = Form(""),
        comments_and_ratings: str = Form(""), sheet_published: str = Form(""), group_added: str = Form("")):
    pref = digest.get_pref(db, user.id)
    pref.digest_enabled = bool(digest_enabled)
    submitted = {"new_clips_in_groups": new_clips_in_groups, "new_match_in_groups": new_match_in_groups,
                 "comments_and_ratings": comments_and_ratings, "sheet_published": sheet_published,
                 "group_added": group_added}
    for event in digest.configurable_events(user):  # a switch the page did not show is never changed
        setattr(pref, event, bool(submitted[event]))
    db.commit()
    return flash.redirect_with_page_notice("/settings/notifications", "Zapisano ustawienia powiadomień.")


@router.post("/notifications/test")
def send_test_digest(request: Request, db: Session = Depends(get_db),
                     admin: User = require(permissions.can_manage_users)):
    sender = mail.get_sender()
    base = digest.base_url()
    if sender is None or not base:
        return _page(request, db, admin, status_code=503,
                     error="Wysyłka maili nie jest skonfigurowana na serwerze, więc nie ma czego testować.")
    try:
        had_news = digest.send_test(db, admin, sender, base)
    except Exception as exc:  # noqa: BLE001 - shown to the admin, who is testing exactly this
        log.warning("Test digest failed", exc_info=True)
        return _page(request, db, admin, status_code=502,
                     error=f"Nie udało się wysłać wiadomości: {type(exc).__name__}: {exc}"[:600])
    note = "" if had_news else " Przez ostatnie 24 godziny nic się nie zmieniło, więc wiadomość jest pusta."
    return _page(request, db, admin, notice=f"Wysłano wiadomość testową na adres {admin.email}.{note}")
