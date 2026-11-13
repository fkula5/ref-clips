"""Switching the digest off from an e-mail: no login, session or CSRF. The token in the URL is the proof,
so a mail scanner that only GETs the link must not unsubscribe anybody: GET shows a confirmation form and
POST (that form, or a mail client's one-click `List-Unsubscribe-Post`) does it. Privacy headers come from
`app.privacy`.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailPreference
from app.web import templates

router = APIRouter()

TOKEN_FORMAT = re.compile(r"^[A-Za-z0-9_-]{43}$")  # security.new_token(); other shapes never reach the DB


def _preference(db: Session, token: str) -> EmailPreference | None:
    if not TOKEN_FORMAT.match(token):
        return None
    return db.scalar(select(EmailPreference).where(EmailPreference.unsubscribe_token == token))


def _page(request: Request, status_code: int, **context):
    return templates.TemplateResponse(request, "unsubscribe.html", context, status_code=status_code)


@router.api_route("/unsubscribe/{token}", methods=["GET", "HEAD"])
def unsubscribe_page(request: Request, token: str, db: Session = Depends(get_db)):
    pref = _preference(db, token)
    if pref is None:
        return _page(request, 404, state="invalid")
    return _page(request, 200, state="confirm" if pref.digest_enabled else "done", token=token)


@router.post("/unsubscribe/{token}")
def unsubscribe(request: Request, token: str, db: Session = Depends(get_db)):
    pref = _preference(db, token)
    if pref is None:
        return _page(request, 404, state="invalid")
    if pref.digest_enabled:
        pref.digest_enabled = False
        db.commit()
    return _page(request, 200, state="done", token=token)
