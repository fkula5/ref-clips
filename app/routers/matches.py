"""Mecze: lista, formularz, szczegóły."""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import services
from app.db import get_db
from app.models import Match, MatchReferee
from app.web import render

router = APIRouter()


def _get_match(db: Session, match_id: int) -> Match:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "Nie ma takiego meczu")
    return match


def _apply_form(db: Session, match: Match, *, date: date_type, level: str, team_a_name: str,
                team_a_color: str, team_b_name: str, team_b_color: str,
                ref_name: list[str], ref_role: list[str]) -> None:
    match.date, match.level = date, level.strip()
    match.team_a_name, match.team_a_color = team_a_name.strip(), team_a_color.strip()
    match.team_b_name, match.team_b_color = team_b_name.strip(), team_b_color.strip()
    wanted: dict[int, str] = {}
    for name, role in zip(ref_name, ref_role):
        if name.strip():
            referee = services.get_or_create_referee(db, name)
            wanted[referee.id] = role if role in ("crew_chief", "umpire") else "umpire"
    for mr in list(match.referees):
        if mr.referee_id in wanted:
            mr.role = wanted.pop(mr.referee_id)
        else:
            match.referees.remove(mr)
    for referee_id, role in wanted.items():
        match.referees.append(MatchReferee(referee_id=referee_id, role=role))


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    matches = db.scalars(
        select(Match).options(selectinload(Match.videos), selectinload(Match.decisions))
        .order_by(Match.date.desc(), Match.id.desc())).all()
    return render(request, "index.html", matches=matches)


@router.get("/matches/new")
def new_match(request: Request):
    return render(request, "match_form.html", match=None, today=date_type.today().isoformat())


@router.post("/matches")
def create_match(
    db: Session = Depends(get_db), date: date_type = Form(), level: str = Form(""),
    team_a_name: str = Form(""), team_a_color: str = Form("białe"),
    team_b_name: str = Form(""), team_b_color: str = Form("ciemne"),
    ref_name: list[str] = Form(default=[]), ref_role: list[str] = Form(default=[]),
):
    match = Match(created_by=services.default_user(db).id)
    _apply_form(db, match, date=date, level=level, team_a_name=team_a_name,
                team_a_color=team_a_color, team_b_name=team_b_name, team_b_color=team_b_color,
                ref_name=ref_name, ref_role=ref_role)
    db.add(match)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.get("/matches/{match_id}")
def match_detail(request: Request, match_id: int, db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    return render(request, "match_detail.html", match=match, busy=busy)


@router.get("/matches/{match_id}/edit")
def edit_match(request: Request, match_id: int, db: Session = Depends(get_db)):
    return render(request, "match_form.html", match=_get_match(db, match_id), today="")


@router.post("/matches/{match_id}")
def update_match(
    match_id: int, db: Session = Depends(get_db), date: date_type = Form(), level: str = Form(""),
    team_a_name: str = Form(""), team_a_color: str = Form("białe"),
    team_b_name: str = Form(""), team_b_color: str = Form("ciemne"),
    ref_name: list[str] = Form(default=[]), ref_role: list[str] = Form(default=[]),
):
    match = _get_match(db, match_id)
    _apply_form(db, match, date=date, level=level, team_a_name=team_a_name,
                team_a_color=team_a_color, team_b_name=team_b_name, team_b_color=team_b_color,
                ref_name=ref_name, ref_role=ref_role)
    db.commit()
    return RedirectResponse(f"/matches/{match.id}", status_code=303)


@router.post("/matches/{match_id}/delete")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    match = _get_match(db, match_id)
    for video in match.videos:
        services.remove_video_files(video)
    db.delete(match)
    db.commit()
    return RedirectResponse("/", status_code=303)
