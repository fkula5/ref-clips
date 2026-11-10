from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import clip_list, feedback, match_list, permissions, services, share, sheets, uploads
from app.auth import require
from app.db import get_db
from app.loaders import get_match
from app.models import OFFICIAL_FUNCTIONS, Match, UploadSession, User
from app.storage import storage
from app.timeutil import local_tz
from app.web import is_htmx, render

router = APIRouter()

TEAM_FIELDS = ("team_a_name", "team_a_color", "team_b_name", "team_b_color")


def match_form(
    date: str = Form(""), level: str = Form(""),
    team_a_name: str = Form(""), team_a_color: str = Form("białe"),
    team_b_name: str = Form(""), team_b_color: str = Form("ciemne"),
    cc_user: str = Form(""), cc_name: str = Form(""), u1_user: str = Form(""),
    u1_name: str = Form(""), u2_user: str = Form(""), u2_name: str = Form(""),
) -> dict[str, str]:
    return dict(locals())


def _form_values(match: Match | None, user: User | None = None) -> dict:
    values: dict = {"date": "", "level": "", "team_a_name": "", "team_a_color": "białe",
                    "team_b_name": "", "team_b_color": "ciemne"}
    for function in OFFICIAL_FUNCTIONS:
        values[f"{function.lower()}_user"] = ""
        values[f"{function.lower()}_name"] = ""
    if match is not None:
        values.update(date=match.date.isoformat(), level=match.level,
                      **{f: getattr(match, f) for f in TEAM_FIELDS})
        for official in match.officials:
            key = official.function.lower()
            values[f"{key}_user"] = str(official.user_id) if official.user_id else ""
            values[f"{key}_name"] = official.name or ""
    else:
        values["date"] = datetime.now(local_tz()).date().isoformat()  # "today" in the local timezone, not UTC
        if user is not None and "referee" in user.roles:
            values["cc_user"] = str(user.id)
    return values


def _render_form(request: Request, db: Session, match: Match | None, values: dict,
                 error: str | None = None, status_code: int = 200):
    return render(request, "match_form.html", status_code=status_code, match=match, values=values,
                  error=error, referees=services.referee_candidates(db),
                  levels=services.known_levels(db))


FIELD_LIMITS = {"level": ("Liga", 100), "team_a_name": ("Nazwa drużyny A", 100),
                "team_a_color": ("Kolor strojów drużyny A", 50), "team_b_name": ("Nazwa drużyny B", 100),
                "team_b_color": ("Kolor strojów drużyny B", 50)}


def _save(db: Session, user: User, match: Match, form: dict[str, str]) -> None:
    try:
        match.date = date_type.fromisoformat(form["date"])
    except ValueError:
        raise services.MatchFormError("Podaj poprawną datę meczu.") from None
    for field, (label, limit) in FIELD_LIMITS.items():
        if len(form[field].strip()) > limit:
            raise services.MatchFormError(f"{label}: najwyżej {limit} znaków.")
    officials = services.officials_from_form(db, form)
    if not permissions.can_save_match(user, [user_id for _, user_id, _ in officials]):
        raise services.MatchForbiddenError(
            "Jako sędzia możesz zapisać tylko mecz, w którego obsadzie jesteś — wybierz swoje konto "
            "na jednej z pozycji.")
    match.level = form["level"].strip()
    for field in TEAM_FIELDS:
        setattr(match, field, form[field].strip())
    services.set_officials(db, match, officials)


@router.get("/")
def index(request: Request, db: Session = Depends(get_db),
          user: User = require(permissions.can_view)):
    filters = match_list.parse_filters(request.query_params)
    result = match_list.list_matches(db, filters, user.id)
    return render(request, "index.html", f=filters, result=result, levels=services.known_levels(db),
                  people=services.people(db),
                  prev_query=filters.query(result.page - 1), next_query=filters.query(result.page + 1))


@router.get("/matches/new")
def new_match(request: Request, db: Session = Depends(get_db),
              user: User = require(permissions.can_create_match)):
    return _render_form(request, db, None, _form_values(None, user))


@router.post("/matches")
def create_match(request: Request, db: Session = Depends(get_db),
                 user: User = require(permissions.can_create_match),
                 form: dict[str, str] = Depends(match_form)):
    match = Match(created_by=user.id)
    try:
        _save(db, user, match, form)
    except services.MatchFormError as exc:
        db.rollback()
        return _render_form(request, db, None, form, str(exc), exc.status_code)
    db.add(match)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


def render_match(request: Request, db: Session, match: Match, *, status_code: int = 200, **extra):
    """Comments sit outside the areas refreshed every 3 s; the HTMX response (recordings panel and clip
    list refresh) does not load them.
    """
    f = clip_list.parse_filters(request.query_params)
    clips = clip_list.select_clips(db, f, match_id=match.id)
    all_clips = match.clips
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    user = request.state.user
    return render(request, "match_detail.html", status_code=status_code, match=match, busy=busy, clips=clips,
                  match_sheets=sheets.visible_to(user, match),
                  f=f, stats=clip_list.clip_stats(db, clips),
                  shareable={c.id for c in clips if share.offerable(request.state.user, c)},
                  pending=any(c.status in ("new", "queued") for c in clips),
                  nav=f.query(scope=False), total_clips=len(all_clips),
                  people=[*clip_list.match_people(db, match), (clip_list.TEAM, "cały zespół")],
                  categories=services.all_categories(db),
                  state=services.match_state(match.videos, services.transcode_queue(db)),
                  undescribed=sum(1 for c in all_clips if not c.is_described),
                  comments=None if is_htmx(request) else feedback.comments_of(db, match_id=match.id), **extra)


@router.get("/matches/{match_id}")
def match_detail(request: Request, match: Match = Depends(get_match),
                 db: Session = Depends(get_db), user: User = require(permissions.can_view)):
    return render_match(request, db, match)


@router.get("/matches/{match_id}/edit")
def edit_match(request: Request, db: Session = Depends(get_db), match: Match = Depends(get_match),
               user: User = require(permissions.can_edit_match, get_match)):
    return _render_form(request, db, match, _form_values(match))


@router.post("/matches/{match_id}")
def update_match(request: Request, db: Session = Depends(get_db), match: Match = Depends(get_match),
                 user: User = require(permissions.can_edit_match, get_match),
                 form: dict[str, str] = Depends(match_form)):
    try:
        _save(db, user, match, form)
    except services.MatchFormError as exc:
        db.rollback()
        return _render_form(request, db, match, form, str(exc), exc.status_code)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.get("/matches/{match_id}/delete")
def confirm_delete_match(request: Request, match: Match = Depends(get_match),
                         user: User = require(permissions.can_delete_match, get_match)):
    clips = len(match.clips)
    return render(request, "match_delete.html", match=match, videos=len(match.videos), clips=clips,
                  # others' drafts must stay hidden, so a non-admin only counts the sheets they can see
                  sheets=len(match.sheets if permissions.can_manage_users(user) else sheets.visible_to(user, match)),
                  undescribed=sum(1 for c in match.clips if not c.is_described))


@router.post("/matches/{match_id}/delete")
def delete_match(db: Session = Depends(get_db), match: Match = Depends(get_match),
                 user: User = require(permissions.can_delete_match, get_match)):
    for video in match.videos:
        services.remove_video_files(video)
    for up in db.scalars(select(UploadSession).where(UploadSession.match_id == match.id)):
        storage.delete(uploads.part_key(up.id))
    db.delete(match)
    db.commit()
    return RedirectResponse("/", status_code=303)
