"""Mecze: lista, formularz z obsadą (CC/U1/U2), szczegóły."""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import permissions, services
from app.auth import require
from app.db import get_db
from app.loaders import get_match
from app.models import OFFICIAL_FUNCTIONS, Match, User
from app.web import render

router = APIRouter()

TEAM_FIELDS = ("team_a_name", "team_a_color", "team_b_name", "team_b_color")


def match_form(
    date: str = Form(""), level: str = Form(""),
    team_a_name: str = Form(""), team_a_color: str = Form("białe"),
    team_b_name: str = Form(""), team_b_color: str = Form("ciemne"),
    cc_user: str = Form(""), cc_name: str = Form(""), u1_user: str = Form(""),
    u1_name: str = Form(""), u2_user: str = Form(""), u2_name: str = Form(""),
) -> dict[str, str]:
    """Pola formularza meczu jako słownik (zależność FastAPI)."""
    return dict(locals())


def _form_values(match: Match | None, user: User | None = None) -> dict:
    """Wartości początkowe formularza. Nowy mecz: użytkownik z rolą sędziego jest od razu
    wstawiony na pierwszą wolną pozycję (CC), z możliwością zmiany funkcji."""
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
        values["date"] = date_type.today().isoformat()
        if user is not None and "referee" in user.roles:
            values["cc_user"] = str(user.id)
    return values


def _render_form(request: Request, db: Session, match: Match | None, values: dict,
                 error: str | None = None, status_code: int = 200):
    return render(request, "match_form.html", status_code=status_code, match=match, values=values,
                  error=error, referees=services.referee_candidates(db))


def _save(db: Session, user: User, match: Match, form: dict[str, str]) -> None:
    """Zapisuje dane meczu i obsadę; sędzia (tylko) musi być w obsadzie, inaczej 403."""
    try:
        match.date = date_type.fromisoformat(form["date"])
    except ValueError:
        raise services.MatchFormError("Podaj poprawną datę meczu.") from None
    officials = services.officials_from_form(db, form)
    if not permissions.can_save_match(user, [user_id for _, user_id, _ in officials]):
        raise HTTPException(403, "Jako sędzia możesz zapisać tylko mecz, w którego obsadzie jesteś")
    match.level = form["level"].strip()
    for field in TEAM_FIELDS:
        setattr(match, field, form[field].strip())
    services.set_officials(db, match, officials)


@router.get("/")
def index(request: Request, db: Session = Depends(get_db),
          user: User = require(permissions.can_view)):
    matches = db.scalars(
        select(Match).options(selectinload(Match.videos), selectinload(Match.clips),
                              selectinload(Match.officials))
        .order_by(Match.date.desc(), Match.id.desc())).all()
    return render(request, "index.html", matches=matches)


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
        return _render_form(request, db, None, form, str(exc), 422)
    db.add(match)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.get("/matches/{match_id}")
def match_detail(request: Request, match: Match = Depends(get_match),
                 user: User = require(permissions.can_view)):
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    return render(request, "match_detail.html", match=match, busy=busy)


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
        return _render_form(request, db, match, form, str(exc), 422)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.post("/matches/{match_id}/delete")
def delete_match(db: Session = Depends(get_db), match: Match = Depends(get_match),
                 user: User = require(permissions.can_delete_match, get_match)):
    for video in match.videos:
        services.remove_video_files(video)
    db.delete(match)
    db.commit()
    return RedirectResponse("/", status_code=303)
