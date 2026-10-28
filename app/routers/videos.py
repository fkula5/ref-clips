"""Nagrania: upload strumieniowy, odtwarzacz, znaczniki kwart, notatki, szybkie decyzje."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.models import PERIODS, VIDEO_SOURCES, Match, PeriodMark, Video
from app.notes_parser import parse_notes, parse_time
from app.storage import storage
from app.textutil import format_clock, safe_filename
from app.web import decision_json, file_response, mark_json, render

router = APIRouter()
CHUNK_FLUSH = 4 * 1024 * 1024


def _get_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Nie ma takiego nagrania")
    return video


# --- upload ---------------------------------------------------------------------
@router.post("/matches/{match_id}/upload")
async def upload_video(match_id: int, request: Request, filename: str, label: str = "",
                       source: str = "upload", db: Session = Depends(get_db)):
    """Surowe body = zawartość pliku. Zapis strumieniowo na dysk (bez wczytywania do pamięci)."""
    if db.get(Match, match_id) is None:
        raise HTTPException(404, "Nie ma takiego meczu")
    declared = int(request.headers.get("content-length") or 0)
    if declared and declared > storage.free_bytes() - 512 * 1024 * 1024:
        raise HTTPException(507, "Za mało miejsca na dysku")

    video = Video(match_id=match_id, source=source if source in VIDEO_SOURCES else "upload",
                  label=label.strip(), original_filename=filename, status="uploading",
                  created_by=services.default_user(db).id)
    db.add(video)
    db.commit()
    key = f"uploads/{video.id}_{safe_filename(filename, 'nagranie')}"
    out = storage.open_write(key)
    written = 0
    try:
        buffer = bytearray()
        async for chunk in request.stream():
            buffer += chunk
            if len(buffer) >= CHUNK_FLUSH:
                await run_in_threadpool(out.write, bytes(buffer))
                written += len(buffer)
                buffer.clear()
        if buffer:
            await run_in_threadpool(out.write, bytes(buffer))
            written += len(buffer)
        if written == 0:
            raise HTTPException(400, "Pusty plik")
    except BaseException:
        out.close()
        storage.delete(key)
        db.delete(video)
        db.commit()
        raise
    out.close()
    video.original_path, video.size_bytes = key, written
    services.queue_transcode(db, video)
    db.commit()
    return {"id": video.id, "size": written}


@router.get("/matches/{match_id}/videos-panel")
def videos_panel(request: Request, match_id: int, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(404)
    busy = any(v.status in ("uploading", "queued", "processing") for v in match.videos)
    return render(request, "_videos_panel.html", match=match, busy=busy)


# --- serwowanie wideo (Range) ---------------------------------------------------
@router.get("/videos/{video_id}/stream")
def stream_video(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    if video.status != "ready" or not video.proxy_path or not storage.exists(video.proxy_path):
        raise HTTPException(409, "Wersja robocza nie jest jeszcze gotowa")
    return file_response(storage.local_path(video.proxy_path))


@router.post("/videos/{video_id}/retry")
def retry_video(video_id: int, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    if video.original_path:
        services.queue_transcode(db, video)
        db.commit()
    return RedirectResponse(f"/matches/{video.match_id}", status_code=303)


@router.post("/videos/{video_id}/update")
def update_video(video_id: int, label: str = Form(""), source: str = Form("upload"),
                 db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    video.label = label.strip()
    video.source = source if source in VIDEO_SOURCES else video.source
    db.commit()
    return RedirectResponse(f"/matches/{video.match_id}", status_code=303)


@router.post("/videos/{video_id}/delete")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
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
        "decisions": [decision_json(d) for d in sorted(video.decisions, key=lambda x: x.time_sec)],
        "next_period": services.next_period(video.marks),
    }


@router.get("/videos/{video_id}")
def player(request: Request, video_id: int, t: float = 0, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    return render(request, "player.html", video=video, match=video.match, state=_state(video),
                  start_at=t)


@router.get("/api/videos/{video_id}/state")
def video_state(video_id: int, db: Session = Depends(get_db)):
    return _state(_get_video(db, video_id))


class MarkIn(BaseModel):
    time_sec: float
    period: str | None = None


@router.post("/api/videos/{video_id}/marks")
def set_mark(video_id: int, body: MarkIn, db: Session = Depends(get_db)):
    """Dodaje znacznik początku kwarty (domyślnie następnej); istniejący jest przesuwany."""
    video = _get_video(db, video_id)
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
def delete_mark(mark_id: int, db: Session = Depends(get_db)):
    mark = db.get(PeriodMark, mark_id)
    if mark is None:
        raise HTTPException(404)
    video = mark.video
    db.delete(mark)
    db.commit()
    db.refresh(video)
    return _state(video)


# --- szybka decyzja (klawisz M) -------------------------------------------------
class QuickDecisionIn(BaseModel):
    time_sec: float
    text: str = ""


@router.post("/api/videos/{video_id}/quick-decision")
def quick_decision(video_id: int, body: QuickDecisionIn, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    time_sec = max(0.0, body.time_sec)
    if video.duration:
        time_sec = min(time_sec, video.duration)
    clock = format_clock(time_sec)
    line = parse_notes(f"{clock} {body.text}", services.referee_defs(video.match),
                       services.tag_defs(db), services.team_defs(video.match))[0]
    decision = services.create_decision(
        db, video, services.default_user(db), time_sec=time_sec, referee_id=line.referee_id,
        team=line.team, tag_names=line.tags, description=f"{clock} {body.text}".strip())
    db.commit()
    return {"decision": decision_json(decision), "warnings": line.warnings, **_state(video)}


# --- notatki: wklejenie, podgląd, zapis -----------------------------------------
@router.get("/videos/{video_id}/notes")
def notes_form(request: Request, video_id: int, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    return render(request, "notes.html", video=video, match=video.match, text="", rows=None)


@router.post("/videos/{video_id}/notes/preview")
def notes_preview(request: Request, video_id: int, text: str = Form(""),
                  db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    rows = services.parse_for_match(db, video.match, text)
    for row in rows:
        if row.ok and video.duration and row.time_sec > video.duration:
            row.warnings.append(f"Czas poza nagraniem (max {format_clock(video.duration)})")
    return render(request, "notes.html", video=video, match=video.match, text=text, rows=rows,
                  all_tags=services.tag_defs(db))


@router.post("/api/videos/{video_id}/notes/parse")
def notes_parse_api(video_id: int, payload: dict, db: Session = Depends(get_db)):
    video = _get_video(db, video_id)
    rows = services.parse_for_match(db, video.match, payload.get("text", ""))
    return [
        {"line_no": r.line_no, "raw": r.raw, "time_sec": r.time_sec, "referee_id": r.referee_id,
         "referee": r.referee_name, "tags": r.tags, "team": r.team, "warnings": r.warnings,
         "ok": r.ok}
        for r in rows
    ]


@router.post("/videos/{video_id}/notes/commit")
async def notes_commit(request: Request, video_id: int, db: Session = Depends(get_db)):
    """Zapisuje (edytowane) wiersze podglądu jako decyzje i zleca wycinanie."""
    video = _get_video(db, video_id)
    form = await request.form()
    user = services.default_user(db)
    valid_referees = {mr.referee_id for mr in video.match.referees}
    created = skipped = 0
    for i in range(int(form.get("count", 0))):
        if not form.get(f"include_{i}"):
            continue
        time_sec = parse_time(str(form.get(f"time_{i}", "")))
        if time_sec is None or (video.duration and time_sec > video.duration):
            skipped += 1
            continue
        ref_raw = str(form.get(f"referee_{i}", ""))
        referee_id = int(ref_raw) if ref_raw.isdigit() and int(ref_raw) in valid_referees else None
        team = str(form.get(f"team_{i}", "")) or None
        tag_names = [t for t in str(form.get(f"tags_{i}", "")).split(",") if t.strip()]
        services.create_decision(
            db, video, user, time_sec=time_sec, referee_id=referee_id,
            team=team if team in ("a", "b") else None, tag_names=tag_names,
            description=str(form.get(f"desc_{i}", "")).strip())
        created += 1
    db.commit()
    return RedirectResponse(f"/clips?video_id={video.id}&created={created}&skipped={skipped}",
                            status_code=303)
