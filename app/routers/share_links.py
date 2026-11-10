from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import flash, permissions, share
from app.auth import require
from app.db import get_db
from app.loaders import get_share_link
from app.models import ShareLink, User
from app.security import hash_token, tokens_equal
from app.web import render

router = APIRouter(prefix="/share-links")


@router.post("")
def create_link(db: Session = Depends(get_db), user: User = require(permissions.can_view),
                clip_ids: list[str] = Form(default=[]), days: str = Form("")):
    """A failure on any clip rejects the whole form (no partial link). Success is a 303 to a page with
    the code, which waits in a short-lived cookie, not in the URL.
    """
    try:
        link, code = share.create_link(db, user, clip_ids, days)
    except share.ShareError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    return flash.redirect_with_share("/share-links/created", link.id, code)


@router.get("/created")
def created_page(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    """Shown once; after a refresh the code is gone."""
    pending = flash.read_share(request)
    link = db.get(ShareLink, pending[0]) if pending else None
    if link is not None and not (link.created_by == user.id and tokens_equal(link.token_hash, hash_token(pending[1]))):
        link = None
    clips = [(item.position, item.clip) for item in link.items] if link else []
    response = render(request, "share_created.html", link=link, clips=clips,
                      url=share.public_url(request, pending[1]) if link else None,
                      public_title=share.public_title)
    flash.clear_share(request, response)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/{link_id}/revoke")
def revoke_link(db: Session = Depends(get_db), link: ShareLink = Depends(get_share_link),
                user: User = require(permissions.can_revoke_share, get_share_link), clip_id: str = Form("")):
    share.revoke(db, link)
    return RedirectResponse(f"/clips/{clip_id}" if clip_id.isascii() and clip_id.isdecimal() else "/clips",
                            status_code=303)
