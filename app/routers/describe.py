"""Ekran opisywania znaczników: kolejka nieopisanych klipów meczu (albo jednego nagrania),
podgląd klipu i pola opisu. Zapis opisu: `POST /clips/{id}/update?context=describe`
(app/routers/clips.py), który wraca tu przez `render_screen`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import permissions, services
from app.auth import require
from app.db import get_db
from app.loaders import get_match
from app.models import Clip, Match, User
from app.storage import storage
from app.textutil import format_clock
from app.web import render

router = APIRouter()

PROPOSAL_NOTE = "Wartości wstępne pochodzą z notatek — sprawdź je i zatwierdź albo popraw."


def scope_video(match: Match, video_id: int | None):
    """Nagranie z adresu, jeśli należy do meczu (inaczej ekran obejmuje cały mecz)."""
    return next((v for v in match.videos if v.id == video_id), None)


def form_values(clip: Clip) -> dict[str, str]:
    """Wartości pól opisu: zapisane w klipie albo wstępne (propozycja z notatek)."""
    return {"official": "team" if clip.whole_team else str(clip.official_id or ""),
            "category_id": str(clip.category_id or ""),
            "custom_category": clip.custom_category or "",
            "description": clip.description or ""}


def preview_of(clip: Clip) -> dict:
    """Podgląd: plik klipu, gdy wycięty; gdy czeka w kolejce — wersja robocza od startu do końca
    klipu (zatrzymanie na końcu robi describe.js); inaczej brak podglądu."""
    if clip.status == "cut" and clip.clip_path and storage.exists(clip.clip_path):
        return {"kind": "file", "src": f"/clips/{clip.id}/file?v={clip.clip_version}"}
    video = clip.video
    if (clip.status in ("new", "queued") and video.status == "ready" and video.purged_at is None
            and video.proxy_path):
        start, end = services.clip_range(clip)
        return {"kind": "draft", "src": f"/videos/{video.id}/stream", "start": start, "end": end}
    return {"kind": "none"}


def cut_problem(clip: Clip) -> dict | None:
    """Stan błędu cięcia: komunikat i czy ma sens „Wytnij ponownie”."""
    if clip.status != "error":
        return None
    video = clip.video
    if "poza nagraniem" in (clip.error or ""):
        return {"message": f"Moment poza nagraniem: znacznik {format_clock(clip.time_sec)} wypada po końcu nagrania, "
                           "więc klipu nie da się wyciąć. Usuń ten znacznik.", "can_recut": False}
    if video.purged_at is not None or video.status != "ready" or not video.proxy_path:
        return {"message": "Nie udało się wyciąć klipu, a pełnego nagrania nie ma już na serwerze, "
                           "więc nie da się go wyciąć ponownie.", "can_recut": False}
    return {"message": f"Nie udało się wyciąć klipu: {clip.error or 'nieznany błąd'}", "can_recut": True}


def render_screen(request: Request, db: Session, match: Match, *, clip_id: int | None = None,
                  video_id: int | None = None, values: dict | None = None, error: str | None = None,
                  status_code: int = 200):
    video = scope_video(match, video_id)
    queue = services.undescribed_queue(db, match.id, video.id if video else None)
    current = next((c for c in queue if c.id == clip_id), None)
    if current is None and clip_id is not None:  # klip spoza kolejki (np. już opisany) — pokazujemy go wprost
        extra = db.get(Clip, clip_id)
        current = extra if extra is not None and extra.match_id == match.id else None
    if current is None and queue:
        current = queue[0]
    in_queue = current is not None and any(c.id == current.id for c in queue)
    position = [c.id for c in queue].index(current.id) + 1 if in_queue else None
    next_clip = services.next_in_queue(queue, current) if current is not None else None
    return render(
        request, "describe.html", status_code=status_code, match=match, scope=video,
        scope_q=f"&video_id={video.id}" if video else "", queue=queue, current=current,
        position=position, next_clip=next_clip, preview=preview_of(current) if current else None,
        problem=cut_problem(current) if current else None,
        blocker=services.describe_block(current) if current else None,
        proposal=services.is_proposal(current) if current else False, proposal_note=PROPOSAL_NOTE,
        values=values if values is not None else (form_values(current) if current else {}),
        error=error, categories=services.categories_for(db, current) if current else [],
        many_videos=len(match.videos) > 1)


@router.get("/matches/{match_id}/describe")
def describe_screen(request: Request, clip: int | None = None, video_id: int | None = None,
                    match: Match = Depends(get_match), db: Session = Depends(get_db),
                    user: User = require(permissions.can_manage_clips, get_match)):
    return render_screen(request, db, match, clip_id=clip, video_id=video_id)
