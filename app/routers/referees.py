from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import clip_list, permissions, referee_profile
from app.auth import require
from app.db import get_db
from app.models import RATING_VERDICTS, User
from app.pagination import parse_page
from app.web import render

router = APIRouter(prefix="/referees")


def _address(person: User, period: str, page: int = 1) -> str:
    pairs = [("range", period if period != referee_profile.DEFAULT_PERIOD else ""),
             ("page", str(page) if page > 1 else "")]
    query = urlencode([(k, v) for k, v in pairs if v])
    return f"/referees/{person.id}" + (f"?{query}" if query else "")


@router.get("/{user_id}")
def referee_profile_page(request: Request, user_id: int, db: Session = Depends(get_db),
                         viewer: User = require(permissions.can_view_referee_profile)):
    person = referee_profile.referee_or_none(db, user_id)
    if person is None:
        raise HTTPException(404, "Nie ma takiego sędziego")
    period = referee_profile.parse_period(request.query_params.get("range"))
    profile = referee_profile.build(db, viewer, person, period, parse_page(request.query_params.get("page")))
    key = referee_profile.person_key(person)
    return render(
        request, "referee_profile.html", p=profile, key=key, periods=referee_profile.PERIODS,
        verdicts=RATING_VERDICTS, clips_link=referee_profile.clips_link,
        page_href=lambda n: _address(person, period, n).partition("?")[2],
        nav=clip_list.ClipFilters(person=key).query(scope=False))
