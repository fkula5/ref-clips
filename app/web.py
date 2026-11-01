"""Wspólne elementy warstwy webowej: szablony, filtry, widoki JSON."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from app import config, services
from app.auth import set_anon_csrf_cookie
from app import models as m
from app import permissions
from app import video as vid
from app.security import new_token
from app.textutil import format_clock

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
env = templates.env
env.filters["clock"] = format_clock


@pass_context
def csrf_input(context) -> Markup:
    """Ukryte pole z tokenem CSRF do formularzy: {{ csrf_input() }}."""
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(
        escape(context.get("csrf_token", "")))


env.globals.update(
    ffmpeg_ok=vid.ffmpeg_available,
    ffmpeg_message=config.FFMPEG_MISSING_MESSAGE,
    csrf_input=csrf_input,
    perm=permissions,
    USER_ROLES=m.USER_ROLES, OFFICIAL_FUNCTIONS=m.OFFICIAL_FUNCTIONS,
    VIDEO_STATUSES=m.VIDEO_STATUSES, CLIP_STATUSES=m.CLIP_STATUSES, PERIODS=m.PERIODS,
    period_for=lambda c: services.period_for(c.video.marks, c.time_sec),
    period_label=lambda c: services.period_label(c.video.marks, c.time_sec),
    clip_bounds=services.clip_range,
    DEFAULT_MARGIN=config.DEFAULT_MARGIN_BEFORE,
)


def render(request: Request, name: str, status_code: int = 200, **context):
    """Renderuje szablon z użytkownikiem i tokenem CSRF.

    Zalogowany dostaje token swojej sesji; niezalogowany (strony logowania) token z ciasteczka,
    które ustawiamy przy pierwszym wyświetleniu formularza."""
    user = getattr(request.state, "user", None)
    anon_cookie = None
    if user is not None:
        csrf_token = request.state.session.csrf_token
    else:
        csrf_token = request.cookies.get(config.CSRF_COOKIE) or new_token()
        if csrf_token != request.cookies.get(config.CSRF_COOKIE):
            anon_cookie = csrf_token
    response = templates.TemplateResponse(
        request, name, {"user": user, "csrf_token": csrf_token, **context}, status_code=status_code)
    if anon_cookie:
        set_anon_csrf_cookie(response, anon_cookie)
    return response


def clip_json(c: m.Clip) -> dict:
    start, end = services.clip_range(c)
    return {
        "id": c.id,
        "video_id": c.video_id,
        "time_sec": c.time_sec,
        "clock": format_clock(c.time_sec),
        "period": services.period_for(c.video.marks, c.time_sec),
        "official": c.official_label or None,
        "category": c.category_label or None,
        "described": c.is_described,
        "description": c.description,
        "status": c.status,
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
