from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import permissions, services, watch
from app.auth import require, via_match
from app.db import get_db
from app.loaders import get_clip, get_mark, get_match, get_video
from app.models import Category, Clip, Match, PeriodMark, User, Video
from app.notes_parser import parse_notes, parse_time
from app.storage import storage
from app.textutil import format_clock
from app.web import clip_json, file_response, mark_json, render

router = APIRouter()

can_upload_video = via_match(permissions.can_upload_to_match)
can_manage_video_clips = via_match(permissions.can_manage_clips)


@router.get("/matches/{match_id}/videos-panel")
def videos_panel(request: Request, match: Match = Depends(get_match),
                 user: User = require(permissions.can_view)):
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    return render(request, "_videos_panel.html", match=match, busy=busy)


@router.get("/videos/{video_id}/stream")
def stream_video(video: Video = Depends(get_video), user: User = require(permissions.can_view)):
    if video.purged_at is not None:
        raise HTTPException(409, "Pełne nagranie zostało usunięte")
    if video.status != "ready" or not video.proxy_path or not storage.exists(video.proxy_path):
        raise HTTPException(409, "Wersja robocza nie jest jeszcze gotowa")
    return file_response(storage.local_path(video.proxy_path))


@router.post("/videos/{video_id}/retry")
def retry_video(db: Session = Depends(get_db), video: Video = Depends(get_video),
                user: User = require(can_upload_video, get_video)):
    """only while the original exists (it is deleted after a successful conversion)"""
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
    return render(request, "video_edit.html", video=video, match=video.match, error=None, warnings=None,
                  kind=_content_kind(video.content), checked=services.declared_periods(video.content) or [])


@router.post("/videos/{video_id}/update")
def update_video(request: Request, label: str = Form(""), content_kind: str = Form("full"),
                 periods: list[str] = Form([]), confirm_marks: str = Form(""),
                 db: Session = Depends(get_db), video: Video = Depends(get_video),
                 user: User = require(can_upload_video, get_video)):
    """After the full recording is removed only the label changes: the declaration and quarter markers
    are frozen (clip quarters must stay as they were).
    """
    if video.purged_at is not None:
        video.label = label.strip()[:100]
        db.commit()
        return RedirectResponse(f"/matches/{video.match_id}", status_code=303)
    try:
        content = services.content_from_form(content_kind, periods)
    except services.MatchFormError as exc:
        return render(request, "video_edit.html", status_code=422, video=video, match=video.match,
                      error=str(exc), warnings=None, kind=content_kind, checked=periods)
    change = services.plan_content_change(video, content)
    if change.needs_confirmation and confirm_marks != change.token:
        return render(request, "video_edit.html", video=video, match=video.match, error=None,
                      warnings=change.warnings(), confirm_token=change.token, label=label,
                      kind=content_kind, checked=periods)
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


def _playable(video: Video) -> bool:
    return video.status == "ready" and video.purged_at is None and bool(video.proxy_path)


def _require_playable(video: Video) -> None:
    if video.purged_at is not None:
        raise HTTPException(409, "Pełne nagranie zostało usunięte — nie można dodawać znaczników")
    if not _playable(video):
        raise HTTPException(409, "Wersja robocza nie jest jeszcze gotowa")


def _periods(video: Video) -> list[dict]:
    marks = {mk.period: mk for mk in video.marks}
    required = set(services.required_periods(video.content))
    return [{"period": p, "required": p in required, "mark": mark_json(marks[p]) if p in marks else None}
            for p in services.allowed_periods(video.content)]


def _state(video: Video, user: User) -> dict:
    return {
        "video_id": video.id,
        "duration": video.duration,
        "fps": video.fps or 25,
        "content_label": services.content_label(video.content),
        "single_period": len(services.allowed_periods(video.content)) == 1,
        "marks": [mark_json(mk) for mk in sorted(video.marks, key=lambda x: x.time_sec)],
        "periods": _periods(video),
        "missing_periods": services.missing_periods(video.content, (mk.period for mk in video.marks)),
        "clips": [{**clip_json(c), "mine": c.author_id == user.id, "can_delete": _can_delete_marker(user, c)}
                  for c in sorted(video.clips, key=lambda x: x.time_sec)],
        "next_period": services.next_period(video.marks, video.content),
    }


def _can_delete_marker(user: User, clip: Clip) -> bool:
    return permissions.can_delete_clip(user, clip) and permissions.can_manage_clips(user, clip.match)


@router.get("/videos/{video_id}")
def player(request: Request, t: float = 0, video: Video = Depends(get_video),
           user: User = require(permissions.can_view)):
    state = _state(video, user) if _playable(video) else None
    return render(request, "player.html", video=video, match=video.match, state=state, start_at=t)


@router.get("/api/videos/{video_id}/state")
def video_state(video: Video = Depends(get_video), user: User = require(permissions.can_view)):
    return _state(video, user)


class MarkIn(BaseModel):
    time_sec: float
    period: str | None = None


@router.post("/api/videos/{video_id}/marks")
def set_mark(body: MarkIn, db: Session = Depends(get_db), video: Video = Depends(get_video),
             user: User = require(can_upload_video, get_video)):
    _require_playable(video)
    period = body.period or services.next_period(video.marks, video.content)
    if period is None:
        raise HTTPException(422, "Wszystkie kwarty mają już znaczniki — wskaż kwartę, której początek "
                                 "chcesz ustawić ponownie.")
    time_sec = max(0.0, body.time_sec)
    try:
        services.check_period_mark(video.content, video.marks, period, time_sec, video.duration)
    except services.PeriodMarkError as exc:
        raise HTTPException(422, str(exc)) from None
    mark = next((mk for mk in video.marks if mk.period == period), None)
    if mark is None:
        video.marks.append(PeriodMark(video_id=video.id, period=period, time_sec=time_sec))
    else:
        mark.time_sec = time_sec
    db.commit()
    db.refresh(video)
    watch.notify_markers_changed(video.id)
    return {"period": period, **_state(video, user)}


@router.delete("/api/marks/{mark_id}")
def delete_mark(db: Session = Depends(get_db), mark: PeriodMark = Depends(get_mark),
                user: User = require(lambda u, mk: can_upload_video(u, mk.video), get_mark)):
    video = mark.video
    _require_playable(video)  # after the full recording is removed, quarter markers are frozen
    if services.allowed_periods(video.content) == [mark.period]:
        raise HTTPException(409, "Plik z jedną kwartą zawsze ma znacznik początku — przesuń go "
                                 "(Ustaw tutaj) zamiast usuwać.")
    db.delete(mark)
    db.commit()
    db.refresh(video)
    watch.notify_markers_changed(video.id)
    return _state(video, user)


class MarkerIn(BaseModel):
    time_sec: float


@router.post("/api/videos/{video_id}/markers")
def add_marker(body: MarkerIn, db: Session = Depends(get_db), video: Video = Depends(get_video),
               user: User = require(can_manage_video_clips, get_video)):
    """A marker at the current time = an undescribed clip (15 s margin on each side, cut queued). A
    second marker by the same author within a second is ignored (`created: false`).
    """
    _require_playable(video)
    clip, created = services.add_marker(db, video, user, body.time_sec)
    db.refresh(video)
    if created:
        watch.notify_markers_changed(video.id)
    return {"marker": clip_json(clip), "created": created, **_state(video, user)}


@router.post("/api/videos/{video_id}/markers/undo")
def undo_marker(db: Session = Depends(get_db), video: Video = Depends(get_video),
                user: User = require(can_manage_video_clips, get_video)):
    _require_playable(video)
    clip = services.undo_marker(db, video, user)
    if clip is None:
        raise HTTPException(404, "Nie masz nieopisanego znacznika do cofnięcia")
    db.refresh(video)
    watch.notify_markers_changed(video.id)
    return {"removed": clip.id, "time_sec": clip.time_sec, **_state(video, user)}


@router.delete("/api/clips/{clip_id}")
def delete_marker(confirm: bool = False, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                  user: User = require(_can_delete_marker, get_clip)):
    """A described clip needs confirmation (`?confirm=true`)."""
    if clip.is_described and not confirm:
        raise HTTPException(409, "Klip jest już opisany — potwierdź usunięcie")
    video = clip.video
    services.remove_clip_files(clip)
    db.delete(clip)
    db.commit()
    db.refresh(video)
    watch.notify_markers_changed(video.id)
    return _state(video, user)


class QuickClipIn(BaseModel):
    time_sec: float
    text: str = ""


@router.post("/api/videos/{video_id}/quick-clip")
def quick_clip(body: QuickClipIn, db: Session = Depends(get_db), video: Video = Depends(get_video),
               user: User = require(can_manage_video_clips, get_video)):
    _require_playable(video)
    time_sec = services.clamp_time(body.time_sec, video.duration)
    clock = format_clock(time_sec)
    line = parse_notes(f"{clock} {body.text}", services.referee_defs(video.match),
                       services.category_defs(db))[0]
    category = services.category_by_name(db, line.category)
    clip = services.create_clip(
        db, video, user, time_sec=time_sec, official_id=line.referee_id,
        category_id=category.id if category else None,
        description=line.description)  # only the remainder: no time, referee or category (they are separate fields)
    db.commit()
    watch.notify_markers_changed(video.id)
    return {"clip": clip_json(clip), "warnings": line.warnings, **_state(video, user)}


def _notes_limit(text: str) -> None:
    try:
        services.clean_notes(text)
    except services.NotesTooLong as exc:
        raise HTTPException(413, str(exc)) from None


def _rows_json(rows) -> list[dict]:
    return [
        {"line_no": r.line_no, "raw": r.raw, "time_sec": r.time_sec, "clock": format_clock(r.time_sec),
         "official_id": r.referee_id, "official": r.referee_name, "category": r.category,
         "description": r.description, "warnings": r.warnings, "ok": r.ok}
        for r in rows
    ]


@router.get("/videos/{video_id}/notes")
def notes_form(request: Request, video: Video = Depends(get_video),
               user: User = require(can_manage_video_clips, get_video)):
    _require_playable(video)
    return render(request, "notes.html", video=video, match=video.match, text="", rows=None)


@router.post("/videos/{video_id}/notes/preview")
def notes_preview(request: Request, text: str = Form(""), db: Session = Depends(get_db),
                  video: Video = Depends(get_video),
                  user: User = require(can_manage_video_clips, get_video)):
    _require_playable(video)
    _notes_limit(text)
    rows = services.parse_for_match(db, video.match, text)
    for row in rows:
        if row.ok and video.duration and row.time_sec > video.duration:
            row.warnings.append(f"Czas poza nagraniem (max {format_clock(video.duration)})")
    return render(request, "notes.html", video=video, match=video.match, text=text, rows=rows,
                  categories=services.active_categories(db))


@router.post("/api/videos/{video_id}/notes/parse")
def notes_parse_api(payload: dict, db: Session = Depends(get_db), video: Video = Depends(get_video),
                    user: User = require(can_manage_video_clips, get_video)):
    text = str(payload.get("text", ""))
    _notes_limit(text)
    return _rows_json(services.parse_for_match(db, video.match, text))


@router.post("/api/matches/{match_id}/notes/parse")
def match_notes_parse(payload: dict, db: Session = Depends(get_db), match: Match = Depends(get_match),
                      user: User = require(permissions.can_manage_clips, get_match)):
    """The recording length is not known yet, so "moment outside the recording" only shows up after
    conversion.
    """
    text = str(payload.get("text", ""))
    _notes_limit(text)
    return _rows_json(services.parse_for_match(db, match, text))


@router.post("/videos/{video_id}/notes/commit")
async def notes_commit(request: Request, db: Session = Depends(get_db),
                       video: Video = Depends(get_video),
                       user: User = require(can_manage_video_clips, get_video)):
    _require_playable(video)
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
