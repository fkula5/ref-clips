from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clip_list, feedback, groups, permissions, services, share
from app.auth import require, via_match
from app.clip_list import query_clips  # noqa: F401 - also used by app/routers/clips_v2.py
from app.db import get_db
from app.loaders import get_clip
from app.models import Clip, Match, User
from app.routers import describe
from app.storage import storage
from app.web import file_response, is_htmx, render

router = APIRouter()


def person_choices(db: Session) -> list[tuple[str, str]]:
    return [*services.people(db), (clip_list.TEAM, "cały zespół")]


@router.get("/clips")
def clips_list(request: Request, db: Session = Depends(get_db),
               user: User = require(permissions.can_view), created: int | None = None, skipped: int = 0):
    f = clip_list.parse_filters(request.query_params)
    clips = clip_list.select_clips(db, f)
    return render(
        request, "clips.html", clips=clips, f=f, created=created, skipped=skipped,
        shareable={c.id for c in clips if share.offerable(user, c)},
        pending=any(c.status in ("new", "queued") for c in clips),
        stats=clip_list.clip_stats(db, clips),
        matches=db.scalars(select(Match).order_by(Match.date.desc(), Match.id.desc())).all(),
        people=person_choices(db), categories=services.all_categories(db), groups=groups.all_groups(db),
        nav=f.query(scope=False), query=str(request.url.query))


def render_clip(request: Request, db: Session, clip: Clip, f: clip_list.ClipFilters, *,
                values: dict | None = None, error: str | None = None, status_code: int = 200, **extra):
    """`f` are the filters the user came from (previous/next clip is computed from them; the current
    clip need not match). HTMX refreshes of the clip section need no ratings or comments, so those
    are not loaded.
    """
    partial = is_htmx(request)
    previous, following = services.neighbours(clip_list.select_clips(db, f, match_id=clip.match_id), clip)
    nav = f.query(scope=False)
    user = request.state.user
    full_video = clip.video.purged_at is None and clip.video.status == "ready" and bool(clip.video.proxy_path)
    return render(
        request, "clip_detail.html", status_code=status_code, c=clip, filename=services.clip_filename(clip),
        categories=services.categories_for(db, clip), busy=clip.status in ("new", "queued"),
        previous=previous, following=following, nav=nav, nav_q=f"?{nav}" if nav else "",
        full_video=full_video, problem=describe.cut_problem(clip),
        share_links=share.active_links(db, clip.id) if permissions.can_share_clip(user, clip) else None,
        blocker=services.describe_block(clip), error=error,
        values=values if values is not None else describe.form_values(clip),
        ratings=None if partial else feedback.ratings_of(db, clip),
        comments=None if partial else feedback.comments_of(db, clip_id=clip.id), **extra)


@router.get("/clips/{clip_id}")
def clip_detail(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_view)):
    return render_clip(request, db, clip, clip_list.parse_filters(request.query_params))


@router.post("/clips/{clip_id}/update")
def clip_update(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_describe_clip, get_clip),
                official: str = Form(""), category_id: str = Form(""),
                custom_category: str = Form(""), description: str = Form(""),
                context: str = "", video_id: int | None = None):
    describing = context == "describe"
    values = {"official": official, "category_id": category_id,
              "custom_category": custom_category, "description": description}
    try:
        services.describe_clip(db, clip, official=official, category_id=category_id,
                               custom_category=custom_category, description=description)
    except services.ClipDescribeError as exc:
        db.rollback()
        if describing:
            return describe.render_screen(request, db, clip.match, clip_id=clip.id, video_id=video_id,
                                          values=values, error=str(exc), status_code=exc.status_code)
        return render_clip(request, db, clip, clip_list.parse_filters(request.query_params),
                           values=values, error=str(exc), status_code=exc.status_code)
    db.commit()
    if describing:
        return _to_next(db, clip, video_id)
    return _to_clip(request, clip)


def _to_clip(request: Request, clip: Clip) -> RedirectResponse:
    nav = clip_list.parse_filters(request.query_params).query(scope=False)
    return RedirectResponse(f"/clips/{clip.id}" + (f"?{nav}" if nav else ""), status_code=303)


def _describe_redirect(match_id: int, following: Clip | None, video_id: int | None) -> RedirectResponse:
    params = [("clip", str(following.id))] if following else []
    if video_id:
        params.append(("video_id", str(video_id)))
    return RedirectResponse(f"/matches/{match_id}/describe" + (f"?{urlencode(params)}" if params else ""),
                            status_code=303)


def _to_next(db: Session, clip: Clip, video_id: int | None) -> RedirectResponse:
    following = services.next_in_queue(services.undescribed_queue(db, clip.match_id, video_id), clip)
    return _describe_redirect(clip.match_id, following, video_id)


@router.post("/clips/{clip_id}/recut")
def clip_recut(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
               user: User = require(via_match(permissions.can_manage_clips), get_clip)):
    video = clip.video
    if video.purged_at is not None or video.status != "ready" or not video.proxy_path:
        raise HTTPException(409, "Pełnego nagrania nie ma już na serwerze — klipu nie da się wyciąć ponownie")
    services.queue_cut(db, clip)
    db.commit()
    return _to_clip(request, clip)


@router.post("/clips/{clip_id}/delete")
def clip_delete(db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_delete_clip, get_clip),
                context: str = "", video_id: int | None = None):
    match_id = clip.match_id
    following = None
    if context == "describe":  # in the describe screen the next clip is computed before this one disappears
        following = services.next_in_queue(services.undescribed_queue(db, match_id, video_id), clip)
    services.remove_clip_files(clip)
    db.delete(clip)
    db.commit()
    if context == "describe":
        return _describe_redirect(match_id, following, video_id)
    return RedirectResponse(f"/matches/{match_id}#klipy", status_code=303)


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
