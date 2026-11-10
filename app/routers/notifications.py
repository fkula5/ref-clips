"""A notification of someone else is answered with 404, never 403. Opening one is a POST (it changes state) that
redirects to the target, so a plain GET link or a prefetch never marks anything as read.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import config, notify, permissions
from app.auth import current_user, require
from app.db import get_db
from app.models import Notification, User
from app.web import render

router = APIRouter()


def own_notification(notification_id: int, db: Session = Depends(get_db),
                     user: User = Depends(current_user)) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or not permissions.can_view_notification(user, notification):
        raise HTTPException(404, "Nie ma takiego powiadomienia")
    return notification


@router.get("/notifications")
def notification_list(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    items = notify.recent(db, user.id, config.NOTIFICATION_LIST_LIMIT)
    return render(request, "notifications.html", items=items, unread=notify.unread_count(db, user.id),
                  capped=len(items) == config.NOTIFICATION_LIST_LIMIT, limit=config.NOTIFICATION_LIST_LIMIT)


@router.get("/notifications/bell")
def bell(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    response = render(request, "_bell.html", bell_count=notify.unread_count(db, user.id))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    notify.mark_all_read(db, user.id)
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/{notification_id}/read")
def read_one(db: Session = Depends(get_db), notification: Notification = Depends(own_notification)):
    notify.mark_read(notification)
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/{notification_id}/open")
def open_target(db: Session = Depends(get_db), notification: Notification = Depends(own_notification)):
    notify.mark_read(notification)
    db.commit()
    return RedirectResponse(notify.target_url(notification), status_code=303)
