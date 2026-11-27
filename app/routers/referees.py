from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import clip_list, permissions, referee_profile
from app.auth import require
from app.db import get_db
from app.models import RATING_VERDICTS, User
from app.pagination import parse_page
from app.textutil import format_clock
from app.timeutil import local
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
    if request.headers.get("accept") == "application/json":
        def tally(value: referee_profile.Tally) -> dict:
            return {"clips": value.clips, "rated": value.rated, "unrated": value.unrated, "verdicts": value.verdicts}

        return JSONResponse({
            "name": person.name, "active": person.is_active, "person": key,
            "period": period, "since": profile.since.isoformat() if profile.since else "",
            "periods": [{"value": value, "label": label} for value, label in referee_profile.PERIODS.items()],
            "verdicts": RATING_VERDICTS, "match_count": profile.match_count,
            "total": tally(profile.total), "uncategorised": profile.uncategorised,
            "page": profile.pager.page, "pages": profile.pager.pages,
            "groups": [{"id": group.id, "name": group.name} for group in profile.groups],
            "matches": [{"id": row.match.id, "name": row.match.title,
                         "level": row.match.level, "function": row.function, "tally": tally(row.tally)}
                        for row in profile.matches],
            "categories": [{"id": row.category.id, "name": row.category.name, "tally": tally(row.tally)}
                           for row in profile.categories],
            "clips": [{"id": clip.id, "match": clip.match.title, "category": clip.category_label,
                       "time": format_clock(clip.time_sec), "description": clip.description} for clip in profile.clips],
            "ratings": [{"id": rating.id, "clip_id": rating.clip_id, "author": rating.coach.name,
                         "date": local(rating.created_at), "text": rating.comment, "verdict": RATING_VERDICTS[rating.verdict]}
                        for rating in profile.ratings],
            "comments": [{"id": cm.id, "clip_id": cm.clip_id, "author": cm.author.name,
                          "date": local(cm.created_at), "text": cm.body} for cm in profile.comments],
        }, headers={"Cache-Control": "no-store"})
    return render(
        request, "referee_profile.html", p=profile, key=key, periods=referee_profile.PERIODS,
        verdicts=RATING_VERDICTS, clips_link=lambda person, **kw: referee_profile.clips_link(person, **{"since": profile.since, **kw}),
        page_href=lambda n: _address(person, period, n).partition("?")[2],
        nav=clip_list.ClipFilters(person=key).query(scope=False))
