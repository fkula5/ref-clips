"""Nagrania: panel i edycja, odtwarzacz, znaczniki kwart, notatki, szybkie klipy."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import permissions, services
from app.auth import require, via_match
from app.db import get_db
from app.loaders import get_mark, get_match, get_video
from app.models import PERIODS, Category, Match, PeriodMark, User, Video
from app.notes_parser import parse_notes, parse_time
from app.storage import storage
from app.textutil import format_clock
from app.web import clip_json, file_response, mark_json, render

router = APIRouter()

# Wgrywanie, znaczniki kwart i klipy: administrator i szkoleniowiec w każdym meczu, sędzia
# tylko w meczu, w którego obsadzie jest (po koncie).
can_upload_video = via_match(permissions.can_upload_to_match)
can_manage_video_clips = via_match(permissions.can_manage_clips)


# --- nagrania meczu (wgrywanie: app/routers/uploads.py, protokół tus) ---------------------
@router.get("/matches/{match_id}/videos-panel")
def videos_panel(request: Request, match: Match = Depends(get_match),
                 user: User = require(permissions.can_view)):
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    return render(request, "_videos_panel.html", match=match, busy=busy)


# --- serwowanie wideo (Range) ---------------------------------------------------
@router.get("/videos/{video_id}/stream")
def stream_video(video: Video = Depends(get_video), user: User = require(permissions.can_view)):
    if video.status != "ready" or not video.proxy_path or not storage.exists(video.proxy_path):
        raise HTTPException(409, "Wersja robocza nie jest jeszcze gotowa")
    return file_response(storage.local_path(video.proxy_path))


@router.post("/videos/{video_id}/retry")
def retry_video(db: Session = Depends(get_db), video: Video = Depends(get_video),
                user: User = require(can_upload_video, get_video)):
    """Ponowienie konwersji — tylko dopóki istnieje oryginał (po udanej konwersji jest usuwany)."""
    if video.status != "error":
        raise HTTPException(409, "Konwersję można ponowić tylko po błędzie")
    if not video.original_path or not storage.exists(video.original_path):
        raise HTTPException(409, "Oryginał został już usunięty — ponowna konwersja jest niemożliwa. "
                                 "Wgraj plik jeszcze raz.")
    services.queue_transcode(db, video)
    db.commit()
    return RedirectResponse(f"/matches/{video.match_id}", status_code=303)


@router.get("/videos/{video_id}/edit")
def edit_video_form(request: Request, video: Video = Depends(get_video),
                    user: User = require(can_upload_video, get_video)):
    return render(request, "video_edit.html", video=video, match=video.match, error=None,
                  kind=_content_kind(video.content), checked=services.declared_periods(video.content) or [])


@router.post("/videos/{video_id}/update")
def update_video(request: Request, label: str = Form(""), content_kind: str = Form("full"),
                 periods: list[str] = Form([]), db: Session = Depends(get_db),
                 video: Video = Depends(get_video),
                 user: User = require(can_upload_video, get_video)):
    """Etykieta i deklaracja zawartości pliku (cały mecz / kwarta / kilka kwart)."""
    try:
        content = services.content_from_form(content_kind, periods)
    except services.MatchFormError as exc:
        return render(request, "video_edit.html", status_code=422, video=video, match=video.match,
                      error=str(exc), kind=content_kind, checked=periods)
    video.label = label.strip()[:100]
    services.set_content(db, video, content)
    db.commit()
    return RedirectResponse(f"/matches/{video.match_id}", status_code=303)


def _content_kind(content: str | None) -> str:
    declared = services.declared_periods(content)
    return "full" if declared is None else declared[0] if len(declared) == 1 else "multi"


@router.post("/videos/{video_id}/delete")
def delete_video(db: Session = Depends(get_db), video: Video = Depends(get_video),
                 user: User = require(permissions.can_delete_video, get_video)):
    match_id = video.match_id
    services.remove_video_files(video)
    db.delete(video)
    db.commit()
    return RedirectResponse(f"/matches/{match_id}", status_code=303)


# --- odtwarzacz -----------------------------------------------------------------
def _state(video: Video) -> dict:
    return {
        "video_id": video.id,
        "duration": video.duration,
        "fps": video.fps or 25,
        "marks": [mark_json(mk) for mk in sorted(video.marks, key=lambda x: x.time_sec)],
        "clips": [clip_json(c) for c in sorted(video.clips, key=lambda x: x.time_sec)],
        "next_period": services.next_period(video.marks),
    }


@router.get("/videos/{video_id}")
def player(request: Request, t: float = 0, video: Video = Depends(get_video),
           user: User = require(permissions.can_view)):
    return render(request, "player.html", video=video, match=video.match, state=_state(video),
                  start_at=t)


@router.get("/api/videos/{video_id}/state")
def video_state(video: Video = Depends(get_video), user: User = require(permissions.can_view)):
    return _state(video)


class MarkIn(BaseModel):
    time_sec: float
    period: str | None = None


@router.post("/api/videos/{video_id}/marks")
def set_mark(body: MarkIn, db: Session = Depends(get_db), video: Video = Depends(get_video),
             user: User = require(can_upload_video, get_video)):
    """Dodaje znacznik początku kwarty (domyślnie następnej); istniejący jest przesuwany."""
    period = body.period or services.next_period(video.marks)
    if period not in PERIODS:
        raise HTTPException(422, "Nieznana kwarta")
    mark = next((mk for mk in video.marks if mk.period == period), None)
    if mark is None:
        mark = PeriodMark(video_id=video.id, period=period, time_sec=max(0.0, body.time_sec))
        video.marks.append(mark)
    else:
        mark.time_sec = max(0.0, body.time_sec)
    db.commit()
    db.refresh(video)
    return {"period": period, **_state(video)}


@router.delete("/api/marks/{mark_id}")
def delete_mark(db: Session = Depends(get_db), mark: PeriodMark = Depends(get_mark),
                user: User = require(lambda u, mk: can_upload_video(u, mk.video), get_mark)):
    video = mark.video
    db.delete(mark)
    db.commit()
    db.refresh(video)
    return _state(video)


# --- szybki klip (klawisz M; w segmencie 4 zastąpi go „Zaznacz”) ----------------
class QuickClipIn(BaseModel):
    time_sec: float
    text: str = ""


@router.post("/api/videos/{video_id}/quick-clip")
def quick_clip(body: QuickClipIn, db: Session = Depends(get_db), video: Video = Depends(get_video),
               user: User = require(can_manage_video_clips, get_video)):
    time_sec = max(0.0, body.time_sec)
    if video.duration:
        time_sec = min(time_sec, video.duration)
    clock = format_clock(time_sec)
    line = parse_notes(f"{clock} {body.text}", services.referee_defs(video.match),
                       services.category_defs(db))[0]
    category = services.category_by_name(db, line.category)
    clip = services.create_clip(
        db, video, user, time_sec=time_sec, official_id=line.referee_id,
        category_id=category.id if category else None,
        description=f"{clock} {body.text}".strip())
    db.commit()
    return {"clip": clip_json(clip), "warnings": line.warnings, **_state(video)}


# --- notatki: wklejenie, podgląd, zapis -----------------------------------------
@router.get("/videos/{video_id}/notes")
def notes_form(request: Request, video: Video = Depends(get_video),
               user: User = require(can_manage_video_clips, get_video)):
    return render(request, "notes.html", video=video, match=video.match, text="", rows=None)


@router.post("/videos/{video_id}/notes/preview")
def notes_preview(request: Request, text: str = Form(""), db: Session = Depends(get_db),
                  video: Video = Depends(get_video),
                  user: User = require(can_manage_video_clips, get_video)):
    rows = services.parse_for_match(db, video.match, text)
    for row in rows:
        if row.ok and video.duration and row.time_sec > video.duration:
            row.warnings.append(f"Czas poza nagraniem (max {format_clock(video.duration)})")
    return render(request, "notes.html", video=video, match=video.match, text=text, rows=rows,
                  categories=services.active_categories(db))


@router.post("/api/videos/{video_id}/notes/parse")
def notes_parse_api(payload: dict, db: Session = Depends(get_db), video: Video = Depends(get_video),
                    user: User = require(can_manage_video_clips, get_video)):
    rows = services.parse_for_match(db, video.match, payload.get("text", ""))
    return [
        {"line_no": r.line_no, "raw": r.raw, "time_sec": r.time_sec, "official_id": r.referee_id,
         "official": r.referee_name, "category": r.category, "warnings": r.warnings, "ok": r.ok}
        for r in rows
    ]


@router.post("/videos/{video_id}/notes/commit")
async def notes_commit(request: Request, db: Session = Depends(get_db),
                       video: Video = Depends(get_video),
                       user: User = require(can_manage_video_clips, get_video)):
    """Zapisuje (edytowane) wiersze podglądu jako klipy i zleca wycinanie."""
    form = await request.form()
    valid_officials = {o.id for o in video.match.officials}
    valid_categories = set(db.scalars(select(Category.id).where(Category.is_active.is_(True))))
    created = skipped = 0
    for i in range(int(form.get("count", 0))):
        if not form.get(f"include_{i}"):
            continue
        time_sec = parse_time(str(form.get(f"time_{i}", "")))
        if time_sec is None or (video.duration and time_sec > video.duration):
            skipped += 1
            continue
        official_raw = str(form.get(f"referee_{i}", ""))
        official_id = int(official_raw) if official_raw.isdigit() and int(official_raw) in valid_officials else None
        category_raw = str(form.get(f"category_{i}", ""))
        category_id = int(category_raw) if category_raw.isdigit() and int(category_raw) in valid_categories else None
        services.create_clip(db, video, user, time_sec=time_sec, official_id=official_id,
                             category_id=category_id, description=str(form.get(f"desc_{i}", "")).strip())
        created += 1
    db.commit()
    return RedirectResponse(f"/clips?video_id={video.id}&created={created}&skipped={skipped}",
                            status_code=303)
