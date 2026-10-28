"""Wspólne elementy warstwy webowej: szablony, filtry, widoki JSON."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates

from app import config, services
from app import models as m
from app import video as vid
from app.textutil import format_clock

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
env = templates.env
env.filters["clock"] = format_clock
env.globals.update(
    ffmpeg_ok=vid.ffmpeg_available,
    ffmpeg_message=config.FFMPEG_MISSING_MESSAGE,
    MATCH_ROLES=m.MATCH_ROLES, VIDEO_SOURCES=m.VIDEO_SOURCES, VIDEO_STATUSES=m.VIDEO_STATUSES,
    RATINGS=m.RATINGS, VISIBILITIES=m.VISIBILITIES, DECISION_STATUSES=m.DECISION_STATUSES,
    PERIODS=m.PERIODS, DEFAULT_MARGIN=config.DEFAULT_MARGIN_BEFORE,
    period_for=lambda d: services.period_for(d.video.marks, d.time_sec),
    clip_bounds=services.decision_bounds,
)


def render(request: Request, name: str, **context):
    return templates.TemplateResponse(request, name, context)


def decision_json(d: m.Decision) -> dict:
    start, end = services.decision_bounds(d)
    return {
        "id": d.id,
        "video_id": d.video_id,
        "time_sec": d.time_sec,
        "clock": format_clock(d.time_sec),
        "period": services.period_for(d.video.marks, d.time_sec),
        "referee": d.referee.name if d.referee else None,
        "team": d.match.team_label(d.team),
        "tags": [t.name for t in d.tags],
        "description": d.description,
        "rating": d.rating,
        "status": d.status,
        "clip_start": start,
        "clip_end": end,
    }


def mark_json(mark: m.PeriodMark) -> dict:
    return {"id": mark.id, "period": mark.period, "time_sec": mark.time_sec,
            "clock": format_clock(mark.time_sec)}


def file_response(path: Path, media_type: str = "video/mp4", download_name: str | None = None):
    """Plik z obsługą HTTP Range (Starlette FileResponse zwraca 206 dla nagłówka Range)."""
    kwargs = {}
    if download_name:
        kwargs = {"filename": download_name, "content_disposition_type": "attachment"}
    return FileResponse(path, media_type=media_type, **kwargs)
