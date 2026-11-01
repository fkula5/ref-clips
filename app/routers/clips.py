"""Klipy: lista z filtrami, szczegóły, opis, komentarze, pobieranie."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import permissions, services
from app.auth import require, via_match
from app.db import get_db
from app.loaders import get_clip, get_comment
from app.models import Category, Clip, Comment, Match, MatchOfficial, User
from app.storage import storage
from app.timeutil import utcnow
from app.web import file_response, render

router = APIRouter()


def query_clips(db: Session, *, match_id=None, video_id=None, person=None, category_id=None,
                period=None, ids=None) -> list[Clip]:
    stmt = select(Clip).options(selectinload(Clip.comments)).order_by(
        Clip.match_id.desc(), Clip.video_id, Clip.time_sec)
    if match_id:
        stmt = stmt.where(Clip.match_id == match_id)
    if video_id:
        stmt = stmt.where(Clip.video_id == video_id)
    if category_id:
        stmt = stmt.where(Clip.category_id == category_id)
    if ids:
        stmt = stmt.where(Clip.id.in_(ids))
    if person:  # "u<id konta>" albo "n<znormalizowane imię i nazwisko>"
        accounts = services.account_names(db)
        official_ids = [oid for oid, user_id, name in db.execute(
            select(MatchOfficial.id, MatchOfficial.user_id, MatchOfficial.name))
            if services.person_key(user_id, name, accounts) == person]
        stmt = stmt.where(Clip.official_id.in_(official_ids))
    clips = list(db.scalars(stmt))
    if period:  # kwarta jest wyliczana ze znaczników, więc filtrujemy w Pythonie
        clips = [c for c in clips if (services.period_for(c.video.marks, c.time_sec) or "") == period]
    return clips


# --- lista ----------------------------------------------------------------------
@router.get("/clips")
def clips_list(request: Request, db: Session = Depends(get_db),
               user: User = require(permissions.can_view), match_id: int | None = None,
               video_id: int | None = None, person: str = "", category_id: int | None = None,
               period: str = "", created: int | None = None, skipped: int = 0):
    clips = query_clips(db, match_id=match_id, video_id=video_id, person=person or None,
                        category_id=category_id, period=period or None)
    pending = any(c.status in ("new", "queued") for c in clips)
    return render(
        request, "clips.html", clips=clips, pending=pending, created=created, skipped=skipped,
        matches=db.scalars(select(Match).order_by(Match.date.desc())).all(),
        people=services.people(db), categories=services.active_categories(db),
        f={"match_id": match_id, "video_id": video_id, "person": person,
           "category_id": category_id, "period": period},
        query=str(request.url.query),
    )


# --- szczegóły i opis -------------------------------------------------------------
@router.get("/clips/{clip_id}")
def clip_detail(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_view)):
    return render(request, "clip_detail.html", c=clip, filename=services.clip_filename(clip),
                  categories=services.active_categories(db),
                  busy=clip.status in ("new", "queued"))


@router.post("/clips/{clip_id}/update")
def clip_update(db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_describe_clip, get_clip),
                official: str = Form(""), category_id: str = Form(""),
                custom_category: str = Form(""), description: str = Form("")):
    """Opis klipu: sędzia z obsady (albo „cały zespół”), kategoria, opis tekstowy."""
    valid_officials = {str(o.id) for o in clip.match.officials}
    clip.whole_team = official == "team"
    clip.official_id = int(official) if official in valid_officials else None
    category = db.get(Category, int(category_id)) if category_id.isdigit() else None
    if category is not None and not category.is_active and category.id != clip.category_id:
        raise HTTPException(422, "Ta kategoria jest nieaktywna")
    clip.category_id = category.id if category else None
    custom = " ".join(custom_category.split())[:100]
    if category is not None and category.is_custom:
        if not custom:
            raise HTTPException(422, "Dla kategorii „własna” wpisz jej nazwę")
        clip.custom_category = custom
    else:
        clip.custom_category = None
    clip.description = description.strip()
    clip.described_at = utcnow()
    db.commit()
    return RedirectResponse(f"/clips/{clip.id}", status_code=303)


@router.post("/clips/{clip_id}/recut")
def clip_recut(db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
               user: User = require(via_match(permissions.can_manage_clips), get_clip)):
    services.queue_cut(db, clip)
    db.commit()
    return RedirectResponse(f"/clips/{clip.id}", status_code=303)


@router.post("/clips/{clip_id}/delete")
def clip_delete(db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_delete_clip, get_clip)):
    match_id = clip.match_id
    services.remove_clip_files(clip)
    db.delete(clip)
    db.commit()
    return RedirectResponse(f"/clips?match_id={match_id}", status_code=303)


def _clip_file(clip: Clip, download: bool):
    if not clip.clip_path or not storage.exists(clip.clip_path):
        raise HTTPException(404, "Klip nie jest jeszcze wycięty")
    return file_response(storage.local_path(clip.clip_path),
                         download_name=services.clip_filename(clip) if download else None)


@router.get("/clips/{clip_id}/file")
def clip_file(clip: Clip = Depends(get_clip), user: User = require(permissions.can_view)):
    return _clip_file(clip, download=False)


@router.get("/clips/{clip_id}/download")
def clip_download(clip: Clip = Depends(get_clip), user: User = require(permissions.can_view)):
    return _clip_file(clip, download=True)


# --- komentarze -----------------------------------------------------------------
@router.post("/clips/{clip_id}/comments")
def add_comment(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_comment), body: str = Form()):
    if body.strip():
        db.add(Comment(clip_id=clip.id, author_id=user.id, body=body.strip()))
        db.commit()
        db.refresh(clip)
    return render(request, "_comments.html", c=clip)


@router.post("/comments/{comment_id}/delete")
def delete_comment(request: Request, db: Session = Depends(get_db),
                   comment: Comment = Depends(get_comment),
                   user: User = require(permissions.can_delete_comment, get_comment)):
    clip, match_id = comment.clip, comment.match_id
    db.delete(comment)
    db.commit()
    if clip is None:
        return RedirectResponse(f"/matches/{match_id}", status_code=303)
    db.refresh(clip)
    return render(request, "_comments.html", c=clip)
