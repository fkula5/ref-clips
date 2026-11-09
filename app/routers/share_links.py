"""Linki udostępniające klipy osobom bez konta: tworzenie (jeden klip albo zaznaczone), pokazanie kodu
raz po utworzeniu i unieważnianie. Strony publiczne `/s/<kod>`: app/routers/share.py."""
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
    """Link do jednego albo kilku klipów. Błąd w którymkolwiek (brak prawa, klip niewycięty, zła ważność,
    za dużo klipów) odrzuca cały formularz, bez częściowego linku. Sukces: 303 na stronę z kodem — kod
    czeka w krótkotrwałym ciasteczku, nie w adresie."""
    try:
        link, code = share.create_link(db, user, clip_ids, days)
    except share.ShareError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from None
    return flash.redirect_with_share("/share-links/created", link.id, code)


@router.get("/created")
def created_page(request: Request, db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    """Pełny adres linku, pokazany tylko raz (po odświeżeniu kodu już nie ma; trzeba utworzyć nowy link)."""
    pending = flash.read_share(request)
    link = db.get(ShareLink, pending[0]) if pending else None
    if link is not None and not (link.created_by == user.id and tokens_equal(link.token_hash, hash_token(pending[1]))):
        link = None
    clips = [(item.position, item.clip) for item in link.items] if link else []
    response = render(request, "share_created.html", link=link, clips=clips,
                      url=share.public_url(request, pending[1]) if link else None,
                      public_title=share.public_title)
    flash.clear_share(request, response)   # przeczytane (albo nieprzydatne) — nigdy drugi raz
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/{link_id}/revoke")
def revoke_link(db: Session = Depends(get_db), link: ShareLink = Depends(get_share_link),
                user: User = require(permissions.can_revoke_share, get_share_link), clip_id: str = Form("")):
    """Unieważnienie linku (twórca albo administrator); wraca na stronę klipu, z której przyszło żądanie."""
    share.revoke(db, link)
    return RedirectResponse(f"/clips/{clip_id}" if clip_id.isascii() and clip_id.isdecimal() else "/clips",
                            status_code=303)
